"""Auditoria determinística de código (base do modo Auditoria do Heavy). Sem LLM.

Fluxo: ferramentas (ruff, vulture, radon, bandit + duplicação por hash de AST) -> achados estruturados -> validação
contra o código REAL (arquivo, linha, trecho lidos do disco) -> filtro de falsos positivos já registrados -> tasks.

Achado: {id, file, line, end_line, snippet, kind, severity, confidence, tool, rule, message, note}
  kind: bug | dead_code | duplication | complexity | security | optimization
  severity: low | medium | high | critical     confidence: low | medium | high
O `id` é estável (não depende do número da linha), então o registro de falsos positivos sobrevive a edições.

Ferramenta ausente ou com erro => status no resultado, nunca derruba a auditoria.
.env (opcionais): AUDIT_DIR (padrão: ~/.assistente_audit/<hash do projeto>), AUDIT_TOOL_TIMEOUT=120
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SEVERITY = {"low": 1, "medium": 2, "high": 3, "critical": 4}
CONFIDENCE = {"low": 1, "medium": 2, "high": 3}
SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "alembic"}
CODE_EXT = (".py", ".js")
_BUG_RULES = ("E9", "F63", "F7", "F82")
INSTALLABLE_TOOLS = ("ruff", "vulture", "radon", "bandit")
DEFAULT_AUDIT_TOOLS = ("ruff", "vulture", "radon", "bandit", "duplication", "spacing")


def _timeout() -> int:
    try:
        from backend.api.settings_store import get_setting

        val = get_setting("audit_tool_timeout", None)
        if val is not None:
            return max(0, int(val))
    except Exception:
        pass
    raw = os.getenv("AUDIT_TOOL_TIMEOUT", "").strip()
    if raw == "0":
        return 0
    try:
        return int(raw or 180)
    except ValueError:
        return 180


def _chunk_size() -> int:
    try:
        from backend.api.settings_store import get_setting

        val = get_setting("audit_chunk_size", None)
        if val is not None:
            return max(10, min(int(val), 200))
    except Exception:
        pass
    try:
        val = int(os.getenv("AUDIT_CHUNK_SIZE", "") or 40)
        return max(10, min(val, 200))
    except ValueError:
        return 40


def _norm(path) -> str:
    text = str(path or "").replace("\\", "/").strip()
    return text[2:] if text.startswith("./") else text


def _rel(path: str, workspace: str) -> str:
    """Caminho relativo ao projeto, aceitando '\\' e '/', com ou sem letra de unidade (Windows)."""
    p, w = _norm(path), _norm(workspace).rstrip("/")
    if w and (p.casefold() == w.casefold() or p.casefold().startswith(w.casefold() + "/")):
        return p[len(w) + 1:]
    return p


def _run(cmd: list[str], cwd: str, timeout: int | None = None) -> subprocess.CompletedProcess | None:
    limit = _timeout() if timeout is None else timeout
    run_timeout = None if (limit is not None and limit <= 0) else limit
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=run_timeout,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    except (OSError, subprocess.TimeoutExpired):
        return None


def _read_lines(path: Path) -> list[str] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc).replace("\r\n", "\n").split("\n")
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace").replace("\r\n", "\n").split("\n")


def _finding(file, line, kind, severity, confidence, tool, rule, message, end_line=None) -> dict:
    return {"id": "", "file": _norm(file), "line": int(line or 1), "end_line": int(end_line or line or 1), "snippet": "",
            "kind": kind, "severity": severity, "confidence": confidence, "tool": tool, "rule": str(rule or ""),
            "message": str(message or "").strip(), "note": ""}


# ── parsers (testáveis sem as ferramentas instaladas) ─────────────────────

def parse_ruff(text: str, workspace: str) -> list[dict]:
    try:
        items = json.loads(text or "[]")
    except ValueError:
        return []
    out = []
    for item in items:
        code = str(item.get("code") or "")
        loc, end = item.get("location") or {}, item.get("end_location") or {}
        if code.startswith(_BUG_RULES):
            kind, sev = "bug", "high"
        elif code in ("F401", "F841", "F811"):
            kind, sev = "dead_code", "low"
        elif code.startswith("B"):
            kind, sev = "bug", "medium"
        elif code.startswith("PERF"):
            kind, sev = "optimization", "low"
        else:
            kind, sev = "bug", "low"
        out.append(_finding(_rel(item.get("filename", ""), workspace), loc.get("row", 1), kind, sev, "high", "ruff", code,
                            item.get("message"), end.get("row")))
    return out


_VULTURE = re.compile(r"^(?P<file>.+?):(?P<line>\d+): (?P<msg>unused .+?) \((?P<pct>\d+)% confidence\)\s*$")


def parse_vulture(text: str, workspace: str) -> list[dict]:
    out = []
    for raw in (text or "").splitlines():
        m = _VULTURE.match(raw.strip())
        if not m:
            continue
        pct = int(m.group("pct"))
        conf = "high" if pct >= 90 else "medium" if pct >= 70 else "low"
        out.append(_finding(_rel(m.group("file"), workspace), m.group("line"), "dead_code", "low", conf, "vulture", "unused",
                            f"{m.group('msg')} ({pct}%)"))
    return out


def parse_radon(text: str, workspace: str) -> list[dict]:
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    out = []
    for path, blocks in (data or {}).items():
        if not isinstance(blocks, list):
            continue
        for b in blocks:
            cc = int(b.get("complexity") or 0)
            if cc <= 10:
                continue
            sev = "high" if cc > 30 else "medium" if cc > 20 else "low"
            out.append(_finding(_rel(path, workspace), b.get("lineno", 1), "complexity", sev, "high", "radon", f"CC{cc}",
                                f"{b.get('name')} tem complexidade ciclomática {cc} (rank {b.get('rank')})", b.get("endline")))
    return out


def parse_bandit(text: str, workspace: str) -> list[dict]:
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    out = []
    for r in data.get("results") or []:
        if r.get("test_id") == "B101":  # assert: ruído (testes)
            continue
        sev = str(r.get("issue_severity") or "LOW").lower()
        conf = str(r.get("issue_confidence") or "LOW").lower()
        out.append(_finding(_rel(r.get("filename", ""), workspace), r.get("line_number", 1), "security",
                            sev if sev in SEVERITY else "low", conf if conf in CONFIDENCE else "low", "bandit",
                            r.get("test_id"), r.get("issue_text")))
    return out


# ── duplicação por hash de AST ────────────────────────────────────────────

class _Normalize(ast.NodeTransformer):
    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_arg(self, node):
        return ast.copy_location(ast.arg(arg="_", annotation=None), node)

    def visit_Constant(self, node):
        return ast.copy_location(ast.Constant(value=type(node.value).__name__), node)


def ast_duplicates(workspace: str, files: list[str], min_nodes: int = 40, progress_cb=None) -> list[dict]:
    seen: dict[str, tuple[str, int, str]] = {}
    out = []
    py_files = [rel for rel in files if rel.endswith(".py")]
    total = len(py_files)
    for idx, rel in enumerate(py_files, start=1):
        if progress_cb and (idx == 1 or idx % 25 == 0 or idx == total):
            progress_cb("duplication", f"{idx}/{total} arquivo(s) .py verificados")
        lines = _read_lines(Path(workspace, rel))
        if lines is None:
            continue
        try:
            tree = ast.parse("\n".join(lines))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if sum(1 for _ in ast.walk(node)) < min_nodes:
                continue
            clone = ast.parse(ast.unparse(node)).body[0]
            clone.name, clone.decorator_list = "f", []
            if clone.body and isinstance(clone.body[0], ast.Expr) and isinstance(getattr(clone.body[0], "value", None), ast.Constant):
                clone.body = clone.body[1:] or [ast.Pass()]
            key = hashlib.sha1(ast.dump(_Normalize().visit(clone)).encode()).hexdigest()
            if key in seen:
                f0, l0, n0 = seen[key]
                out.append(_finding(rel, node.lineno, "duplication", "medium", "high", "ast-hash", "DUP",
                                    f"{node.name} é estruturalmente idêntica a {n0} ({f0}:{l0})", getattr(node, "end_lineno", None)))
            else:
                seen[key] = (rel, node.lineno, node.name)
    return out


# ── espaçamento de linhas em branco (E301 / E302 / E305) ─────────────────

_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _stmt_start_line(stmt: ast.AST) -> int:
    decs = getattr(stmt, "decorator_list", None) or []
    return min([stmt.lineno] + [d.lineno for d in decs])


def _block_start_line(lines: list[str], prev_end: int, code_start: int, col_offset: int) -> int:
    """Recua para incluir comentários diretamente colados acima do bloco (mesma indentação)."""
    start = code_start
    while start - 1 > prev_end:
        above = lines[start - 2]
        stripped = above.lstrip(" ")
        indent = len(above) - len(stripped)
        if stripped.startswith("#") and indent == col_offset:
            start -= 1
        else:
            break
    return start


def _blank_lines_between(lines: list[str], prev_end: int, block_start: int, code_start: int) -> tuple[int, int]:
    """Devolve (blanks_imediatos_antes_do_bloco, maior_sequencia_de_blanks_no_intervalo)."""
    immediate = 0
    idx = block_start - 2
    while idx >= prev_end:
        if not lines[idx].strip():
            immediate += 1
            idx -= 1
        else:
            break
    best = run = 0
    for line_no in range(prev_end + 1, code_start):
        if not lines[line_no - 1].strip():
            run += 1
            if run > best:
                best = run
        else:
            run = 0
    return immediate, best


def _collect_spacing_issues(lines: list[str]) -> list[dict]:
    """Encontra faltas de linhas em branco (E302/E305 no topo; E301 em métodos de classe)."""
    try:
        tree = ast.parse("\n".join(lines))
    except SyntaxError:
        return []
    issues: list[dict] = []

    def check_body(body: list[ast.stmt], required_def: int, required_after: int, rule_before: str, rule_after: str) -> None:
        for prev, curr in zip(body, body[1:]):
            prev_is_def = isinstance(prev, _DEF_NODES)
            curr_is_def = isinstance(curr, _DEF_NODES)
            if curr_is_def:
                req, rule = required_def, rule_before
            elif prev_is_def:
                req, rule = required_after, rule_after
            else:
                continue
            prev_end = getattr(prev, "end_lineno", None) or prev.lineno
            code_start = _stmt_start_line(curr)
            if code_start <= prev_end:
                continue
            block_start = _block_start_line(lines, prev_end, code_start, getattr(curr, "col_offset", 0))
            immediate, max_gap = _blank_lines_between(lines, prev_end, block_start, code_start)
            if max_gap >= req:
                continue
            insert_at = block_start if immediate < req else code_start
            existing = immediate if insert_at == block_start else 0
            if insert_at == code_start:
                idx = code_start - 2
                while idx >= prev_end and not lines[idx].strip():
                    existing += 1
                    idx -= 1
            missing = req - existing
            if missing <= 0:
                continue
            label = (
                "classe/função de topo" if rule == "E302"
                else "após classe/função de topo" if rule == "E305"
                else "método/bloco em classe"
            )
            issues.append({
                "line": code_start,
                "end_line": curr.lineno,
                "insert_before": insert_at,
                "missing": missing,
                "rule": rule,
                "message": f"esperado {req} linha(s) em branco ({label}), encontrado {max_gap}",
            })

    check_body(tree.body, 2, 2, "E302", "E305")
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            check_body(node.body, 1, 1, "E301", "E301")
    issues.sort(key=lambda item: (item["insert_before"], item["line"]))
    return issues


def ast_spacing_findings(workspace: str, files: list[str], progress_cb=None) -> list[dict]:
    out: list[dict] = []
    py_files = [rel for rel in files if rel.endswith(".py")]
    total = len(py_files)
    for idx, rel in enumerate(py_files, start=1):
        if progress_cb and (idx == 1 or idx % 25 == 0 or idx == total):
            progress_cb("spacing", f"{idx}/{total} arquivo(s) .py verificados")
        lines = _read_lines(Path(workspace, rel))
        if lines is None:
            continue
        for item in _collect_spacing_issues(lines):
            out.append(_finding(rel, item["line"], "style", "low", "high", "spacing", item["rule"], item["message"], item["end_line"]))
    return out


def _read_text_meta(path: Path) -> tuple[str, str, str] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    eol = "\r\n" if b"\r\n" in data else "\n"
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data.decode("utf-8-sig"), "utf-8-sig", eol
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc), enc, eol
        except UnicodeDecodeError:
            continue
    return None


def fix_spacing(workspace: str, files: list[str] | None = None) -> dict:
    """Insere linhas em branco faltantes (E301/E302/E305) em arquivos .py validando sintaxe antes de gravar."""
    root = Path(workspace).resolve()
    targets = [_norm(p) for p in files] if files is not None else project_code_files(str(root))
    py_files = [f for f in targets if f.endswith(".py")]
    fixed: list[dict] = []
    errors: list[str] = []
    for rel in py_files:
        try:
            target = (root / rel).resolve()
            target.relative_to(root)
        except ValueError:
            errors.append(f"{rel}: fora do projeto")
            continue
        if not target.is_file():
            continue
        meta = _read_text_meta(target)
        if meta is None:
            errors.append(f"{rel}: erro ao ler arquivo")
            continue
        text, enc, eol = meta
        lines = text.replace("\r\n", "\n").split("\n")
        issues = _collect_spacing_issues(lines)
        if not issues:
            continue
        updated = list(lines)
        inserted = 0
        for item in sorted(issues, key=lambda x: x["insert_before"], reverse=True):
            pos = item["insert_before"] - 1
            missing = item["missing"]
            updated[pos:pos] = [""] * missing
            inserted += missing
        new_text = "\n".join(updated)
        try:
            ast.parse(new_text)
        except SyntaxError as exc:
            errors.append(f"{rel}: sintaxe inválida após ajuste ({exc})")
            continue
        final_text = new_text.replace("\n", eol) if eol != "\n" else new_text
        try:
            target.write_bytes(final_text.encode(enc))
        except OSError as exc:
            errors.append(f"{rel}: erro ao salvar ({exc})")
            continue
        fixed.append({"file": rel, "issues": len(issues), "inserted_lines": inserted})
    return {"fixed": fixed, "checked": len(py_files), "errors": errors}


# ── validação contra o código real ────────────────────────────────────────

def _fingerprint(f: dict) -> str:
    base = "|".join([f["kind"], f["file"], f["rule"], re.sub(r"\s+", " ", f["snippet"]).strip()[:300]])
    return hashlib.sha1(base.encode("utf-8", "replace")).hexdigest()[:12]


def _build_word_index(workspace: str, limit: int = 1500) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for base, dirs, names in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            if not n.endswith((".py", ".js", ".html")):
                continue
            if len(index) >= limit:
                return index
            rel = os.path.relpath(os.path.join(base, n), workspace).replace("\\", "/")
            index[rel] = _read_lines(Path(base, n)) or []
    return index


def _word_hits(workspace: str, name: str, skip_file: str, skip_line: int, limit: int = 1500,
               file_index: dict[str, list[str]] | None = None) -> int:
    pat = re.compile(r"\b" + re.escape(name) + r"\b")
    pool = file_index if file_index is not None else _build_word_index(workspace, limit=limit)
    hits = 0
    for rel, lines in pool.items():
        for i, text in enumerate(lines, start=1):
            if pat.search(text) and not (rel == skip_file and i == skip_line):
                hits += 1
    return hits


def _decorated_def(workspace: str, rel: str, line: int) -> bool:
    lines = _read_lines(Path(workspace, rel))
    if not lines:
        return False
    try:
        tree = ast.parse("\n".join(lines))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.decorator_list:
            if node.lineno == line or any(d.lineno == line for d in node.decorator_list):
                return True
    return False


def validate_findings(workspace: str, findings: list[dict], progress_cb=None) -> tuple[list[dict], list[str]]:
    """Preenche snippet/id com o código real e descarta o que não confere. Devolve (válidos, motivos_descartes)."""
    root = Path(workspace).resolve()
    good, dropped = [], []
    has_vulture = any(f.get("tool") == "vulture" for f in findings)
    word_index = _build_word_index(str(root)) if has_vulture else None
    total = len(findings)
    for idx, f in enumerate(findings, start=1):
        if progress_cb and total and (idx == 1 or idx % 50 == 0 or idx == total):
            progress_cb("Validando achados", f"{idx}/{total} achado(s) conferidos no código real")
        rel = f["file"]
        try:
            target = (root / rel).resolve()
            target.relative_to(root)
        except ValueError:
            dropped.append(f"{rel}: fora do projeto")
            continue
        lines = _read_lines(target) if target.is_file() else None
        if not lines or not (1 <= f["line"] <= len(lines)):
            dropped.append(f"{rel}:{f['line']}: linha inexistente")
            continue
        end = min(max(f["end_line"], f["line"]), f["line"] + 11, len(lines))
        f = dict(f)
        f["end_line"] = end
        f["snippet"] = "\n".join(lines[f["line"] - 1:end])
        if f["rule"] == "F401" and rel.endswith("__init__.py"):
            dropped.append(f"{rel}:{f['line']}: import em __init__ (reexport)")
            continue
        if f["tool"] == "vulture":
            m = re.search(r"'([^']+)'", f["message"])
            name = m.group(1) if m else ""
            if name and not re.search(r"\b" + re.escape(name) + r"\b", f["snippet"]):
                dropped.append(f"{rel}:{f['line']}: vulture apontou '{name}' mas a linha não o contém")
                continue
            if _decorated_def(workspace, rel, f["line"]):
                dropped.append(f"{rel}:{f['line']}: função/classe decorada (rota, tool, fixture)")
                continue
            if name and name.startswith("test"):
                dropped.append(f"{rel}:{f['line']}: teste")
                continue
            if name:
                hits = _word_hits(workspace, name, rel, f["line"], file_index=word_index)
                if hits:
                    f["confidence"] = "low"
                    f["note"] = f"'{name}' aparece {hits}x em outros pontos do projeto; confirme antes de apagar"
        f["id"] = _fingerprint(f)
        good.append(f)
    return good, dropped


# ── registro de falsos positivos ──────────────────────────────────────────

def audit_dir(workspace: str) -> Path:
    custom = os.getenv("AUDIT_DIR", "").strip()
    if custom:
        return Path(custom)
    key = hashlib.sha1(str(Path(workspace).resolve()).encode()).hexdigest()[:10]
    return Path.home() / ".assistente_audit" / key


def _fp_path(workspace: str) -> Path:
    return audit_dir(workspace) / "false_positives.json"


def load_false_positives(workspace: str) -> dict[str, dict]:
    try:
        data = json.loads(_fp_path(workspace).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def mark_false_positive(workspace: str, finding: dict, reason: str = "") -> bool:
    fid = finding.get("id") or ""
    if not fid:
        return False
    data = load_false_positives(workspace)
    data[fid] = {"file": finding.get("file"), "rule": finding.get("rule"), "kind": finding.get("kind"), "reason": reason[:300]}
    path = _fp_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return True


def unmark_false_positive(workspace: str, fid: str) -> bool:
    data = load_false_positives(workspace)
    if fid not in data:
        return False
    del data[fid]
    path = _fp_path(workspace)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


# ── arquivos (completo ou incremental por git diff) ───────────────────────

def project_code_files(workspace: str) -> list[str]:
    out = []
    for base, dirs, names in os.walk(workspace):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for n in sorted(names):
            if n.endswith(CODE_EXT):
                out.append(os.path.relpath(os.path.join(base, n), workspace).replace("\\", "/"))
    return out


def changed_files(workspace: str, base: str | None = None) -> list[str] | None:
    """Arquivos de código alterados em relação a `base` (merge-base) + working tree + novos. None = não é repo git."""
    probe = _run(["git", "rev-parse", "--is-inside-work-tree"], workspace)
    if probe is None or probe.returncode != 0:
        return None
    names: set[str] = set()
    cmds = [["git", "diff", "--name-only", "HEAD"], ["git", "ls-files", "--others", "--exclude-standard"]]
    if base:
        mb = _run(["git", "merge-base", base, "HEAD"], workspace)
        if mb is not None and mb.returncode == 0 and mb.stdout.strip():
            cmds.append(["git", "diff", "--name-only", mb.stdout.strip(), "HEAD"])
    for cmd in cmds:
        res = _run(cmd, workspace)
        if res is not None and res.returncode == 0:
            names.update(ln.strip().replace("\\", "/") for ln in res.stdout.splitlines() if ln.strip())
    return sorted(n for n in names if n.endswith(CODE_EXT) and os.path.isfile(os.path.join(workspace, n))
                  and not any(part in SKIP_DIRS for part in n.split("/")))


# ── execução das ferramentas ──────────────────────────────────────────────

def _chunks(items: list[str], size: int | None = None):
    step = _chunk_size() if size is None else size
    for i in range(0, len(items), step):
        yield items[i:i + step]


def _tool_cmd(name: str) -> list[str] | None:
    bin_dir = Path(sys.executable).resolve().parent
    local_names = (f"{name}.exe", name) if os.name == "nt" else (name,)
    for candidate in local_names:
        local_exe = bin_dir / candidate
        if local_exe.is_file():
            return [str(local_exe)]
    exe = shutil.which(name)
    if exe:
        return [exe]
    if importlib.util.find_spec(name) is not None:
        return [sys.executable, "-m", name]
    return None


def missing_tools(tools: tuple[str, ...] | list[str] = INSTALLABLE_TOOLS) -> list[str]:
    """Ferramentas externas de auditoria ausentes no ambiente Python do assistente."""
    return [t for t in tools if t in INSTALLABLE_TOOLS and _tool_cmd(t) is None]


def install_tools(tools: list[str], progress_cb=None) -> dict:
    """Instala bibliotecas de auditoria permitidas no ambiente Python atual (sys.executable -m pip)."""
    allowed = [t for t in dict.fromkeys(tools) if t in INSTALLABLE_TOOLS]
    installed: list[str] = []
    already: list[str] = []
    failed: dict[str, str] = {}
    total = len(allowed)
    for idx, pkg in enumerate(allowed, start=1):
        if _tool_cmd(pkg) is not None:
            already.append(pkg)
            if progress_cb:
                progress_cb("Instalando libs", f"{idx}/{total}: {pkg} já instalado")
            continue
        if progress_cb:
            progress_cb("Instalando libs", f"{idx}/{total}: executando pip install {pkg}...")
        res = _run([sys.executable, "-m", "pip", "install", pkg], os.getcwd(), timeout=300)
        importlib.invalidate_caches()
        if res is None:
            failed[pkg] = "timeout ou falha ao executar pip"
            continue
        if res.returncode != 0:
            detail = (res.stderr or res.stdout or "").strip().splitlines()
            failed[pkg] = (detail[-1] if detail else f"código {res.returncode}")[:220]
            continue
        if _tool_cmd(pkg) is None:
            failed[pkg] = "instalado mas executável/módulo não encontrado"
            continue
        installed.append(pkg)
        if progress_cb:
            progress_cb("Instalando libs", f"{idx}/{total}: {pkg} instalado com sucesso")
    return {"installed": installed, "already": already, "failed": failed}


def _run_tool(name: str, workspace: str, files: list[str], progress_cb=None) -> tuple[list[dict], str]:
    py = [f for f in files if f.endswith(".py")]
    if not py:
        return [], "sem arquivos .py"
    base = _tool_cmd(name)
    if base is None:
        return [], "ausente (pip install " + name + ")"
    chunks = list(_chunks(py))
    total_chunks = len(chunks)
    total_py = len(py)
    found: list[dict] = []
    timeouts = 0
    done_files = 0
    for idx, chunk in enumerate(chunks, start=1):
        if progress_cb:
            pct = int((done_files / total_py) * 100) if total_py else 0
            progress_cb(name, f"lote {idx}/{total_chunks} ({done_files}/{total_py} arquivos · {pct}%)")
        if name == "ruff":
            res = _run(base + ["check", "--select", "E9,F,B,PERF", "--no-cache", "--isolated", "--output-format=json"] + chunk, workspace)
            if res is not None and res.returncode == 2 and "output-format" in (res.stderr or ""):
                res = _run(base + ["check", "--select", "E9,F,B,PERF", "--no-cache", "--isolated", "--format=json"] + chunk, workspace)
            ok, parser = (0, 1), parse_ruff
        elif name == "vulture":
            res, ok, parser = _run(base + chunk + ["--min-confidence", "60"], workspace), (0, 3), parse_vulture
        elif name == "radon":
            res, ok, parser = _run(base + ["cc", "-j", "-n", "C"] + chunk, workspace), (0,), parse_radon
        elif name == "bandit":
            res, ok, parser = _run(base + ["-q", "-f", "json"] + chunk, workspace), (0, 1), parse_bandit
        else:
            return [], "ferramenta desconhecida"
        done_files += len(chunk)
        if res is None:
            timeouts += 1
            continue
        if res.returncode not in ok:
            return found, f"erro (código {res.returncode}): {(res.stderr or res.stdout or '').strip()[:200]}"
        found.extend(parser(res.stdout, workspace))
    if progress_cb:
        progress_cb(name, f"concluído ({total_py}/{total_py} arquivos · {len(found)} achado(s) bruto(s))")
    if timeouts:
        return found, f"parcial ({timeouts}/{total_chunks} lote(s) com timeout)"
    return found, "ok"


def run_audit(workspace: str, paths: list[str] | None = None, incremental: bool = False, base: str | None = None,
              tools: tuple[str, ...] = DEFAULT_AUDIT_TOOLS,
              min_confidence: str = "low", use_registry: bool = True, progress_cb=None) -> dict:
    started = time.perf_counter()
    root = str(Path(workspace).resolve())
    status: dict[str, str] = {}
    if progress_cb:
        progress_cb("Descobrindo arquivos", "listando arquivos de código do workspace...")
    files = [_norm(p) for p in paths] if paths else project_code_files(root)
    if incremental:
        changed = changed_files(root, base)
        if changed is None:
            status["incremental"] = "não é repositório git: auditoria completa"
        else:
            files = [f for f in files if f in set(changed)]
    py_count = sum(1 for f in files if f.endswith(".py"))
    if progress_cb:
        progress_cb("Descobrindo arquivos", f"{len(files)} arquivo(s) de código ({py_count} .py)")
    raw: list[dict] = []
    for tool in tools:
        if tool == "duplication":
            raw.extend(ast_duplicates(root, files, progress_cb=progress_cb))
            status[tool] = "ok"
            continue
        if tool == "spacing":
            raw.extend(ast_spacing_findings(root, files, progress_cb=progress_cb))
            status[tool] = "ok"
            continue
        found, st = _run_tool(tool, root, files, progress_cb=progress_cb)
        raw.extend(found)
        status[tool] = st
    valid, dropped = validate_findings(root, raw, progress_cb=progress_cb)
    registry = load_false_positives(root) if use_registry else {}
    kept = [f for f in valid if f["id"] not in registry and CONFIDENCE[f["confidence"]] >= CONFIDENCE.get(min_confidence, 1)]
    unique: dict[str, dict] = {}
    for f in kept:
        unique.setdefault(f["id"], f)
    ordered = sorted(unique.values(), key=lambda f: (-SEVERITY[f["severity"]], -CONFIDENCE[f["confidence"]], f["file"], f["line"]))
    return {
        "findings": ordered,
        "tools": status,
        "files": len(files),
        "audited_files": list(files),
        "elapsed_seconds": round(time.perf_counter() - started, 1),
        "dropped": dropped,
        "ignored_false_positives": len([f for f in valid if f["id"] in registry]),
    }


# ── achados -> tasks importáveis ──────────────────────────────────────────

def findings_to_tasks(findings: list[dict], max_per_task: int = 5) -> list[dict]:
    by_file: dict[str, list[dict]] = {}
    for f in findings:
        by_file.setdefault(f["file"], []).append(f)
    tasks = []
    for rel, items in by_file.items():
        for start in range(0, len(items), max_per_task):
            group = items[start:start + max_per_task]
            top = max(SEVERITY[f["severity"]] for f in group)
            blocks = []
            for f in group:
                snippet = "\n".join("    " + ln for ln in f["snippet"].split("\n"))
                note = f"\n  Atenção: {f['note']}" if f["note"] else ""
                blocks.append(f"- [{f['kind']}/{f['severity']}/{f['rule']}] linha {f['line']}: {f['message']}{note}\n{snippet}")
            desc = (f"Corrija SOMENTE os achados abaixo em {rel}, com a menor mudança possível e sem alterar o comportamento. "
                    "Leia o arquivo antes. Se um achado for falso positivo, não mexa nele e explique no resumo.\n\n" + "\n".join(blocks))
            tasks.append({
                "title": f"Auditoria: {rel} ({len(group)} achado(s))"[:255],
                "description": desc,
                "reason": "Achados validados contra o código real (" + ", ".join(sorted({f['tool'] for f in group})) + ").",
                "files": [rel],
                "priority": "high" if top >= 3 else "medium" if top == 2 else "low",
                "steps": [],
                "verify": [{"type": "python_syntax", "path": rel}] if rel.endswith(".py") else [],
            })
    return tasks


# ── comando de chat (@audit) ──────────────────────────────────────────────

AUDIT_TAG = re.compile(r"(?<!\S)@audit(?:oria)?(?!\S)", re.IGNORECASE)
TAG_LOOKAHEAD = 50
_SEV_PT = {"critical": "crítica", "high": "alta", "medium": "média", "low": "baixa"}
_CONF_PT = {"high": "alta", "medium": "média", "low": "baixa"}

AUDIT_HELP = (
    "**Auditoria determinística** (ruff, vulture, radon, bandit e duplicação por AST, sem LLM)\n\n"
    "- `@audit` — audita o projeto todo\n"
    "- Também vale em português: `Audite o arquivo nodes.py`, `Audite os arquivos a.py, b.py e c.py`, `Audite a pasta backend/api`, `Audite o que mudou`\n"
    "- `@audit diff` — só o que mudou (git diff + arquivos novos); `@audit diff base=main` compara com a branch\n"
    "- `@audit backend/api backend/graph/nodes.py` — só essas pastas/arquivos\n"
    "- `min=medium` — mostra só achados com confiança média ou alta (padrão: todos)\n"
    "- `tools=ruff,bandit` — escolhe as ferramentas (ruff, vulture, radon, bandit, duplication, spacing)\n"
    "- `@audit fix` — corrige automaticamente linhas em branco faltantes em `.py` (`@audit fix diff` ou `@audit fix arquivo.py`)\n"
    "- `@audit pdf` — gera/baixa o relatório completo em PDF do último `@audit` (também salvo em Artefatos)\n"
    "- `@audit instalar` — instala via `pip` as ferramentas de auditoria ausentes no ambiente do assistente\n"
    "- `@audit tasks` — transforma o último relatório em tasks (`@audit tasks 1 3 5` escolhe pelos números)\n"
    "- `@audit falso 4 motivo` — marca o achado nº 4 (ou o id) como falso positivo; não volta mais\n"
    "- `@audit desfazer <id>` — tira do registro de falsos positivos\n"
)


_INSTALL_YES = re.compile(
    r"^\s*(?:sim|s|ok|pode|pode\s+instalar|instala|instale|instalar|claro|manda|yes|bora)\s*[.!?]*\s*$",
    re.I,
)
_INSTALL_NO = re.compile(
    r"^\s*(?:n[ãa]o|n|continuar|pular|sem\s+instalar|s[óo]\s+rodar|rodar\s+mesmo\s+assim|no)\s*[.!?]*\s*$",
    re.I,
)


def _parse_install_followup(text: str, messages) -> dict | None:
    if not messages:
        return None
    prev_ai = None
    for msg in reversed(list(messages)[:-1]):
        kind = getattr(msg, "type", "")
        if kind == "tool" or (kind == "ai" and getattr(msg, "tool_calls", None)):
            continue
        if kind == "ai":
            prev_ai = msg
        break
    if prev_ai is None:
        return None
    prev_text = str(getattr(prev_ai, "content", "") or "")
    if "@audit instalar" not in prev_text:
        return None
    if _INSTALL_YES.match(text):
        return {"cmd": "install", "args": []}
    if _INSTALL_NO.match(text):
        return {"cmd": "continue"}
    return None


def parse_command(text: str, messages=None) -> dict | None:
    """None se a mensagem não é um comando de auditoria (@audit, pedido natural ou resposta a instalação)."""
    text = str(text or "")
    if AUDIT_TAG.search(text[:TAG_LOOKAHEAD]):
        return _parse_tagged(text)
    natural = _parse_natural(text)
    if natural is not None:
        return natural
    return _parse_install_followup(text, messages)


def _parse_tagged(text: str) -> dict | None:
    zone = text[:TAG_LOOKAHEAD]
    rest = (AUDIT_TAG.sub("", zone, count=1) + text[TAG_LOOKAHEAD:]).strip()
    tokens = rest.split()
    head = tokens[0].lower() if tokens else ""
    if head in ("ajuda", "help"):
        return {"cmd": "help"}
    if head in ("tasks", "task", "tarefas"):
        return {"cmd": "tasks", "args": tokens[1:]}
    if head in ("falso", "fp"):
        return {"cmd": "fp", "args": tokens[1:2], "reason": " ".join(tokens[2:])}
    if head in ("desfazer", "unfp"):
        return {"cmd": "unfp", "args": tokens[1:2]}
    if head in ("pdf", "relatorio", "relatório"):
        return {"cmd": "pdf"}
    if head in ("instalar", "install", "pip"):
        return {"cmd": "install", "args": tokens[1:]}
    if head in ("continuar", "skip", "pular"):
        return {"cmd": "continue"}
    if head in ("fix", "corrigir", "format", "formatar", "linhas"):
        fix_cmd = {"cmd": "fix", "incremental": False, "base": None, "paths": []}
        for tok in tokens[1:]:
            low = tok.lower()
            if low in ("diff", "incremental"):
                fix_cmd["incremental"] = True
            elif low.startswith("base="):
                fix_cmd["base"] = tok[5:] or None
            else:
                word = tok.strip("\"'`<>.,;:!?")
                if word and word.lower() not in _NL_STOP | _NL_FOLDER | _NL_WHOLE:
                    fix_cmd["paths"].append(word)
        return fix_cmd
    cmd = {"cmd": "run", "incremental": False, "base": None, "min": "low", "tools": None, "paths": []}
    for tok in tokens:
        low = tok.lower()
        if low in ("diff", "incremental"):
            cmd["incremental"] = True
        elif low == "completo":
            cmd["incremental"] = False
        elif low.startswith("base="):
            cmd["base"] = tok[5:] or None
        elif low.startswith("min=") and low[4:] in CONFIDENCE:
            cmd["min"] = low[4:]
        elif low.startswith("tools="):
            names = tuple(n for n in low[6:].split(",") if n in ("ruff", "vulture", "radon", "bandit", "duplication", "spacing"))
            cmd["tools"] = names or None
        else:
            word = tok.strip("\"'`<>.,;:!?")
            if word and word.lower() not in _NL_STOP | _NL_FOLDER | _NL_WHOLE:
                cmd["paths"].append(word)
    return cmd


_NL_START = re.compile(
    r"^\s*(?:por favor[,\s]+)?(?:(?:pode|poderia|consegue)\s+)?"
    r"(?:audite|auditar|(?:fa[çc]a|fazer|rode|rodar|execute|executar)\s+(?:uma\s+)?auditoria)\b(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_NL_STOP = {"o", "a", "os", "as", "e", "um", "uma", "do", "da", "dos", "das", "de", "no", "na", "nos", "nas", "em", "para",
            "pra", "por", "favor", "me", "arquivo", "arquivos", "codigo", "código", "fonte", "somente", "apenas", "só", "so"}
_NL_FOLDER = {"pasta", "pastas", "diretório", "diretorio", "diretórios", "diretorios"}
_NL_WHOLE = {"projeto", "repositório", "repositorio", "tudo", "inteiro", "completo", "completa"}
_NL_DIFF = {"mudou", "mudaram", "alterado", "alterados", "alteração", "alterações", "alteracao", "alteracoes", "diff",
            "incremental", "novos", "modificado", "modificados", "modificações", "modificacoes"}


def _parse_natural(text: str) -> dict | None:
    """'Audite o arquivo x.py', 'audite os arquivos a.py, b.py e c.py', 'audite a pasta backend/api', 'audite o projeto',
    'audite o que mudou'. Só vale se houver caminho, 'projeto/tudo' ou 'mudou': senão a mensagem segue para o LLM."""
    if len(text) > 400:
        return None
    match = _NL_START.match(text)
    if not match:
        return None
    paths: list[str] = []
    folder_mode = whole = diff = False
    for raw in re.split(r"[\s,;]+", match.group("rest")):
        tok = raw.strip("\"'`()[]<>.,;:!?")
        low = tok.lower()
        if not tok or low in _NL_STOP:
            continue
        if low in _NL_FOLDER:
            folder_mode = True
        elif low in _NL_WHOLE:
            whole = True
        elif low in _NL_DIFF:
            diff = True
        elif "/" in tok or tok.endswith(CODE_EXT) or folder_mode:
            paths.append(tok)
    if not (paths or whole or diff):
        return None
    return {"cmd": "run", "incremental": diff, "base": None, "min": "low", "tools": None, "paths": paths}


def expand_paths(workspace: str, tokens: list[str]) -> tuple[list[str], list[str]]:
    """Pastas viram a lista de arquivos de código dentro delas. Devolve (arquivos, erros)."""
    root = Path(workspace).resolve()
    files: list[str] = []
    errors: list[str] = []
    for tok in tokens:
        rel = _norm(tok).rstrip("/")
        try:
            target = (root / rel).resolve()
            target.relative_to(root)
        except ValueError:
            errors.append(f"{tok}: fora do projeto")
            continue
        if target.is_file() and rel.endswith(CODE_EXT):
            files.append(rel)
        elif target.is_dir():
            prefix = rel + "/" if rel else ""
            files.extend(f for f in project_code_files(str(root)) if f.startswith(prefix))
        else:
            matches = [f for f in project_code_files(str(root)) if f == rel or f.endswith("/" + rel)] if rel else []
            if len(matches) == 1:
                files.append(matches[0])
            elif matches:
                errors.append(f"{tok}: ambíguo ({', '.join(matches[:4])}); use o caminho completo")
            else:
                errors.append(f"{tok}: não encontrado (ou não é .py/.js)")
    return sorted(set(files)), errors


def _last_path(workspace: str, thread_id: str) -> Path:
    return audit_dir(workspace) / f"last_{re.sub(r'[^A-Za-z0-9_.-]', '_', str(thread_id))[:80]}.json"


def save_last(workspace: str, thread_id: str, result: dict) -> None:
    path = _last_path(workspace, thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_last(workspace: str, thread_id: str) -> dict | None:
    try:
        data = json.loads(_last_path(workspace, thread_id).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _pending_install_path(workspace: str, thread_id: str) -> Path:
    return audit_dir(workspace) / f"pending_install_{re.sub(r'[^A-Za-z0-9_.-]', '_', str(thread_id))[:80]}.json"


def save_pending_install(workspace: str, thread_id: str, payload: dict) -> None:
    path = _pending_install_path(workspace, thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_pending_install(workspace: str, thread_id: str) -> dict | None:
    try:
        data = json.loads(_pending_install_path(workspace, thread_id).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def clear_pending_install(workspace: str, thread_id: str) -> None:
    try:
        _pending_install_path(workspace, thread_id).unlink(missing_ok=True)
    except OSError:
        pass


def select_findings(findings: list[dict], args: list[str]) -> list[dict]:
    """args: números do relatório (1-based), ids ou vazio/'todos' = todos."""
    if not args or args[0].lower() in ("todos", "all"):
        return list(findings)
    chosen, seen = [], set()
    for a in args:
        found = None
        if a.isdigit() and 1 <= int(a) <= len(findings):
            found = findings[int(a) - 1]
        else:
            found = next((f for f in findings if f.get("id") == a), None)
        if found is not None and found["id"] not in seen:
            seen.add(found["id"])
            chosen.append(found)
    return chosen


def format_report(result: dict, limit: int = 25, max_chars: int = 12000) -> str:
    findings = result.get("findings") or []
    lines = [f"## Auditoria — {result.get('files', 0)} arquivo(s) analisado(s)", ""]
    lines.append("**Ferramentas:** " + ", ".join(f"{k}: {v}" for k, v in (result.get("tools") or {}).items()))
    if findings:
        by_sev = {k: sum(1 for f in findings if f["severity"] == k) for k in ("critical", "high", "medium", "low")}
        lines.append("**Achados:** " + ", ".join(f"{n} {_SEV_PT[k]}" for k, n in by_sev.items() if n)
                     + f" (total {len(findings)})")
    extras = []
    if result.get("ignored_false_positives"):
        extras.append(f"{result['ignored_false_positives']} falso(s) positivo(s) do registro ignorado(s)")
    if result.get("dropped"):
        extras.append(f"{len(result['dropped'])} descartado(s) na validação contra o código")
    if extras:
        lines.append("**Filtrados:** " + "; ".join(extras))
    lines.append("")
    if not findings:
        lines.append("Nenhum achado validado.")
    for i, f in enumerate(findings[:limit], start=1):
        lines.append(f"{i}. **[{_SEV_PT[f['severity']]} · {f['kind']}]** `{f['file']}:{f['line']}` — {f['message']} "
                     f"({f['tool']} {f['rule']}, confiança {_CONF_PT[f['confidence']]}, id `{f['id']}`)")
        if f.get("note"):
            lines.append(f"   ↳ {f['note']}")
        if i <= 8 and f.get("snippet"):
            snippet = "\n".join(f["snippet"].split("\n")[:3])
            lines.append("   ```\n   " + snippet.replace("\n", "\n   ") + "\n   ```")
    if len(findings) > limit:
        lines.append(f"\n… e mais {len(findings) - limit} achado(s) (use `min=medium` ou filtre por pasta).")
    if findings:
        has_spacing = any(f.get("tool") == "spacing" for f in findings)
        fix_hint = "`@audit fix` corrige linhas em branco automaticamente; " if has_spacing else ""
        lines.append(f"\nPróximos passos: {fix_hint}`@audit tasks` cria as tasks; `@audit falso <número>` registra um falso positivo.")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars] + "\n… (relatório cortado)"
