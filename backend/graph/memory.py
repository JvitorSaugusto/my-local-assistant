"""Memória do usuário: fatos que ele pediu para lembrar ("lembre que eu uso Windows", "meu projeto é X").

Fica em um JSON (ASSISTANT_MEMORY_FILE; padrão <raiz do projeto>/data/user_memory.json), com escrita atômica.
O bloco de memórias entra no contexto dos modos standard/code/notas/enhance. Desligar: ASSISTANT_MEMORY=0.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

MAX_ITEMS = 100
MAX_CHARS = 240
_LOCK = threading.Lock()


def enabled() -> bool:
    return os.getenv("ASSISTANT_MEMORY", "1") == "1"


def _path() -> Path:
    custom = os.getenv("ASSISTANT_MEMORY_FILE")
    return Path(custom) if custom else Path(__file__).resolve().parents[2] / "data" / "user_memory.json"


def _load() -> list[dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return [i for i in data if isinstance(i, dict) and i.get("text")] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def list_all() -> list[dict]:
    with _LOCK:
        return _load()


def add(text: str) -> tuple[dict | None, str]:
    """(item, mensagem). Evita duplicados e respeita os limites."""
    fact = re.sub(r"\s+", " ", text or "").strip()
    if len(fact) < 3:
        return None, "Fato vazio demais para guardar."
    if len(fact) > MAX_CHARS:
        fact = fact[: MAX_CHARS - 1].rstrip() + "…"
    with _LOCK:
        items = _load()
        for item in items:
            if item["text"].lower() == fact.lower():
                return item, f"Já estava guardado (#{item['id']})."
        if len(items) >= MAX_ITEMS:
            return None, f"Memória cheia ({MAX_ITEMS} itens). Peça para esquecer algum antes."
        item = {"id": max((i["id"] for i in items), default=0) + 1, "text": fact, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        items.append(item)
        _save(items)
        return item, f"Guardado (#{item['id']}): {fact}"


def remove(item_id: int) -> bool:
    with _LOCK:
        items = _load()
        kept = [i for i in items if i["id"] != item_id]
        if len(kept) == len(items):
            return False
        _save(kept)
        return True


def prompt_block(max_chars: int = 1500) -> str:
    """Bloco para o contexto de sistema ('' se desligado ou vazio)."""
    if not enabled():
        return ""
    items = list_all()
    if not items:
        return ""
    lines: list[str] = []
    used = 0
    for item in reversed(items):  # mais recentes primeiro quando faltar espaço
        line = f"- [{item['id']}] {item['text']}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    lines.reverse()
    return "MEMÓRIAS DO USUÁRIO (fatos que ele pediu para lembrar; use com naturalidade, sem recitar):\n" + "\n".join(lines)
