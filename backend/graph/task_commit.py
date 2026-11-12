"""Commit automático por task (opt-in: TASK_AUTOCOMMIT=1 no .env).

Regras de segurança (para nunca misturar o seu trabalho com o da task):
- só commita os arquivos que a task tocou (`git commit -- <arquivos>`); o resto do que você tem aberto não entra;
- se algum desses arquivos JÁ tinha alterações suas não commitadas antes da task, não commita nada e avisa;
- nunca commita em main/master (as tools já bloqueiam escrita nelas);
- ignora a cópia temporária do dry-run, tasks com extract_zip/copy_upload e arquivos ignorados pelo git;
- qualquer problema vira uma mensagem; nunca derruba a task.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROTECTED_BRANCHES = {"main", "master"}
_PATH_OPS = {"create_file", "replace_text", "append", "write_markdown", "create_pdf"}
_MULTI_OPS = {"extract_zip", "copy_upload"}


def enabled():
    return os.getenv("TASK_AUTOCOMMIT", "0") == "1"


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        timeout=60,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _out(done):
    return (done.stdout or b"").decode("utf-8", errors="replace").strip()


def _norm(data):
    return None if data is None else data.replace(b"\r\n", b"\n")


def _read(path):
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def capture_originals(workspace, steps):
    """Estado dos arquivos que os passos vão tocar, ANTES de a task rodar."""
    root = Path(workspace).resolve()
    files, multi = {}, False
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        op = step.get("op")
        if op in _MULTI_OPS:
            multi = True
        elif op in _PATH_OPS:
            rel = str(step.get("path") or "").replace("\\", "/")
            if rel and rel not in files:
                files[rel] = _read(root / rel)
    return {"files": files, "multi": multi}


def commit_task(workspace, task_id, title, pre, mode="determinística"):
    """Commita o que a task mudou. Devolve uma linha para o relatório, ou None se não há o que dizer."""
    if not enabled():
        return None
    try:
        return _commit(workspace, task_id, title, pre, mode)
    except Exception as exc:  # noqa: BLE001 - o commit é um extra
        return f"⚠️ commit automático da #{task_id} falhou: {exc}"


def _commit(workspace, task_id, title, pre, mode):
    root = Path(workspace).resolve()
    if root.name.startswith("dryrun_"):
        return None
    top_done = _git(root, "rev-parse", "--show-toplevel")
    if top_done.returncode != 0:
        return None  # não é um repositório git
    top = Path(_out(top_done)).resolve()
    branch = _out(_git(root, "rev-parse", "--abbrev-ref", "HEAD"))
    if branch in PROTECTED_BRANCHES:
        return f"⏭️ commit automático ignorado: você está na branch protegida '{branch}'."
    if pre.get("multi"):
        return f"⏭️ commit automático da #{task_id} ignorado: a task extrai/copia vários arquivos; commite manualmente."

    changed = []
    for rel, original in pre.get("files", {}).items():
        if _read(root / rel) != original:
            changed.append((rel, original, (root / rel).resolve().relative_to(top).as_posix()))
    if not changed:
        return None

    dirty = []
    for rel, original, top_rel in changed:
        if original is None:
            continue  # arquivo novo: não havia nada seu ali
        head = _git(root, "show", f"HEAD:{top_rel}")
        if head.returncode != 0 or _norm(head.stdout) != _norm(original):
            dirty.append(rel)
    if dirty:
        return (
            f"⏭️ commit automático da #{task_id} ignorado: estes arquivos já tinham alterações suas não commitadas "
            f"({', '.join(dirty)}). Revise e commite manualmente para não misturar."
        )

    paths = []
    for _rel, _original, top_rel in changed:
        if _git(root, "check-ignore", "-q", "--", top_rel).returncode == 0:
            continue
        if _git(root, "add", "--", top_rel).returncode == 0:
            paths.append(top_rel)
    if not paths:
        return None
    if not _out(_git(root, "diff", "--cached", "--name-only", "--", *paths)):
        return None

    message = f"task #{task_id}: {str(title).strip()[:120]}\n\nExecutada automaticamente pelo assistente ({mode})."
    done = _git(root, "commit", "-q", "-m", message, "--", *paths)
    if done.returncode != 0:
        detail = (_out(done) or (done.stderr or b"").decode("utf-8", errors="replace").strip())[-200:]
        return f"⚠️ commit automático da #{task_id} falhou: {detail}"
    short = _out(_git(root, "rev-parse", "--short", "HEAD"))
    return f"📌 commit {short} em '{branch}': task #{task_id} ({len(paths)} arquivo(s))."


def commit_from_journal(task_id, title):
    """Task dinâmica aprovada: commita o que a IA mudou, usando o diário de alterações como estado anterior."""
    if not enabled():
        return None
    try:
        try:
            from .task_journal import journal_originals
        except ImportError:
            from backend.graph.task_journal import journal_originals
        data = journal_originals(task_id)
        if not data:
            return None
        pre = {"files": data["files"], "multi": False}
        return commit_task(data["workspace"], task_id, title, pre, "dinâmica, aprovada na revisão")
    except Exception as exc:  # noqa: BLE001
        return f"⚠️ commit automático da #{task_id} falhou: {exc}"
