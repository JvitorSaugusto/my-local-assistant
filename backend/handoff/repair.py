"""Reparo determinístico de âncoras `old` de replace_text (sem LLM, zero tokens).

Quando o `old` de um passo não bate exatamente com o arquivo (espaços no fim da linha, linha em branco com
espaços, indentação diferente), procura no arquivo real UM único bloco de linhas iguais ignorando espaços nas
pontas e troca o `old` pelo texto real. Se houver zero ou mais de um bloco candidato, não mexe.
"""
from __future__ import annotations

from pathlib import Path


def _read(path):
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding).replace("\r\n", "\n")
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace").replace("\r\n", "\n")


def _indent(line):
    return line[: len(line) - len(line.lstrip())]


def _find_unique_block(text, old):
    """Devolve o bloco real (com quebra final) que equivale a `old` ignorando espaços nas pontas das linhas."""
    if not old.endswith("\n"):
        return None
    wanted = [line.strip() for line in old.split("\n")[:-1]]
    if not wanted or not any(wanted):
        return None
    lines = text.split("\n")
    size = len(wanted)
    found = None
    for start in range(len(lines) - size + 1):
        if all(lines[start + k].strip() == wanted[k] for k in range(size)):
            if found is not None:
                return None
            found = start
    if found is None:
        return None
    return "\n".join(lines[found : found + size]) + "\n"


def _reindent(new, old_first, real_first):
    old_ind, real_ind = _indent(old_first), _indent(real_first)
    if old_ind == real_ind:
        return new
    out = []
    for line in new.split("\n"):
        if not line.strip():
            out.append(line)
        elif real_ind.startswith(old_ind):
            out.append(real_ind[len(old_ind):] + line)
        elif old_ind.startswith(real_ind) and line.startswith(old_ind[len(real_ind):]):
            out.append(line[len(old_ind) - len(real_ind):])
        else:
            out.append(line)
    return "\n".join(out)


def repair_steps(workspace, steps):
    """Devolve (steps_reparados, notas). Só altera `old`/`new` de replace_text que não batiam no arquivo."""
    root = Path(workspace).resolve()
    virtual = {}
    fixed = []
    notes = []
    for number, step in enumerate(steps or [], start=1):
        step = dict(step)
        if step.get("op") != "replace_text":
            fixed.append(step)
            continue
        rel = str(step.get("path") or "").replace("\\", "/")
        try:
            target = (root / rel).resolve()
            target.relative_to(root)
        except ValueError:
            fixed.append(step)
            continue
        if not target.is_file():
            fixed.append(step)
            continue
        if rel not in virtual:
            virtual[rel] = _read(target)
        text = virtual[rel]
        old = str(step.get("old") or "").replace("\r\n", "\n")
        new = str(step.get("new") or "").replace("\r\n", "\n")
        if old and text.count(old) == 1:
            step["old"], step["new"] = old, new
        elif old and text.count(old) == 0:
            block = _find_unique_block(text, old)
            if block is not None and text.count(block) == 1:
                new = _reindent(new, old.split("\n")[0], block.split("\n")[0])
                step["old"], step["new"] = block, new
                notes.append(f"passo {number} ({rel}): âncora reparada por código")
                old = block
        if old and text.count(old) == 1:
            virtual[rel] = text.replace(old, new, 1)
        fixed.append(step)
    return fixed, notes
