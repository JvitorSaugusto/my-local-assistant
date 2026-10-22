"""Geração de documentos (PDF) a partir de Markdown simples.

Sem LLM e sem efeitos colaterais: recebe texto, devolve bytes. Usado pela
tool `create_pdf_file` e pelo passo `create_pdf` das microtasks.

Suporta: títulos (#..####), parágrafos, listas (-, *, 1.), citações (>),
blocos de código (```), tabelas com pipe, linha horizontal (---) e, inline,
**negrito**, *itálico*, `código` e [texto](url).

Requer: pip install reportlab
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

# Fontes TrueType com cobertura Unicode ampla (acentos, setas, símbolos).
# Se nenhuma for encontrada, cai para Helvetica (cobre pt-BR, mas não emojis).
_FONT_CANDIDATES = [
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
    ),
    (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/ariali.ttf",
        "C:/Windows/Fonts/arialbi.ttf",
    ),
    (
        "/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial Italic.ttf",
        "/Library/Fonts/Arial Bold Italic.ttf",
    ),
]

_REPLACEMENTS = {
    "→": "->", "←": "<-", "⇒": "=>", "✓": "[x]", "✔": "[x]", "✅": "[x]",
    "❌": "[ ]", "⚠️": "(!)", "⚠": "(!)", "•": "-", "“": '"', "”": '"',
}

_fonts_cache: dict | None = None


class PdfDependencyError(RuntimeError):
    """reportlab não está instalado."""


def _setup_fonts() -> dict:
    """Registra uma família TrueType se existir; devolve os nomes a usar."""
    global _fonts_cache
    if _fonts_cache is not None:
        return _fonts_cache

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for regular, bold, italic, bold_italic in _FONT_CANDIDATES:
        if all(Path(p).exists() for p in (regular, bold, italic, bold_italic)):
            try:
                pdfmetrics.registerFont(TTFont("DocBody", regular))
                pdfmetrics.registerFont(TTFont("DocBody-Bold", bold))
                pdfmetrics.registerFont(TTFont("DocBody-Italic", italic))
                pdfmetrics.registerFont(TTFont("DocBody-BoldItalic", bold_italic))
                pdfmetrics.registerFontFamily(
                    "DocBody",
                    normal="DocBody",
                    bold="DocBody-Bold",
                    italic="DocBody-Italic",
                    boldItalic="DocBody-BoldItalic",
                )
                _fonts_cache = {"body": "DocBody", "bold": "DocBody-Bold", "unicode": True}
                return _fonts_cache
            except Exception:  # fonte corrompida: tenta a próxima
                continue

    _fonts_cache = {"body": "Helvetica", "bold": "Helvetica-Bold", "unicode": False}
    return _fonts_cache


def _replace_symbols(text: str) -> str:
    """Troca emojis/símbolos que nenhuma fonte embutida cobre por equivalentes em texto."""
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text


def _to_cp1252(text: str) -> str:
    """Para Helvetica/Courier: troca símbolos conhecidos e o resto não coberto por '?'."""
    return _replace_symbols(text).encode("cp1252", errors="replace").decode("cp1252")


def _inline(text: str, unicode_ok: bool) -> str:
    """Markdown inline -> mini-HTML do reportlab (já escapado)."""
    text = _to_cp1252(text) if not unicode_ok else _replace_symbols(text)

    text = escape(text)
    text = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1 (\2)", text)
    return text


_HEADING = re.compile(r"^(#{1,4})\s+(.*\S)\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def markdown_to_pdf_bytes(markdown: str, title: str = "") -> bytes:
    """Converte Markdown em PDF (A4) e devolve os bytes."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable,
            Paragraph,
            Preformatted,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover
        raise PdfDependencyError(
            "A biblioteca 'reportlab' não está instalada. Rode: pip install reportlab"
        ) from exc

    fonts = _setup_fonts()
    body_font, bold_font, unicode_ok = fonts["body"], fonts["bold"], fonts["unicode"]

    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "DocP", parent=base["BodyText"], fontName=body_font, fontSize=10.5, leading=15, spaceAfter=6
    )
    headings = {
        level: ParagraphStyle(
            f"DocH{level}",
            parent=base["Heading1"],
            fontName=bold_font,
            fontSize=size,
            leading=size + 5,
            spaceBefore=14 if level <= 2 else 10,
            spaceAfter=6,
        )
        for level, size in {1: 20, 2: 16, 3: 13, 4: 11.5}.items()
    }
    title_style = ParagraphStyle(
        "DocTitle", parent=headings[1], fontSize=24, leading=29, spaceAfter=14, spaceBefore=0
    )
    quote = ParagraphStyle(
        "DocQuote", parent=body, leftIndent=14, textColor=colors.HexColor("#555555"),
        borderPadding=(2, 0, 2, 8),
    )
    bullet_style = ParagraphStyle("DocBullet", parent=body, spaceAfter=3)
    code_style = ParagraphStyle(
        "DocCode", parent=body, fontName="Courier", fontSize=8.8, leading=11.5,
        backColor=colors.HexColor("#F3F4F6"), borderPadding=6, spaceBefore=4, spaceAfter=10,
        leftIndent=4,
    )

    flow: list = []
    if title.strip():
        flow.append(Paragraph(_inline(title.strip(), unicode_ok), title_style))

    lines = markdown.replace("\r\n", "\n").split("\n")
    i, n = 0, len(lines)
    para_buf: list[str] = []

    def flush_paragraph() -> None:
        if para_buf:
            text = " ".join(s.strip() for s in para_buf)
            flow.append(Paragraph(_inline(text, unicode_ok), body))
            para_buf.clear()

    while i < n:
        line = lines[i]

        # bloco de código
        if line.strip().startswith("```"):
            flush_paragraph()
            i += 1
            code_lines = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i].rstrip("\n"))
                i += 1
            i += 1  # fecha a cerca
            code = _to_cp1252("\n".join(code_lines).expandtabs(4)) or " "
            flow.append(Preformatted(code, code_style))
            continue

        # tabela
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            flush_paragraph()
            header = _split_row(line)
            rows = [header]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            width = len(header)
            cell_style = ParagraphStyle("DocCell", parent=body, fontSize=9.5, leading=12, spaceAfter=0)
            head_style = ParagraphStyle("DocHead", parent=cell_style, fontName=bold_font)
            data = []
            for r_idx, row in enumerate(rows):
                row = (row + [""] * width)[:width]
                style = head_style if r_idx == 0 else cell_style
                data.append([Paragraph(_inline(c, unicode_ok), style) for c in row])
            table = Table(data, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            flow.extend([table, Spacer(1, 8)])
            continue

        if not line.strip():
            flush_paragraph()
            i += 1
            continue

        match = _HEADING.match(line)
        if match:
            flush_paragraph()
            level = len(match.group(1))
            flow.append(Paragraph(_inline(match.group(2), unicode_ok), headings[level]))
            i += 1
            continue

        if _RULE.match(line):
            flush_paragraph()
            flow.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#CBD5E1")))
            flow.append(Spacer(1, 6))
            i += 1
            continue

        match = _BULLET.match(line)
        if match:
            flush_paragraph()
            indent = len(match.group(1).replace("\t", "    "))
            style = ParagraphStyle(
                f"DocBullet{indent}", parent=bullet_style, leftIndent=14 + indent * 4,
                bulletIndent=4 + indent * 4,
            )
            flow.append(Paragraph(_inline(match.group(2), unicode_ok), style, bulletText="•"))
            i += 1
            continue

        match = _NUMBERED.match(line)
        if match:
            flush_paragraph()
            indent = len(match.group(1).replace("\t", "    "))
            style = ParagraphStyle(
                f"DocNum{indent}", parent=bullet_style, leftIndent=18 + indent * 4,
                bulletIndent=2 + indent * 4,
            )
            flow.append(Paragraph(_inline(match.group(3), unicode_ok), style, bulletText=f"{match.group(2)}."))
            i += 1
            continue

        if line.lstrip().startswith(">"):
            flush_paragraph()
            flow.append(Paragraph(_inline(line.lstrip()[1:].strip(), unicode_ok), quote))
            i += 1
            continue

        para_buf.append(line)
        i += 1

    flush_paragraph()

    if not flow:
        flow.append(Paragraph(" ", body))

    def _footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(body_font, 8.5)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=title.strip() or "Documento",
    )
    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
