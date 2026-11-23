"""Rotas de Configurações do Assistente e Controle do Ollama/VRAM (/api/settings)."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.api.settings_store import get_all_settings, update_settings
from backend.graph.task_commit import enabled as autocommit_enabled
from backend.graph.task_commit import set_enabled as set_autocommit_enabled

settings_router = APIRouter()


class SettingsUpdatePayload(BaseModel):
    web_search_enabled: bool | None = None
    assistant_memory_enabled: bool | None = None
    autocommit_enabled: bool | None = None
    audit_tool_timeout: int | None = Field(default=None, ge=0, le=3600)
    audit_chunk_size: int | None = Field(default=None, ge=10, le=200)
    ollama_keep_alive: str | None = Field(default=None, max_length=24)


class OllamaUnloadPayload(BaseModel):
    model: str | None = None


def ollama_base_url() -> str:
    raw = os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
    raw = raw.strip().rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    return raw


def _ollama_request(path: str, payload: dict[str, Any] | None = None, timeout: int = 10) -> dict[str, Any]:
    url = f"{ollama_base_url()}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace").strip()
        return json.loads(body) if body else {}


def _fetch_ollama_ps() -> dict[str, Any]:
    try:
        data = _ollama_request("/api/ps", timeout=5)
    except Exception as exc:  # noqa: BLE001
        return {
            "online": False,
            "base_url": ollama_base_url(),
            "models": [],
            "total_vram_bytes": 0,
            "total_size_bytes": 0,
            "error": str(exc),
        }

    models = []
    total_vram = 0
    total_size = 0
    for item in data.get("models") or []:
        size = int(item.get("size") or 0)
        vram = int(item.get("size_vram") or 0)
        details = item.get("details") or {}
        total_size += size
        total_vram += vram
        models.append(
            {
                "name": str(item.get("name") or item.get("model") or ""),
                "size": size,
                "size_vram": vram,
                "size_ram": max(0, size - vram),
                "expires_at": str(item.get("expires_at") or ""),
                "parameter_size": str(details.get("parameter_size") or ""),
                "quantization_level": str(details.get("quantization_level") or ""),
            }
        )
    return {
        "online": True,
        "base_url": ollama_base_url(),
        "models": models,
        "total_vram_bytes": total_vram,
        "total_size_bytes": total_size,
        "error": None,
    }


def _unload_ollama_models(model_name: str | None = None) -> dict[str, Any]:
    target = (model_name or "").strip()
    if target and target != "*":
        names = [target]
    else:
        ps = _fetch_ollama_ps()
        if not ps["online"]:
            return {"unloaded": [], "failed": {"ollama": ps["error"] or "Ollama offline"}}
        names = [m["name"] for m in ps["models"] if m.get("name")]

    unloaded: list[str] = []
    failed: dict[str, str] = {}
    for name in names:
        try:
            _ollama_request("/api/generate", {"model": name, "prompt": "", "keep_alive": 0}, timeout=15)
            unloaded.append(name)
        except Exception as exc:  # noqa: BLE001
            try:
                _ollama_request("/api/chat", {"model": name, "messages": [], "keep_alive": 0}, timeout=15)
                unloaded.append(name)
            except Exception:  # noqa: BLE001
                failed[name] = str(exc)
    return {"unloaded": unloaded, "failed": failed}


def _current_payload() -> dict[str, Any]:
    data = get_all_settings()
    data["autocommit_enabled"] = autocommit_enabled()
    return {"settings": data, "ollama_base_url": ollama_base_url()}


@settings_router.get("")
@settings_router.get("/")
async def get_settings():
    return _current_payload()


@settings_router.put("")
@settings_router.put("/")
async def put_settings(payload: SettingsUpdatePayload):
    patch = payload.model_dump(exclude_none=True)
    if "autocommit_enabled" in patch:
        set_autocommit_enabled(bool(patch.pop("autocommit_enabled")))
    if patch:
        update_settings(patch)
    return _current_payload()


@settings_router.get("/ollama/ps")
async def get_ollama_ps():
    return await asyncio.to_thread(_fetch_ollama_ps)


@settings_router.post("/ollama/unload")
async def unload_ollama(payload: OllamaUnloadPayload):
    result = await asyncio.to_thread(_unload_ollama_models, payload.model)
    status = await asyncio.to_thread(_fetch_ollama_ps)
    return {**result, "ollama": status}
