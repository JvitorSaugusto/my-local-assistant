"""Planejador local (Fase D): o modelo escolhe LINHAS e texto novo; o sistema preenche o `old` por código.

Fluxo: dossiê (arquivos com linhas numeradas) -> LLM devolve edições {arquivo, linhas, texto novo} ->
o sistema lê o arquivo real e monta os `steps` (replace_text com `old` EXATO, ampliado até ser único) ->
dry-run numa cópia com o executor real -> se falhar, o relatório volta ao modelo (até MAX_RETRIES vezes).
O modelo nunca escreve `old`, que é onde modelos locais mais erram. Só o texto NOVO vem do modelo.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .dryrun import dry_run_tasks
from .repair import repair_steps
from .pack import _dossier_body

MAX_RETRIES = 2
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_MAX_EXPAND = 8


class Edit(BaseModel):
    kind: Literal["replace_lines", "insert_after", "create_file"] = Field(
        description="replace_lines: troca (ou apaga, se new_text vazio) as linhas start_line..end_line. "
        "insert_after: insere new_text depois da linha start_line. create_file: cria arquivo novo com new_text."
    )
    path: str = Field(description="Caminho relativo ao projeto, com / (ex.: backend/main.py).")
    start_line: int = Field(default=0, description="Primeira linha (numeração mostrada no arquivo). Ignorado em create_file.")
    end_line: int = Field(default=0, description="Última linha, inclusive. Só em replace_lines.")
    new_text: str = Field(default="", description="Texto novo SEM numeração de linha e com a indentação exata.")


class Plan(BaseModel):
    branch: str = Field(default="", description="Nome curto da branch, ex.: fix/cache-front.")
    edits: list[Edit] = Field(default_factory=list)
    missing: str = Field(default="", description="Se faltar contexto para planejar, diga o que falta e deixe edits vazio.")


PLANNER_PROMPT = """Você é um planejador de edições de código. Recebe uma tarefa e os arquivos com linhas numeradas (`N: texto`).
Devolva as edições como linhas + texto novo. Você NÃO escreve o texto antigo: o sistema o lê do arquivo.

REGRAS
- Use SOMENTE números de linha que aparecem nos arquivos mostrados. Não chute linhas que não viu.
- replace_lines: troca as linhas start_line..end_line (inclusive); new_text vazio apaga.
- insert_after: insere new_text DEPOIS da linha start_line.
- create_file: só para arquivo que ainda não existe; new_text é o conteúdo inteiro.
- new_text NÃO leva o prefixo `N: ` e deve ter a indentação exata do código ao redor (Python: 4 espaços).
- Uma edição = um trecho contíguo. Edições do mesmo arquivo não podem se sobrepor.
- Faça a menor mudança que cumpre a tarefa; não reescreva trechos que não precisam mudar.
- Se faltar contexto (arquivo/trecho não mostrado), deixe edits vazio e explique em `missing`."""


def _slug(title: str) -> str:
    ascii_title = re.sub(r"[^a-z0-9]+", "-", title.lower().encode("ascii", "ignore").decode()).strip("-")
    return f"feat/{ascii_title[:40] or 'task'}"


def _norm_read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _first_signature(text: str) -> str | None:
    for line in text.split("\n"):
        if len(line.strip()) >= 12:
            return line.strip()
    return None


def build_steps(workspace: str, plan: Plan, allowed: set[str], title: str = "") -> tuple[list[dict], list[dict], list[str]]:
    """(steps, verify, erros). `old` sai SEMPRE do arquivo real."""
    root = Path(workspace).resolve()
    errors: list[str] = []
    per_file: dict[str, list[tuple[int, int, Edit]]] = {}
    creates: list[Edit] = []

    for number, edit in enumerate(plan.edits, start=1):
        rel = edit.path.strip().replace("\\", "/")
        try:
            target = (root / rel).resolve()
            target.relative_to(root)
        except ValueError:
            errors.append(f"edição {number}: caminho fora do projeto: {rel!r}")
            continue
        if edit.kind == "create_file":
            if target.exists():
                errors.append(f"edição {number}: '{rel}' já existe; use replace_lines/insert_after.")
            elif not edit.new_text.strip():
                errors.append(f"edição {number}: create_file sem conteúdo.")
            else:
                creates.append(edit.model_copy(update={"path": rel}))
            continue
        if rel not in allowed:
            errors.append(f"edição {number}: '{rel}' não está nos arquivos da tarefa mostrados ({', '.join(sorted(allowed)) or 'nenhum'}).")
            continue
        if not target.is_file():
            errors.append(f"edição {number}: '{rel}' não existe.")
            continue
        start = edit.start_line
        end = edit.end_line if edit.kind == "replace_lines" else edit.start_line
        per_file.setdefault(rel, []).append((start, end, edit.model_copy(update={"path": rel})))

    steps: list[dict] = []
    verify: list[dict] = []
    touched_py: list[str] = []

    for rel, items in per_file.items():
        text = _norm_read(root / rel)
        lines = text.splitlines(keepends=True)
        total = len(lines)
        items.sort(key=lambda it: (it[0], it[1]))
        for number, (start, end, edit) in enumerate(items, start=1):
            if start < 1 or end < start or end > total:
                errors.append(f"{rel}: intervalo de linhas inválido ({start}-{end}); o arquivo tem {total} linhas.")
        for (s1, e1, _), (s2, e2, _) in zip(items, items[1:]):
            if s2 <= e1:
                errors.append(f"{rel}: edições se sobrepõem nas linhas {s1}-{e1} e {s2}-{e2}.")
        if errors:
            continue

        ranges = [(s, e) for s, e, _ in items]
        for index, (start, end, edit) in enumerate(items):
            first, last = start, end
            new_body = edit.new_text.replace("\r\n", "\n")
            if edit.kind == "insert_after":
                new_body = new_body if new_body.endswith("\n") or not new_body else new_body + "\n"
            elif new_body and not new_body.endswith("\n") and lines[last - 1].endswith("\n"):
                new_body += "\n"
            before_extra = after_extra = ""
            old = "".join(lines[first - 1 : last])
            new = (old + new_body) if edit.kind == "insert_after" else new_body
            if edit.kind == "insert_after" and not old.endswith("\n"):
                old_for_insert = old
                new = old_for_insert + "\n" + new_body.rstrip("\n")
            # amplia com linhas vizinhas até o `old` ser único no arquivo
            grow = 0
            while text.count(old) > 1 and grow < _MAX_EXPAND:
                grow += 1
                lo_ok = first > 1 and not any(s <= first - 1 <= e for k, (s, e) in enumerate(ranges) if k != index)
                hi_ok = last < total and not any(s <= last + 1 <= e for k, (s, e) in enumerate(ranges) if k != index)
                if grow % 2 and lo_ok:
                    first -= 1
                    before_extra = lines[first - 1] + before_extra
                elif hi_ok:
                    last += 1
                    after_extra += lines[last - 1]
                elif lo_ok:
                    first -= 1
                    before_extra = lines[first - 1] + before_extra
                else:
                    break
                old = "".join(lines[first - 1 : last])
            if text.count(old) != 1:
                errors.append(f"{rel}: não foi possível tornar único o trecho das linhas {start}-{end}; indique linhas mais específicas.")
                continue
            new = before_extra + new + after_extra
            steps.append({"op": "replace_text", "path": rel, "old": old, "new": new, "occurrences": "one"})
            sig = _first_signature(new_body)
            if sig and sig not in (old or ""):
                verify.append({"type": "contains", "path": rel, "text": sig})
        if rel.endswith(".py"):
            touched_py.append(rel)

    for edit in creates:
        steps.append({"op": "create_file", "path": edit.path, "content": edit.new_text})
        if edit.path.endswith(".py"):
            touched_py.append(edit.path)
        verify.append({"type": "file_exists", "path": edit.path})

    verify += [{"type": "python_syntax", "path": p} for p in dict.fromkeys(touched_py)]
    branch = plan.branch.strip()
    if not _BRANCH_RE.match(branch) or ".." in branch or branch in {"main", "master"}:
        branch = _slug(title)
    if steps:
        if os.getenv("HANDOFF_PLAN_CREATE_BRANCH", "") == "1":
            steps.insert(0, {"op": "create_branch", "branch": branch})
    return steps, verify, errors


def _default_llm():
    from backend.graph.config import generate_llm  # mesmo modelo/ctx do Generate: sem recarga no Ollama

    return generate_llm.with_structured_output(Plan)


async def _try_repair(workspace: str, task: dict, runner: Any | None, thread_id: str | None) -> dict | None:
    """Antes de chamar o LLM: se a task já tem steps, conserta por código os `old` que não batem."""
    steps = task.get("steps") or []
    if not steps:
        return None
    fixed, notes = repair_steps(workspace, steps)
    if not notes:
        return None
    candidate = {**task, "steps": fixed, "verify": task.get("verify") or []}
    dry = await dry_run_tasks(workspace, [candidate], runner=runner, thread_id=thread_id)
    if not dry["ok"]:
        return None
    return {"ok": True, "attempts": 0, "task": candidate, "report": dry["report"], "error": "", "repaired": notes}


async def plan_and_check(
    workspace: str,
    task: dict,
    llm: Any | None = None,
    runner: Any | None = None,
    max_retries: int = MAX_RETRIES,
    thread_id: str | None = None,
) -> dict:
    """Devolve {ok, task (com steps/verify), attempts, report, error}. Não altera o projeto."""
    from backend.graph.context_builder import build_task_dossier  # import tardio

    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Pasta não encontrada: {workspace}")
    title = str(task.get("title") or "").strip()
    if not title or not str(task.get("description") or "").strip():
        raise ValueError("A task precisa de title e description.")
    files = [str(f).strip().replace("\\", "/") for f in (task.get("files") or []) if str(f).strip()]
    repaired = await _try_repair(str(root), task, runner, thread_id)
    if repaired is not None:
        return repaired
    model = llm or _default_llm()

    dossier, _report = await asyncio.to_thread(build_task_dossier, str(root), files, 36_000, 14_000, 8_000)
    allowed = {f for f in files if (root / f).is_file()}
    header = (
        f"TAREFA: {title}\n\nDESCRIÇÃO:\n{task.get('description')}\n\nMOTIVO:\n{task.get('reason') or '-'}\n\n"
        f"ARQUIVOS: {', '.join(files) or '(nenhum)'}\n\n"
    )
    messages: list[Any] = [("system", PLANNER_PROMPT), ("human", header + (_dossier_body(dossier) if dossier else "(sem arquivos visíveis)"))]

    result: dict = {"ok": False, "attempts": 0, "task": dict(task), "report": "", "error": ""}
    for attempt in range(1, max_retries + 2):
        result["attempts"] = attempt
        plan = await model.ainvoke(messages)
        if isinstance(plan, dict):
            plan = Plan.model_validate(plan)
        if not plan.edits:
            result["error"] = plan.missing.strip() or "O modelo não propôs nenhuma edição."
            return result

        steps, verify, errors = build_steps(str(root), plan, allowed, title)
        if errors:
            feedback = "O plano foi rejeitado antes de executar:\n" + "\n".join(f"- {e}" for e in errors)
        else:
            candidate = {**task, "steps": steps, "verify": verify}
            dry = await dry_run_tasks(str(root), [candidate], runner=runner, thread_id=thread_id)
            result["report"] = dry["report"]
            if dry["ok"]:
                result.update(ok=True, task=candidate, error="")
                return result
            feedback = "O dry-run falhou:\n" + dry["report"]
        result["error"] = feedback
        messages += [("ai", plan.model_dump_json()), ("human", feedback + "\n\nCorrija e devolva o plano COMPLETO de novo (mesmas regras).")]
    return result


async def save_plan(task_id: int, steps: list[dict], verify: list[dict]) -> bool:
    """Grava steps/verify na task (pending/failed -> pending) para o @generate executá-la sem LLM."""
    from sqlalchemy import update

    from backend.database.config import async_session_env
    from backend.database.models import TaskModel

    async with async_session_env() as db:
        res = await db.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id, TaskModel.status.in_(("pending", "failed")))
            .values(steps=steps, verify=verify, status="pending", last_error=None)
        )
        await db.commit()
        return (res.rowcount or 0) > 0  # type: ignore[attr-defined]
