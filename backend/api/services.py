import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.api.schemas import ChatRequestSchema
from backend.database.models import AiChatModel


class ChatService:
    
    def __init__(self, db: AsyncSession):
        self.db = db
        
    async def create_new_chat(self, payload: ChatRequestSchema):
        thread_id=str(uuid.uuid4())
        
        new_chat = AiChatModel(**payload.model_dump(), thread_id=thread_id)
        
        self.db.add(new_chat)
        await self.db.commit()
        await self.db.refresh(new_chat)
        
        return new_chat
    
    async def list_chats(self):
        stmt = select(AiChatModel).order_by(AiChatModel.created_at.desc())
        result =  await self.db.scalars(stmt)
        
        return result.all()
        
    async def detail_chat(self, chat_id: int):
        return await self.db.get(AiChatModel, chat_id)
        
    async def update_chat(self, chat_id: int, new_title: str):
        chat = await self.detail_chat(chat_id)
        
        if not chat:
            return
            
        chat.title = new_title
        await self.db.commit()
        await self.db.refresh(chat)
        
        return chat
        
    async def delete_chat(self, chat_id: int):
        chat = await self.detail_chat(chat_id)
        
        if not chat:
            return False
            
        await self.db.delete(chat)
        await self.db.commit()
        
        return True