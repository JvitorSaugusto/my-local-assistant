"""Gerador determinístico de relatório completo de auditoria em PDF (sem dependências externas)."""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from .ops_core import pack_dir

_SEV_PT = {"critical": "CRÍTICA", "high": "ALTA", "medium": "MÉDIA", "low": "BAIXA"}
_CONF_PT = {"high": "alta", "medium": "média", "low": "baixa"}

_PAGE_W = 595.28  # A4 portrait (pt)
_PAGE_H = 841.89
_MARGIN_X = 44.0
_MARGIN_TOP = 48.0
_MARGIN_BOTTOM = 48.0


def _clean_latin(text: str) -> str:
    """Converte caracteres fora do WinAnsi/cp1252 para equivalentes seguros no PDF."""
    replacements = {
        "\u2014": "-",
        "\u2013": "-",
        "\u2026": "...",
        "\u2022": "*",
        "\u00b7": "|",
        "\u21b3": "->",
        "\u2192": "->",
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u00a0": " ",
        "\t": "    ",
    }
    out = str(text or "")
    for src, dst in replacements.items():
        out = out.replace(src, dst)
    return out.encode("cp1252", errors="replace").decode("cp1252")


def _pdf_escape(text: str) -> str:
    clean = _clean_latin(text)
    return clean.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_line(text: str, max_chars: int) -> list[str]:
    clean = _clean_latin(text)
    if not clean:
        return [""]
    lines: list[str] = []
    for raw in clean.splitlines() or [""]:
        if len(raw) <= max_chars:
            lines.append(raw)
            continue
        words = raw.split(" ")
        buf = ""
        for word in words:
            if not buf:
                if len(word) <= max_chars:
                    buf = word
                else:
                    for i in range(0, len(word), max_chars):
                        chunk = word[i : i + max_chars]
                        if len(chunk) == max_chars:
                            lines.append(chunk)
                        else:
                            buf = chunk
            elif len(buf) + 1 + len(word) <= max_chars:
                buf += " " + word
            else:
                lines.append(buf)
                if len(word) <= max_chars:
                    buf = word
                else:
                    buf = ""
                    for i in range(0, len(word), max_chars):
                        chunk = word[i : i + max_chars]
                        if len(chunk) == max_chars:
                            lines.append(chunk)
                        else:
                            buf = chunk
        if buf:
            lines.append(buf)
    return lines or [""]


class _SimplePDF:
    """Construtor mínimo de PDF 1.4 multipágina com Helvetica, Helvetica-Bold e Courier (WinAnsi)."""

    def __init__(self, header_title: str):
        self.header_title = _clean_latin(header_title)[:80]
        self.pages: list[list[str]] = []
        self.y = _PAGE_H - _MARGIN_TOP
        self._new_page()

    def _new_page(self) -> None:
        self.pages.append([])
        self.y = _PAGE_H - _MARGIN_TOP
        if len(self.pages) > 1:
            self._cmd(
                f"0.45 0.48 0.54 rg BT /F1 8 Tf {_MARGIN_X:.1f} {_PAGE_H - 28:.1f} Td "
                f"({_pdf_escape(self.header_title)}) Tj ET 0 0 0 rg"
            )
            self._cmd(
                f"0.85 0.87 0.90 RG 0.5 w {_MARGIN_X:.1f} {_PAGE_H - 34:.1f} m "
                f"{_PAGE_W - _MARGIN_X:.1f} {_PAGE_H - 34:.1f} l S 0 0 0 RG"
            )
            self.y = _PAGE_H - 52.0

    def _cmd(self, op: str) -> None:
        self.pages[-1].append(op)

    def _ensure(self, height: float) -> None:
        if self.y - height < _MARGIN_BOTTOM:
            self._new_page()

    def spacer(self, pts: float = 8.0) -> None:
        self.y -= pts
        if self.y < _MARGIN_BOTTOM:
            self._new_page()

    def rule(self) -> None:
        self._ensure(10.0)
        y_pos = self.y - 3.0
        self._cmd(
            f"0.82 0.84 0.88 RG 0.6 w {_MARGIN_X:.1f} {y_pos:.1f} m "
            f"{_PAGE_W - _MARGIN_X:.1f} {y_pos:.1f} l S 0 0 0 RG"
        )
        self.y -= 10.0

    def heading(self, text: str, size: float = 13.0) -> None:
        leading = size + 5.0
        wrapped = _wrap_line(text, int(88 * (10.0 / size)))
        self._ensure(leading * len(wrapped) + 8.0)
        self._cmd("0.10 0.14 0.24 rg")
        for ln in wrapped:
            self._cmd(f"BT /F2 {size:.1f} Tf {_MARGIN_X:.1f} {self.y:.1f} Td ({_pdf_escape(ln)}) Tj ET")
            self.y -= leading
        self._cmd("0 0 0 rg")
        self.y -= 2.0

    def text(self, text: str, size: float = 9.5, bold: bool = False, indent: float = 0.0, muted: bool = False) -> None:
        font = "/F2" if bold else "/F1"
        usable = _PAGE_W - (2 * _MARGIN_X) - indent
        max_chars = max(24, int(usable / (size * 0.52)))
        leading = size + 3.8
        wrapped = _wrap_line(text, max_chars)
        if muted:
            self._cmd("0.38 0.41 0.47 rg")
        for ln in wrapped:
            self._ensure(leading)
            self._cmd(f"BT {font} {size:.1f} Tf {_MARGIN_X + indent:.1f} {self.y:.1f} Td ({_pdf_escape(ln)}) Tj ET")
            self.y -= leading
        if muted:
            self._cmd("0 0 0 rg")

    def code_block(self, code: str, indent: float = 10.0) -> None:
        size = 8.2
        leading = 11.2
        usable = _PAGE_W - (2 * _MARGIN_X) - indent - 12.0
        max_chars = max(24, int(usable / (size * 0.60)))
        raw_lines = str(code or "").replace("\r\n", "\n").split("\n")[:12]
        wrapped: list[str] = []
        for raw in raw_lines:
            wrapped.extend(_wrap_line(raw, max_chars))
        if not wrapped:
            return
        box_h = len(wrapped) * leading + 8.0
        if self.y - box_h < _MARGIN_BOTTOM and box_h < (_PAGE_H - _MARGIN_TOP - _MARGIN_BOTTOM):
            self._new_page()
        x0 = _MARGIN_X + indent
        w = _PAGE_W - (2 * _MARGIN_X) - indent
        top_y = self.y + 3.0
        cur_lines: list[str] = []

        def _flush(block_lines: list[str], start_y: float) -> None:
            if not block_lines:
                return
            bh = len(block_lines) * leading + 8.0
            by = start_y - bh
            self._cmd(f"0.95 0.96 0.98 rg {x0:.1f} {by:.1f} {w:.1f} {bh:.1f} re f 0.14 0.16 0.20 rg")
            ty = start_y - leading + 1.0
            for ln in block_lines:
                self._cmd(f"BT /F3 {size:.1f} Tf {x0 + 6.0:.1f} {ty:.1f} Td ({_pdf_escape(ln)}) Tj ET")
                ty -= leading
            self._cmd("0 0 0 rg")

        for ln in wrapped:
            if self.y - leading - 8.0 < _MARGIN_BOTTOM:
                _flush(cur_lines, top_y)
                self._new_page()
                top_y = self.y + 3.0
                cur_lines = []
            cur_lines.append(ln)
            self.y -= leading
        _flush(cur_lines, top_y)
        self.y -= 10.0

    def to_bytes(self) -> bytes:
        total = len(self.pages)
        for idx, ops in enumerate(self.pages, start=1):
            footer = f"Página {idx} de {total}"
            ops.append(
                f"0.45 0.48 0.54 rg BT /F1 8 Tf {_PAGE_W - _MARGIN_X - 70:.1f} 24.0 Td "
                f"({_pdf_escape(footer)}) Tj ET 0 0 0 rg"
            )

        objects: list[bytes] = []

        def add_obj(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog_id = add_obj(b"")
        pages_id = add_obj(b"")
        f1 = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        f3 = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")

        page_ids: list[int] = []
        for ops in self.pages:
            stream = ("\n".join(ops) + "\n").encode("cp1252", errors="replace")
            content_id = add_obj(
                f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"endstream"
            )
            page_id = add_obj(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {_PAGE_W:.2f} {_PAGE_H:.2f}] "
                f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R /F3 {f3} 0 R >> >> "
                f"/Contents {content_id} 0 R >>".encode("ascii")
            )
            page_ids.append(page_id)

        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
        objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for idx, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out.extend(f"{idx} 0 obj\n".encode("ascii"))
            out.extend(body)
            out.extend(b"\nendobj\n")

        xref_pos = len(out)
        out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        out.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
        out.extend(
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n".encode("ascii")
        )
        return bytes(out)


def build_audit_pdf(workspace: str, result: dict, scope_label: str = "Projeto completo") -> Path:
    """Gera o relatório completo em PDF na pasta de artefatos (pack_dir) e devolve o caminho."""
    root = Path(workspace).resolve()
    project_name = root.name or str(root)
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    findings = list(result.get("findings") or [])
    tools = dict(result.get("tools") or {})
    audited_files = list(result.get("audited_files") or [])
    total_files = int(result.get("files") or len(audited_files))
    elapsed = result.get("elapsed_seconds")

    pdf = _SimplePDF(f"Relatório de Auditoria — {project_name}")
    pdf.heading(f"Relatório Completo de Auditoria — {project_name}", size=15.0)
    pdf.text(f"Workspace: {root}", size=9.0, muted=True)
    meta_parts = [f"Gerado em: {now_str}", f"Escopo: {scope_label}", f"Arquivos analisados: {total_files}"]
    if elapsed is not None:
        meta_parts.append(f"Duração: {elapsed} s")
    pdf.text(" | ".join(meta_parts), size=9.0, muted=True)
    pdf.rule()

    pdf.heading("1. Resumo Geral", size=12.0)
    by_sev = {k: sum(1 for f in findings if f.get("severity") == k) for k in ("critical", "high", "medium", "low")}
    sev_summary = ", ".join(f"{n} {_SEV_PT[k].lower()}" for k, n in by_sev.items() if n) or "0 achados"
    pdf.text(f"Total de achados validados: {len(findings)} ({sev_summary})", bold=True)

    by_kind: dict[str, int] = {}
    for f in findings:
        k = str(f.get("kind") or "outros")
        by_kind[k] = by_kind.get(k, 0) + 1
    if by_kind:
        kind_line = ", ".join(f"{k}: {v}" for k, v in sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0])))
        pdf.text(f"Por categoria: {kind_line}")

    if result.get("ignored_false_positives"):
        pdf.text(f"Falsos positivos ignorados pelo registro: {result['ignored_false_positives']}", muted=True)
    if result.get("dropped"):
        pdf.text(f"Descartados na validação contra o código real: {len(result['dropped'])}", muted=True)

    pdf.spacer(6.0)
    pdf.heading("2. Ferramentas Executadas", size=12.0)
    if tools:
        for tool_name, tool_status in tools.items():
            pdf.text(f"- {tool_name}: {tool_status}", indent=6.0)
    else:
        pdf.text("Nenhuma ferramenta registrada.", muted=True)

    pdf.spacer(6.0)
    pdf.heading(f"3. Todos os Achados Validados ({len(findings)})", size=12.0)
    if not findings:
        pdf.text("Nenhum achado validado nos arquivos auditados.")
    else:
        for idx, f in enumerate(findings, start=1):
            sev = _SEV_PT.get(str(f.get("severity") or "low"), "BAIXA")
            conf = _CONF_PT.get(str(f.get("confidence") or "low"), "baixa")
            header = (
                f"{idx}. [{sev} | {f.get('kind', '')}] {f.get('file', '')}:{f.get('line', 1)} "
                f"({f.get('tool', '')} {f.get('rule', '')} | confiança {conf} | id {f.get('id', '')})"
            )
            pdf.text(header, size=9.5, bold=True)
            pdf.text(str(f.get("message") or ""), size=9.2, indent=10.0)
            if f.get("note"):
                pdf.text(f"Nota: {f['note']}", size=8.8, indent=10.0, muted=True)
            if f.get("snippet"):
                pdf.code_block(str(f["snippet"]), indent=10.0)
            pdf.spacer(3.0)

    pdf.spacer(6.0)
    pdf.heading(f"4. Arquivos Auditados ({len(audited_files) or total_files})", size=12.0)
    if audited_files:
        for rel in audited_files:
            pdf.text(f"- {rel}", size=8.6, indent=6.0)
    else:
        pdf.text(f"{total_files} arquivo(s) analisado(s) (lista detalhada indisponível).", size=8.8, muted=True)

    base = pack_dir()
    now = time.time()
    for old in base.glob("auditoria_*.pdf"):
        try:
            if now - old.stat().st_mtime > 30 * 24 * 3600:
                old.unlink()
        except OSError:
            continue
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower())[:36].strip("-") or "projeto"
    out_path = base / f"auditoria_{time.strftime('%Y%m%d_%H%M%S')}_{slug}.pdf"
    tmp = out_path.with_name(out_path.name + ".part")
    try:
        tmp.write_bytes(pdf.to_bytes())
        tmp.replace(out_path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return out_path
