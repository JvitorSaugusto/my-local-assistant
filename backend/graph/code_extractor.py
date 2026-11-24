"""Extrator estruturado de trechos de código por termo, função, rota ou classe/View.

Retorna blocos completos (sem cortar funções/métodos/classes no meio), com cabeçalho
padronizado (`ARQUIVO`, `CAMINHO`, `ESCOPO`, `MATCH`) e salva automaticamente em `.txt`
na pasta de artefatos (`pack_dir()`) quando o resultado for extenso ou solicitado.
"""

from __future__ import annotations

import ast
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.graph.ops_core import _BAD_EXT, _ZIP_BLOCKED_DIRS, is_secret_path, pack_dir

_JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_IGNORED_DIRS = _ZIP_BLOCKED_DIRS | {"dist", "build", ".next", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_JS_DECL_RE = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?"
    r"(?:(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|"
    r"class\s+([A-Za-z_$][\w$]*)|"
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>|"
    r"(?:public|private|protected|static|async|\s)*([A-Za-z_$][\w$]*)\s*\([^;]*\)\s*\{)"
)


@dataclass
class ExtractedBlock:
    rel_path: str
    start_line: int
    end_line: int
    scope: str
    code: str
    matches: list[str] = field(default_factory=list)


def _iter_target_files(root: Path, subpath: str = "") -> list[Path]:
    base = root
    if subpath and str(subpath).strip():
        clean = str(subpath).strip().replace("\\", "/")
        while clean.startswith("./"):
            clean = clean[2:]
        candidate = (root / clean).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"ERRO DE SEGURANÇA: caminho fora do workspace: {subpath}") from exc
        if not candidate.exists():
            raise ValueError(f"ERRO: caminho não encontrado no workspace: {subpath}")
        if candidate.is_file():
            return [candidate]
        base = candidate

    found: list[Path] = []
    for current, dirs, names in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in _IGNORED_DIRS and not d.startswith("."))
        for name in sorted(names):
            full = Path(current, name)
            rel = full.relative_to(root).as_posix()
            if is_secret_path(rel) or rel.lower().endswith(_BAD_EXT):
                continue
            found.append(full)
    return found


def _py_node_span(node: ast.AST) -> tuple[int, int]:
    decs = getattr(node, "decorator_list", None) or []
    start = min([getattr(node, "lineno", 1)] + [getattr(d, "lineno", 1) for d in decs])
    end = getattr(node, "end_lineno", getattr(node, "lineno", start)) or start
    return start, max(start, end)


def _py_scope_for_line(tree: ast.AST, line_no: int, lines: list[str], include_full_class: bool) -> tuple[int, int, str]:
    """Encontra o escopo AST (classe/função/método) que envolve `line_no`."""
    stack: list[ast.AST] = []

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                s, e = _py_node_span(child)
                if s <= line_no <= e:
                    stack.append(child)
                    walk(child)
                    return

    walk(tree)

    if not stack:
        # Nível de módulo (ex.: urlpatterns, constantes, inclusão de routers)
        start = max(1, line_no - 10)
        end = min(len(lines), line_no + 15)
        return start, end, f"módulo (linhas {start}-{end})"

    # Se pediu a classe/view inteira, ou se o match caiu diretamente na linha de declaração da classe
    classes = [n for n in stack if isinstance(n, ast.ClassDef)]
    innermost = stack[-1]
    if classes and (
        include_full_class
        or (isinstance(innermost, ast.ClassDef) and line_no <= innermost.lineno + 1)
    ):
        target = classes[0] if include_full_class else innermost
        s, e = _py_node_span(target)
        return s, e, f"class {target.name} (linhas {s}-{e})"

    if isinstance(innermost, ast.ClassDef):
        s, e = _py_node_span(innermost)
        if (e - s) <= 220:
            return s, e, f"class {innermost.name} (linhas {s}-{e})"
        # Classe muito grande com match em atributo fora de método: devolve janela ampla dentro da classe
        ws = max(s, line_no - 12)
        we = min(e, line_no + 18)
        return ws, we, f"class {innermost.name} (linhas {ws}-{we})"

    # Função ou método (mantém breadcrumb completo: class X > def y)
    s, e = _py_node_span(innermost)
    parts = []
    for n in stack:
        if isinstance(n, ast.ClassDef):
            parts.append(f"class {n.name}")
        elif isinstance(n, ast.AsyncFunctionDef):
            parts.append(f"async def {n.name}")
        elif isinstance(n, ast.FunctionDef):
            parts.append(f"def {n.name}")
    return s, e, f"{' > '.join(parts)} (linhas {s}-{e})"


def _js_scope_for_line(lines: list[str], line_no: int, include_full_class: bool) -> tuple[int, int, str]:
    """Heurística de escopo para JS/TS: acha declaração acima e fecha o bloco por chaves."""
    idx = line_no - 1
    decl_idx = None
    decl_name = ""
    decl_kind = ""

    for i in range(idx, max(-1, idx - 120), -1):
        m = _JS_DECL_RE.match(lines[i])
        if not m:
            continue
        is_class = bool(m.group(2))
        name = m.group(1) or m.group(2) or m.group(3) or m.group(4) or ""
        if include_full_class and not is_class:
            continue
        decl_idx = i
        decl_name = name
        decl_kind = "class" if is_class else "function"
        break

    if decl_idx is None:
        s = max(1, line_no - 10)
        e = min(len(lines), line_no + 15)
        return s, e, f"linhas {s}-{e}"

    depth = 0
    opened = False
    end_idx = min(len(lines) - 1, decl_idx + 220)
    for j in range(decl_idx, min(len(lines), decl_idx + 260)):
        depth += lines[j].count("{") - lines[j].count("}")
        if "{" in lines[j]:
            opened = True
        if opened and depth <= 0 and j >= idx:
            end_idx = j
            break

    s, e = decl_idx + 1, end_idx + 1
    return s, e, f"{decl_kind} {decl_name} (linhas {s}-{e})"


def _fallback_scope(lines: list[str], line_no: int) -> tuple[int, int, str]:
    s = max(1, line_no - 10)
    e = min(len(lines), line_no + 15)
    return s, e, f"linhas {s}-{e}"


def _dedupe_and_merge_blocks(blocks: list[ExtractedBlock]) -> list[ExtractedBlock]:
    """Mescla blocos iguais ou contidos em um bloco maior no mesmo arquivo."""
    by_file: dict[str, list[ExtractedBlock]] = {}
    for b in blocks:
        by_file.setdefault(b.rel_path, []).append(b)

    merged_all: list[ExtractedBlock] = []
    for rel, group in sorted(by_file.items()):
        group.sort(key=lambda b: (b.start_line, -(b.end_line - b.start_line)))
        kept: list[ExtractedBlock] = []
        for blk in group:
            contained = False
            for existing in kept:
                if existing.start_line <= blk.start_line and blk.end_line <= existing.end_line:
                    for m in blk.matches:
                        if m not in existing.matches:
                            existing.matches.append(m)
                    contained = True
                    break
            if not contained:
                kept.append(blk)
        merged_all.extend(kept)
    return merged_all


def format_extracted_blocks(blocks: list[ExtractedBlock], not_found: list[str] | None = None) -> str:
    sep = "# " + "=" * 40
    parts: list[str] = []
    if not_found:
        parts.append("=== TERMOS SEM OCORRÊNCIA ===\n" + "\n".join(f"- {q}" for q in not_found))
    for blk in blocks:
        filename = blk.rel_path.rsplit("/", 1)[-1]
        match_str = ", ".join(blk.matches)
        parts.append(
            f"{sep}\n"
            f"ARQUIVO: {filename}\n"
            f"CAMINHO: {blk.rel_path}\n"
            f"ESCOPO: {blk.scope}\n"
            f"MATCH: {match_str}\n"
            f"{sep}\n\n"
            f"{blk.code.rstrip()}"
        )
    return "\n\n".join(parts) + "\n"


def save_snippets_txt(content: str, hint: str = "trechos") -> Path:
    base = pack_dir()
    now = time.time()
    for old in base.glob("trechos_*.txt"):
        try:
            if now - old.stat().st_mtime > 30 * 24 * 3600:
                old.unlink()
        except OSError:
            continue
    slug = re.sub(r"[^a-z0-9]+", "-", str(hint).lower())[:36].strip("-") or "codigo"
    path = base / f"trechos_{time.strftime('%Y%m%d_%H%M%S')}_{slug}.txt"
    tmp = path.with_name(path.name + ".part")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def extract_snippets(
    workspace_path: str,
    queries: list[str],
    subpath: str = "",
    include_full_class: bool = False,
    save_txt: str = "auto",
    max_blocks: int = 25,
) -> dict[str, Any]:
    """Busca múltiplos termos no workspace/subpasta e extrai os escopos completos (função/método/classe)."""
    if not workspace_path or not str(workspace_path).strip():
        return {"error": "ERRO: nenhum projeto selecionado no workspace."}
    root = Path(workspace_path).expanduser().resolve()
    if not root.is_dir():
        return {"error": f"ERRO: diretório do workspace não existe: {workspace_path}"}

    clean_queries = [str(q).strip() for q in (queries or []) if str(q).strip()]
    clean_queries = list(dict.fromkeys(clean_queries))[:20]
    if not clean_queries:
        return {"error": "ERRO: informe pelo menos um termo, função, rota ou classe para localizar."}

    try:
        files = _iter_target_files(root, subpath)
    except ValueError as exc:
        return {"error": str(exc)}

    matched_queries: set[str] = set()
    raw_blocks: list[ExtractedBlock] = []
    lower_queries = [(q, q.lower()) for q in clean_queries]

    for full in files:
        if len(raw_blocks) >= max_blocks * 3:
            break
        try:
            data = full.read_bytes()
        except OSError:
            continue
        if len(data) > 2 * 1024 * 1024 or b"\0" in data[:8000]:
            continue
        text = data.decode("utf-8", errors="replace")
        low_text = text.lower()

        file_hits = [(orig, low) for orig, low in lower_queries if low in low_text]
        if not file_hits:
            continue

        rel = full.relative_to(root).as_posix()
        lines = text.splitlines()
        suffix = full.suffix.lower()
        py_tree = None
        if suffix == ".py":
            try:
                py_tree = ast.parse(text)
            except SyntaxError:
                py_tree = None

        for line_idx, line in enumerate(lines, start=1):
            low_line = line.lower()
            line_matches = [orig for orig, low in file_hits if low in low_line]
            if not line_matches:
                continue
            matched_queries.update(line_matches)
            if py_tree is not None:
                s, e, scope = _py_scope_for_line(py_tree, line_idx, lines, include_full_class)
            elif suffix in _JS_EXTS:
                s, e, scope = _js_scope_for_line(lines, line_idx, include_full_class)
            else:
                s, e, scope = _fallback_scope(lines, line_idx)
            code = "\n".join(lines[s - 1 : e])
            raw_blocks.append(
                ExtractedBlock(
                    rel_path=rel,
                    start_line=s,
                    end_line=e,
                    scope=scope,
                    code=code,
                    matches=list(line_matches),
                )
            )

    blocks = _dedupe_and_merge_blocks(raw_blocks)[:max_blocks]
    not_found = [q for q in clean_queries if q not in matched_queries]

    if not blocks:
        return {
            "blocks": [],
            "not_found": not_found,
            "txt_path": None,
            "txt_url": None,
            "formatted": "",
            "summary": "Nenhuma ocorrência encontrada para: " + ", ".join(clean_queries),
        }

    formatted = format_extracted_blocks(blocks, not_found)
    mode = str(save_txt or "auto").strip().lower()
    should_save = mode == "always" or (mode == "auto" and (len(formatted) > 3500 or len(blocks) >= 3))

    txt_path = None
    txt_url = None
    if should_save:
        hint = subpath.strip("/").split("/")[-1] if subpath.strip("/") else clean_queries[0]
        saved = save_snippets_txt(formatted, hint=hint)
        txt_path = str(saved)
        txt_url = f"/api/handoff/packs/{saved.name}"

    index_lines = [
        f"- `{b.rel_path}` · **{b.scope}** · match: {', '.join(f'`{m}`' for m in b.matches)}"
        for b in blocks
    ]
    return {
        "blocks": [
            {
                "path": b.rel_path,
                "scope": b.scope,
                "start_line": b.start_line,
                "end_line": b.end_line,
                "matches": b.matches,
            }
            for b in blocks
        ],
        "not_found": not_found,
        "txt_path": txt_path,
        "txt_url": txt_url,
        "txt_name": Path(txt_path).name if txt_path else None,
        "formatted": formatted,
        "summary": "\n".join(index_lines),
    }
