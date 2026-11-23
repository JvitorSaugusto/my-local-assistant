from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.chat_search import search_chats_and_messages
from backend.api.schemas import ChatRequestSchema, ChatResponseSchema, ChatUpdateSchema
from backend.api.services import ChatService
from backend.database.config import get_db
from backend.graph.presets import list_presets


def get_chat_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ChatService:
    return ChatService(db)


ServiceDependency = Annotated[ChatService, Depends(get_chat_service)]

chat_router = APIRouter()


@chat_router.get("/presets", status_code=200)
async def get_chat_presets():
    return {"presets": list_presets()}


@chat_router.get("/search", status_code=200)
async def search_chats(q: str, request: Request, service: ServiceDependency, limit: int = 30):
    chats = await service.list_chats()
    app_graph = getattr(request.app.state, "compiled_graph", None)
    results = await search_chats_and_messages(chats, app_graph, q, limit=max(1, min(limit, 60)))
    return {"query": q, "results": results}


@chat_router.post("/", status_code=201)
async def create_new_chat(request: ChatRequestSchema, service: ServiceDependency):
    return await service.create_new_chat(request)


@chat_router.get("/", status_code=200, response_model=list[ChatResponseSchema])
async def list_chats(service: ServiceDependency):
    return await service.list_chats()


@chat_router.put("/{chat_id}", status_code=200)
async def update_chat(chat_id: int, request: ChatUpdateSchema, service: ServiceDependency):
    return await service.update_chat(
        chat_id=chat_id,
        new_title=request.title,
        pinned=request.pinned,
        folder=request.folder,
        tags=request.tags,
    )


@chat_router.get("/{chat_id}", status_code=200)
async def detail_chat(chat_id: int, service: ServiceDependency):
    return await service.detail_chat(chat_id=chat_id)


@chat_router.delete("/{chat_id}", status_code=204)
async def delete_chat(chat_id: int, service: ServiceDependency):
    return await service.delete_chat(chat_id=chat_id)