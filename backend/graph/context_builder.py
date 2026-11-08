"""Dossiê de contexto montado PELO SISTEMA para o agente Generate.

Em vez de mandar o modelo "ler" os arquivos e decidir sozinho o que abrir (e
pular, por exemplo, as constantes do topo de um arquivo grande), o sistema monta
um pacote determinístico com:

1. o `git diff` do que mudou (contra a branch principal, incluindo o que ainda
   não foi commitado);
2. cada arquivo da tarefa: inteiro quando cabe; senão, o CABEÇALHO (imports e
   constantes antes da primeira função/classe), o esboço de definições e as
   janelas ao redor do que o diff alterou;
3. as definições de constantes/classes usadas mas definidas em OUTRO arquivo
   (resolvidas por AST, sem LLM).

Tudo respeita um orçamento de caracteres; o que ficou de fora é declarado no
relatório, para nunca haver truncamento silencioso.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

_BLOCKED_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__"}
_MAX_INDEXED_FILES = 400
_MAX_INDEXED_BYTES = 400_000
_DEF_LINES = 40
_MAX_REFERENCES = 12


def estimate_tokens(text: str) -> int:
    """Estimativa conservadora (português + código): ~3 caracteres por token."""
    return len(text) // 3 + 1


# ──────────────────────────────────────────────────────────────────────────
# Acesso seguro a arquivos e git
# ──────────────────────────────────────────────────────────────────────────

def _blocked(relative: Path) -> bool:
    for part in relative.parts:
        name = part.lower()
        if name in _BLOCKED_PARTS or name == ".env" or name.startswith(".env."):
            return True
    return False


def _resolve(root: Path, rel: str) -> Path | None:
    try:
        target = (root / rel.strip()).resolve()
        relative = target.relative_to(root)
    except (ValueError, OSError):
        return None
    return None if _blocked(relative) else target


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    try:
        return raw.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        return None


def _git(root: Path, *args: str, timeout: int = 20) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def diff_base(root: Path) -> tuple[str, str]:
    """(ref, descrição). Em branch de trabalho: merge-base com main/master; senão HEAD."""
    branch = _git(root, "branch", "--show-current").strip()
    if branch and branch not in {"main", "master"}:
        for candidate in ("main", "master"):
            base = _git(root, "merge-base", "HEAD", candidate).strip()
            if base:
                return base, f"{candidate} (branch '{branch}')"
    return "HEAD", "HEAD (alterações ainda não commitadas)"


def _clip(text: str, limit: int, note: str) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    newline = cut.rfind("\n")
    if newline > limit // 2:
        cut = cut[:newline]
    return cut + f"\n{note}"


# ──────────────────────────────────────────────────────────────────────────
# Análise de arquivos
# ──────────────────────────────────────────────────────────────────────────

def _numbered(lines: list[str], first: int, last: int) -> str:
    return "\n".join(f"{n}: {lines[n - 1]}" for n in range(first, last + 1))


def _first_def_line(tree: ast.Module) -> int | None:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            decorators = getattr(node, "decorator_list", [])
            return min([node.lineno] + [d.lineno for d in decorators])
    return None


def _outline(tree: ast.Module) -> list[str]:
    items: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            items.append(f"{node.lineno}: class {node.name}")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    items.append(f"{sub.lineno}:     def {sub.name}(...)")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            items.append(f"{node.lineno}: def {node.name}(...)")
    return items


def _hunk_ranges(diff_text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff_text, re.MULTILINE):
        start = int(match.group(1))
        count = int(match.group(2) or 1)
        ranges.append((start, start + max(count, 1) - 1))
    return ranges


def _merge(ranges: list[tuple[int, int]], total: int, margin: int) -> list[tuple[int, int]]:
    expanded = sorted((max(1, a - margin), min(total, b + margin)) for a, b in ranges)
    merged: list[tuple[int, int]] = []
    for a, b in expanded:
        if merged and a <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _file_diff(diff_text: str, rel: str) -> str:
    """Trecho do diff que pertence a `rel`."""
    chunks = re.split(r"(?m)^(?=diff --git )", diff_text)
    marker = f" b/{rel}"
    return "".join(c for c in chunks if c.startswith("diff --git") and c.split("\n", 1)[0].endswith(marker))


def _partial_view(text: str, rel: str, file_diff: str, budget: int) -> str:
    lines = text.split("\n")
    total = len(lines)
    parts: list[str] = [
        f"[ARQUIVO PARCIAL: {total} linhas. Abaixo: cabeçalho, esboço e trechos alterados. "
        "Para ler outra parte, use read_file_chunk.]"
    ]

    tree: ast.Module | None = None
    if rel.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None

    header_end = min(total, 120)
    if tree is not None:
        first_def = _first_def_line(tree)
        if first_def:
            header_end = min(first_def - 1, 200)
    if header_end >= 1:
        parts.append(f"--- cabeçalho (linhas 1-{header_end}: imports e constantes) ---")
        parts.append(_numbered(lines, 1, header_end))

    if tree is not None:
        outline = _outline(tree)
        if outline:
            parts.append("--- esboço de definições (linha: assinatura) ---")
            parts.append("\n".join(outline))

    windows = _merge(_hunk_ranges(file_diff), total, 25) if file_diff else []
    for first, last in windows:
        if first <= header_end:
            first = header_end + 1
        if first > last:
            continue
        parts.append(f"--- trecho alterado (linhas {first}-{last}) ---")
        parts.append(_numbered(lines, first, last))

    return _clip("\n".join(parts), budget, "[... PARCIAL TRUNCADO pelo orçamento de contexto ...]")


# ──────────────────────────────────────────────────────────────────────────
# Resolução de referências (constantes / classes definidas em outro arquivo)
# ──────────────────────────────────────────────────────────────────────────

def _looks_relevant(name: str) -> bool:
    if len(name) < 4:
        return False
    return name.isupper() or (name[0].isupper() and any(c.islower() for c in name))


def _defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _used_names(tree: ast.Module) -> set[str]:
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _index_definitions(root: Path) -> dict[str, tuple[str, int, int]]:
    """nome -> (arquivo relativo, linha inicial, linha final) das definições de módulo."""
    index: dict[str, tuple[str, int, int]] = {}
    scanned = 0
    for path in sorted(root.rglob("*.py")):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if _blocked(relative):
            continue
        scanned += 1
        if scanned > _MAX_INDEXED_FILES:
            break
        try:
            if path.stat().st_size > _MAX_INDEXED_BYTES:
                continue
        except OSError:
            continue
        text = _read_text(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        rel = relative.as_posix()
        for node in tree.body:
            end = getattr(node, "end_lineno", node.lineno)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                index.setdefault(node.name, (rel, node.lineno, end))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        index.setdefault(target.id, (rel, node.lineno, end))
    return index


def resolve_references(root: Path, py_texts: dict[str, str]) -> list[tuple[str, str, int, str]]:
    """[(nome, arquivo, linha, trecho)] de nomes usados mas definidos fora dos arquivos da tarefa."""
    used: set[str] = set()
    defined: set[str] = set()
    for text in py_texts.values():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        used |= _used_names(tree)
        defined |= _defined_names(tree)

    wanted = sorted(n for n in used - defined if _looks_relevant(n))
    if not wanted:
        return []

    index = _index_definitions(root)
    task_files = set(py_texts)
    found: list[tuple[str, str, int, str]] = []
    for name in wanted:
        hit = index.get(name)
        if not hit or hit[0] in task_files:
            continue
        rel, start, end = hit
        text = _read_text(root / rel)
        if text is None:
            continue
        lines = text.split("\n")
        end = min(end, start + _DEF_LINES - 1)
        found.append((name, rel, start, _numbered(lines, start, end)))
        if len(found) >= _MAX_REFERENCES:
            break
    return found


# ──────────────────────────────────────────────────────────────────────────
# Montagem do dossiê
# ──────────────────────────────────────────────────────────────────────────

def build_task_dossier(
    workspace: str | None,
    files: list[str],
    max_chars: int = 48_000,
    per_file_chars: int = 20_000,
    diff_chars: int = 12_000,
) -> tuple[str, dict]:
    """Devolve (texto do dossiê, relatório). Texto vazio se não houver nada útil."""
    report: dict = {
        "base": None, "diff_chars": 0, "files": [], "references": [],
        "truncated": False, "chars": 0, "est_tokens": 0,
    }
    if not workspace or not files:
        return "", report

    root = Path(workspace).resolve()
    if not root.is_dir():
        return "", report

    rels: list[str] = []
    for item in files:
        item = str(item).strip().replace("\\", "/")
        if item and item not in rels:
            rels.append(item)

    base, base_label = diff_base(root)
    report["base"] = base_label
    existing = [r for r in rels if (p := _resolve(root, r)) is not None and p.is_file()]
    raw_diff = _git(root, "diff", "--no-color", "-U3", base, "--", *existing) if existing else ""
    sections: list[str] = []
    used_chars = 0

    if raw_diff.strip():
        clipped = _clip(raw_diff, diff_chars, "[... diff truncado ...]")
        report["diff_chars"] = len(clipped)
        report["truncated"] |= len(clipped) < len(raw_diff)
        sections.append(f"### Alterações recentes (git diff contra {base_label})\n<<<DIFF>>>\n{clipped.rstrip()}\n<<<FIM DIFF>>>")
        used_chars += len(clipped)

    py_texts: dict[str, str] = {}
    file_blocks: list[str] = []
    for rel in rels:
        path = _resolve(root, rel)
        entry = {"path": rel, "mode": "ausente", "lines": 0, "chars": 0}
        report["files"].append(entry)

        if path is None:
            entry["mode"] = "bloqueado"
            continue
        if not path.is_file():
            continue

        text = _read_text(path)
        if text is None:
            entry["mode"] = "binário/ilegível"
            continue

        lines = text.split("\n")
        entry["lines"] = len(lines)
        remaining = max_chars - used_chars
        if remaining < 1500:
            entry["mode"] = "omitido (orçamento)"
            report["truncated"] = True
            continue

        limit = min(per_file_chars, remaining)
        numbered_len = len(text) + 8 * len(lines)
        if numbered_len <= limit:
            body = _numbered(lines, 1, len(lines))
            entry["mode"] = "completo"
        else:
            body = _partial_view(text, rel, _file_diff(raw_diff, rel), limit)
            entry["mode"] = "parcial"
            report["truncated"] = True

        entry["chars"] = len(body)
        used_chars += len(body)
        file_blocks.append(f"#### {rel} ({entry['mode']}, {len(lines)} linhas)\n<<<ARQUIVO {rel}>>>\n{body}\n<<<FIM ARQUIVO>>>")
        if rel.endswith(".py"):
            py_texts[rel] = text

    if file_blocks:
        sections.append("### Arquivos da tarefa\n" + "\n\n".join(file_blocks))

    if py_texts:
        budget_left = max(0, max_chars - used_chars)
        refs = resolve_references(root, py_texts)
        ref_blocks: list[str] = []
        for name, rel, line, snippet in refs:
            block = f"#### {name} — definido em {rel}:{line}\n<<<DEFINIÇÃO>>>\n{snippet}\n<<<FIM DEFINIÇÃO>>>"
            if len(block) > budget_left:
                report["truncated"] = True
                break
            budget_left -= len(block)
            ref_blocks.append(block)
            report["references"].append(f"{name} ({rel}:{line})")
        if ref_blocks:
            sections.append("### Definições referenciadas (resolvidas automaticamente)\n" + "\n\n".join(ref_blocks))

    if not sections:
        return "", report

    text = (
        "## DOSSIÊ DE CONTEXTO (montado pelo sistema; é a fonte de verdade)\n"
        "Use ESTE conteúdo antes de chamar ferramentas de leitura. Só afirme valores que "
        "apareçam literalmente aqui ou em arquivos que você leu. Se um valor não estiver visível, "
        "escreva VERIFICAR em vez de inventar.\n\n" + "\n\n".join(sections)
    )
    report["chars"] = len(text)
    report["est_tokens"] = estimate_tokens(text)
    return text, report


def format_report(report: dict, num_ctx: int | None = None, prompt_tokens: int | None = None) -> str:
    """Linhas curtas para o log/chat: o que o modelo realmente recebeu."""
    lines = ["🧾 Contexto entregue ao agente:"]
    if report.get("base"):
        lines.append(f"- git diff contra {report['base']}: {report['diff_chars']} caracteres")
    for entry in report.get("files", []):
        detail = f"{entry['mode']}"
        if entry.get("lines"):
            detail += f", {entry['lines']} linhas, {entry['chars']} caracteres enviados"
        lines.append(f"- {entry['path']}: {detail}")
    if report.get("references"):
        lines.append("- definições resolvidas: " + ", ".join(report["references"]))
    if report.get("rag_chars"):
        lines.append(f"- trechos do RAG: {report['rag_chars']} caracteres")
    if report.get("rag_chars"):
        lines.append(f"- trechos do RAG: {report['rag_chars']} caracteres")
    lines.append(f"- dossiê: ~{report.get('est_tokens', 0)} tokens estimados")
    if report.get("truncated"):
        lines.append("⚠️ Parte do conteúdo ficou de fora do dossiê (orçamento). O agente deve usar read_file_chunk para o restante.")
    if num_ctx and prompt_tokens:
        pct = round(100 * prompt_tokens / num_ctx)
        lines.append(f"- prompt total estimado: ~{prompt_tokens} de {num_ctx} tokens ({pct}% do num_ctx)")
        if prompt_tokens > 0.85 * num_ctx:
            lines.append("⚠️ O prompt está perto do limite de num_ctx: o Ollama corta o início SEM avisar. Reduza os arquivos da tarefa ou aumente num_ctx.")
    return "\n".join(lines)


def task_changes(workspace: str | None, files: list[str], max_chars: int = 40_000) -> dict:
    """Alterações dos arquivos da tarefa para revisão humana (diff + arquivos novos)."""
    result: dict = {"base": None, "diff": "", "new_files": [], "missing": [], "truncated": False}
    if not workspace:
        return result

    root = Path(workspace).resolve()
    if not root.is_dir():
        return result

    rels: list[str] = []
    for item in files:
        item = str(item).strip().replace("\\", "/")
        if item and item not in rels:
            rels.append(item)

    base, label = diff_base(root)
    result["base"] = label

    existing: list[str] = []
    for rel in rels:
        path = _resolve(root, rel)
        if path is not None and path.is_file():
            existing.append(rel)
        else:
            result["missing"].append(rel)
    if not existing:
        return result

    raw = _git(root, "diff", "--no-color", "-U3", base, "--", *existing)
    result["diff"] = _clip(raw, max_chars, "[... diff truncado ...]")
    result["truncated"] = len(result["diff"]) < len(raw)

    untracked = set(_git(root, "ls-files", "--others", "--exclude-standard", "--", *existing).split("\n"))
    room = max(0, max_chars - len(result["diff"]))
    for rel in existing:
        if rel not in untracked:
            continue
        text = _read_text(root / rel)
        if text is None:
            continue
        shown = _clip(text, max(2_000, room // max(1, len(untracked))), "[... arquivo truncado ...]")
        result["truncated"] |= len(shown) < len(text)
        result["new_files"].append({"path": rel, "content": shown})
    return result
