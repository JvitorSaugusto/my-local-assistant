"""Rotas do Gerenciador Visual de Memórias do Assistente (/api/memories)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.graph import memory

memory_router = APIRouter()


class MemoryTextPayload(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@memory_router.get("")
@memory_router.get("/")
async def get_memories():
    return {
        "enabled": memory.enabled(),
        "items": memory.list_all(),
        "max_items": memory.MAX_ITEMS,
        "max_chars": memory.MAX_CHARS,
    }


@memory_router.post("", status_code=201)
@memory_router.post("/", status_code=201)
async def create_memory(payload: MemoryTextPayload):
    item, msg = memory.add(payload.text)
    if item is None:
        raise HTTPException(status_code=400, detail=msg)
    return {"item": item, "message": msg, "items": memory.list_all()}


@memory_router.put("/{item_id}")
async def update_memory(item_id: int, payload: MemoryTextPayload):
    item, msg = memory.update(item_id, payload.text)
    if item is None:
        code = 404 if "não existe" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg)
    return {"item": item, "message": msg, "items": memory.list_all()}


@memory_router.delete("/{item_id}")
async def delete_memory(item_id: int):
    removed = memory.remove(item_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Não existe memória #{item_id}.")
    return {"removed": True, "id": item_id, "items": memory.list_all()}
