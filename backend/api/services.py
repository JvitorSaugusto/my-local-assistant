from collections.abc import Sequence
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.api.schemas import ChatRequestSchema
from backend.database.models import AiChatModel, TaskModel


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
    
class TaskService:
    
    def __init__(self, db: AsyncSession):
            self.db = db
            
    async def get_pending_by_thread(self, thread_id: str) -> Sequence[TaskModel]:
        stmt = select(TaskModel).where(
            TaskModel.thread_id == thread_id,
            TaskModel.status == "pending"
        ).order_by(TaskModel.id)
        
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_all(self) -> Sequence[TaskModel]:
        stmt = select(TaskModel).order_by(TaskModel.id)
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def update(self, task_id: int, updates: dict) -> TaskModel | None:
        task = await self.db.get(TaskModel, task_id)
        if not task:
            return None
            
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)
                
        await self.db.commit()
        await self.db.refresh(task)
        
        return task
    
    async def delete(self, task_id: int) -> bool:
        task = await self.db.get(TaskModel, task_id)
        if not task:
            return False
            
        await self.db.delete(task)
        await self.db.commit()
        
        return True