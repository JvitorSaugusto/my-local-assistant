"""Leitura de texto para as tools do agente, com suporte a PDF e DOCX.

PDF usa `pypdf` (importado só quando necessário). DOCX é lido direto do zip,
sem dependências extras. Qualquer outro arquivo é lido como UTF-8.
"""

import re
import zipfile
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_EXTRACTED_CHARS = 400_000
MAX_PDF_PAGES = 300
MAX_DOCX_XML_BYTES = 20 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError("Leitura de PDF indisponível: instale 'pypdf'.") from exc

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("PDF protegido por senha: não é possível extrair o texto.")

    parts: list[str] = []
    total = len(reader.pages)
    for number, page in enumerate(reader.pages[:MAX_PDF_PAGES], start=1):
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(f"[página {number}]\n{text}")

    if not parts:
        raise ValueError(
            "O PDF não tem camada de texto (provavelmente é um scan). OCR não é suportado."
        )
    if total > MAX_PDF_PAGES:
        parts.append(f"[... PDF com {total} páginas; lidas apenas as {MAX_PDF_PAGES} primeiras]")
    return "\n\n".join(parts)


def _paragraph_text(paragraph: ET.Element) -> str:
    chunks: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t" and node.text:
            chunks.append(node.text)
        elif node.tag == f"{_W}tab":
            chunks.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            chunks.append("\n")
    return "".join(chunks)


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise ValueError("DOCX grande demais para extrair o texto.")
            xml_bytes = archive.read(info)
    except KeyError as exc:
        raise ValueError("Arquivo DOCX inválido (sem word/document.xml).") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError("Arquivo DOCX inválido (não é um zip).") from exc

    body = ET.fromstring(xml_bytes).find(f"{_W}body")
    if body is None:
        return ""

    lines: list[str] = []
    for child in body:
        if child.tag == f"{_W}p":
            text = _paragraph_text(child).strip()
            if not text:
                continue
            style = child.find(f"{_W}pPr/{_W}pStyle")
            style_id = (style.get(f"{_W}val") if style is not None else "") or ""
            match = re.match(r"(?i)heading\s*(\d)", style_id)
            lines.append(f"{'#' * int(match.group(1))} {text}" if match else text)
        elif child.tag == f"{_W}tbl":
            for row in child.iter(f"{_W}tr"):
                cells = [
                    " ".join(_paragraph_text(p).strip() for p in cell.iter(f"{_W}p")).strip()
                    for cell in row.findall(f"{_W}tc")
                ]
                lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


@lru_cache(maxsize=16)
def _extract_cached(path_str: str, mtime_ns: int, size: int) -> str:
    path = Path(path_str)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _extract_pdf(path)
    elif suffix == ".docx":
        text = _extract_docx(path)
    else:
        data = path.read_bytes()
        text = None
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = data.decode("latin-1", errors="replace")

    if len(text) > MAX_EXTRACTED_CHARS:
        text = text[:MAX_EXTRACTED_CHARS] + "\n[... texto truncado]"
    return text


def read_text_for_tools(path: Path) -> str:
    """Devolve o texto do arquivo (PDF/DOCX são convertidos). Levanta exceção em caso de erro."""
    stat = path.stat()
    return _extract_cached(str(path), stat.st_mtime_ns, stat.st_size)
