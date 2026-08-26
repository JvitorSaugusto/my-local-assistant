from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from backend.api.schemas import ChatRequestSchema, ChatResponseSchema
from backend.api.services import ChatService
from backend.database.config import get_db


def get_chat_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ChatService:
    return ChatService(db)

ServiceDependency = Annotated[ChatService, Depends(get_chat_service)]

chat_router = APIRouter()


@chat_router.post("/", status_code=201)
async def create_new_chat(request: ChatRequestSchema, service: ServiceDependency):
    return await service.create_new_chat(request)

@chat_router.put("/{chat_id}", status_code=200)    
async def update_chat(chat_id: int, request: ChatRequestSchema, service: ServiceDependency):
    return await service.update_chat(chat_id=chat_id, new_title=request.title)

@chat_router.get("/", status_code=200, response_model=list[ChatResponseSchema])   
async def list_chats(service: ServiceDependency):
    return await service.list_chats()

@chat_router.get("/{chat_id}", status_code=200)    
async def detail_chat(chat_id: int, service: ServiceDependency):
    return await service.detail_chat(chat_id=chat_id)

@chat_router.delete("/{chat_id}", status_code=204)    
async def delete_chat(chat_id: int, service: ServiceDependency):
    return await service.delete_chat(chat_id=chat_id)