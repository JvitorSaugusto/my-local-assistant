"""Checkpoint Git leve por conversa para desfazer um lote inteiro de tasks com 1 clique."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CHECKPOINTS: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_checkpoint(thread_id: str, workspace_path: str, task_ids: list[int] | None = None) -> dict[str, Any] | None:
    if not thread_id or not workspace_path:
        return None
    root = Path(workspace_path).expanduser().resolve()
    if not root.is_dir():
        return None
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    sha = (res.stdout or "").strip()
    if not sha:
        return None
    entry = {
        "thread_id": thread_id,
        "workspace_path": str(root),
        "commit_sha": sha,
        "short_sha": sha[:8],
        "task_ids": list(task_ids or []),
        "created_at": _now_iso(),
    }
    _CHECKPOINTS[thread_id] = entry
    return entry


def get_checkpoint(thread_id: str) -> dict[str, Any] | None:
    return _CHECKPOINTS.get(thread_id)


def rollback_checkpoint(thread_id: str) -> dict[str, Any]:
    entry = _CHECKPOINTS.get(thread_id)
    if not entry:
        raise ValueError("Nenhum checkpoint de lote salvo para esta conversa.")
    root = Path(entry["workspace_path"])
    if not root.is_dir():
        raise ValueError(f"Diretório não encontrado: {root}")
    sha = entry["commit_sha"]
    res = subprocess.run(
        ["git", "reset", "--hard", sha],
        cwd=str(root),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=20,
    )
    if res.returncode != 0:
        raise ValueError((res.stderr or res.stdout or "Falha no git reset --hard").strip())
    _CHECKPOINTS.pop(thread_id, None)
    return {
        "reverted": True,
        "commit_sha": sha,
        "short_sha": entry["short_sha"],
        "output": (res.stdout or "").strip(),
    }
