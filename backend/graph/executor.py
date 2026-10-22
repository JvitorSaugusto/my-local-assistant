"""Executor determinístico de microtasks (sem LLM).

Uma microtask traz `steps` (operações exatas) e, opcionalmente, `verify`
(verificações pós-execução). Aqui os passos são aplicados em ordem; o primeiro
que falhar interrompe a tarefa, que fica `failed` com o motivo detalhado.

Propriedades importantes:
- IDEMPOTENTE: reexecutar uma tarefa que falhou no meio é seguro. Passos já
  aplicados são detectados e pulados ("skipped"), então "Reiniciar" continua
  de onde parou.
- SEGURO: reaproveita os mesmos guardas das tools (branch main/master
  bloqueada, validação de Python antes de gravar) e confina tudo ao workspace.
- SEM DELETE: não existe operação de remoção de arquivo.
"""

from __future__ import annotations

import ast
import asyncio
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import TypeAdapter, ValidationError

from backend.api.schemas import TaskCheck, TaskStep

from .tools import (
    PROTECTED_BRANCHES,
    _confined_path,
    _read_text_keep_newline,
    append_to_file,
    apply_create_pdf,
    apply_replace_text,
    apply_write_markdown,
    create_new_file,
)

_STEPS_ADAPTER = TypeAdapter(list[TaskStep])
_CHECKS_ADAPTER = TypeAdapter(list[TaskCheck])

_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

# Um repositório por vez: evita duas execuções trocando de branch ao mesmo tempo.
_REPO_LOCKS: dict[str, threading.Lock] = {}
_REPO_LOCKS_GUARD = threading.Lock()


def _lock_for(workspace: str) -> threading.Lock:
    key = str(Path(workspace).resolve())
    with _REPO_LOCKS_GUARD:
        return _REPO_LOCKS.setdefault(key, threading.Lock())


@dataclass
class TaskRunResult:
    ok: bool
    error: str | None = None
    failed_step: int | None = None  # 1-indexado
    log: list[dict[str, Any]] = field(default_factory=list)

    def report(self) -> str:
        icons = {"ok": "✅", "skipped": "⏭️", "failed": "❌"}
        lines = [
            f"{icons.get(item['status'], '•')} passo {item['index']}/{item['total']} "
            f"({item['label']}): {item['detail']}"
            for item in self.log
        ]
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# Utilidades
# ──────────────────────────────────────────────────────────────────────────

def _runtime(workspace: str) -> SimpleNamespace:
    """Stand-in de ToolRuntime: as tools só leem `runtime.state`."""
    return SimpleNamespace(state={"workspace_path": workspace, "messages": []})


def _git(workspace: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _classify(result: str) -> str:
    """Converte o texto devolvido pelas tools em ok | skipped | failed."""
    head = result.lstrip().upper()
    if head.startswith("ERRO"):
        return "failed"
    if head.startswith("NADA A FAZER"):
        return "skipped"
    return "ok"


def _normalized(path: Path) -> str | None:
    try:
        text, _ = _read_text_keep_newline(path)
        return text
    except (OSError, UnicodeDecodeError):
        return None


def _same_path(a: str, b: str) -> bool:
    return os.path.normpath(a.strip()) == os.path.normpath(b.strip())


def _modified_later(path: str, later_steps: list[Any]) -> bool:
    """True se algum passo POSTERIOR da mesma tarefa altera este arquivo.

    Necessário para a idempotência: ao reiniciar, um `create_file` encontra o
    arquivo já alterado pelos passos seguintes (append/replace_text) e isso é
    esperado, não um conflito. Cada passo posterior verifica o próprio efeito.
    """
    return any(
        getattr(step, "op", "") in {"append", "replace_text", "write_markdown"}
        and _same_path(getattr(step, "path", ""), path)
        for step in later_steps
    )


def _label(step: Any) -> str:
    path = getattr(step, "path", None) or getattr(step, "branch", "")
    return f"{step.op} {path}".strip()


# ──────────────────────────────────────────────────────────────────────────
# Passos
# ──────────────────────────────────────────────────────────────────────────

def _step_create_branch(workspace: str, branch: str) -> tuple[str, str]:
    repo = Path(workspace).resolve()

    if not (repo / ".git").exists():
        return "failed", f"'{workspace}' não é a raiz de um repositório git."

    try:
        current = _git(workspace, "branch", "--show-current").stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return "failed", f"não foi possível consultar o git: {exc}"

    if current and current not in PROTECTED_BRANCHES:
        return "skipped", f"já está na branch de trabalho '{current}' (reaproveitada)."

    if branch in PROTECTED_BRANCHES or not _BRANCH_RE.match(branch) or ".." in branch:
        return "failed", f"nome de branch inválido ou protegido: '{branch}'."

    created = _git(workspace, "checkout", "-b", branch)
    if created.returncode == 0:
        return "ok", f"branch '{branch}' criada e ativada."

    if "already exists" in created.stderr:
        switched = _git(workspace, "checkout", branch)
        if switched.returncode == 0:
            return "ok", f"branch '{branch}' já existia e foi ativada."
        return "failed", f"não foi possível ativar '{branch}': {switched.stderr.strip()}"

    return "failed", f"erro ao criar a branch: {created.stderr.strip()}"


def _step_create_file(
    workspace: str, path: str, content: str, later_steps: list[Any]
) -> tuple[str, str]:
    resolved, error = _confined_path(path, workspace)
    if error:
        return "failed", error
    assert resolved is not None

    if resolved.exists():
        existing = _normalized(resolved)
        if existing is not None and existing.strip() == content.replace("\r\n", "\n").strip():
            return "skipped", "arquivo já existe com exatamente este conteúdo."
        if _modified_later(path, later_steps):
            return "skipped", "arquivo já existe (passos seguintes desta tarefa o modificam)."
        return "failed", (
            "o arquivo já existe com conteúdo DIFERENTE. Use replace_text para alterar partes "
            "ou write_markdown com overwrite=true (somente .md/.txt)."
        )

    result = create_new_file.func(file_path=path, content=content, runtime=_runtime(workspace))
    return _classify(result), result


def _step_append(workspace: str, path: str, content: str) -> tuple[str, str]:
    resolved, error = _confined_path(path, workspace)
    if error:
        return "failed", error
    assert resolved is not None

    snippet = content.replace("\r\n", "\n").strip()
    if resolved.is_file() and snippet:
        existing = _normalized(resolved)
        if existing is not None and existing.rstrip().endswith(snippet):
            return "skipped", "o conteúdo já está no final do arquivo."

    result = append_to_file.func(file_path=path, content=content, runtime=_runtime(workspace))
    return _classify(result), result


def _step_write_markdown(workspace: str, step, later_steps: list[Any]) -> tuple[str, str]:
    resolved, error = _confined_path(step.path, workspace)
    if error:
        return "failed", error
    assert resolved is not None

    if resolved.is_file():
        existing = _normalized(resolved)
        if existing is not None and existing.strip() == step.content.replace("\r\n", "\n").strip():
            return "skipped", "documento já existe com exatamente este conteúdo."
        if not step.overwrite and _modified_later(step.path, later_steps):
            return "skipped", "documento já existe (passos seguintes desta tarefa o modificam)."

    result = apply_write_markdown(workspace, step.path, step.content, step.overwrite)
    return _classify(result), result


def _step_create_pdf(workspace: str, step) -> tuple[str, str]:
    resolved, error = _confined_path(step.path, workspace)
    if error:
        return "failed", error
    assert resolved is not None

    if resolved.is_file() and not step.overwrite:
        return "skipped", "PDF já existe (use overwrite=true para regenerar)."

    result = apply_create_pdf(workspace, step.path, step.content, step.title, step.overwrite)
    return _classify(result), result


def _run_step(workspace: str, step, later_steps: list[Any]) -> tuple[str, str]:
    if step.op == "create_branch":
        return _step_create_branch(workspace, step.branch)
    if step.op == "create_file":
        return _step_create_file(workspace, step.path, step.content, later_steps)
    if step.op == "replace_text":
        result = apply_replace_text(
            workspace,
            step.path,
            step.old,
            step.new,
            replace_all=(step.occurrences == "all"),
            strip_numbers=False,
        )
        return _classify(result), result
    if step.op == "append":
        return _step_append(workspace, step.path, step.content)
    if step.op == "write_markdown":
        return _step_write_markdown(workspace, step, later_steps)
    if step.op == "create_pdf":
        return _step_create_pdf(workspace, step)
    return "failed", f"operação desconhecida: {step.op}"


# ──────────────────────────────────────────────────────────────────────────
# Verificações
# ──────────────────────────────────────────────────────────────────────────

def _python_syntax_error(path: Path, shown: str) -> str | None:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return f"{shown}: erro de sintaxe na linha {exc.lineno} ({exc.msg})"
    except (OSError, UnicodeDecodeError) as exc:
        return f"{shown}: não foi possível ler ({exc})"
    return None


def run_checks(checks: list[Any], workspace: str) -> list[str]:
    """Executa verificações; devolve a lista de falhas (vazia = tudo certo).

    Aceita modelos pydantic ou dicts (como vêm do banco).
    """
    try:
        parsed = _CHECKS_ADAPTER.validate_python(
            [c.model_dump() if hasattr(c, "model_dump") else c for c in checks]
        )
    except ValidationError as exc:
        return [f"verificação mal formada: {exc.errors()[0].get('msg', exc)}"]

    failures: list[str] = []

    for check in parsed:
        resolved, error = _confined_path(check.path, workspace)
        if error:
            failures.append(f"{check.type} {check.path}: {error}")
            continue
        assert resolved is not None

        if check.type == "file_exists":
            if not resolved.is_file():
                failures.append(f"file_exists: '{check.path}' não existe.")
            continue

        if not resolved.is_file():
            failures.append(f"{check.type}: '{check.path}' não existe.")
            continue

        if check.type == "python_syntax":
            problem = _python_syntax_error(resolved, check.path)
            if problem:
                failures.append(problem)
            continue

        text = _normalized(resolved)
        if text is None:
            failures.append(f"{check.type}: não foi possível ler '{check.path}'.")
            continue

        needle = check.text.replace("\r\n", "\n")
        if check.type == "contains" and needle not in text:
            failures.append(f"contains: '{check.path}' não contém o texto esperado: {needle[:80]!r}")
        if check.type == "not_contains" and needle in text:
            failures.append(f"not_contains: '{check.path}' ainda contém o texto proibido: {needle[:80]!r}")

    return failures


# ──────────────────────────────────────────────────────────────────────────
# Orquestração
# ──────────────────────────────────────────────────────────────────────────

def execute_task_sync(task: dict, workspace: str) -> TaskRunResult:
    """Executa os `steps` da tarefa e depois as verificações."""
    if not workspace:
        return TaskRunResult(ok=False, error="Nenhum workspace definido para esta conversa.")

    if not Path(workspace).is_dir():
        return TaskRunResult(ok=False, error=f"O workspace '{workspace}' não existe.")

    try:
        steps = _STEPS_ADAPTER.validate_python(task.get("steps") or [])
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        return TaskRunResult(
            ok=False, error=f"Passos mal formados ({where}): {first.get('msg')}"
        )

    if not steps:
        return TaskRunResult(ok=False, error="A tarefa não possui passos (steps) para executar.")

    result = TaskRunResult(ok=True)
    touched_python: list[str] = []

    with _lock_for(workspace):
        total = len(steps)

        for index, step in enumerate(steps, start=1):
            try:
                status, detail = _run_step(workspace, step, steps[index:])
            except Exception as exc:  # um bug de passo nunca derruba o worker
                status, detail = "failed", f"exceção inesperada: {type(exc).__name__}: {exc}"

            result.log.append(
                {"index": index, "total": total, "label": _label(step), "status": status, "detail": detail}
            )

            if status == "failed":
                applied = [i["index"] for i in result.log if i["status"] == "ok"]
                result.ok = False
                result.failed_step = index
                result.error = (
                    f"Passo {index}/{total} ({_label(step)}) falhou:\n{detail}\n\n"
                    + (f"Passos já aplicados: {applied}. " if applied else "Nenhum passo foi aplicado antes. ")
                    + "Reiniciar é seguro: o que já foi feito é detectado e pulado."
                )
                return result

            path = getattr(step, "path", "")
            if path.endswith(".py") and path not in touched_python:
                touched_python.append(path)

        # Revisão automática: todo .py tocado precisa ter sintaxe válida.
        problems: list[str] = []
        for rel in touched_python:
            resolved, error = _confined_path(rel, workspace)
            if resolved is not None and resolved.is_file():
                problem = _python_syntax_error(resolved, rel)
                if problem:
                    problems.append(problem)

        problems.extend(run_checks(task.get("verify") or [], workspace))

    if problems:
        result.ok = False
        result.error = (
            "Os passos foram aplicados, mas a verificação final falhou:\n"
            + "\n".join(f"- {p}" for p in problems)
        )

    return result


async def execute_task(task: dict, workspace: str) -> TaskRunResult:
    """Versão assíncrona (roda em thread para não bloquear o event loop)."""
    return await asyncio.to_thread(execute_task_sync, task, workspace)
