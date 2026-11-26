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
import re
import subprocess
from pathlib import Path

PROTECTED_BRANCHES = {"main", "master"}
_PATH_OPS = {"create_file", "replace_text", "append", "write_markdown", "create_pdf", "delete_file"}
_MULTI_OPS = {"extract_zip", "copy_upload"}

_CONVENTIONAL_TYPES = {
    "feat", "fix", "refactor", "test", "docs", "style", "perf", "chore", "build", "ci", "revert",
}
_TYPE_ALIASES = {
    "tests": "test",
    "feature": "feat",
    "bugfix": "fix",
    "hotfix": "fix",
    "doc": "docs",
}
_CONVENTIONAL_RE = re.compile(
    r"^([a-zA-Z]+)(?:\(([a-zA-Z0-9_./-]+)\))?(!)?:\s*(.+)$"
)
_TEST_FILE_RE = re.compile(
    r"(?:^|/)(?:tests?/.*\.py|test_[^/]+\.py|[^/]+_test\.py|"
    r"__tests__/.*\.(?:js|jsx|ts|tsx|mjs|cjs)|"
    r"[^/]+\.(?:test|spec)\.(?:js|jsx|ts|tsx|mjs|cjs))$",
    re.IGNORECASE,
)
_GENERIC_DIRS = {
    "src", "app", "backend", "frontend", "web", "client", "server", "lib", "packages", "tests", "__tests__",
}


_RUNTIME_ENABLED: bool | None = None


def _state_file() -> Path | None:
    raw = os.getenv("TASK_AUTOCOMMIT_FILE")
    if raw:
        return Path(raw)
    if os.getenv("PYTEST_CURRENT_TEST"):
        return None
    return Path.home() / ".assistente_local" / "autocommit.state"


def enabled():
    state_file = _state_file()
    if state_file is not None:
        try:
            if state_file.is_file():
                raw = state_file.read_text(encoding="utf-8").strip().lower()
                if raw in ("1", "true", "on"):
                    return True
                if raw in ("0", "false", "off"):
                    return False
        except OSError:
            pass
    if _RUNTIME_ENABLED is not None:
        return _RUNTIME_ENABLED
    return os.getenv("TASK_AUTOCOMMIT", "0") == "1"


def set_enabled(value: bool | None) -> bool:
    global _RUNTIME_ENABLED
    _RUNTIME_ENABLED = bool(value) if value is not None else None
    state_file = _state_file()
    if state_file is not None:
        try:
            if value is None:
                state_file.unlink(missing_ok=True)
            else:
                state_file.parent.mkdir(parents=True, exist_ok=True)
                state_file.write_text("1" if value else "0", encoding="utf-8")
        except OSError:
            pass
    return enabled()


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
        elif op == "move_file":
            for key in ("source", "destination"):
                rel = str(step.get(key) or "").replace("\\", "/")
                if rel and rel not in files:
                    files[rel] = _read(root / rel)
    return {"files": files, "multi": multi}


def _infer_commit_type(title: str, paths: list[str] | None = None) -> str:
    low = str(title or "").lower()
    if re.search(r"\b(?:corrig|fix|bug|erro|falha|repar|blind|quebr|resolv)\w*", low):
        return "fix"
    if re.search(r"\b(?:test|pytest|vitest|jest|spec|cobertura)\w*", low):
        return "test"
    if re.search(r"\b(?:refator|refactor|padroniz|limp|renome|organiz|reestrutur)\w*", low):
        return "refactor"
    if re.search(r"\b(?:doc|readme|documenta|coment)\w*", low):
        return "docs"
    if re.search(r"\b(?:perf|otimiz|vram|cache|veloz|lat[eê]ncia)\w*", low):
        return "perf"
    if re.search(r"\b(?:estilo|style|css|layout|[ií]cone|svg|tema|visual)\w*", low):
        return "style"
    if re.search(r"\b(?:chore|config|depend[eê]ncia|package\.json|build|ci|workflow)\b", low):
        return "chore"

    clean_paths = [str(p).replace("\\", "/") for p in (paths or []) if str(p).strip()]
    if clean_paths:
        if all(_TEST_FILE_RE.search(p) for p in clean_paths):
            return "test"
        if all(Path(p).suffix.lower() in {".md", ".txt", ".rst"} for p in clean_paths):
            return "docs"
        if all(Path(p).suffix.lower() in {".css", ".scss", ".sass", ".less"} for p in clean_paths):
            return "style"
    return "feat"


def _infer_commit_scope(paths: list[str] | None = None, explicit_scope: str | None = None) -> str:
    if explicit_scope and str(explicit_scope).strip():
        clean = re.sub(r"[^a-z0-9_./-]+", "-", str(explicit_scope).lower()).strip("-")
        if clean:
            return clean[:24]

    candidates: list[str] = []
    for raw in paths or []:
        parts = [p for p in str(raw).replace("\\", "/").split("/") if p]
        dirs = parts[:-1]
        picked = next((d for d in reversed(dirs) if d.lower() not in _GENERIC_DIRS), "")
        if not picked and parts:
            picked = Path(parts[-1]).stem
        norm = re.sub(r"[^a-z0-9_-]+", "-", picked.lower()).strip("-")
        if norm:
            candidates.append(norm[:24])

    if not candidates:
        return ""
    if len(set(candidates)) == 1:
        return candidates[0]
    return max(set(candidates), key=candidates.count)


def format_conventional_commit(title: str, paths: list[str] | None = None) -> str:
    """Formata o título da task estritamente no padrão Conventional Commits (<= 72 chars)."""
    raw = re.sub(r"\s+", " ", str(title or "")).strip().rstrip(".")
    raw = re.sub(r"^(?:task\s*#\d+\s*:\s*)+", "", raw, flags=re.IGNORECASE).strip()

    explicit_scope: str | None = None
    match = _CONVENTIONAL_RE.match(raw)
    if match:
        head = match.group(1).lower()
        norm_type = _TYPE_ALIASES.get(head, head)
        cscope = (match.group(2) or "").strip().lower()
        bang = match.group(3) or ""
        desc = match.group(4).strip()
        if norm_type in _CONVENTIONAL_TYPES:
            if not cscope:
                cscope = _infer_commit_scope(paths)
            prefix = f"{norm_type}({cscope}){bang}: " if cscope else f"{norm_type}{bang}: "
            max_desc = max(12, 72 - len(prefix))
            return prefix + desc[:max_desc].rstrip()
        # Prefixo não padrão (ex.: "frontend: ...", "prompts(code): ...") vira escopo
        explicit_scope = cscope or head
        raw = desc

    ctype = _infer_commit_type(raw, paths)
    cscope = _infer_commit_scope(paths, explicit_scope)
    desc = raw or "atualiza arquivos da tarefa"
    if len(desc) >= 2 and desc[0].isupper() and desc[1].islower():
        desc = desc[0].lower() + desc[1:]
    prefix = f"{ctype}({cscope}): " if cscope else f"{ctype}: "
    max_desc = max(12, 72 - len(prefix))
    return prefix + desc[:max_desc].rstrip()


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

    subject = format_conventional_commit(title, paths)
    message = (
        f"{subject}\n\n"
        f"Executada automaticamente pelo assistente ({mode}).\n"
        f"Task-ID: #{task_id}"
    )
    done = _git(root, "commit", "-q", "-m", message, "--", *paths)
    if done.returncode != 0:
        detail = (_out(done) or (done.stderr or b"").decode("utf-8", errors="replace").strip())[-200:]
        return f"⚠️ commit automático da #{task_id} falhou: {detail}"
    short = _out(_git(root, "rev-parse", "--short", "HEAD"))
    return f"📌 commit {short} em '{branch}': {subject} (task #{task_id}, {len(paths)} arquivo(s))."


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
