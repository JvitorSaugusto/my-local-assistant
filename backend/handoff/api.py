"""Rotas do pacote de handoff (/api/handoff). Só traduz HTTP para chamadas dos módulos."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .dryrun import dry_run_tasks
from .pack import DEFAULT_BUDGET, build_pack
from .planner import plan_and_check, save_plan
from .primer import build_primer

handoff_router = APIRouter()


class PackRequest(BaseModel):
    path: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    budget_tokens: int = Field(default=DEFAULT_BUDGET, ge=4000, le=120000)
    instructions: str | None = None
    thread_id: str | None = None


class DryRunRequest(BaseModel):
    path: str = Field(min_length=1)
    tasks: list[dict] = Field(min_length=1)
    thread_id: str | None = None


@handoff_router.get("/primer")
async def primer(path: str, max_tokens: int = 2000, thread_id: str | None = None):
    """Primer do projeto em markdown (~2k tokens), para abrir um chat novo numa IA externa."""
    try:
        return await build_primer(path, max(500, min(max_tokens, 8000)), thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erro ao gerar o primer: {exc}") from exc


@handoff_router.post("/pack")
async def pack(payload: PackRequest):
    """Um único .md com problema + primer + arquivos + trechos do RAG, mascarado e dentro do orçamento."""
    try:
        return await build_pack(
            payload.path, payload.problem, payload.files, payload.budget_tokens, payload.instructions, payload.thread_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erro ao montar o pacote: {exc}") from exc


@handoff_router.get("/packs/{name}")
async def download_pack(name: str):
    """Baixa um pacote .md gerado pelo chat (só da pasta de pacotes, sem caminhos)."""
    from fastapi.responses import FileResponse

    from backend.graph.ops_core import pack_file_path

    path = pack_file_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="Pacote não encontrado.")
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=path.name)


@handoff_router.post("/dryrun")
async def dryrun(payload: DryRunRequest):
    """Aplica as tasks numa cópia temporária (executor real) e devolve um relatório curto; não altera o projeto."""
    try:
        return await dry_run_tasks(payload.path, payload.tasks, thread_id=payload.thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erro no dry-run: {exc}") from exc


class PlanRequest(BaseModel):
    path: str = Field(min_length=1)
    task: dict
    task_id: int | None = None
    save: bool = False


@handoff_router.post("/plan")
async def plan(payload: PlanRequest):
    """Planejador local: o modelo indica linhas e texto novo, o sistema monta os steps e valida com dry-run.

    Com save=true e task_id, grava steps/verify na task (se o plano passou) para o @generate executá-la sem LLM.
    """
    try:
        result = await plan_and_check(payload.path, payload.task)
        result["saved"] = False
        if payload.save and payload.task_id and result["ok"]:
            result["saved"] = await save_plan(payload.task_id, result["task"]["steps"], result["task"]["verify"])
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erro no planejador: {exc}") from exc
