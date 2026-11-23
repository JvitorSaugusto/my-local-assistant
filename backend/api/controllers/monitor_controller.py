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
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result
