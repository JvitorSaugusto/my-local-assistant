"""Pré-validação de sintaxe em microtasks determinísticas antes de salvar no banco.

Pega erros clássicos de JSON gerado por IA (ex.: `\\n` virando quebra de linha real dentro
de string Python/JS, ou JSON inválido em `create_file`) ainda na importação, antes de
poluir a fila de tarefas.
"""

from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path
from typing import Any

from backend.graph.task_guards import _JS_SUFFIXES, _js_error_text


def _check_js_snippet(suffix: str, code: str) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ("check" + suffix)
        target.write_bytes(code.encode("utf-8"))
        return _js_error_text(target)


def _check_py_syntax(code: str) -> str | None:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        line_info = f"linha {exc.lineno}: " if exc.lineno else ""
        return f"{line_info}{exc.msg}"
    return None


def _has_unterminated_string_in_py(code: str) -> str | None:
    """Para trechos parciais (replace_text), reporta apenas erro claro de string não fechada."""
    try:
        ast.parse(code)
    except SyntaxError as exc:
        msg = (exc.msg or "").lower()
        if "unterminated string literal" in msg or "eol while scanning string literal" in msg:
            line_info = f"linha {exc.lineno}: " if exc.lineno else ""
            return f"{line_info}{exc.msg}"
    return None


def prevalidate_steps(steps: list[Any] | None) -> list[str]:
    """Valida passos determinísticos em memória. Devolve lista de erros (vazia se tudo OK)."""
    if not steps:
        return []
    errors: list[str] = []
    for idx, step in enumerate(steps, start=1):
        op = getattr(step, "op", None) if not isinstance(step, dict) else step.get("op")
        rel = str((getattr(step, "path", None) if not isinstance(step, dict) else step.get("path")) or "").strip()
        if not rel:
            continue
        suffix = Path(rel).suffix.lower()

        if op == "create_file":
            content = str(getattr(step, "content", "") if not isinstance(step, dict) else step.get("content", ""))
            if suffix == ".py":
                err = _check_py_syntax(content)
                if err:
                    errors.append(f"Passo {idx} (create_file {rel}): erro de sintaxe Python ({err}).")
            elif suffix == ".json":
                try:
                    json.loads(content)
                except ValueError as exc:
                    errors.append(f"Passo {idx} (create_file {rel}): JSON inválido ({exc}).")
            elif suffix in _JS_SUFFIXES:
                err = _check_js_snippet(suffix, content)
                if err:
                    errors.append(f"Passo {idx} (create_file {rel}): erro de sintaxe JS ({err}).")

        elif op == "append":
            content = str(getattr(step, "content", "") if not isinstance(step, dict) else step.get("content", ""))
            if suffix == ".py":
                err = _check_py_syntax(content)
                if err:
                    errors.append(f"Passo {idx} (append {rel}): erro de sintaxe Python ({err}).")
            elif suffix in _JS_SUFFIXES:
                err = _check_js_snippet(suffix, content)
                if err:
                    errors.append(f"Passo {idx} (append {rel}): erro de sintaxe JS ({err}).")

        elif op == "replace_text" and suffix == ".py":
            new_text = str(getattr(step, "new", "") if not isinstance(step, dict) else step.get("new", ""))
            err = _has_unterminated_string_in_py(new_text)
            if err:
                errors.append(
                    f"Passo {idx} (replace_text {rel}): string não fechada no código novo ({err}). "
                    "Verifique se algum '\\\\n' virou quebra de linha real no JSON."
                )
    return errors
