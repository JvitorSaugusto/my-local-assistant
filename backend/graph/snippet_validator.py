"""Valida por código os trechos de código citados no dossiê do gatherer."""
import re
from pathlib import Path

_FILE_RE = re.compile(r"Arquivo:\s*`?([^`\n]+?)`?\s*$")
_PLACEHOLDERS = {"...", "# ...", "// ...", "/* ... */", "<...>"}


def _read_lines(path):
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return [line.strip() for line in data.decode(encoding).splitlines()]
        except UnicodeDecodeError:
            continue
    return [line.strip() for line in data.decode("latin-1", errors="replace").splitlines()]


def _check_block(block, current, root):
    wanted = [line.strip() for line in block if line.strip() and line.strip() not in _PLACEHOLDERS]
    if not wanted or not current or not root:
        return True, ""
    full = Path(root) / current.replace("\\", "/")
    if not full.is_file():
        return True, ""
    lines = _read_lines(full)
    pos = 0
    for want in wanted:
        while pos < len(lines) and lines[pos] != want:
            pos += 1
        if pos >= len(lines):
            return False, "linha inexistente no arquivo: " + want[:70]
        pos += 1
    return True, ""


def validate_snippets(dossier, root):
    """Remove blocos de código do dossiê cujas linhas não existem, em ordem, no arquivo real.

    Devolve (texto_limpo, [(arquivo, motivo), ...]). Linhas '...' e '# ...' são descartadas do bloco.
    """
    if not dossier or not root:
        return dossier, []
    out = []
    report = []
    current = None
    in_code = False
    fence = ""
    buf = []
    for line in dossier.splitlines():
        if not in_code:
            match = _FILE_RE.search(line)
            if match and "Arquivo:" in line:
                current = match.group(1).strip()
            out.append(line)
            if line.strip().startswith("```"):
                in_code = True
                fence = line
                buf = []
            continue
        if line.strip().startswith("```"):
            in_code = False
            ok, reason = _check_block(buf, current, root)
            if ok:
                out.append(fence)
                out.extend(item for item in buf if item.strip() not in _PLACEHOLDERS)
                out.append(line)
            else:
                out.append("TRECHO NÃO VALIDADO (" + reason + "): releia " + str(current) + " antes de citar.")
                report.append((current, reason))
            continue
        buf.append(line)
    if in_code:
        out.append(fence)
        out.extend(buf)
    return "\n".join(out), report
