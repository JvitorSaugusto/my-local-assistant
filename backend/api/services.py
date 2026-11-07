from collections.abc import Sequence
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.api.schemas import ChatRequestSchema, TaskCreateSchema
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

    UPDATABLE_FIELDS = {
        "title", "description", "files", "reason", "priority",
        "status", "code_snippet", "last_error", "steps", "verify", "attempts",
    }
    VALID_STATUSES = {"pending", "queued", "running", "review", "completed", "failed"}
    
    def __init__(self, db: AsyncSession):
            self.db = db
            
    async def create(self, tasks_data: list[TaskCreateSchema], thread_id: str) -> list[TaskModel]:
        new_tasks = [
            TaskModel(**task.model_dump(), thread_id=thread_id) 
            for task in tasks_data
        ]
        
        self.db.add_all(new_tasks)
        await self.db.commit()
        
        for task in new_tasks:
            await self.db.refresh(task)
            
        return new_tasks
            
    async def get_pending_by_thread(self, thread_id: str) -> Sequence[TaskModel]:
        stmt = select(TaskModel).where(
            TaskModel.thread_id == thread_id,
            TaskModel.status == "pending"
        ).order_by(TaskModel.id)
        
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_thread(
        self, thread_id: str, status: str | None = None
    ) -> Sequence[TaskModel]:
        """Todas as tarefas da conversa (inclui failed/completed para o painel exibir)."""
        stmt = select(TaskModel).where(TaskModel.thread_id == thread_id)
        if status:
            stmt = stmt.where(TaskModel.status == status)
        stmt = stmt.order_by(TaskModel.id)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def retry(self, task_id: int) -> TaskModel | None:
        """Devolve uma tarefa 'failed' para 'pending' (o erro anterior é limpo).

        Retorna None se a tarefa não existir; levanta ValueError se não estiver
        em um estado que permita reiniciar.
        """
        task = await self.db.get(TaskModel, task_id)
        if not task:
            return None

        if task.status not in {"failed", "queued", "running"}:
            raise ValueError(
                f"Só é possível reiniciar tarefas com falha (status atual: {task.status})."
            )

        task.status = "pending"
        task.last_error = None

        await self.db.commit()
        await self.db.refresh(task)

        return task

    async def get_all(self) -> Sequence[TaskModel]:
        stmt = select(TaskModel).order_by(TaskModel.id)
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def update(self, task_id: int, updates: dict) -> TaskModel | None:
        task = await self.db.get(TaskModel, task_id)
        if not task:
            return None
            
        if "status" in updates and updates["status"] not in self.VALID_STATUSES:
            raise ValueError(f"Status inválido: {updates['status']!r}.")

        for key, value in updates.items():
            if key in self.UPDATABLE_FIELDS:
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

    async def delete_many(self, task_ids: list[int]) -> dict:
        """Exclui várias tarefas. Tarefas em execução (queued/running) são preservadas.

        Retorna {"deleted": [ids], "skipped": [{"id": id, "reason": "..."}]}.
        """
        ids = list(dict.fromkeys(task_ids))
        result = await self.db.execute(select(TaskModel).where(TaskModel.id.in_(ids)))
        found = {task.id: task for task in result.scalars().all()}

        deleted: list[int] = []
        skipped: list[dict] = []
        for task_id in ids:
            task = found.get(task_id)
            if task is None:
                skipped.append({"id": task_id, "reason": "tarefa não encontrada"})
            elif task.status in {"queued", "running"}:
                skipped.append({"id": task_id, "reason": f"está em execução ({task.status})"})
            else:
                await self.db.delete(task)
                deleted.append(task_id)

        await self.db.commit()
        return {"deleted": deleted, "skipped": skipped}


    async def get(self, task_id: int) -> TaskModel | None:
        return await self.db.get(TaskModel, task_id)
