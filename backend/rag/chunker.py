"""Divide arquivos em chunks com identidade (classe, função/método, cabeçalho...).

Python usa AST. JS/TS usa declarações no início da linha. Markdown usa títulos.
O resto usa janelas de linhas. Nada aqui usa LLM nem rede.
"""

from __future__ import annotations

import ast
import re

from .entities import Chunk

CLASS_WHOLE_MAX_LINES = 80  # classe até este tamanho vira UM chunk
HEADER_MAX_LINES = 200
WINDOW_LINES = 80
WINDOW_OVERLAP = 10

_JS_DECL = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?:"
    r"(?P<fn>(?:async\s+)?function\s*\*?\s*(?P<fname>[A-Za-z_$][\w$]*))"
    r"|(?P<cls>class\s+(?P<cname>[A-Za-z_$][\w$]*))"
    r"|(?:const|let|var)\s+(?P<vname>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
    r")"
)
_MD_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


def chunk_file(path: str, text: str, language: str, max_lines: int = 200) -> list[Chunk]:
    text = text.replace("\r\n", "\n")
    if not text.strip():
        return []
    if language == "python":
        try:
            raw = _python_chunks(path, text)
        except SyntaxError:
            raw = _window_chunks(path, text, language)
    elif language in {"javascript", "typescript"}:
        raw = _js_chunks(path, text, language) or _window_chunks(path, text, language)
    elif language == "markdown":
        raw = _markdown_chunks(path, text) or _window_chunks(path, text, language)
    else:
        raw = _window_chunks(path, text, language)

    result: list[Chunk] = []
    for chunk in raw:
        result.extend(_split_long(chunk, max_lines))
    return result


def _make(path, language, kind, qualname, parent, start, end, code) -> Chunk:
    return Chunk(path=path, language=language, kind=kind, qualname=qualname, parent=parent,
                 start_line=start, end_line=end, code=code)


def _numbered_slice(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start - 1 : end])


def _span(node: ast.AST) -> tuple[int, int]:
    decorators = getattr(node, "decorator_list", [])
    start = min([node.lineno] + [d.lineno for d in decorators])  # type: ignore[attr-defined]
    return start, node.end_lineno  # type: ignore[attr-defined,return-value]


# ── Python ───────────────────────────────────────────────────────────────
def _python_chunks(path: str, text: str) -> list[Chunk]:
    tree = ast.parse(text)
    lines = text.split("\n")
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    chunks: list[Chunk] = []

    first_def_start = None
    for node in tree.body:
        if isinstance(node, defs):
            first_def_start = _span(node)[0]
            break

    header_end = (first_def_start - 1) if first_def_start else len(lines)
    header_end = min(header_end, HEADER_MAX_LINES)
    if header_end >= 1 and _numbered_slice(lines, 1, header_end).strip():
        chunks.append(_make(path, "python", "header", "<cabeçalho do módulo>", "", 1, header_end,
                            _numbered_slice(lines, 1, header_end)))

    if first_def_start:
        late = [n for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.lineno > first_def_start]
        if late:
            parts = [f"# linha {n.lineno}\n{_numbered_slice(lines, *_span(n))}" for n in late]
            chunks.append(_make(path, "python", "constants", "<constantes do módulo>", "",
                                late[0].lineno, late[-1].end_lineno or late[-1].lineno, "\n\n".join(parts)))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            s, e = _span(node)
            chunks.append(_make(path, "python", "function", node.name, "", s, e, _numbered_slice(lines, s, e)))
        elif isinstance(node, ast.ClassDef):
            chunks.extend(_class_chunks(path, lines, node, parent="", prefix=""))
    return chunks


def _class_chunks(path: str, lines: list[str], node: ast.ClassDef, parent: str, prefix: str) -> list[Chunk]:
    s, e = _span(node)
    qual = f"{prefix}{node.name}"
    if e - s + 1 <= CLASS_WHOLE_MAX_LINES:
        return [_make(path, "python", "class", qual, parent, s, e, _numbered_slice(lines, s, e))]

    members = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    first_member = _span(members[0])[0] if members else e + 1
    skeleton = [_numbered_slice(lines, s, first_member - 1)]
    for member in members:
        if isinstance(member, ast.ClassDef):
            skeleton.append(f"    class {member.name}: ...")
            continue
        ms, _ = _span(member)
        body_start = member.body[0].lineno
        sig = _numbered_slice(lines, ms, max(ms, body_start - 1))
        skeleton.append(sig + "\n        ...")
    out = [_make(path, "python", "class_skeleton", qual, parent, s, e, "\n".join(skeleton))]

    for member in members:
        ms, me = _span(member)
        if isinstance(member, ast.ClassDef):
            out.extend(_class_chunks(path, lines, member, parent=qual, prefix=f"{qual}."))
        else:
            out.append(_make(path, "python", "method", f"{qual}.{member.name}", qual, ms, me,
                             _numbered_slice(lines, ms, me)))
    return out


# ── JavaScript / TypeScript ──────────────────────────────────────────────
def _js_chunks(path: str, text: str, language: str) -> list[Chunk]:
    lines = text.split("\n")
    starts: list[tuple[int, str, str]] = []  # (linha 1-based, kind, nome)
    for index, line in enumerate(lines, start=1):
        match = _JS_DECL.match(line)
        if not match:
            continue
        if match.group("cls"):
            starts.append((index, "class", match.group("cname")))
        elif match.group("fn"):
            starts.append((index, "function", match.group("fname")))
        else:
            starts.append((index, "function", match.group("vname")))
    if not starts:
        return []

    chunks: list[Chunk] = []
    first = starts[0][0]
    # comentários imediatamente acima da 1ª declaração pertencem a ela
    while first > 1 and lines[first - 2].strip().startswith(("//", "*", "/*")):
        first -= 1
    if first > 1 and _numbered_slice(lines, 1, first - 1).strip():
        chunks.append(_make(path, language, "header", "<cabeçalho do arquivo>", "", 1, first - 1,
                            _numbered_slice(lines, 1, first - 1)))
    for i, (start, kind, name) in enumerate(starts):
        end = (starts[i + 1][0] - 1) if i + 1 < len(starts) else len(lines)
        while end > start and (not lines[end - 1].strip() or lines[end - 1].strip().startswith(("//", "/*", "*"))):
            end -= 1
        chunks.append(_make(path, language, kind, name, "", start, end, _numbered_slice(lines, start, end)))
    return chunks


# ── Markdown e janelas ───────────────────────────────────────────────────
def _markdown_chunks(path: str, text: str) -> list[Chunk]:
    lines = text.split("\n")
    marks = [(i, m.group(2)) for i, line in enumerate(lines, start=1) if (m := _MD_HEADING.match(line))]
    if not marks:
        return []
    chunks: list[Chunk] = []
    if marks[0][0] > 1 and _numbered_slice(lines, 1, marks[0][0] - 1).strip():
        chunks.append(_make(path, "markdown", "section", "<introdução>", "", 1, marks[0][0] - 1,
                            _numbered_slice(lines, 1, marks[0][0] - 1)))
    for i, (start, title) in enumerate(marks):
        end = (marks[i + 1][0] - 1) if i + 1 < len(marks) else len(lines)
        chunks.append(_make(path, "markdown", "section", title, "", start, end, _numbered_slice(lines, start, end)))
    return chunks


def _window_chunks(path: str, text: str, language: str) -> list[Chunk]:
    lines = text.split("\n")
    chunks: list[Chunk] = []
    start = 1
    while start <= len(lines):
        end = min(len(lines), start + WINDOW_LINES - 1)
        code = _numbered_slice(lines, start, end)
        if code.strip():
            chunks.append(_make(path, language, "block", f"{path}:{start}-{end}", "", start, end, code))
        if end >= len(lines):
            break
        start = end - WINDOW_OVERLAP + 1
    return chunks


def _split_long(chunk: Chunk, max_lines: int) -> list[Chunk]:
    lines = chunk.code.split("\n")
    if len(lines) <= max_lines:
        return [chunk]
    step = max(20, max_lines - WINDOW_OVERLAP)
    windows = [(i, min(len(lines), i + max_lines)) for i in range(0, len(lines), step)]
    if len(windows) > 1 and windows[-1][1] - windows[-1][0] <= WINDOW_OVERLAP:
        windows.pop()
    parts = len(windows)
    out = []
    for number, (a, b) in enumerate(windows, start=1):
        out.append(Chunk(
            path=chunk.path, language=chunk.language, kind=chunk.kind, qualname=chunk.qualname,
            parent=chunk.parent, start_line=chunk.start_line + a, end_line=chunk.start_line + b - 1,
            code="\n".join(lines[a:b]), part=number, parts=parts,
        ))
    return out
