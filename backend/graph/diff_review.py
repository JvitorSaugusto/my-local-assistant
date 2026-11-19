"""Revisor de diff determinístico (sem LLM): roda no executor DEPOIS dos passos e ANTES do commit automático.

Compara cada .py tocado (original guardado pelo FileSnapshot x versão nova) e procura o que o verify declarado não pega:
  - BLOQUEIA (rollback): bloco adicionado que já existe em outro ponto do mesmo arquivo (código colado em duplicidade,
    como um 'quantity -= qty' que passa a rodar duas vezes). Só vale para arquivos que já existiam.
  - AVISA (a task fica concluída, mas o commit automático é pulado até você revisar):
      * atributo novo com sublinhado (item.is_defective) que não existe em nenhum outro lugar do projeto nem nas
        bibliotecas instaladas: típico de campo inventado pelo modelo;
      * a task apagou mais da metade de um arquivo de 30+ linhas.
Ferramenta de leitura falhou ou arquivo gigante => a checagem é pulada, nunca reprova por engano.

.env (opcionais): TASK_REVIEW=1 (0 desliga tudo), TASK_REVIEW_DUP=1, TASK_REVIEW_UNKNOWN=warn (block bloqueia, off desliga),
TASK_REVIEW_LIB_SECONDS=8 (tempo máximo olhando as bibliotecas instaladas)
"""
from __future__ import annotations

import difflib
import os
import re
import sysconfig
import time
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build"}
MAX_LINES = 4000
_ATTR = re.compile(r"\b[A-Za-z_]\w*\.([A-Za-z_][A-Za-z0-9_]{5,})\b")


def _flag(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip().lower()


def _decode(data) -> str | None:
    if data is None:
        return None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc).replace("\r\n", "\n")
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace").replace("\r\n", "\n")


def _read(path: Path) -> str | None:
    try:
        return _decode(path.read_bytes())
    except OSError:
        return None


def _chunks(old: list[str], new: list[str]):
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    return matcher.get_opcodes()


def duplicated_blocks(old: list[str], new: list[str]) -> list[tuple[int, int, int]]:
    """[(início, fim, onde_já_existe)] (1-based) de blocos adicionados que já existem inteiros em outro ponto do arquivo."""
    stripped = [ln.strip() for ln in new]
    found = []
    for tag, _i1, _i2, j1, j2 in _chunks(old, new):
        if tag not in ("insert", "replace"):
            continue
        while j1 < j2 and not stripped[j1]:
            j1 += 1
        while j2 > j1 and not stripped[j2 - 1]:
            j2 -= 1
        block = stripped[j1:j2]
        significant = [ln for ln in block if ln]
        if len(significant) < 4 or sum(len(ln) for ln in significant) < 80:
            continue
        size = len(block)
        for k in range(0, len(stripped) - size + 1):
            if (k + size <= j1 or k >= j2) and stripped[k:k + size] == block:
                found.append((j1 + 1, j2, k + 1))
                break
    return found


def _added_text(old: list[str], new: list[str]) -> str:
    out = []
    for tag, _i1, _i2, j1, j2 in _chunks(old, new):
        if tag in ("insert", "replace"):
            out.extend(new[j1:j2])
    return "\n".join(out)


def _candidates(old_text: str, added: str) -> list[str]:
    names = []
    for match in _ATTR.finditer(added):
        name = match.group(1)
        if "_" not in name or name.startswith("__") or name in names:
            continue
        if re.search(r"\b" + re.escape(name) + r"\b", old_text):
            continue
        escaped = re.escape(name)
        defined = (
            rf"\b(?:def|class)\s+{escaped}\b"            # def nome / class nome
            rf"|\b(?:self|cls)\.{escaped}\s*=(?!=)"      # self.nome = ...
            rf"|(?m:^\s*{escaped}\s*(?::[^=\n]+)?=(?!=))"  # nome = ... / nome: tipo = ... no nível da classe
            rf"|(?m:^\s*{escaped}\s*:\s*[A-Za-z_\[\"'])"  # nome: tipo
        )
        if re.search(defined, added):
            continue
        names.append(name)
    return names


def _project_has(root: Path, names: list[str], skip: set[Path], limit: int = 3000) -> set[str]:
    found: set[str] = set()
    checked = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            if not fname.endswith((".py", ".js", ".html", ".sql")):
                continue
            path = Path(base, fname).resolve()
            if path in skip:
                continue
            checked += 1
            if checked > limit:
                return found
            try:
                data = path.read_bytes()[:2_000_000]
            except OSError:
                continue
            for n in names:
                if n not in found and n.encode() in data:
                    found.add(n)
            if len(found) == len(names):
                return found
    return found


def _libs_have(names: list[str]) -> set[str]:
    try:
        budget = float(os.getenv("TASK_REVIEW_LIB_SECONDS", "") or 8)
    except ValueError:
        budget = 8.0
    deadline = time.monotonic() + budget
    dirs = []
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        path = sysconfig.get_paths().get(key)
        if path and path not in dirs and os.path.isdir(path):
            dirs.append(path)
    found: set[str] = set()
    for top in dirs:
        for base, subdirs, files in os.walk(top):
            subdirs[:] = [d for d in subdirs if d not in ("__pycache__", "test", "tests", "idlelib", "turtledemo")]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                if time.monotonic() > deadline:
                    return found
                try:
                    data = Path(base, fname).read_bytes()[:1_500_000]
                except OSError:
                    continue
                for n in names:
                    if n not in found and n.encode() in data:
                        found.add(n)
                if len(found) == len(names):
                    return found
    return found


def review_changes(workspace: str, originals: dict) -> dict:
    """originals: {Path: bytes|None} do FileSnapshot. Devolve {blocking, warnings, risk}."""
    result = {"blocking": [], "warnings": [], "risk": "baixo"}
    if _flag("TASK_REVIEW", "1") in ("0", "false", "no", "off") or not originals:
        return result
    try:
        root = Path(workspace).resolve()
        touched = {Path(p).resolve() for p in originals}
        for path, orig in originals.items():
            path = Path(path).resolve()
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if not rel.endswith(".py") or orig is None:
                continue
            old_text, new_text = _decode(orig), _read(path)
            if old_text is None or new_text is None:
                continue
            old, new = old_text.split("\n"), new_text.split("\n")
            if len(old) > MAX_LINES or len(new) > MAX_LINES:
                continue
            if _flag("TASK_REVIEW_DUP", "1") not in ("0", "off"):
                for start, end, other in duplicated_blocks(old, new):
                    result["blocking"].append(
                        f"revisão do diff: {rel}: o bloco das linhas {start}-{end} é idêntico ao das linhas {other}-{other + end - start}; "
                        "parece código colado em duplicidade (a lógica passaria a rodar duas vezes)"
                    )
            mode = _flag("TASK_REVIEW_UNKNOWN", "warn")
            if mode != "off":
                names = _candidates(old_text, _added_text(old, new))
                if names:
                    missing = [n for n in names if n not in _project_has(root, names, {path})]
                    if missing:
                        missing = [n for n in missing if n not in _libs_have(missing)]
                    if missing:
                        text = (f"{rel}: usa {', '.join(missing[:6])} sem que exista em nenhum outro lugar do projeto nem nas "
                                "bibliotecas instaladas (campo ou função inventada?)")
                        (result["blocking"] if mode == "block" else result["warnings"]).append("revisão do diff: " + text)
            if len(old) >= 30:
                removed = sum(i2 - i1 for tag, i1, i2, _j1, _j2 in _chunks(old, new) if tag in ("delete", "replace"))
                if removed / len(old) > 0.5:
                    result["warnings"].append(f"revisão do diff: {rel}: a task apagou ou reescreveu {removed} de {len(old)} linhas")
        if result["blocking"] or result["warnings"]:
            result["risk"] = "alto"
        elif len(touched) > 5:
            result["risk"] = "médio"
    except Exception as exc:  # a revisão nunca derruba a task
        print(f"[REVIEW] ignorada: {type(exc).__name__}: {exc}")
        return {"blocking": [], "warnings": [], "risk": "baixo"}
    return result
