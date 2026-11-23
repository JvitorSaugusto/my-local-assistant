import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from backend.api.services import TaskService
from backend.api.schemas import TaskBulkDeleteSchema, TaskCreateSchema, TaskResponseSchema
from backend.database.config import get_db
from pydantic import BaseModel
from backend.graph.context_builder import task_changes
from backend.graph.task_commit import enabled as autocommit_enabled, set_enabled as set_autocommit_enabled
from backend.graph.task_journal import journal_diff, journal_revert


class AutoCommitPayload(BaseModel):
    enabled: bool


task_router = APIRouter()

async def get_task_service(db: Annotated[AsyncSession, Depends(get_db)]) -> TaskService:
    return TaskService(db)

TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]


@task_router.get("/autocommit")
async def get_autocommit_status():
    return {"enabled": autocommit_enabled()}


@task_router.put("/autocommit")
async def update_autocommit_status(payload: AutoCommitPayload):
    return {"enabled": set_autocommit_enabled(payload.enabled)}


class AutonomyConfigPayload(BaseModel):
    auto_plan_tasks: bool | None = None
    auto_heal_failed_tasks: bool | None = None
    max_verify_retries: int | None = None
    chat_readonly_mode: bool | None = None


@task_router.get("/autonomy")
async def get_autonomy_settings():
    from backend.graph.autonomy_config import get_autonomy_config

    return {"autonomy": get_autonomy_config()}


@task_router.put("/autonomy")
async def put_autonomy_settings(payload: AutonomyConfigPayload):
    from backend.graph.autonomy_config import update_autonomy_config

    return {"autonomy": update_autonomy_config(payload.model_dump(exclude_none=True))}


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



class AutoPlanPayload(BaseModel):
    workspace_path: str


@task_router.post("/{task_id}/heal", response_model=TaskResponseSchema)
async def heal_failed_task(task_id: int, service: TaskServiceDep):
    """Prepara uma task que falhou para auto-correção pela IA, injetando o erro anterior na descrição."""
    task = await service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    if task.status not in ("failed", "review"):
        raise HTTPException(status_code=409, detail="Apenas tarefas com falha ou em revisão podem ser enviadas para correção.")

    err = (task.last_error or "").strip()
    desc = (task.description or "").strip()
    marker = "**Erro da tentativa anterior (corrigir automaticamente):**"
    if err and marker not in desc:
        desc = f"{desc}\n\n{marker}\n```text\n{err[:1500]}\n```".strip()

    updated = await service.update(
        task_id,
        {
            "status": "pending",
            "last_error": None,
            "description": desc,
            "steps": [],
        },
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return updated


@task_router.post("/{thread_id}/auto-plan")
async def auto_plan_pending_tasks(thread_id: str, payload: AutoPlanPayload, service: TaskServiceDep):
    """Analisa tasks pendentes sem steps: planeja as elegíveis com dry-run e mantém as demais no modo livre."""
    from pathlib import Path

    workspace = (payload.workspace_path or "").strip()
    if not workspace or not Path(workspace).expanduser().is_dir():
        raise HTTPException(status_code=400, detail="Informe um workspace válido para planejar.")

    tasks = await service.get_by_thread(thread_id, status="pending")
    planned: list[int] = []
    kept_free: list[dict] = []
    root = Path(workspace).expanduser().resolve()

    for task in tasks:
        if task.steps:
            continue
        files = [str(f).strip() for f in (task.files or []) if str(f).strip()]
        existing = [f for f in files if (root / f).is_file()]
        is_doc_only = bool(files) and all(Path(f).suffix.lower() in {".md", ".txt", ".pdf"} for f in files)
        if not existing or len(files) > 3 or is_doc_only:
            kept_free.append({"id": task.id, "reason": "elegível para modo livre (doc/criação/muitos arquivos)"})
            continue

        try:
            from backend.handoff.planner import plan_task

            res = await asyncio.to_thread(
                plan_task,
                str(root),
                {
                    "title": task.title,
                    "description": task.description,
                    "reason": task.reason or "",
                    "files": files,
                    "priority": task.priority or "medium",
                    "steps": [],
                    "verify": task.verify or [],
                },
            )
            if res.get("ok") and (res.get("task") or {}).get("steps"):
                await service.update(
                    task.id,
                    {
                        "steps": res["task"]["steps"],
                        "verify": res["task"].get("verify") or task.verify or [],
                    },
                )
                planned.append(task.id)
            else:
                kept_free.append({"id": task.id, "reason": "dry-run não passou; mantida no modo livre"})
        except Exception as exc:  # noqa: BLE001
            kept_free.append({"id": task.id, "reason": f"mantida no modo livre ({exc})"})

    return {"planned": planned, "kept_free": kept_free}


@task_router.get("/{thread_id}/checkpoint")
async def get_batch_checkpoint(thread_id: str):
    from backend.graph.batch_checkpoint import get_checkpoint

    return {"checkpoint": get_checkpoint(thread_id)}


@task_router.post("/{thread_id}/checkpoint/rollback")
async def rollback_batch_checkpoint(thread_id: str):
    from backend.graph.batch_checkpoint import rollback_checkpoint

    try:
        return await asyncio.to_thread(rollback_checkpoint, thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
