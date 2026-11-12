"""Proteções do executor: rollback de arquivos, checagem de sintaxe extra (JS/JSON) e pytest.

Tudo aqui é determinístico (sem LLM). Variáveis de ambiente (todas opcionais):
- TASK_ROLLBACK_ON_FAIL=0  desliga o rollback automático (padrão: ligado)
- TASK_JS_CHECK=0          desliga a checagem de sintaxe JavaScript com `node --check` (padrão: ligada se o node existir)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SINGLE_PATH_OPS = {"create_file", "replace_text", "append", "write_markdown", "create_pdf"}
_JS_SUFFIXES = (".js", ".mjs", ".cjs")
_ESM_HINTS = (
    "Cannot use import statement outside a module",
    "Unexpected token 'export'",
    "Cannot use 'import.meta' outside a module",
)


def _node():
    if os.getenv("TASK_JS_CHECK", "1") != "1":
        return None
    return shutil.which("node")


def _js_error_text(path):
    node = _node()
    if not node:
        return None
    try:
        done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode == 0:
        return None
    detail = (done.stderr or done.stdout or "").strip()
    if any(hint in detail for hint in _ESM_HINTS):
        return None
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    return (" | ".join(lines[:4])[:300]) or "erro de sintaxe"


def js_edit_error(suffix, before, after):
    """Mensagem de erro se a edição deixaria um .js com erro de sintaxe que ele não tinha antes; senão None."""
    ext = str(suffix or "").lower()
    if ext not in _JS_SUFFIXES or not _node():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        path_after = Path(tmp) / ("after" + ext)
        path_after.write_bytes(after.encode("utf-8"))
        error = _js_error_text(path_after)
        if not error:
            return None
        path_before = Path(tmp) / ("before" + ext)
        path_before.write_bytes(before.encode("utf-8"))
        if _js_error_text(path_before):
            return None  # o arquivo já estava quebrado antes da edição
    return "ERRO: edição REJEITADA — o arquivo JavaScript ficaria com erro de sintaxe. NADA foi salvo.\n" + error


class FileSnapshot:
    """Guarda o conteúdo original dos arquivos que a tarefa toca e desfaz tudo se ela falhar."""

    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.enabled = os.getenv("TASK_ROLLBACK_ON_FAIL", "1") == "1"
        self.blocked = False
        self._orig = {}

    def touch_step(self, step):
        if not self.enabled:
            return
        op = getattr(step, "op", "")
        if op in ("extract_zip", "copy_upload"):
            self.blocked = True  # muitos arquivos: não dá para desfazer com segurança
            return
        if op not in _SINGLE_PATH_OPS:
            return
        rel = str(getattr(step, "path", "") or "").replace("\\", "/")
        if not rel:
            return
        target = (self.root / rel).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            return
        if target in self._orig:
            return
        try:
            self._orig[target] = target.read_bytes() if target.is_file() else None
        except OSError:
            self.blocked = True

    def restore(self):
        """Desfaz as mudanças desta tarefa. True só se algum arquivo realmente voltou ao estado anterior."""
        if not self.enabled or self.blocked or not self._orig:
            return False
        changed = 0
        for target, original in self._orig.items():
            try:
                if original is None:
                    if target.is_file():
                        target.unlink()
                        changed += 1
                elif not target.is_file() or target.read_bytes() != original:
                    target.write_bytes(original)
                    changed += 1
            except OSError:
                continue
        self._orig = {}
        return changed > 0


def extra_syntax_problems(workspace, steps):
    """Sintaxe de .json e .js tocados pela tarefa (o .py já é checado pelo executor)."""
    root = Path(workspace).resolve()
    problems = []
    seen = set()
    for step in steps or []:
        rel = str(getattr(step, "path", "") or "").replace("\\", "/")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue
        if not target.is_file():
            continue
        low = rel.lower()
        if low.endswith(".json"):
            try:
                json.loads(target.read_text(encoding="utf-8-sig"))
            except ValueError as exc:
                problems.append(f"{rel}: JSON inválido ({exc})")
            except OSError:
                pass
        elif low.endswith(_JS_SUFFIXES):
            error = _js_error_text(target)
            if error:
                problems.append(f"{rel}: erro de sintaxe JavaScript: {error}")
    return problems


def run_pytest(workspace, rel, timeout=120):
    """Roda um arquivo de teste com o pytest do mesmo Python do backend. Devolve a lista de falhas."""
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", rel],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return [f"pytest {rel}: passou de {timeout}s e foi interrompido."]
    except OSError as exc:
        return [f"pytest {rel}: não foi possível executar ({exc})."]
    if done.returncode == 0:
        return []
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    if "No module named pytest" in output:
        return [f"pytest {rel}: o pytest não está instalado neste ambiente (pip install pytest)."]
    tail = "\n".join(output.splitlines()[-25:])
    return [f"pytest {rel} falhou:\n{tail[:1500]}"]
