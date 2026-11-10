"""Funções utilitárias puras usadas pelos nós do grafo (sem acesso a LLM/DB)."""

import ast
import json as _json
import os as _os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import SystemMessage

from .config import WRITE_AND_GIT_TOOLS


# ----------------------------------------------------------------------
# Metadados de mensagens (horário / tempo de resposta)
# ----------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def stamp_message(msg, started_at: float | None = None):
    """Grava created_at (e opcionalmente elapsed_seconds) na mensagem."""
    msg.additional_kwargs.setdefault("created_at", now_iso())
    if started_at is not None:
        msg.additional_kwargs["elapsed_seconds"] = round(
            time.perf_counter() - started_at, 2
        )
    return msg


# ----------------------------------------------------------------------
# Tool calls / parsing / sintaxe
# ----------------------------------------------------------------------

def _extract_gatherer_tool_trace(messages, start_idx: int) -> list[dict]:
    """
    Extrai somente o nome e os argumentos das tools utilizadas
    durante a execução atual do Context Gatherer.

    Não preserva:
    - conteúdo de ToolMessage;
    - pensamentos do modelo;
    - IDs das tool calls;
    - respostas completas das ferramentas.
    """
    trace = []

    for msg in messages[start_idx + 1 :]:
        if msg.type != "ai":
            continue

        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            continue

        for tool_call in tool_calls:
            trace.append(
                {
                    "name": tool_call.get("name"),
                    "args": tool_call.get("args", {}),
                }
            )

    return trace


WRITE_TOOL_NAMES = {
    "create_new_file",
    "edit_existing_file",
    "batch_edit_file",
    "append_to_file",
    "replace_in_file",
    "write_markdown_file",
    "create_pdf_file",
    "create_git_branch",
}

# Subconjunto de WRITE_TOOL_NAMES que de fato modifica conteúdo de arquivo
# (create_git_branch não altera nenhum arquivo).
FILE_WRITE_TOOL_NAMES = WRITE_TOOL_NAMES - {"create_git_branch"}


def _has_write_call(messages) -> bool:
    return any(
        call["name"] in WRITE_TOOL_NAMES
        for msg in messages
        if getattr(msg, "tool_calls", None)
        for call in msg.tool_calls
    )


GENERATE_TOOL_NAMES = {tool.name for tool in WRITE_AND_GIT_TOOLS}


def _parse_xml_tool_fallback(content: str) -> list[dict]:
    """
    Recupera tool calls que o Qwen escreveu em formato XML no conteúdo
    da resposta quando o Ollama não conseguiu convertê-las para
    response.tool_calls.
    """

    if not content or "<function=" not in content:
        return []

    recovered_calls = []

    function_matches = re.finditer(
        r"<function=([^>\s]+)>(.*?)</function>",
        content,
        re.DOTALL,
    )

    for function_match in function_matches:
        tool_name = function_match.group(1).strip()

        # Segurança: só aceita ferramentas realmente registradas
        # no Generate.
        if tool_name not in GENERATE_TOOL_NAMES:
            print(
                f"⚠️ [PARSER FALLBACK] Tool '{tool_name}' "
                "não está registrada no Generate. Ignorando."
            )
            continue

        function_body = function_match.group(2)

        args = {}

        parameter_matches = re.finditer(
            r"<parameter=([^>\s]+)>(.*?)</parameter>",
            function_body,
            re.DOTALL,
        )

        for parameter_match in parameter_matches:
            parameter_name = parameter_match.group(1).strip()
            parameter_value = parameter_match.group(2).strip()

            args[parameter_name] = parameter_value

        recovered_calls.append(
            {
                "name": tool_name,
                "args": args,
                "id": f"fallback-{uuid.uuid4().hex}",
                "type": "tool_call",
            }
        )

    return recovered_calls


def _extract_edited_python_files(messages) -> list[str]:
    """
    Extrai (sem duplicar, preservando a ordem) os caminhos dos arquivos
    .py tocados por tool calls de escrita nas mensagens informadas.
    """
    edited_files: list[str] = []

    for msg in messages:
        for call in getattr(msg, "tool_calls", None) or []:
            if call.get("name") not in FILE_WRITE_TOOL_NAMES:
                continue

            file_path = (call.get("args") or {}).get("file_path")

            if (
                isinstance(file_path, str)
                and file_path.endswith(".py")
                and file_path not in edited_files
            ):
                edited_files.append(file_path)

    return edited_files


def _check_python_syntax(file_paths: list[str], workspace: str | None) -> list[str]:
    """
    Faz ast.parse nos arquivos Python informados (resolvidos contra o
    workspace quando o caminho é relativo) e devolve a lista de erros.
    Lista vazia = tudo certo.
    """
    errors: list[str] = []

    for file_path in file_paths:
        path = Path(file_path)

        if not path.is_absolute() and workspace:
            path = Path(workspace) / path

        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            errors.append(
                f"{file_path}: linha {e.lineno}, coluna {e.offset} - {e.msg}"
            )
        except OSError as e:
            errors.append(f"{file_path}: não foi possível ler ({e})")

    return errors


def build_system_context(*parts: str | None) -> SystemMessage:
    """Junta múltiplas partes de contexto de sistema em uma única SystemMessage, separadas por um divisor."""
    valid_parts = [p.strip() for p in parts if p and p.strip()]
    return SystemMessage(content="\n\n---\n\n".join(valid_parts))


# ----------------------------------------------------------------------
# Formatação de saída do Heavy
# ----------------------------------------------------------------------

def format_task_description(task: dict) -> str:
    """Monta a descrição em Markdown de uma tarefa gerada pelo Heavy."""
    sections = [
        ("Objetivo", task.get("objective", "")),
        ("Localização Alvo", task.get("target", "")),
        ("Lógica da Alteração (Instruções Detalhadas)", task.get("logic", "")),
        ("Restrições do Usuário", task.get("constraints", "")),
    ]
    return "\n\n".join(
        f"**{label}:**\n{str(value).strip()}"
        for label, value in sections
        if value and str(value).strip()
    )


def build_security_report(findings: list[dict]) -> str:
    report = "\n\n## 🛡️ Achados de Segurança\n\n"
    for finding in findings:
        cat = finding.get("category", "Desconhecido")
        risk = str(finding.get("risk", "Desconhecido")).upper()
        file_path = finding.get("file", "Desconhecido")
        evidence = finding.get("evidence", "")
        tech = finding.get("technical_analysis", "")

        # cerca maior que qualquer ``` dentro da evidência
        fence = "`" * max(3, max((len(m) for m in re.findall(r"`+", evidence)), default=0) + 1)

        report += f"### 🔴 {cat} ({risk})\n"
        report += f"**Arquivo:** `{file_path}`\n"
        report += f"**Evidência (Código):**\n{fence}text\n{evidence}\n{fence}\n"
        report += f"**Análise Técnica:** {tech}\n\n"
    return report


def _extract_written_files(messages, only: set[str] | None = None) -> list[str]:
    """Caminhos gravados por tool calls de escrita (sem repetição, na ordem). `only` filtra por nome de tool."""
    written: list[str] = []
    for msg in messages:
        for call in getattr(msg, "tool_calls", None) or []:
            name = call.get("name")
            if name not in FILE_WRITE_TOOL_NAMES or (only is not None and name not in only):
                continue
            file_path = (call.get("args") or {}).get("file_path")
            if isinstance(file_path, str) and file_path.strip() and file_path not in written:
                written.append(file_path)
    return written


def _messages_of_current_task(messages) -> list:
    """Mensagens da execução ATUAL da tarefa (a partir do último prompt interno da tarefa)."""
    start = 0
    for index in range(len(messages) - 1, -1, -1):
        tag = (getattr(messages[index], "additional_kwargs", None) or {}).get("message_tag")
        if tag == "internal_task_instruction":
            start = index
            break
    return list(messages[start:])



# ----------------------------------------------------------------------
# Pipeline do Heavy: stack, mapa visual, mapa bruto e validação de tasks
# ----------------------------------------------------------------------

_TREE_IGNORED_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "env", ".next", "dist",
    "build", "out", ".expo", ".idea", ".vscode", "staticfiles", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "site-packages", "coverage", "htmlcov", "target",
}
_TREE_SKIP_FILES = {".ds_store", "thumbs.db", ".env"}
_TREE_SKIP_SUFFIXES = {".pyc", ".pyo", ".log"}
_TREE_ICONS = {
    ".py": "🐍", ".js": "🟨", ".jsx": "⚛️", ".ts": "🟦", ".tsx": "⚛️", ".php": "🐘",
    ".html": "🌐", ".css": "🎨", ".scss": "🎨", ".json": "🧾", ".md": "📝", ".txt": "📄",
    ".sql": "🗄️", ".yml": "⚙️", ".yaml": "⚙️", ".toml": "⚙️", ".ini": "⚙️", ".cfg": "⚙️",
    ".sh": "🖥️", ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️", ".svg": "🖼️", ".ico": "🖼️",
    ".gif": "🖼️", ".zip": "📦", ".sqlite3": "🗄️", ".db": "🗄️",
}


def _tree_icon(name: str) -> str:
    return _TREE_ICONS.get(Path(name).suffix.lower(), "📄")


def _tree_skip_file(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TREE_SKIP_FILES or Path(lowered).suffix in _TREE_SKIP_SUFFIXES


def _tree_children(directory: Path) -> list[Path]:
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    dirs = sorted(
        (e for e in entries if e.is_dir() and e.name not in _TREE_IGNORED_DIRS and not e.name.startswith(".")),
        key=lambda e: e.name.lower(),
    )
    files = sorted(
        (e for e in entries if e.is_file() and not _tree_skip_file(e.name)),
        key=lambda e: e.name.lower(),
    )
    return dirs + files


def render_project_tree(root, max_depth: int = 4, max_entries: int = 300) -> str:
    """Árvore visual (📁/📄) montada por código, sem LLM: sempre fiel ao disco."""
    base = Path(root)
    if not base.is_dir():
        return ""

    lines = [f"📁 {base.name or str(base)}/"]
    counters = {"shown": 0, "omitted": 0}

    def _walk(directory: Path, prefix: str, depth: int) -> None:
        items = _tree_children(directory)
        for index, entry in enumerate(items):
            if counters["shown"] >= max_entries:
                counters["omitted"] += len(items) - index
                return
            is_last = index == len(items) - 1
            branch = "└── " if is_last else "├── "
            counters["shown"] += 1
            if entry.is_dir():
                at_limit = depth + 1 >= max_depth
                hidden = " …" if at_limit and _tree_children(entry) else ""
                lines.append(f"{prefix}{branch}📁 {entry.name}/{hidden}")
                if not at_limit:
                    _walk(entry, prefix + ("    " if is_last else "│   "), depth + 1)
            else:
                lines.append(f"{prefix}{branch}{_tree_icon(entry.name)} {entry.name}")

    _walk(base, "", 0)
    if counters["omitted"]:
        lines.append(f"… e mais {counters['omitted']} itens (peça uma subpasta para ver o resto)")
    return "\n".join(lines)


def _read_small(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def detect_project_stack(workspace: str | None, max_depth: int = 3) -> str:
    """Descreve a stack e as pastas de topo REAIS do workspace (marcadores no disco)."""
    if not workspace:
        return ""
    root = Path(workspace)
    if not root.is_dir():
        return ""

    found: list[str] = []
    manage_dirs: list[str] = []

    def add(label: str) -> None:
        if label not in found:
            found.append(label)

    root_str = str(root)
    for current, dirs, files in _os.walk(root_str):
        dirs[:] = [d for d in dirs if d not in _TREE_IGNORED_DIRS and not d.startswith(".")]
        depth = current[len(root_str):].count(_os.sep)
        if depth >= max_depth:
            dirs[:] = []
        rel = _os.path.relpath(current, root_str)
        where = "raiz" if rel == "." else rel.replace("\\", "/")
        by_lower = {name.lower(): name for name in files}

        if "manage.py" in by_lower:
            add("Django")
            manage_dirs.append(where)
        for marker in ("requirements.txt", "pyproject.toml", "pipfile"):
            if marker in by_lower:
                text = _read_small(Path(current) / by_lower[marker]).lower()
                for needle, label in (
                    ("djangorestframework", "Django REST Framework"),
                    ("simplejwt", "SimpleJWT"),
                    ("django", "Django"),
                    ("fastapi", "FastAPI"),
                    ("flask", "Flask"),
                    ("sqlalchemy", "SQLAlchemy"),
                    ("celery", "Celery"),
                ):
                    if needle in text:
                        add(label)
        if "package.json" in by_lower:
            try:
                data = _json.loads(_read_small(Path(current) / by_lower["package.json"]) or "{}")
            except ValueError:
                data = {}
            deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
            for needle, label in (
                ("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("express", "Express"),
                ("vite", "Vite"), ("tailwindcss", "Tailwind"), ("typescript", "TypeScript"),
                ("expo", "Expo"), ("@nestjs/core", "NestJS"),
            ):
                if needle in deps:
                    add(label)
        if "composer.json" in by_lower and "laravel/framework" in _read_small(Path(current) / by_lower["composer.json"]):
            add("Laravel")
        if "pom.xml" in by_lower:
            add("Java/Maven")
        if "go.mod" in by_lower:
            add("Go")

    top_dirs = [e.name for e in _tree_children(root) if e.is_dir()][:15]
    stack_line = ", ".join(found) if found else "não detectada (sem manage.py, requirements.txt, package.json ou composer.json)"
    top_line = ", ".join(f"{name}/" for name in top_dirs) if top_dirs else "(nenhuma subpasta)"
    manage_line = f" (manage.py em: {', '.join(manage_dirs)})" if manage_dirs else ""
    return f"Stack detectada: {stack_line}{manage_line}\nPastas de topo reais: {top_line}"


def _leaf_name(dir_path: str) -> str:
    return Path(str(dir_path).replace("\\", "/")).name.lower()


def _dir_depth(dir_path: str) -> int:
    return len([part for part in re.split(r"[\\/]+", str(dir_path)) if part and part != "."])


def _mentions_name(name: str, text: str) -> bool:
    if not name or name == ".":
        return False
    pattern = r"(?<!\w)" + re.escape(name) + r"(?!\w)"
    return re.search(pattern, text.lower()) is not None


def extract_repo_map_output(messages, start_idx: int, user_text: str = "", max_chars: int = 14000) -> str:
    """Saída CRUA de generate_repo_map desta execução (a limpeza do gatherer apaga as ToolMessages)."""
    scope = messages[start_idx + 1 :]
    call_info: dict[str, tuple[str, str]] = {}
    for msg in scope:
        for call in getattr(msg, "tool_calls", None) or []:
            args = call.get("args") or {}
            call_info[str(call.get("id"))] = (call.get("name") or "", str(args.get("dir_path") or "."))

    maps: list[tuple[str, str]] = []
    for msg in scope:
        if msg.type != "tool":
            continue
        fallback = (getattr(msg, "name", "") or "", ".")
        name, dir_path = call_info.get(str(getattr(msg, "tool_call_id", "")), fallback)
        if name != "generate_repo_map":
            continue
        text = msg.content if isinstance(msg.content, str) else str(msg.content)
        if not text.strip() or text.strip().startswith("ERRO"):
            continue
        maps.append((dir_path, text.strip()))

    if not maps:
        return ""

    mentioned = [m for m in maps if _mentions_name(_leaf_name(m[0]), user_text)]
    chosen = max(mentioned, key=lambda m: _dir_depth(m[0])) if mentioned else min(maps, key=lambda m: _dir_depth(m[0]))
    text = chosen[1]
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n… (mapa truncado)"
    return text


def pick_map_dir(workspace: str | None, trace: list[dict] | None, user_text: str = "") -> Path | None:
    """Pasta cujo mapa visual deve ser mostrado: a citada no pedido, senão a mais rasa mapeada."""
    if not workspace:
        return None
    root = Path(workspace)
    if not root.is_dir():
        return None
    resolved_root = root.resolve()

    candidates: list[tuple[str, Path]] = []
    for call in trace or []:
        if call.get("name") != "generate_repo_map":
            continue
        raw = str((call.get("args") or {}).get("dir_path") or ".").strip().replace("\\", "/")
        path = Path(raw)
        candidate = (path if path.is_absolute() else root / raw).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            continue
        if candidate.is_dir():
            candidates.append((raw, candidate))

    if not candidates:
        return root

    mentioned = [c for c in candidates if _mentions_name(_leaf_name(c[0]), user_text)]
    if mentioned:
        return max(mentioned, key=lambda c: _dir_depth(c[0]))[1]
    return min(candidates, key=lambda c: _dir_depth(c[0]))[1]


_TASK_WORD_RE = re.compile(r"\b(tasks?|tarefas?)\b", re.IGNORECASE)
_TASK_VERB_RE = re.compile(
    r"\b(gere|crie|implemente|adicione|corrija|refatore|monte|planeje|aplique|aplicar)\b", re.IGNORECASE
)
_MAP_INTENT_RE = re.compile(
    r"\b(mapa|[áa]rvore|tree|estrutura\s+(?:de\s+)?(?:pastas?|diret[óo]rios?|arquivos?|projeto))\b",
    re.IGNORECASE,
)
_FEATURE_RE = re.compile(r"login|logout|cadastro|registro|autentica|crud|sess[ãa]o", re.IGNORECASE)


def wants_tasks(text: str) -> bool:
    text = text or ""
    if _TASK_WORD_RE.search(text):
        return True
    return bool(_TASK_VERB_RE.search(text)) and not _MAP_INTENT_RE.search(text)


def wants_project_map(text: str) -> bool:
    text = text or ""
    return bool(_MAP_INTENT_RE.search(text)) and not _TASK_WORD_RE.search(text)


def needs_task_split(text: str) -> bool:
    return wants_tasks(text) and bool(_FEATURE_RE.search(text or ""))


_PIPELINE_WORDS_RE = re.compile(r"dossi[eê]|context gatherer|\bcoletor\b|tool calls?", re.IGNORECASE)
_ECHO_RE = re.compile(
    r"^\s*voc[êe]\s+(?:est[áa]\s+(?:solicitando|pedindo)|deseja|quer|pediu|solicitou)", re.IGNORECASE
)


def mentions_internal_pipeline(text: str) -> bool:
    return bool(_PIPELINE_WORDS_RE.search(text or ""))


def starts_with_echo(text: str) -> bool:
    return bool(_ECHO_RE.search(text or ""))


_DOSSIER_FILE_RE = re.compile(r"(?m)^###\s+\d+\.\s+Arquivo:\s*`?([^`\n]+?)`?\s*$")
_WILL_CREATE_RE = re.compile(r"n[ãa]o existe|dever[áa] ser criado|ser[áa] criado", re.IGNORECASE)


def ground_dossier(dossier: str, workspace: str | None) -> tuple[str, list[str]]:
    """Remove do dossiê os blocos de arquivos que NÃO existem no disco (alucinação do gatherer)."""
    if not dossier or not workspace:
        return dossier, []
    matches = list(_DOSSIER_FILE_RE.finditer(dossier))
    if not matches:
        return dossier, []

    root = Path(workspace)
    tail_match = re.search(r"(?m)^MAPA ESTRUTURAL", dossier[matches[-1].end():])
    tail_start = matches[-1].end() + tail_match.start() if tail_match else len(dossier)

    pieces = [dossier[: matches[0].start()]]
    removed: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else tail_start
        section = dossier[match.start():end]
        raw_path = match.group(1).strip().replace("\\", "/")
        path = Path(raw_path)
        candidate = path if path.is_absolute() else root / raw_path
        if candidate.exists() or _WILL_CREATE_RE.search(section):
            pieces.append(section)
        else:
            removed.append(raw_path)
    pieces.append(dossier[tail_start:])
    return "".join(pieces), removed


_CREATE_RE = re.compile(r"\b(cri[ae]r?|crie|cria[çc][ãa]o|novo arquivo|novo m[óo]dulo|create|new file)\b", re.IGNORECASE)


def _task_rel_path(raw, root: Path) -> str:
    text = str(raw or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return text
    return text


def validate_generated_tasks(tasks, workspace: str | None, stack: str | None = None) -> tuple[list[dict], list[str]]:
    """Separa tasks utilizáveis das que apontam para arquivos inexistentes, stack errada ou lógica genérica."""
    if not tasks:
        return [], []
    root = Path(workspace) if workspace else None
    stack_lower = (stack or "").lower()
    has_django = "django" in stack_lower
    has_fastapi = "fastapi" in stack_lower

    kept: list[dict] = []
    problems: list[str] = []
    for task in tasks:
        title = str(task.get("title") or "Sem Título").strip()
        text = " ".join(str(task.get(key) or "") for key in ("objective", "target", "logic"))
        issues: list[str] = []

        files = [f for f in (task.get("files") or []) if str(f).strip()]
        if not files:
            issues.append("nenhum arquivo listado em `files`")
        if len(str(task.get("logic") or "").strip()) < 80:
            issues.append("`logic` genérica (menos de 80 caracteres)")

        if root is not None:
            for raw in files:
                rel = _task_rel_path(raw, root)
                target = root / rel
                if target.exists():
                    continue
                if target.parent.is_dir() and _CREATE_RE.search(text):
                    continue
                issues.append(f"`{rel}` não existe no projeto")

        if has_django and not has_fastapi and re.search(r"\b(fastapi|apirouter|flask)\b", text, re.IGNORECASE):
            issues.append("cita FastAPI/Flask, mas o projeto é Django")
        if has_fastapi and not has_django and re.search(r"\b(django|rest_framework)\b", text, re.IGNORECASE):
            issues.append("cita Django, mas o projeto é FastAPI")

        if issues:
            problems.append(f"{title}: " + "; ".join(issues))
        else:
            kept.append(task)
    return kept, problems


def number_generated_tasks(tasks: list[dict]) -> list[dict]:
    """Numera as tasks ([1/N]) e registra a ordem de execução na restrição de cada uma."""
    total = len(tasks)
    if total < 2:
        return tasks
    for position, task in enumerate(tasks, start=1):
        title = re.sub(r"^\[\d+/\d+\]\s*", "", str(task.get("title") or "Sem Título").strip())
        task["title"] = f"[{position}/{total}] {title}"
        if position > 1:
            extra = f"Executar somente depois da task {tasks[position - 2]['title']}."
            current = str(task.get("constraints") or "").strip()
            if not current or current.lower() in {"nenhuma", "nenhum"}:
                task["constraints"] = extra
            else:
                task["constraints"] = f"{current}\n{extra}"
    return tasks
