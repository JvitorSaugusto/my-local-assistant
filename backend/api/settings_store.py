"""Preferências persistidas do assistente em JSON (aplicadas em tempo real, sem reiniciar o servidor)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_MEMORY_CACHE: dict[str, Any] = {}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "on", "yes", "sim")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def settings_file_path() -> Path | None:
    custom = os.getenv("ASSISTANT_SETTINGS_FILE", "").strip()
    if custom:
        return Path(custom)
    if os.getenv("PYTEST_CURRENT_TEST"):
        return None
    return Path.home() / ".assistente_local" / "settings.json"


def _defaults() -> dict[str, Any]:
    return {
        "web_search_enabled": _env_bool("WEB_SEARCH_ENABLED", True),
        "assistant_memory_enabled": _env_bool("ASSISTANT_MEMORY", True),
        "audit_tool_timeout": _env_int("AUDIT_TOOL_TIMEOUT", 180),
        "audit_chunk_size": max(10, min(_env_int("AUDIT_CHUNK_SIZE", 40), 200)),
        "ollama_keep_alive": os.getenv("OLLAMA_KEEP_ALIVE_APP", "15m").strip() or "15m",
    }


def _read_overrides() -> dict[str, Any]:
    path = settings_file_path()
    if path is None:
        return dict(_MEMORY_CACHE)
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_overrides(data: dict[str, Any]) -> None:
    path = settings_file_path()
    if path is None:
        _MEMORY_CACHE.clear()
        _MEMORY_CACHE.update(data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def get_all_settings() -> dict[str, Any]:
    with _LOCK:
        merged = _defaults()
        overrides = _read_overrides()
        for key in merged:
            if key in overrides and overrides[key] is not None:
                merged[key] = overrides[key]
        return merged


def get_setting(key: str, default: Any = None) -> Any:
    return get_all_settings().get(key, default)


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        overrides = _read_overrides()
        if "web_search_enabled" in patch and patch["web_search_enabled"] is not None:
            overrides["web_search_enabled"] = bool(patch["web_search_enabled"])
        if "assistant_memory_enabled" in patch and patch["assistant_memory_enabled"] is not None:
            overrides["assistant_memory_enabled"] = bool(patch["assistant_memory_enabled"])
        if "audit_tool_timeout" in patch and patch["audit_tool_timeout"] is not None:
            val = int(patch["audit_tool_timeout"])
            overrides["audit_tool_timeout"] = max(0, min(val, 3600))
        if "audit_chunk_size" in patch and patch["audit_chunk_size"] is not None:
            val = int(patch["audit_chunk_size"])
            overrides["audit_chunk_size"] = max(10, min(val, 200))
        if "ollama_keep_alive" in patch and patch["ollama_keep_alive"] is not None:
            raw = str(patch["ollama_keep_alive"]).strip()[:24]
            if raw:
                overrides["ollama_keep_alive"] = raw
        _write_overrides(overrides)
    return get_all_settings()
