from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from backend.api.services import TaskService
from backend.api.schemas import TaskResponseSchema
from backend.database.config import get_db


task_router = APIRouter()

async def get_task_service(db: Annotated[AsyncSession, Depends(get_db)]) -> TaskService:
    return TaskService(db)

TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]


@task_router.get("/", response_model=list[TaskResponseSchema])
async def list_tasks(service: TaskServiceDep):
    return await service.get_all()


@task_router.put("/{task_id}")
async def update_task(task_id: int, updates: dict, service: TaskServiceDep):
    task = await service.update(task_id, updates)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task


@task_router.delete("/{task_id}")
async def delete_task(task_id: int, service: TaskServiceDep):
    success = await service.delete(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return {"message": "Tarefa excluída com sucesso"}


@task_router.get("/{thread_id}/tasks", response_model=list[TaskResponseSchema])
async def get_pending_tasks(thread_id: str, service: TaskServiceDep):
    return await service.get_pending_by_thread(thread_id)