"""Primer do projeto (Fase C): resumo de ~2k tokens GERADO POR CÓDIGO, sem LLM e sem código-fonte.

Serve para abrir um chat novo numa IA externa sem reenviar o projeto: arquitetura, modelos, grafo,
tools, rotas e as últimas tasks aplicadas. Tudo vem de AST/regex dos arquivos e do banco, então não
alucina e não fica desatualizado como um ARCHITECTURE.md escrito à mão.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from datetime import date
from pathlib import Path

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", "dist", "build", ".idea", ".vscode", ".next",
    "coverage", "site-packages", ".rag_work",
}
MAX_PY_BYTES = 400_000
_ROUTE = re.compile(r"""^\s*@(\w+)\.(get|post|put|delete|patch)\(\s*["']([^"']*)["']""", re.M)
_INCLUDE = re.compile(r"""include_router\(\s*(\w+)\s*,\s*prefix\s*=\s*["']([^"']+)["']""")
_NODE = re.compile(r"""add_node\(\s*["'](\w+)["']""")
_OLLAMA = re.compile(r"""^(\w+)\s*=\s*ChatOllama\(\s*model\s*=\s*["']([^"']+)["'](.*)$""", re.M)
_NUM_CTX = re.compile(r"num_ctx\s*=\s*([\w]+)")


def estimate_tokens(text: str) -> int:
    return len(text) // 3 + 1


def _ignored(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return any(p in IGNORE_DIRS for p in parts[:-1]) or name == ".env" or name.startswith(".env.")


def list_files(root: Path) -> list[str]:
    """Respeita o .gitignore quando é repositório git; senão percorre as pastas."""
    names: list[str] | None = None
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "-c", "-o", "--exclude-standard"],
            capture_output=True, timeout=30,
        )
        if out.returncode == 0 and out.stdout:
            names = [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        names = None
    if names is None:
        names = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            names += [(Path(dirpath) / f).relative_to(root).as_posix() for f in filenames]
    return sorted({n.replace("\\", "/") for n in names if not _ignored(n.replace("\\", "/"))})


def _first_line(text: str | None, limit: int = 90) -> str:
    line = (text or "").strip().split("\n", 1)[0].strip()
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _is_tool_decorator(dec: ast.expr) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
    return name == "tool"


class _Facts:
    def __init__(self) -> None:
        self.docs: dict[str, str] = {}
        self.tools: list[tuple[str, str, str]] = []  # (nome, resumo, arquivo)
        self.routes: dict[str, list[tuple[str, str]]] = {}  # variável do router -> [(MÉTODO, caminho)]
        self.prefixes: dict[str, str] = {}
        self.nodes: list[str] = []
        self.models: list[tuple[str, str, str]] = []  # (variável, modelo, num_ctx)


def _scan(root: Path, files: list[str]) -> _Facts:
    facts = _Facts()
    for rel in files:
        if not rel.endswith(".py"):
            continue
        path = root / rel
        try:
            if path.stat().st_size > MAX_PY_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        doc = ast.get_docstring(tree)
        if doc:
            facts.docs[rel] = _first_line(doc)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                _is_tool_decorator(d) for d in node.decorator_list
            ):
                facts.tools.append((node.name, _first_line(ast.get_docstring(node), 70), rel))
        for var, method, route in _ROUTE.findall(text):
            facts.routes.setdefault(var, []).append((method.upper(), route))
        for var, prefix in _INCLUDE.findall(text):
            facts.prefixes[var] = prefix
        if rel.endswith("builder.py"):
            facts.nodes += [n for n in _NODE.findall(text) if n not in facts.nodes]
        for var, model, rest in _OLLAMA.findall(text):
            ctx = _NUM_CTX.search(rest)
            facts.models.append((var, model, ctx.group(1) if ctx else "?"))
    return facts


def _architecture(files: list[str], facts: _Facts, level: int) -> str:
    """level 2: pastas com cada .py e seu resumo; 1: só nomes dos .py; 0: só pastas com contagem."""
    by_dir: dict[str, list[str]] = {}
    for rel in files:
        folder, _, name = rel.rpartition("/")
        by_dir.setdefault(folder or ".", []).append(name)
    lines: list[str] = []
    for folder in sorted(by_dir):
        names = by_dir[folder]
        py = [n for n in names if n.endswith(".py") and n != "__init__.py"]
        other = [n for n in names if n not in py and n != "__init__.py"]
        exts: dict[str, int] = {}
        for n in other:
            exts[Path(n).suffix or n] = exts.get(Path(n).suffix or n, 0) + 1
        extra = ", ".join(f"{c}×{e}" for e, c in sorted(exts.items()))
        head = f"{folder}/" if folder != "." else "./"
        if level == 0:
            lines.append(f"{head} ({len(py)} .py{', ' + extra if extra else ''})")
            continue
        lines.append(head + (f" (+ {extra})" if extra else ""))
        for n in py[:25]:
            rel = f"{folder}/{n}" if folder != "." else n
            doc = facts.docs.get(rel, "")
            lines.append(f"  {n}" + (f" — {doc}" if doc and level == 2 else ""))
        if len(py) > 25:
            lines.append(f"  … +{len(py) - 25} arquivos .py")
    return "\n".join(lines)


def _routes_text(facts: _Facts) -> str:
    lines = []
    for var, items in sorted(facts.routes.items(), key=lambda kv: facts.prefixes.get(kv[0], kv[0])):
        prefix = facts.prefixes.get(var, "")
        label = prefix or f"({var})"
        lines.append(f"{label}: " + ", ".join(f"{m} {p or '/'}" for m, p in items))
    return "\n".join(lines)


async def recent_tasks(limit: int = 8, thread_id: str | None = None) -> list[dict]:
    """Últimas tasks aplicadas (completed/review). Vazio se o banco não estiver acessível."""
    try:
        from sqlalchemy import select

        from backend.database.config import async_session_env
        from backend.database.models import TaskModel

        stmt = select(TaskModel).where(TaskModel.status.in_(("completed", "review")))
        if thread_id:
            stmt = stmt.where(TaskModel.thread_id == thread_id)
        async with async_session_env() as db:
            rows = (await db.execute(stmt.order_by(TaskModel.id.desc()).limit(limit))).scalars().all()
        return [
            {"id": r.id, "title": r.title, "status": r.status, "files": list(r.files or [])}
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        print(f"ℹ️ [PRIMER] tasks indisponíveis (seguindo sem elas): {exc}")
        return []


async def build_primer(
    workspace: str, max_tokens: int = 2000, thread_id: str | None = None, tasks_limit: int = 8
) -> dict:
    """Devolve {"markdown", "est_tokens", "truncated"}. Nunca inclui código-fonte nem .env."""
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Pasta não encontrada: {workspace}")
    files = list_files(root)
    facts = _scan(root, files)

    fixed: list[str] = [
        f"# PRIMER DO PROJETO: {root.name}",
        f"Gerado por código em {date.today().isoformat()} a partir do repositório (sem LLM, sem código-fonte). "
        "Para ver o código, peça por arquivo + função/linhas.",
    ]
    if facts.models:
        fixed.append("## Modelos\n" + "\n".join(f"- {v}: {m} (num_ctx={c})" for v, m, c in facts.models))
    if facts.nodes:
        fixed.append("## Nós do grafo (LangGraph)\n" + ", ".join(facts.nodes))
    if facts.tools:
        fixed.append(
            "## Tools do agente\n" + "\n".join(f"- {n}: {d}" if d else f"- {n}" for n, d, _ in sorted(facts.tools))
        )
    routes = _routes_text(facts)
    if routes:
        fixed.append("## Rotas HTTP\n" + routes)
    tasks = await recent_tasks(tasks_limit, thread_id)
    if tasks:
        fixed.append(
            "## Últimas tasks aplicadas (mais recente primeiro)\n"
            + "\n".join(
                f"- #{t['id']} [{t['status']}] {t['title']}" + (f" — {', '.join(t['files'][:4])}" if t["files"] else "")
                for t in tasks
            )
        )

    truncated = False
    markdown = ""
    for level in (2, 1, 0):
        arch = "## Estrutura de arquivos\n" + _architecture(files, facts, level)
        markdown = "\n\n".join(fixed + [arch])
        if estimate_tokens(markdown) <= max_tokens:
            break
        truncated = level != 0 or truncated
    else:
        # Mesmo só com pastas passou do orçamento: corta a estrutura no limite, declarando o corte.
        budget = max(0, max_tokens * 3 - len("\n\n".join(fixed)) - 80)
        markdown = "\n\n".join(fixed + [arch[:budget].rsplit("\n", 1)[0] + "\n[... estrutura cortada pelo orçamento ...]"])
        truncated = True
    return {"markdown": markdown, "est_tokens": estimate_tokens(markdown), "truncated": truncated}
