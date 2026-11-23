"""Configurações persistentes de autonomia do assistente (Quality Gate, Auto-heal, Auto-plan e Read-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STORE_PATH = Path(__file__).resolve().parents[2] / "autonomy_settings.json"

DEFAULT_AUTONOMY: dict[str, Any] = {
    "auto_plan_tasks": True,
    "auto_heal_failed_tasks": True,
    "max_verify_retries": 3,
    "chat_readonly_mode": False,
}


def get_autonomy_config() -> dict[str, Any]:
    data = dict(DEFAULT_AUTONOMY)
    if _STORE_PATH.is_file():
        try:
            loaded = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update({k: v for k, v in loaded.items() if k in DEFAULT_AUTONOMY})
        except (OSError, ValueError):
            pass
    try:
        retries = int(data.get("max_verify_retries", 3))
    except (TypeError, ValueError):
        retries = 3
    data["max_verify_retries"] = max(1, min(5, retries))
    data["auto_plan_tasks"] = bool(data.get("auto_plan_tasks", True))
    data["auto_heal_failed_tasks"] = bool(data.get("auto_heal_failed_tasks", True))
    data["chat_readonly_mode"] = bool(data.get("chat_readonly_mode", False))
    return data


def update_autonomy_config(updates: dict[str, Any]) -> dict[str, Any]:
    current = get_autonomy_config()
    for key in DEFAULT_AUTONOMY:
        if key in updates and updates[key] is not None:
            current[key] = updates[key]
    try:
        current["max_verify_retries"] = max(1, min(5, int(current["max_verify_retries"])))
    except (TypeError, ValueError):
        current["max_verify_retries"] = 3
    current["auto_plan_tasks"] = bool(current["auto_plan_tasks"])
    current["auto_heal_failed_tasks"] = bool(current["auto_heal_failed_tasks"])
    current["chat_readonly_mode"] = bool(current["chat_readonly_mode"])
    try:
        _STORE_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return current
