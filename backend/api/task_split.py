"""Divisão automática de microtasks grandes em partes menores (sem LLM).

Uma task determinística com muitos passos (ou muito texto) é cortada em partes sequenciais "Título (1/3)", "(2/3)"...
As partes entram no banco em ordem de id, e o despacho já bloqueia as seguintes se uma falhar. Cada parte tem rollback
próprio (o que as partes anteriores aplicaram fica aplicado). As checagens de `verify` vão para a parte que mexeu por último
no arquivo; `pytest` e `literals_grounded` vão para a última parte.

.env (todos opcionais):
  TASK_AUTOSPLIT=1     liga/desliga a divisão (0 desliga)
  TASK_MAX_CHARS=12000 limite de caracteres (JSON dos passos) por parte
  TASK_MAX_STEPS=8     limite de passos por parte
"""
from __future__ import annotations

import difflib
import json
import os
import re

_LAST_GROUP_CHECKS = {"pytest", "literals_grounded"}


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def _norm(path) -> str:
    return str(path or "").replace("\\", "/").strip()


def _size(step: dict) -> int:
    return len(json.dumps(step, ensure_ascii=False))


def group_steps(steps: list[dict], max_chars: int, max_steps: int) -> list[list[dict]]:
    """Agrupa passos em ordem, sem reordenar. Um passo maior que o limite fica sozinho."""
    groups: list[list[dict]] = []
    current: list[dict] = []
    used = 0
    for step in steps:
        size = _size(step)
        if current and (len(current) >= max_steps or used + size > max_chars):
            groups.append(current)
            current, used = [], 0
        current.append(step)
        used += size
    if current:
        groups.append(current)
    return groups


def _last_touch(groups: list[list[dict]]) -> dict[str, int]:
    touched: dict[str, int] = {}
    for index, group in enumerate(groups):
        for step in group:
            path = _norm(step.get("path"))
            if path:
                touched[path] = index
    return touched


def split_task(task: dict, max_chars: int | None = None, max_steps: int | None = None) -> list[dict]:
    """Devolve [task] se não precisa dividir; senão a lista de partes (dicts com os mesmos campos)."""
    steps = list(task.get("steps") or [])
    if not steps or not _flag("TASK_AUTOSPLIT", True):
        return [task]
    limit_chars = max_chars or _int("TASK_MAX_CHARS", 12000)
    limit_steps = max_steps or _int("TASK_MAX_STEPS", 8)
    groups = group_steps([dict(s) for s in steps], limit_chars, limit_steps)
    if len(groups) <= 1:
        return [task]

    total = len(groups)
    last = total - 1
    touched = _last_touch(groups)
    checks: list[list[dict]] = [[] for _ in groups]
    for check in task.get("verify") or []:
        check = dict(check)
        if check.get("type") in _LAST_GROUP_CHECKS:
            checks[last].append(check)
            continue
        checks[touched.get(_norm(check.get("path")), last)].append(check)

    original_files = [_norm(f) for f in (task.get("files") or []) if _norm(f)]
    base_title = str(task.get("title") or "Task")
    parts: list[dict] = []
    for index, group in enumerate(groups):
        paths: list[str] = []
        for item in [*group, *checks[index]]:
            path = _norm(item.get("path"))
            if path and path not in paths:
                paths.append(path)
        ordered = [f for f in original_files if f in paths] + [p for p in paths if p not in original_files]
        part = dict(task)
        part["title"] = f"{base_title} ({index + 1}/{total})"[:255]
        part["description"] = (
            f"[Parte {index + 1}/{total}, dividida automaticamente de '{base_title}']\n" + str(task.get("description") or "")
        )
        part["files"] = ordered or list(task.get("files") or [])
        part["steps"] = group
        part["verify"] = checks[index]
        if index > 0:
            part["code_snippet"] = None
        parts.append(part)
    return parts


def drop_near_duplicates(tasks: list[dict], threshold: float = 0.8) -> tuple[list[dict], list[str]]:
    """Descarta, dentro do mesmo lote, task quase igual a outra anterior (mesmos arquivos, título e descrição muito parecidos).
    Auditoria e partes '(i/n)' nunca são descartadas."""
    kept: list[dict] = []
    dropped: list[str] = []
    for task in tasks:
        title = str(task.get("title") or "").lower()
        files = frozenset(_norm(f) for f in (task.get("files") or []) if _norm(f))
        exempt = title.startswith("auditoria:") or bool(re.search(r"\(\d+/\d+\)\s*$", title))
        duplicate = False
        if files and not exempt:
            text = str(task.get("description") or "").lower()[:1500]
            for other in kept:
                other_files = frozenset(_norm(f) for f in (other.get("files") or []) if _norm(f))
                if other_files != files:
                    continue
                if difflib.SequenceMatcher(None, title, str(other.get("title") or "").lower()).ratio() < 0.6:
                    continue
                if difflib.SequenceMatcher(None, text, str(other.get("description") or "").lower()[:1500]).ratio() >= threshold:
                    duplicate = True
                    break
        if duplicate:
            dropped.append(str(task.get("title") or ""))
        else:
            kept.append(task)
    return kept, dropped


def expand_tasks(tasks_data) -> list[dict]:
    """Recebe modelos pydantic (TaskCreateSchema) ou dicts e devolve dicts prontos para o TaskModel."""
    raw = [item.model_dump() if hasattr(item, "model_dump") else dict(item) for item in tasks_data]
    if _flag("TASK_DEDUPE", True):
        raw, dropped = drop_near_duplicates(raw)
        for title in dropped:
            print(f"[TASKS] duplicata descartada: {title}")
    out: list[dict] = []
    for data in raw:
        out.extend(split_task(data))
    return out
