"""Registro de artefatos (.txt e .md) gerados dentro de uma conversa (thread_id)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from backend.database.config import async_session_env
from backend.graph.ops_core import pack_file_path

_ready = False

_CREATE_TABLE = text(
    "CREATE TABLE IF NOT EXISTS chat_artifacts ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "thread_id TEXT NOT NULL, "
    "filename TEXT NOT NULL, "
    "kind TEXT NOT NULL DEFAULT 'txt', "
    "title TEXT NOT NULL DEFAULT '', "
    "size_bytes INTEGER NOT NULL DEFAULT 0, "
    "created_at TEXT NOT NULL, "
    "UNIQUE(thread_id, filename))"
)

_CREATE_TABLE_PG = text(
    "CREATE TABLE IF NOT EXISTS chat_artifacts ("
    "id SERIAL PRIMARY KEY, "
    "thread_id TEXT NOT NULL, "
    "filename TEXT NOT NULL, "
    "kind TEXT NOT NULL DEFAULT 'txt', "
    "title TEXT NOT NULL DEFAULT '', "
    "size_bytes INTEGER NOT NULL DEFAULT 0, "
    "created_at TEXT NOT NULL, "
    "UNIQUE(thread_id, filename))"
)

_UPSERT = text(
    "INSERT INTO chat_artifacts (thread_id, filename, kind, title, size_bytes, created_at) "
    "VALUES (:thread_id, :filename, :kind, :title, :size_bytes, :created_at) "
    "ON CONFLICT (thread_id, filename) DO UPDATE SET "
    "kind = excluded.kind, title = excluded.title, size_bytes = excluded.size_bytes, created_at = excluded.created_at"
)

_SELECT = text(
    "SELECT filename, kind, title, size_bytes, created_at "
    "FROM chat_artifacts WHERE thread_id = :thread_id ORDER BY id DESC"
)

_DELETE = text(
    "DELETE FROM chat_artifacts WHERE thread_id = :thread_id AND filename = :filename"
)


async def ensure_artifacts_table() -> None:
    global _ready
    if _ready:
        return
    async with async_session_env() as db:
        dialect = getattr(getattr(db, "bind", None), "dialect", None)
        name = getattr(dialect, "name", "")
        stmt = _CREATE_TABLE_PG if "postgres" in name else _CREATE_TABLE
        await db.execute(stmt)
        await db.commit()
    _ready = True


async def record_artifact(
    thread_id: str | None,
    filename: str,
    kind: str | None = None,
    title: str = "",
    size_bytes: int = 0,
) -> None:
    tid = str(thread_id or "").strip()
    fname = Path(str(filename or "")).name
    if not tid or not fname:
        return
    ext = Path(fname).suffix.lstrip(".").lower()
    resolved_kind = (kind or ext or "txt").lower()
    await ensure_artifacts_table()
    async with async_session_env() as db:
        await db.execute(
            _UPSERT,
            {
                "thread_id": tid,
                "filename": fname,
                "kind": resolved_kind,
                "title": (title or fname)[:200],
                "size_bytes": int(size_bytes or 0),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await db.commit()


async def list_artifacts(thread_id: str) -> list[dict]:
    tid = str(thread_id or "").strip()
    if not tid:
        return []
    await ensure_artifacts_table()
    async with async_session_env() as db:
        rows = (await db.execute(_SELECT, {"thread_id": tid})).all()
    items: list[dict] = []
    for row in rows:
        fname = row[0]
        disk_path = pack_file_path(fname)
        exists = disk_path is not None
        size = disk_path.stat().st_size if exists else int(row[3] or 0)
        items.append(
            {
                "filename": fname,
                "kind": row[1] or Path(fname).suffix.lstrip(".").lower() or "txt",
                "title": row[2] or fname,
                "size_bytes": size,
                "created_at": row[4],
                "exists": exists,
                "url": f"/api/handoff/packs/{fname}",
            }
        )
    return items


async def delete_artifact(thread_id: str, filename: str) -> bool:
    tid = str(thread_id or "").strip()
    fname = Path(str(filename or "")).name
    if not tid or not fname:
        return False
    await ensure_artifacts_table()
    async with async_session_env() as db:
        res = await db.execute(_DELETE, {"thread_id": tid, "filename": fname})
        await db.commit()
        return (res.rowcount or 0) > 0  # type: ignore[attr-defined]
