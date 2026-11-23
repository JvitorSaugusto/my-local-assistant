"""Rotas do Monitor Docker Compose e Testador de Rotas Locais (/api/monitor)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.docker_monitor import monitor_manager
from backend.graph.dev_tools import run_local_route_suite

monitor_router = APIRouter()


class MonitorStartPayload(BaseModel):
    workspace_path: str = Field(min_length=1)
    thread_id: str = ""
    auto_diagnose: bool = True


class MonitorStopPayload(BaseModel):
    workspace_path: str = Field(min_length=1)


class RouteTestPayload(BaseModel):
    base_url: str = Field(min_length=1)
    routes: str = ""
    timeout: int = Field(default=8, ge=1, le=30)
    auth_header: str = ""


@monitor_router.get("/status")
async def get_monitor_status(workspace_path: str = ""):
    return monitor_manager.status_all(workspace_path)


@monitor_router.post("/start")
async def start_monitor(payload: MonitorStartPayload, request: Request):
    app_graph = getattr(request.app.state, "compiled_graph", None)
    try:
        info = await monitor_manager.start(
            payload.workspace_path,
            payload.thread_id,
            auto_diagnose=payload.auto_diagnose,
            app_graph=app_graph,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"monitor": info}


@monitor_router.post("/stop")
async def stop_monitor(payload: MonitorStopPayload):
    return await monitor_manager.stop(payload.workspace_path)


@monitor_router.post("/build")
async def build_monitor(payload: MonitorStartPayload, request: Request):
    app_graph = getattr(request.app.state, "compiled_graph", None)
    try:
        return await monitor_manager.run_build(payload.workspace_path, payload.thread_id, app_graph=app_graph)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@monitor_router.post("/test-routes")
async def test_routes(payload: RouteTestPayload):
    result = await asyncio.to_thread(
        run_local_route_suite,
        payload.base_url,
        payload.routes,
        payload.timeout,
        payload.auth_header,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class GitCommitPayload(BaseModel):
    workspace_path: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=300)


def _run_git(workspace_path: str, args: list[str], timeout: int = 20) -> tuple[int, str, str]:
    import subprocess
    from pathlib import Path

    root = Path(workspace_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Diretório não encontrado: {workspace_path}")
    done = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )
    return done.returncode, (done.stdout or "").rstrip("\r\n"), (done.stderr or "").strip()


@monitor_router.get("/git/status")
async def git_quick_status(workspace_path: str):
    if not workspace_path or not workspace_path.strip():
        raise HTTPException(status_code=400, detail="Informe workspace_path.")
    try:
        rc_b, branch, err_b = await asyncio.to_thread(_run_git, workspace_path, ["branch", "--show-current"])
        if rc_b != 0:
            raise ValueError(err_b or "Diretório não é um repositório Git.")
        rc_s, status_out, err_s = await asyncio.to_thread(_run_git, workspace_path, ["status", "--short"])
        if rc_s != 0:
            raise ValueError(err_s or "Falha ao ler git status.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erro ao executar git: {exc}") from exc

    files = []
    for line in status_out.splitlines():
        if len(line) >= 4:
            files.append({"status": line[:2].strip() or "?", "path": line[3:].strip()})
    return {"branch": branch or "(detached)", "files": files, "clean": len(files) == 0}


@monitor_router.get("/git/diff")
async def git_quick_diff(workspace_path: str, file: str = ""):
    if not workspace_path or not workspace_path.strip():
        raise HTTPException(status_code=400, detail="Informe workspace_path.")
    args = ["diff", "HEAD"]
    if file.strip():
        args.extend(["--", file.strip()])
    try:
        rc, out, err = await asyncio.to_thread(_run_git, workspace_path, args)
        if rc != 0 and "unknown revision" in err.lower():
            rc, out, err = await asyncio.to_thread(_run_git, workspace_path, ["diff"] + (["--", file.strip()] if file.strip() else []))
        if rc != 0:
            raise ValueError(err or "Falha ao gerar git diff.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erro ao executar git diff: {exc}") from exc

    truncated = False
    if len(out) > 25000:
        out = out[:25000].rstrip() + "\n\n[... diff cortado em 25 KB ...]"
        truncated = True
    return {"diff": out or "(sem alterações rastreadas no diff)", "truncated": truncated}


@monitor_router.post("/git/commit")
async def git_quick_commit(payload: GitCommitPayload):
    msg = payload.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Informe uma mensagem de commit.")
    try:
        rc_a, _, err_a = await asyncio.to_thread(_run_git, payload.workspace_path, ["add", "-A"])
        if rc_a != 0:
            raise ValueError(err_a or "Falha no git add.")
        rc_c, out_c, err_c = await asyncio.to_thread(_run_git, payload.workspace_path, ["commit", "-m", msg])
        if rc_c != 0:
            detail = (err_c or out_c or "Nada para commitar.").strip()
            raise ValueError(detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erro ao commitar: {exc}") from exc
    return {"committed": True, "output": out_c}
