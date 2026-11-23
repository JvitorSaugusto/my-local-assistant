"""Metadados de organização de conversas: fixar no topo da sidebar, pasta e tags."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import text

from backend.database.config import async_session_env

_ready = False

_CREATE_TABLE = text(
    "CREATE TABLE IF NOT EXISTS chat_meta ("
    "thread_id TEXT PRIMARY KEY, "
    "pinned INTEGER NOT NULL DEFAULT 0, "
    "folder TEXT NOT NULL DEFAULT '', "
    "tags TEXT NOT NULL DEFAULT '[]', "
    "updated_at TEXT NOT NULL)"
)

_UPSERT = text(
    "INSERT INTO chat_meta (thread_id, pinned, folder, tags, updated_at) "
    "VALUES (:thread_id, :pinned, :folder, :tags, :updated_at) "
    "ON CONFLICT (thread_id) DO UPDATE SET "
    "pinned = excluded.pinned, folder = excluded.folder, tags = excluded.tags, updated_at = excluded.updated_at"
)

_SELECT_ALL = text("SELECT thread_id, pinned, folder, tags FROM chat_meta")
_SELECT_ONE = text("SELECT pinned, folder, tags FROM chat_meta WHERE thread_id = :thread_id")
_DELETE_ONE = text("DELETE FROM chat_meta WHERE thread_id = :thread_id")


def default_meta() -> dict:
    return {"pinned": False, "folder": "", "tags": []}


def clean_folder(folder: str | None) -> str:
    return re.sub(r"\s+", " ", str(folder or "")).strip()[:40]


def clean_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        item = re.sub(r"\s+", " ", str(raw or "").lstrip("#")).strip()[:30]
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
        if len(out) >= 8:
            break
    return out


def _parse_tags(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
        return clean_tags(data) if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


async def ensure_chat_meta_table() -> None:
    global _ready
    if _ready:
        return
    async with async_session_env() as db:
        await db.execute(_CREATE_TABLE)
        await db.commit()
    _ready = True


async def list_all_meta() -> dict[str, dict]:
    await ensure_chat_meta_table()
    async with async_session_env() as db:
        rows = (await db.execute(_SELECT_ALL)).all()
    return {
        str(row[0]): {
            "pinned": bool(row[1]),
            "folder": clean_folder(row[2]),
            "tags": _parse_tags(row[3]),
        }
        for row in rows
    }


async def get_meta(thread_id: str) -> dict:
    tid = str(thread_id or "").strip()
    if not tid:
        return default_meta()
    await ensure_chat_meta_table()
    async with async_session_env() as db:
        rows = (await db.execute(_SELECT_ONE, {"thread_id": tid})).all()
    if not rows:
        return default_meta()
    row = rows[0]
    return {
        "pinned": bool(row[0]),
        "folder": clean_folder(row[1]),
        "tags": _parse_tags(row[2]),
    }


async def upsert_meta(
    thread_id: str,
    pinned: bool | None = None,
    folder: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    tid = str(thread_id or "").strip()
    if not tid:
        return default_meta()
    current = await get_meta(tid)
    next_pinned = current["pinned"] if pinned is None else bool(pinned)
    next_folder = current["folder"] if folder is None else clean_folder(folder)
    next_tags = current["tags"] if tags is None else clean_tags(tags)

    await ensure_chat_meta_table()
    async with async_session_env() as db:
        await db.execute(
            _UPSERT,
            {
                "thread_id": tid,
                "pinned": 1 if next_pinned else 0,
                "folder": next_folder,
                "tags": json.dumps(next_tags, ensure_ascii=False),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await db.commit()
    return {"pinned": next_pinned, "folder": next_folder, "tags": next_tags}


async def delete_meta(thread_id: str) -> None:
    tid = str(thread_id or "").strip()
    if not tid:
        return
    await ensure_chat_meta_table()
    async with async_session_env() as db:
        await db.execute(_DELETE_ONE, {"thread_id": tid})
        await db.commit()
