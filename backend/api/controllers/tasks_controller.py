import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from backend.api.services import TaskService
from backend.api.schemas import TaskBulkDeleteSchema, TaskCreateSchema, TaskResponseSchema
from backend.database.config import get_db
from backend.graph.context_builder import task_changes
from backend.graph.task_journal import journal_diff, journal_revert


task_router = APIRouter()

async def get_task_service(db: Annotated[AsyncSession, Depends(get_db)]) -> TaskService:
    return TaskService(db)

TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]

@task_router.post("/{thread_id}", response_model=list[TaskResponseSchema], status_code=201)
async def create_tasks(tasks_data: list[TaskCreateSchema], thread_id: str, service: TaskServiceDep):
    return await service.create(tasks_data, thread_id)

@task_router.get("/", response_model=list[TaskResponseSchema])
async def list_tasks(service: TaskServiceDep):
    return await service.get_all()


@task_router.put("/{task_id}", response_model=TaskResponseSchema)
async def update_task(task_id: int, updates: dict, service: TaskServiceDep):
    try:
        task = await service.update(task_id, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
async def get_thread_tasks(thread_id: str, service: TaskServiceDep, status: str | None = None):
    """Todas as tarefas da conversa. Use ?status=pending para filtrar."""
    return await service.get_by_thread(thread_id, status)


@task_router.post("/{task_id}/retry", response_model=TaskResponseSchema)
async def retry_task(task_id: int, service: TaskServiceDep):
    """Reinicia uma tarefa que falhou (volta para 'pending')."""
    try:
        task = await service.retry(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task


@task_router.post("/bulk/delete")
async def bulk_delete_tasks(payload: TaskBulkDeleteSchema, service: TaskServiceDep):
    """Exclui várias tarefas de uma vez. Tarefas em execução são ignoradas e listadas em 'skipped'."""
    return await service.delete_many(payload.ids)



@task_router.get("/{task_id}/diff")
async def task_diff(task_id: int, workspace: str, service: TaskServiceDep):
    """Alterações dos arquivos da tarefa (git diff + arquivos novos), para revisão humana."""
    task = await service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    if not workspace.strip():
        raise HTTPException(status_code=400, detail="Informe o diretório de trabalho (workspace).")
    from_journal = await asyncio.to_thread(journal_diff, workspace, task_id)
    if from_journal is not None:
        return from_journal
    return await asyncio.to_thread(task_changes, workspace, list(task.files or []))


@task_router.post("/{task_id}/revert")
async def revert_task(task_id: int, workspace: str, service: TaskServiceDep):
    """Desfaz no disco as alterações feitas por uma task em modo dinâmico (usa o diário de alterações)."""
    task = await service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    if not workspace.strip():
        raise HTTPException(status_code=400, detail="Informe o diretório de trabalho (workspace).")
    outcome = await asyncio.to_thread(journal_revert, workspace, task_id)
    if outcome is None:
        raise HTTPException(
            status_code=404,
            detail="Não há diário de alterações para esta tarefa (não rodou em modo dinâmico, já foi aprovada ou já foi desfeita).",
        )
    return outcome
