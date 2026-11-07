"""Checagem de fundamentação (grounding) SEM LLM.

Dado um documento gerado (ex.: um .txt/.md de documentação) e os arquivos-fonte
em que ele deveria se basear, extrai do documento os valores "verificáveis"
(textos entre aspas/crases, nomes de header e códigos HTTP) e confere se cada um
aparece literalmente nas fontes. O que não aparece em lugar nenhum é sinalizado.

É uma checagem de REVISÃO, não uma prova: valores implícitos do framework
(ex.: um 405 que o Django devolve sozinho) também aparecem como "não encontrados"
e podem ser liberados com a lista `allow`.
"""

from __future__ import annotations

import http
import re
from pathlib import Path

_BLOCKED_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__"}

# Só valores "com cara de identificador" são conferidos (sem espaços, sem acentos):
# nomes de campo, constantes, headers, valores de enum, rotas.
_TOKEN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-:/@+]{1,59}$")
_QUOTED = re.compile(r"`([^`\n]{2,60})`|\"([^\"\n]{2,60})\"|'([A-Za-z0-9_][A-Za-z0-9_.\-:/@+]{1,59})'")
_HEADER = re.compile(r"\bX-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b")
_NUMBER = re.compile(r"(?<![\w.])([1-5]\d\d)(?![\w.])")
_HTTP_HINT = re.compile(r"http|status|código|codigo|retorn|respost|response|erro|error", re.IGNORECASE)

_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

DEFAULT_ALLOW = {
    "VERIFICAR",
    "true", "false", "null", "None", "True", "False",
    "json", "JSON", "utf-8", "UTF-8",
    "application/json", "Content-Type", "Authorization",
}


def _safe_read(workspace: str, rel: str) -> str | None:
    """Lê um arquivo de texto dentro do workspace; None se não existir/fora/bloqueado."""
    try:
        root = Path(workspace).resolve()
        target = (root / rel.strip()).resolve()
        relative = target.relative_to(root)
    except (ValueError, OSError):
        return None

    for part in relative.parts:
        name = part.lower()
        if name in _BLOCKED_PARTS or name == ".env" or name.startswith(".env."):
            return None

    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def extract_literals(doc_text: str) -> dict[str, list[str]]:
    """Valores verificáveis do documento, sem repetição e na ordem em que aparecem."""
    quoted: list[str] = []
    for match in _QUOTED.finditer(doc_text):
        value = next((g for g in match.groups() if g), "").strip()
        if value and _TOKEN.match(value) and value not in quoted:
            quoted.append(value)

    headers: list[str] = []
    for match in _HEADER.finditer(doc_text):
        value = match.group(0)
        if value not in headers:
            headers.append(value)

    codes: list[str] = []
    for line in doc_text.splitlines():
        if not _HTTP_HINT.search(line):
            continue
        for match in _NUMBER.finditer(line):
            value = match.group(1)
            try:
                http.HTTPStatus(int(value))
            except ValueError:
                continue
            if value not in codes:
                codes.append(value)

    return {"quoted": quoted, "headers": headers, "http_codes": codes}


def _in_sources(kind: str, value: str, sources_text: str, sources_lower: str) -> bool:
    if kind == "headers":
        wsgi = "HTTP_" + value.upper().replace("-", "_")
        return value.lower() in sources_lower or wsgi in sources_text

    if kind == "http_codes":
        code = int(value)
        name = http.HTTPStatus(code).name
        candidates = (f"HTTP_{code}", f"HTTPStatus.{name}", f"status.{name}")
        return bool(re.search(rf"(?<![\w.]){code}(?![\w.])", sources_text)) or any(
            c in sources_text for c in candidates
        )

    if value.upper() in _HTTP_METHODS:
        method = value.lower()
        return bool(
            re.search(rf"def\s+{method}\b|['\"]{method}['\"]|methods\s*=.*{method}", sources_lower)
        )

    if value in sources_text:
        return True

    if value.upper().startswith("X-"):
        return value.lower() in sources_lower or ("HTTP_" + value.upper().replace("-", "_")) in sources_text

    return False


def find_ungrounded(doc_text: str, sources_text: str, allow: set[str] | None = None) -> dict[str, list[str]]:
    """Valores citados no documento que não existem nas fontes, por categoria."""
    allowed = {a.lower() for a in (DEFAULT_ALLOW | set(allow or ()))}
    sources_lower = sources_text.lower()
    missing: dict[str, list[str]] = {}

    for kind, values in extract_literals(doc_text).items():
        for value in values:
            if value.lower() in allowed:
                continue
            if not _in_sources(kind, value, sources_text, sources_lower):
                missing.setdefault(kind, []).append(value)

    return missing


def check_literals_grounded(
    doc_path: str,
    sources: list[str],
    workspace: str,
    allow: list[str] | None = None,
    max_report: int = 25,
) -> list[str]:
    """Devolve a lista de falhas (vazia = tudo fundamentado nas fontes)."""
    doc_text = _safe_read(workspace, doc_path)
    if doc_text is None:
        return [f"literals_grounded: não foi possível ler o documento '{doc_path}'."]

    texts: list[str] = []
    problems: list[str] = []
    for source in sources:
        text = _safe_read(workspace, source)
        if text is None:
            problems.append(f"literals_grounded: fonte '{source}' não encontrada no workspace.")
        else:
            texts.append(text)

    if not texts:
        return problems or ["literals_grounded: nenhuma fonte foi informada."]

    missing = find_ungrounded(doc_text, "\n".join(texts), set(allow or ()))
    if not missing:
        return problems

    labels = {
        "quoted": "valores entre aspas/crases",
        "headers": "headers",
        "http_codes": "códigos HTTP",
    }
    shown = 0
    parts: list[str] = []
    for kind, values in missing.items():
        room = max_report - shown
        if room <= 0:
            break
        chunk = values[:room]
        shown += len(chunk)
        parts.append(f"{labels[kind]}: " + ", ".join(repr(v) for v in chunk))

    total = sum(len(v) for v in missing.values())
    extra = f" (+{total - shown} omitidos)" if total > shown else ""
    problems.append(
        f"literals_grounded: '{doc_path}' cita {total} valor(es) que NÃO aparecem nas fontes "
        f"({', '.join(sources)}) — " + "; ".join(parts) + extra + ". "
        "Remova, corrija ou troque por 'VERIFICAR' o que não estiver no código."
    )
    return problems


DOC_SUFFIXES = {".md", ".markdown", ".txt"}


def auto_check_documents(written: list[str], task_files: list[str], workspace: str) -> list[str]:
    """Confere cada documento (.md/.txt) gravado contra os demais arquivos da tarefa.

    `written`: caminhos gravados pelo agente; `task_files`: campo `files` da tarefa.
    Sem documentos ou sem arquivos-fonte, não há o que conferir (lista vazia).
    """
    docs: list[str] = []
    for item in written:
        if Path(item).suffix.lower() in DOC_SUFFIXES and item not in docs:
            docs.append(item)

    sources = [
        f for f in task_files
        if Path(f).suffix.lower() not in DOC_SUFFIXES | {".pdf"} and _safe_read(workspace, f) is not None
    ]
    if not docs or not sources:
        return []

    failures: list[str] = []
    for doc in docs:
        failures.extend(check_literals_grounded(doc, sources, workspace))
    return failures
