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
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import TypeAdapter, ValidationError

from backend.api.schemas import TaskCheck, TaskStep
from backend.api.uploads import find_upload

from .tools import (
    PROTECTED_BRANCHES,
    _check_not_on_protected_branch,
    _confined_path,
    _read_text_keep_newline,
    append_to_file,
    apply_create_pdf,
    apply_replace_text,
    apply_write_markdown,
    create_new_file,
)
from .grounding import check_literals_grounded
from .task_guards import FileSnapshot, extra_syntax_problems, run_pytest

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
    head = result.lstrip().lstrip("❌⚠️ ").upper()
    if head.startswith(("ERRO", "EDIÇÃO REJEITADA", "EDICAO REJEITADA", "REJEITAD", "FALHA")):
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


# Limites do extract_zip (proteção contra zip bomb / zip slip).
ZIP_MAX_ENTRIES = 5000
ZIP_MAX_FILE_BYTES = 25 * 1024 * 1024
ZIP_MAX_TOTAL_BYTES = 200 * 1024 * 1024
_ZIP_JUNK = ("__macosx/",)
_ZIP_JUNK_NAMES = {".ds_store", "thumbs.db"}


def _write_bytes_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _step_copy_upload(workspace: str, thread_id: str | None, step) -> tuple[str, str]:
    source, error = find_upload(workspace, thread_id, step.source)
    if error:
        return "failed", error
    assert source is not None

    resolved, error = _confined_path(step.path, workspace)
    if error:
        return "failed", error
    assert resolved is not None

    if resolved.is_dir():
        return "failed", (
            f"'{step.path}' é uma pasta. Informe o caminho do arquivo final "
            f"(ex.: {step.path.rstrip('/')}/{source.name})."
        )

    security_error = _check_not_on_protected_branch(str(resolved))
    if security_error:
        return "failed", security_error

    data = source.read_bytes()
    if resolved.exists():
        try:
            if resolved.read_bytes() == data:
                return "skipped", f"'{step.path}' já existe com exatamente o conteúdo do anexo."
        except OSError as exc:
            return "failed", f"não foi possível ler '{step.path}': {exc}"
        if not step.overwrite:
            return "failed", (
                f"'{step.path}' já existe com conteúdo DIFERENTE. "
                "Use overwrite=true para substituí-lo pelo anexo."
            )

    try:
        _write_bytes_atomic(resolved, data)
    except OSError as exc:
        return "failed", f"erro ao gravar '{step.path}': {exc}"
    return "ok", f"anexo '{source.name}' copiado para '{step.path}' ({len(data)} bytes)."


def _zip_entry_name(raw: str) -> str | None:
    """Nome normalizado de uma entrada, ou levanta ValueError se for perigoso."""
    name = raw.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise ValueError(f"caminho absoluto no zip: '{raw}'")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"caminho com '..' no zip: '{raw}'")
    return "/".join(parts) or None


def _step_extract_zip(workspace: str, thread_id: str | None, step) -> tuple[str, str]:
    source, error = find_upload(workspace, thread_id, step.source)
    if error:
        return "failed", error
    assert source is not None

    dest_root, error = _confined_path(step.path, workspace)
    if error:
        return "failed", error
    assert dest_root is not None
    if dest_root.exists() and not dest_root.is_dir():
        return "failed", f"'{step.path}' existe e não é uma pasta."

    security_error = _check_not_on_protected_branch(str(dest_root / "x"))
    if security_error:
        return "failed", security_error

    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        return "failed", f"zip inválido ou corrompido: {exc}"

    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > ZIP_MAX_ENTRIES:
            return "failed", f"zip com arquivos demais ({len(infos)} > {ZIP_MAX_ENTRIES})."

        entries: list[tuple[zipfile.ZipInfo, str]] = []
        ignored = 0
        total = 0
        for info in infos:
            try:
                name = _zip_entry_name(info.filename)
            except ValueError as exc:
                return "failed", f"zip rejeitado por segurança: {exc}. Nada foi extraído."
            if not name:
                continue
            low = name.lower()
            if low.startswith(_ZIP_JUNK) or low.rsplit("/", 1)[-1] in _ZIP_JUNK_NAMES:
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:  # symlink
                ignored += 1
                continue
            if info.flag_bits & 0x1:
                return "failed", "zip protegido por senha: não é possível extrair."
            if info.file_size > ZIP_MAX_FILE_BYTES:
                return "failed", f"'{name}' é grande demais ({info.file_size} bytes) para extrair."
            total += info.file_size
            if total > ZIP_MAX_TOTAL_BYTES:
                return "failed", "o conteúdo do zip passa do limite total permitido."
            entries.append((info, name))

        if not entries:
            return "failed", "o zip não tem nenhum arquivo utilizável."

        if step.strip_top_folder:
            tops = {n.split("/", 1)[0] for _, n in entries}
            if len(tops) == 1 and all("/" in n for _, n in entries):
                entries = [(i, n.split("/", 1)[1]) for i, n in entries]

        # Fase 1: planejar (nada é gravado ainda).
        plan: list[tuple[Path, zipfile.ZipInfo, bytes, str]] = []
        identical = protected = 0
        kept: list[str] = []
        for info, name in entries:
            target, err = _confined_path(f"{step.path.rstrip('/')}/{name}", workspace)
            if err or target is None:
                protected += 1
                continue
            data = bytearray()
            with archive.open(info) as handle:
                while True:
                    chunk = handle.read(64 * 1024)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > ZIP_MAX_FILE_BYTES:
                        return "failed", f"'{name}' passou do limite de tamanho ao extrair."
            data = bytes(data)

            if target.is_dir():
                return "failed", f"'{name}' conflita com uma pasta existente em '{step.path}'."
            if target.exists():
                try:
                    same = target.read_bytes() == data
                except OSError:
                    same = False
                if same:
                    identical += 1
                    continue
                if step.on_conflict != "overwrite":
                    kept.append(name)
                    continue
                plan.append((target, info, data, "atualizado"))
            else:
                plan.append((target, info, data, "criado"))

    created = updated = 0
    for target, _info, data, kind in plan:
        try:
            _write_bytes_atomic(target, data)
        except OSError as exc:
            return "failed", f"erro ao gravar '{target.name}': {exc}"
        created += kind == "criado"
        updated += kind == "atualizado"

    parts = [f"{created} criado(s)", f"{updated} atualizado(s)", f"{identical} idêntico(s) pulado(s)"]
    if kept:
        sample = ", ".join(kept[:5]) + ("..." if len(kept) > 5 else "")
        parts.append(f"{len(kept)} conflito(s) MANTIDO(S) sem alterar (on_conflict=skip): {sample}")
    if protected:
        parts.append(f"{protected} em área protegida ignorado(s)")
    if ignored:
        parts.append(f"{ignored} symlink(s) ignorado(s)")
    detail = f"zip '{source.name}' → '{step.path}': " + ", ".join(parts) + "."
    return ("ok" if (created or updated) else "skipped"), detail


def _heal_replace(workspace: str, step, original_result: str):
    """Se o `old` não bateu só por espaços/indentação, usa o ÚNICO bloco equivalente do arquivo (sem LLM)."""
    if os.getenv("TASK_HEAL_WHITESPACE", "1") != "1" or step.occurrences == "all":
        return None
    if "não foi encontrado" not in original_result:
        return None
    try:
        from backend.handoff.repair import repair_steps

        fixed, notes = repair_steps(
            workspace, [{"op": "replace_text", "path": step.path, "old": step.old, "new": step.new}]
        )
    except Exception:  # noqa: BLE001 - o reparo é um extra: nunca derruba a tarefa
        return None
    if not notes:
        return None
    healed = apply_replace_text(
        workspace, step.path, fixed[0]["old"], fixed[0]["new"], replace_all=False, strip_numbers=False
    )
    status = _classify(healed)
    if status == "failed":
        return None
    return status, healed + " (âncora ajustada: só espaços/indentação diferiam; bloco único equivalente.)"


def _run_step(
    workspace: str, step, later_steps: list[Any], thread_id: str | None = None
) -> tuple[str, str]:
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
        status = _classify(result)
        if status == "failed":
            healed = _heal_replace(workspace, step, result)
            if healed is not None:
                return healed
        return status, result
    if step.op == "append":
        return _step_append(workspace, step.path, step.content)
    if step.op == "write_markdown":
        return _step_write_markdown(workspace, step, later_steps)
    if step.op == "create_pdf":
        return _step_create_pdf(workspace, step)
    if step.op == "copy_upload":
        return _step_copy_upload(workspace, thread_id, step)
    if step.op == "extract_zip":
        return _step_extract_zip(workspace, thread_id, step)
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

        if check.type == "pytest":
            failures.extend(run_pytest(workspace, check.path))
            continue

        if check.type == "literals_grounded":
            failures.extend(check_literals_grounded(check.path, check.sources, workspace, check.allow))
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

def execute_task_sync(task: dict, workspace: str, thread_id: str | None = None) -> TaskRunResult:
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
    snapshot = FileSnapshot(workspace)
    touched_python: list[str] = []

    with _lock_for(workspace):
        total = len(steps)

        for index, step in enumerate(steps, start=1):
            try:
                snapshot.touch_step(step)
                status, detail = _run_step(workspace, step, steps[index:], thread_id)
            except Exception as exc:  # um bug de passo nunca derruba o worker
                status, detail = "failed", f"exceção inesperada: {type(exc).__name__}: {exc}"

            result.log.append(
                {"index": index, "total": total, "label": _label(step), "status": status, "detail": detail}
            )

            if status == "failed":
                applied = [i["index"] for i in result.log if i["status"] == "ok"]
                rolled_back = snapshot.restore()
                result.ok = False
                result.failed_step = index
                result.error = (
                    f"Passo {index}/{total} ({_label(step)}) falhou:\n{detail}\n\n"
                    + (
                        "Rollback feito: os arquivos voltaram ao estado anterior à tarefa. "
                        if rolled_back
                        else (f"Passos já aplicados: {applied}. " if applied else "Nenhum passo foi aplicado antes. ")
                    )
                    + "Reiniciar é seguro: o que já foi feito é detectado e pulado."
                )
                return result

            path = getattr(step, "path", "")
            if path.endswith(".py") and path not in touched_python:
                touched_python.append(path)

        # Revisão automática: todo .py tocado precisa ter sintaxe válida.
        problems: list[str] = []
        problems.extend(extra_syntax_problems(workspace, steps))
        for rel in touched_python:
            resolved, error = _confined_path(rel, workspace)
            if resolved is not None and resolved.is_file():
                problem = _python_syntax_error(resolved, rel)
                if problem:
                    problems.append(problem)

        problems.extend(run_checks(task.get("verify") or [], workspace))

    if problems:
        with _lock_for(workspace):
            rolled_back = snapshot.restore()
        result.ok = False
        result.error = (
            ("Os passos foram DESFEITOS (rollback), pois a verificação final falhou:\n" if rolled_back else "Os passos foram aplicados, mas a verificação final falhou:\n")
            + "\n".join(f"- {p}" for p in problems)
        )

    return result


def workspace_summary(workspace: str) -> str:
    """Linha(s) curtas para o relatório: onde foi aplicado, branch e o que mudou (git)."""
    lines = [f"📂 Workspace: {Path(workspace).resolve()}"]
    try:
        branch = _git(workspace, "branch", "--show-current").stdout.strip()
        if branch:
            lines.append(f"🌿 Branch: {branch}")
        stat = _git(workspace, "diff", "--stat", "HEAD").stdout.strip()
        lines.append(
            f"📝 Alterações no git (vs HEAD):\n{stat}" if stat
            else "📝 O git NÃO detecta nenhuma alteração neste workspace."
        )
    except (OSError, subprocess.SubprocessError):
        lines.append("(git indisponível: não foi possível listar as alterações)")
    return "\n".join(lines)


def missing_listed_files(files: list[str] | None, workspace: str) -> list[str]:
    """Arquivos citados em `files` da tarefa que não existem no workspace."""
    missing: list[str] = []
    for rel in files or []:
        resolved, error = _confined_path(rel, workspace)
        if error or resolved is None or not resolved.exists():
            missing.append(rel)
    return missing


async def execute_task(task: dict, workspace: str, thread_id: str | None = None) -> TaskRunResult:
    """Versão assíncrona (roda em thread para não bloquear o event loop)."""
    return await asyncio.to_thread(execute_task_sync, task, workspace, thread_id)
