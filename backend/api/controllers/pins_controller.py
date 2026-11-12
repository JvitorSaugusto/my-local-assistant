"""Fixar o projeto (workspace) e as fontes do RAG a uma conversa.

O vínculo fica no banco (tabela chat_pins, criada sozinha na primeira chamada), então vale em qualquer
aparelho: quem abre a conversa recebe de volta o mesmo projeto e as mesmas fontes.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.database.config import async_session_env

pins_router = APIRouter()

_ready = False

_CREATE_TABLE = text(
    "CREATE TABLE IF NOT EXISTS chat_pins ("
    "thread_id TEXT PRIMARY KEY, "
    "workspace_path TEXT, "
    "source_ids TEXT NOT NULL DEFAULT '[]', "
    "updated_at TEXT)"
)
_SELECT = text("SELECT workspace_path, source_ids FROM chat_pins WHERE thread_id = :thread_id")
_UPSERT = text(
    "INSERT INTO chat_pins (thread_id, workspace_path, source_ids, updated_at) "
    "VALUES (:thread_id, :workspace_path, :source_ids, :updated_at) "
    "ON CONFLICT (thread_id) DO UPDATE SET "
    "workspace_path = excluded.workspace_path, source_ids = excluded.source_ids, updated_at = excluded.updated_at"
)
_DELETE = text("DELETE FROM chat_pins WHERE thread_id = :thread_id")


class PinPayload(BaseModel):
    workspace_path: str = Field(min_length=1, description="Pasta do projeto, no computador onde o backend roda.")
    source_ids: list[int] = Field(default_factory=list, description="Fontes do RAG a consultar junto.")


async def ensure_pins_table() -> None:
    global _ready
    if _ready:
        return
    async with async_session_env() as db:
        await db.execute(_CREATE_TABLE)
        await db.commit()
    _ready = True


def _pin_dict(thread_id: str, row) -> dict:
    if row is None:
        return {"thread_id": thread_id, "pinned": False, "workspace_path": None, "source_ids": []}
    try:
        ids = [int(item) for item in json.loads(row[1] or "[]")]
    except (TypeError, ValueError):
        ids = []
    return {"thread_id": thread_id, "pinned": True, "workspace_path": row[0], "source_ids": ids}


@pins_router.get("/{thread_id}")
async def get_pin(thread_id: str):
    await ensure_pins_table()
    async with async_session_env() as db:
        row = (await db.execute(_SELECT, {"thread_id": thread_id})).first()
    return _pin_dict(thread_id, row)


@pins_router.put("/{thread_id}")
async def put_pin(thread_id: str, payload: PinPayload):
    workspace = payload.workspace_path.strip()
    try:
        is_dir = Path(workspace).expanduser().is_dir()
    except OSError:
        is_dir = False
    if not is_dir:
        raise HTTPException(status_code=400, detail=f"Pasta não encontrada no servidor: {workspace}")

    ids = sorted({int(item) for item in payload.source_ids})
    await ensure_pins_table()
    async with async_session_env() as db:
        await db.execute(
            _UPSERT,
            {
                "thread_id": thread_id,
                "workspace_path": workspace,
                "source_ids": json.dumps(ids),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await db.commit()
    return {"thread_id": thread_id, "pinned": True, "workspace_path": workspace, "source_ids": ids}


@pins_router.delete("/{thread_id}")
async def delete_pin(thread_id: str):
    await ensure_pins_table()
    async with async_session_env() as db:
        await db.execute(_DELETE, {"thread_id": thread_id})
        await db.commit()
    return {"thread_id": thread_id, "pinned": False, "workspace_path": None, "source_ids": []}
