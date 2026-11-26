"""Extrator estruturado de trechos de código por termo, função, rota ou classe/View.

Retorna blocos completos (sem cortar funções/métodos/classes no meio), com cabeçalho
padronizado (`ARQUIVO`, `CAMINHO`, `ESCOPO`, `MATCH`), matching por fronteira de token
(evita falsos positivos como `sync` casando com `async`/`AsyncSession`), mesclagem de
janelas sobrepostas, ranking por relevância com cobertura justa por termo e salvamento
em `.txt` na pasta de artefatos (`pack_dir()`).
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
_MIGRATION_DIR_NAMES = {"migrations", "versions"}
_MAX_SCAN_FILES = 1500
_MAX_MERGED_MODULE_LINES = 120
_HIGH_SIGNAL_PATH_PARTS = ("routers", "router", "views", "controllers", "services", "endpoints", "api", "core")

_IDENT_RE = re.compile(r"^[A-Za-zÀ-ÿ0-9_]+$")
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
    is_module_window: bool = False
    is_fallback: bool = False
    score: float = 0.0


def _compile_query_matcher(query: str) -> re.Pattern[str]:
    """Compila matcher inteligente para cada termo.

    - Rotas com '/': ignora barras sobrando nas pontas (ex.: '/api/auth/jwt/' casa com '/api/auth/jwt').
    - Identificadores simples (ex.: 'sync', 'Gestor', 'jwt'): exige fronteira não-alfanumérica para
      evitar que 'sync' case com 'async' ou 'AsyncSession', mantendo match em '_sync_user' e '/users/sync'.
    - Expressões com pontuação/espaços: busca literal case-insensitive.
    """
    q = str(query or "").strip()
    if "/" in q:
        core = q.strip("/")
        if core:
            return re.compile(re.escape(core), re.IGNORECASE)
    if _IDENT_RE.fullmatch(q):
        return re.compile(rf"(?<![A-Za-z0-9]){re.escape(q)}(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(re.escape(q), re.IGNORECASE)


def _query_specificity(query: str) -> float:
    """Peso de especificidade do termo: rotas e nomes compostos têm prioridade sobre palavras curtas."""
    q = str(query or "").strip()
    base = q.split(" (via ", 1)[0]
    is_fb = " (via " in q
    weight = 2.0
    if "/" in base:
        weight += 8.0
    if "_" in base:
        weight += 4.0
    if len(base) >= 12:
        weight += 3.0
    elif len(base) >= 7:
        weight += 1.5
    if is_fb:
        weight *= 0.45
    return weight


def _clean_query_token(raw: str) -> str:
    q = str(raw or "").strip()
    if len(q) >= 2 and q[0] == q[-1] and q[0] in ("'", '"', "`"):
        q = q[1:-1].strip()
    return q


def _resolve_single_subpath(root: Path, raw_part: str) -> Path:
    clean = str(raw_part or "").strip().replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    candidate = (root / clean).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"ERRO DE SEGURANÇA: caminho fora do workspace: {raw_part}") from exc
    if not candidate.exists() and clean.lower().startswith(root.name.lower() + "/"):
        alt = (root / clean[len(root.name) + 1 :]).resolve()
        try:
            alt.relative_to(root)
            if alt.exists():
                candidate = alt
        except ValueError:
            pass
    if not candidate.exists():
        raise ValueError(f"ERRO: caminho não encontrado no workspace: {raw_part}")
    return candidate


def _iter_target_files(root: Path, subpath: str = "", include_migrations: bool = False) -> list[Path]:
    raw_parts = [p.strip() for p in re.split(r"[\n,;]+", str(subpath or "")) if p.strip()]
    targets = [_resolve_single_subpath(root, part) for part in raw_parts] if raw_parts else [root]

    found: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        if target.is_file():
            rel = target.relative_to(root).as_posix()
            if not is_secret_path(rel) and not rel.lower().endswith(_BAD_EXT) and target not in seen:
                seen.add(target)
                found.append(target)
            continue
        for current, dirs, names in os.walk(target):
            next_dirs = []
            for d in sorted(dirs):
                if d in _IGNORED_DIRS or d.startswith("."):
                    continue
                if not include_migrations and d.lower() in _MIGRATION_DIR_NAMES:
                    continue
                next_dirs.append(d)
            dirs[:] = next_dirs
            for name in sorted(names):
                full = Path(current, name)
                if full in seen:
                    continue
                rel = full.relative_to(root).as_posix()
                if is_secret_path(rel) or rel.lower().endswith(_BAD_EXT):
                    continue
                seen.add(full)
                found.append(full)
                if len(found) >= _MAX_SCAN_FILES:
                    return found
    return found


def _py_node_span(node: ast.AST) -> tuple[int, int]:
    decs = getattr(node, "decorator_list", None) or []
    start = min([getattr(node, "lineno", 1)] + [getattr(d, "lineno", 1) for d in decs])
    end = getattr(node, "end_lineno", getattr(node, "lineno", start)) or start
    return start, max(start, end)


def _py_scope_for_line(
    tree: ast.AST,
    line_no: int,
    lines: list[str],
    include_full_class: bool,
) -> tuple[int, int, str, bool]:
    """Encontra o escopo AST (classe/função/método) que envolve `line_no`.
    Retorna `(start_line, end_line, scope_label, is_module_window)`.
    """
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
        start = max(1, line_no - 8)
        end = min(len(lines), line_no + 12)
        return start, end, f"módulo (linhas {start}-{end})", True

    classes = [n for n in stack if isinstance(n, ast.ClassDef)]
    innermost = stack[-1]
    if classes and (
        include_full_class
        or (isinstance(innermost, ast.ClassDef) and line_no <= innermost.lineno + 1)
    ):
        target = classes[0] if include_full_class else innermost
        s, e = _py_node_span(target)
        return s, e, f"class {target.name} (linhas {s}-{e})", False

    if isinstance(innermost, ast.ClassDef):
        s, e = _py_node_span(innermost)
        if (e - s) <= 220:
            return s, e, f"class {innermost.name} (linhas {s}-{e})", False
        ws = max(s, line_no - 12)
        we = min(e, line_no + 18)
        return ws, we, f"class {innermost.name} (linhas {ws}-{we})", False

    s, e = _py_node_span(innermost)
    parts = []
    for n in stack:
        if isinstance(n, ast.ClassDef):
            parts.append(f"class {n.name}")
        elif isinstance(n, ast.AsyncFunctionDef):
            parts.append(f"async def {n.name}")
        elif isinstance(n, ast.FunctionDef):
            parts.append(f"def {n.name}")
    return s, e, f"{' > '.join(parts)} (linhas {s}-{e})", False


def _js_scope_for_line(
    lines: list[str],
    line_no: int,
    include_full_class: bool,
) -> tuple[int, int, str, bool]:
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
        s = max(1, line_no - 8)
        e = min(len(lines), line_no + 12)
        return s, e, f"linhas {s}-{e}", True

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
    return s, e, f"{decl_kind} {decl_name} (linhas {s}-{e})", False


def _fallback_scope(lines: list[str], line_no: int) -> tuple[int, int, str, bool]:
    s = max(1, line_no - 8)
    e = min(len(lines), line_no + 12)
    return s, e, f"linhas {s}-{e}", True


def _merge_matches(dst: list[str], src: list[str]) -> None:
    for item in src:
        if item not in dst:
            dst.append(item)


def _dedupe_and_merge_blocks(
    blocks: list[ExtractedBlock],
    file_lines: dict[str, list[str]] | None = None,
) -> list[ExtractedBlock]:
    """Remove duplicados e funde janelas sobrepostas de módulo no mesmo arquivo."""
    by_file: dict[str, list[ExtractedBlock]] = {}
    for b in blocks:
        by_file.setdefault(b.rel_path, []).append(b)

    merged_all: list[ExtractedBlock] = []
    for rel, group in sorted(by_file.items()):
        # Primeiro separa blocos estruturais (função/classe) de janelas genéricas de módulo
        struct_blocks = [b for b in group if not b.is_module_window]
        mod_blocks = [b for b in group if b.is_module_window]

        # 1. Deduplica blocos estruturais contidos uns nos outros
        struct_blocks.sort(key=lambda b: (b.start_line, -(b.end_line - b.start_line)))
        kept_struct: list[ExtractedBlock] = []
        for blk in struct_blocks:
            contained = False
            for existing in kept_struct:
                if existing.start_line <= blk.start_line and blk.end_line <= existing.end_line:
                    _merge_matches(existing.matches, blk.matches)
                    existing.is_fallback = existing.is_fallback and blk.is_fallback
                    contained = True
                    break
            if not contained:
                kept_struct.append(blk)

        # 2. Funde janelas de módulo sobrepostas ou adjacentes (evita repetir o mesmo trecho 4x)
        mod_blocks.sort(key=lambda b: (b.start_line, b.end_line))
        lines_ref = (file_lines or {}).get(rel)
        kept_mod: list[ExtractedBlock] = []
        for blk in mod_blocks:
            # Se já está completamente dentro de um bloco estrutural, incorpora os matches nele
            absorbed = False
            for sb in kept_struct:
                if sb.start_line <= blk.start_line and blk.end_line <= sb.end_line:
                    _merge_matches(sb.matches, blk.matches)
                    sb.is_fallback = sb.is_fallback and blk.is_fallback
                    absorbed = True
                    break
            if absorbed:
                continue

            if kept_mod:
                prev = kept_mod[-1]
                overlaps_or_near = blk.start_line <= prev.end_line + 3
                new_end = max(prev.end_line, blk.end_line)
                if overlaps_or_near and (new_end - prev.start_line + 1) <= _MAX_MERGED_MODULE_LINES:
                    prev.end_line = new_end
                    _merge_matches(prev.matches, blk.matches)
                    prev.is_fallback = prev.is_fallback and blk.is_fallback
                    if lines_ref is not None:
                        prev.code = "\n".join(lines_ref[prev.start_line - 1 : prev.end_line])
                    prefix = "módulo" if prev.scope.startswith("módulo") else "linhas"
                    prev.scope = (
                        f"módulo (linhas {prev.start_line}-{prev.end_line})"
                        if prefix == "módulo"
                        else f"linhas {prev.start_line}-{prev.end_line}"
                    )
                    continue
            kept_mod.append(blk)

        # 3. Se uma janela de módulo invadiu o início de um bloco estrutural, apara a sobreposição
        if lines_ref is not None and kept_struct and kept_mod:
            trimmed_mod: list[ExtractedBlock] = []
            for mb in kept_mod:
                s, e = mb.start_line, mb.end_line
                for sb in kept_struct:
                    if s < sb.start_line <= e <= sb.end_line:
                        e = sb.start_line - 1
                    elif sb.start_line <= s <= sb.end_line < e:
                        s = sb.end_line + 1
                if s <= e:
                    mb.start_line, mb.end_line = s, e
                    mb.code = "\n".join(lines_ref[s - 1 : e])
                    prefix = "módulo" if mb.scope.startswith("módulo") else "linhas"
                    mb.scope = f"módulo (linhas {s}-{e})" if prefix == "módulo" else f"linhas {s}-{e}"
                    trimmed_mod.append(mb)
            kept_mod = trimmed_mod

        merged_all.extend(kept_struct)
        merged_all.extend(kept_mod)
    return merged_all


def _score_block(blk: ExtractedBlock) -> float:
    """Calcula relevância do bloco para priorizar definições exatas sobre ruído genérico."""
    score = 0.0
    exact_count = 0
    for m in blk.matches:
        score += _query_specificity(m)
        if " (via " not in m:
            exact_count += 1
    if len(blk.matches) > 1:
        score += 3.5 * (len(blk.matches) - 1)
    if exact_count > 0:
        score += 4.0
    if not blk.is_module_window:
        score += 5.0
    else:
        # Penaliza janelas que são majoritariamente imports/comentários
        code_lines = [ln.strip() for ln in blk.code.splitlines() if ln.strip()]
        non_import = [ln for ln in code_lines if not ln.startswith(("import ", "from ", "#"))]
        if len(non_import) <= 3:
            score -= 3.5

    low_path = blk.rel_path.lower()
    path_parts = set(low_path.split("/"))
    if any(part in path_parts for part in _HIGH_SIGNAL_PATH_PARTS):
        score += 2.0
    if "tests" in path_parts or low_path.rsplit("/", 1)[-1].startswith("test_"):
        score -= 2.5
    return score


def _select_top_blocks(
    blocks: list[ExtractedBlock],
    clean_queries: list[str],
    max_blocks: int,
) -> list[ExtractedBlock]:
    """Seleciona até `max_blocks` garantindo cobertura justa de TODOS os termos encontrados."""
    for b in blocks:
        b.score = _score_block(b)

    if len(blocks) <= max_blocks:
        return sorted(blocks, key=lambda b: (-b.score, b.rel_path, b.start_line))

    selected: list[ExtractedBlock] = []
    selected_ids: set[int] = set()

    # Fase 1: ordena termos do mais específico ao mais genérico e garante os melhores blocos de cada termo
    ordered_queries = sorted(clean_queries, key=lambda q: -_query_specificity(q))
    for q in ordered_queries:
        if len(selected) >= max_blocks:
            break
        q_blocks = [
            b for b in blocks
            if id(b) not in selected_ids
            and any(m == q or m.startswith(f"{q} (via ") for m in b.matches)
        ]
        q_blocks.sort(key=lambda b: (-b.score, b.rel_path, b.start_line))
        for pick in q_blocks[:2]:
            if len(selected) >= max_blocks:
                break
            selected.append(pick)
            selected_ids.add(id(pick))

    # Fase 2: completa o restante do orçamento pelos blocos de maior pontuação global
    remaining = [b for b in blocks if id(b) not in selected_ids]
    remaining.sort(key=lambda b: (-b.score, b.rel_path, b.start_line))
    for pick in remaining:
        if len(selected) >= max_blocks:
            break
        selected.append(pick)
        selected_ids.add(id(pick))

    # Ordena o resultado final mantendo os blocos mais relevantes no topo (melhor contexto no .txt e no chat)
    selected.sort(key=lambda b: (-b.score, b.rel_path, b.start_line))
    return selected


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


def _scan_files_with_matchers(
    files: list[Path],
    root: Path,
    matchers: list[tuple[str, re.Pattern[str]]],
    include_full_class: bool,
    is_fallback: bool,
    file_cache: dict[str, tuple[str, list[str], str, ast.AST | None]],
    file_lines: dict[str, list[str]],
    matched_queries: set[str],
    raw_blocks: list[ExtractedBlock],
) -> None:
    for full in files:
        rel = full.relative_to(root).as_posix()
        cached = file_cache.get(rel)
        if cached is None:
            try:
                data = full.read_bytes()
            except OSError:
                continue
            if len(data) > 2 * 1024 * 1024 or b"\0" in data[:8000]:
                continue
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            suffix = full.suffix.lower()
            py_tree = None
            if suffix == ".py":
                try:
                    py_tree = ast.parse(text)
                except SyntaxError:
                    py_tree = None
            cached = (text, lines, suffix, py_tree)
            file_cache[rel] = cached

        text, lines, suffix, py_tree = cached
        file_hits = [(label, rx) for label, rx in matchers if rx.search(text)]
        if not file_hits:
            continue
        file_lines[rel] = lines

        for line_idx, line in enumerate(lines, start=1):
            line_matches = [label for label, rx in file_hits if rx.search(line)]
            if not line_matches:
                continue
            for label in line_matches:
                orig_q = label.split(" (via ", 1)[0] if is_fallback else label
                matched_queries.add(orig_q)
            if py_tree is not None:
                s, e, scope, is_mod = _py_scope_for_line(py_tree, line_idx, lines, include_full_class)
            elif suffix in _JS_EXTS:
                s, e, scope, is_mod = _js_scope_for_line(lines, line_idx, include_full_class)
            else:
                s, e, scope, is_mod = _fallback_scope(lines, line_idx)
            code = "\n".join(lines[s - 1 : e])
            raw_blocks.append(
                ExtractedBlock(
                    rel_path=rel,
                    start_line=s,
                    end_line=e,
                    scope=scope,
                    code=code,
                    matches=list(line_matches),
                    is_module_window=is_mod,
                    is_fallback=is_fallback,
                )
            )


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

    clean_queries = [_clean_query_token(q) for q in (queries or [])]
    clean_queries = [q for q in clean_queries if q]
    clean_queries = list(dict.fromkeys(clean_queries))[:20]
    if not clean_queries:
        return {"error": "ERRO: informe pelo menos um termo, função, rota ou classe para localizar."}

    include_migrations = "migration" in str(subpath or "").lower() or "alembic" in str(subpath or "").lower() or any(
        "migration" in q.lower() or "alembic" in q.lower() for q in clean_queries
    )

    try:
        files = _iter_target_files(root, subpath, include_migrations=include_migrations)
    except ValueError as exc:
        return {"error": str(exc)}

    matched_queries: set[str] = set()
    raw_blocks: list[ExtractedBlock] = []
    file_cache: dict[str, tuple[str, list[str], str, ast.AST | None]] = {}
    file_lines: dict[str, list[str]] = {}

    primary_matchers = [(q, _compile_query_matcher(q)) for q in clean_queries]
    _scan_files_with_matchers(
        files=files,
        root=root,
        matchers=primary_matchers,
        include_full_class=include_full_class,
        is_fallback=False,
        file_cache=file_cache,
        file_lines=file_lines,
        matched_queries=matched_queries,
        raw_blocks=raw_blocks,
    )

    # Fallback para rotas longas com prefixo separado no router (ex.: /api/internal/portal/users/sync -> users/sync)
    missing_routes = [q for q in clean_queries if q not in matched_queries and "/" in q]
    if missing_routes:
        fallback_matchers: list[tuple[str, re.Pattern[str]]] = []
        seen_fb: set[str] = set()
        for orig in missing_routes:
            segs = [s for s in orig.strip("/").split("/") if s and not (s.startswith("{") and s.endswith("}"))]
            candidates: list[str] = []
            if len(segs) >= 2:
                candidates.append("/".join(segs[-2:]))
            if segs and len(segs[-1]) >= 4:
                candidates.append(segs[-1])
            for cand in candidates:
                label = f"{orig} (via {cand})"
                if label not in seen_fb:
                    seen_fb.add(label)
                    fallback_matchers.append((label, _compile_query_matcher(cand)))
        if fallback_matchers:
            _scan_files_with_matchers(
                files=files,
                root=root,
                matchers=fallback_matchers,
                include_full_class=include_full_class,
                is_fallback=True,
                file_cache=file_cache,
                file_lines=file_lines,
                matched_queries=matched_queries,
                raw_blocks=raw_blocks,
            )

    merged = _dedupe_and_merge_blocks(raw_blocks, file_lines=file_lines)
    blocks = _select_top_blocks(merged, clean_queries, max_blocks=max_blocks)
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
        first_sub = next((p.strip().strip("/") for p in re.split(r"[\n,;]+", str(subpath or "")) if p.strip()), "")
        hint = first_sub.split("/")[-1] if first_sub else clean_queries[0]
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
