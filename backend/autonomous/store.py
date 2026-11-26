"""Persistência isolada em SQLite WAL + construtor de contexto zerado para cada ciclo."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .schemas import MissionRecord, MissionStatus, utc_now_iso
from .state_machine import calculate_progress, next_pending_item


def default_autonomous_db_path() -> Path:
    env_path = (os.getenv("AUTONOMOUS_DB_PATH") or "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    base = Path(os.getenv("AUTONOMOUS_DATA_DIR") or ".autonomous_data").expanduser().resolve()
    return base / "missions.db"


class MissionStore:
    """Armazenamento transacional isolado em SQLite WAL para missões autônomas."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path).expanduser().resolve() if db_path else default_autonomous_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS autonomous_missions (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        workspace_path TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_autonomous_missions_ws_updated
                    ON autonomous_missions (workspace_path, updated_at DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS autonomous_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        mission_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        message TEXT NOT NULL,
                        details_json TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (mission_id) REFERENCES autonomous_missions(id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_autonomous_events_mission
                    ON autonomous_events (mission_id, id DESC)
                    """
                )

    def save(self, mission: MissionRecord) -> MissionRecord:
        mission.updated_at = utc_now_iso()
        payload = mission.model_dump_json()
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO autonomous_missions
                        (id, title, workspace_path, status, payload_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        workspace_path = excluded.workspace_path,
                        status = excluded.status,
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        mission.id,
                        mission.title,
                        mission.workspace_path,
                        mission.status.value,
                        payload,
                        mission.created_at,
                        mission.updated_at,
                    ),
                )
        return mission

    def get(self, mission_id: str) -> MissionRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload_json FROM autonomous_missions WHERE id = ?",
                (mission_id,),
            ).fetchone()
        if row is None:
            return None
        return MissionRecord.model_validate_json(row["payload_json"])

    def list_missions(
        self,
        *,
        workspace_path: str | None = None,
        status: MissionStatus | None = None,
        limit: int = 50,
    ) -> list[MissionRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if workspace_path:
            clauses.append("workspace_path = ?")
            params.append(workspace_path)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT payload_json FROM autonomous_missions {where} "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        params.append(max(1, min(int(limit), 200)))

        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [MissionRecord.model_validate_json(r["payload_json"]) for r in rows]

    def delete(self, mission_id: str) -> bool:
        with closing(self._connect()) as conn:
            with conn:
                cur = conn.execute(
                    "DELETE FROM autonomous_missions WHERE id = ?",
                    (mission_id,),
                )
        return cur.rowcount > 0

    def append_event(
        self,
        mission_id: str,
        event_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> int:
        now = utc_now_iso()
        details_json = json.dumps(details, ensure_ascii=False) if details is not None else None
        with closing(self._connect()) as conn:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO autonomous_events
                        (mission_id, event_type, message, details_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (mission_id, event_type, message, details_json, now),
                )
                return int(cur.lastrowid or 0)

    def list_events(self, mission_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, mission_id, event_type, message, details_json, created_at
                FROM autonomous_events
                WHERE mission_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (mission_id, max(1, min(int(limit), 500))),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in reversed(rows):
            events.append(
                {
                    "id": row["id"],
                    "mission_id": row["mission_id"],
                    "event_type": row["event_type"],
                    "message": row["message"],
                    "details": json.loads(row["details_json"]) if row["details_json"] else None,
                    "created_at": row["created_at"],
                }
            )
        return events


def build_clean_context_brief(
    mission: MissionRecord,
    *,
    max_decisions: int = 12,
    max_chars: int = 6000,
) -> str:
    """Monta um resumo compacto e determinístico para iniciar cada ciclo com contexto 100% limpo."""
    progress = calculate_progress(mission)
    lines: list[str] = [
        f"# MISSÃO AUTÔNOMA: {mission.title} (`{mission.id}`)",
        f"- **Modo:** {mission.mode.value} | **Status:** {mission.status.value} | **Branch:** {mission.branch_name or '(ainda não criada)'}",
        f"- **Progresso objetivo:** {progress.done_items}/{progress.total_items} concluídos "
        f"({progress.effective_pct:.1f}% efetivo; {progress.blocked_items} bloqueado(s); "
        f"fases {progress.completed_phases}/{progress.total_phases})",
        "",
        "## Objetivo Principal",
        mission.objective.strip(),
    ]

    if mission.business_rules:
        lines.append("")
        lines.append("## Regras de Negócio (imutáveis)")
        for idx, rule in enumerate(mission.business_rules, start=1):
            lines.append(f"{idx}. {rule.strip()}")

    if mission.conventions:
        lines.append("")
        lines.append("## Convenções Obrigatórias")
        for conv in mission.conventions:
            lines.append(f"- {conv.strip()}")

    if mission.phases:
        lines.append("")
        lines.append("## Checklist por Fases")
        for phase in sorted(mission.phases, key=lambda p: p.order):
            lines.append(f"### Fase {phase.order}: {phase.title} [{phase.status.value}]")
            for item in phase.items:
                icon = {
                    "done": "[x]",
                    "in_progress": "[~]",
                    "blocked": "[!]",
                    "skipped": "[-]",
                    "pending": "[ ]",
                }.get(item.status.value, "[ ]")
                suffix = f" (erro: {item.last_error[:90]})" if item.last_error and item.status.value == "blocked" else ""
                lines.append(f"- {icon} `{item.id}` {item.title}{suffix}")

    nxt = next_pending_item(mission)
    if nxt is not None:
        phase, item = nxt
        lines.append("")
        lines.append(f"## Próximo Alvo: Fase {phase.order} · `{item.id}` — {item.title}")
        if item.description:
            lines.append(item.description.strip())
        if item.target_files:
            lines.append("Arquivos alvo: " + ", ".join(f"`{f}`" for f in item.target_files))
        if item.acceptance_criteria:
            lines.append("Critérios de aceite:")
            for crit in item.acceptance_criteria:
                lines.append(f"- {crit}")

    if mission.decisions:
        lines.append("")
        lines.append("## Decisões Recentes")
        for dec in mission.decisions[-max_decisions:]:
            tag = f"[{dec.item_id}] " if dec.item_id else ""
            lines.append(f"- {tag}{dec.summary.strip()}")

    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 45].rsplit("\n", 1)[0] + "\n\n[... resumo truncado para preservar janela ...]"
    return text
