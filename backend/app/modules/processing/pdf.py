"""PDF safety checks, text/layout extraction and page rendering (PyMuPDF).

Documents are hostile input. PyMuPDF does not execute embedded JavaScript, launch actions or
attachments; we additionally never read embedded files, never follow links and never render
annotations' actions. Text extracted here is *data*, never instructions.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from app.core.errors import InvalidDocument

MIN_TEXT_CHARS = 25  # below this a page is treated as image-only (scanned)


@dataclass(frozen=True)
class PdfLine:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class ParsedPage:
    page_no: int  # 1-based
    width: float
    height: float
    text: str
    lines: tuple[PdfLine, ...]
    has_text_layer: bool


def _open(data: bytes) -> pymupdf.Document:
    if not data.startswith(b"%PDF-"):
        raise InvalidDocument("File is not a PDF (signature check failed)", code="NOT_PDF")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - parser errors on hostile input are expected
        raise InvalidDocument("PDF could not be parsed", code="CORRUPT_PDF") from exc
    return doc


def inspect_pdf(data: bytes, *, max_bytes: int, max_pages: int) -> int:
    """Validate a PDF and return its page count. Raises InvalidDocument."""
    if len(data) == 0:
        raise InvalidDocument("File is empty", code="EMPTY_FILE")
    if len(data) > max_bytes:
        raise InvalidDocument(f"File exceeds {max_bytes // (1024 * 1024)} MB limit", code="FILE_TOO_LARGE")
    doc = _open(data)
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise InvalidDocument("Password-protected PDFs are not accepted", code="ENCRYPTED_PDF")
        count = doc.page_count
        if count == 0:
            raise InvalidDocument("PDF has no pages", code="EMPTY_PDF")
        if count > max_pages:
            raise InvalidDocument(f"PDF exceeds {max_pages} page limit", code="TOO_MANY_PAGES")
        return int(count)
    finally:
        doc.close()


def parse_pdf(data: bytes) -> list[ParsedPage]:
    doc = _open(data)
    pages: list[ParsedPage] = []
    try:
        for index in range(doc.page_count):
            page = doc.load_page(index)
            rect = page.rect
            raw = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
            lines: list[PdfLine] = []
            for block in raw.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    text = "".join(span.get("text", "") for span in line.get("spans", []))
                    text = " ".join(text.split())
                    if text:
                        x0, y0, x1, y1 = line["bbox"]
                        lines.append(PdfLine(text=text, bbox=(x0, y0, x1, y1)))
            full = "\n".join(line.text for line in lines)
            pages.append(
                ParsedPage(
                    page_no=index + 1,
                    width=float(rect.width),
                    height=float(rect.height),
                    text=full,
                    lines=tuple(lines),
                    has_text_layer=len(full.strip()) >= MIN_TEXT_CHARS,
                )
            )
    finally:
        doc.close()
    return pages


def parse_single_page(data: bytes, page_no: int) -> ParsedPage:
    for page in parse_pdf(data):
        if page.page_no == page_no:
            return page
    raise InvalidDocument("Page not found", code="PAGE_NOT_FOUND")


def render_page_png(data: bytes, page_no: int, zoom: float = 1.5) -> bytes:
    doc = _open(data)
    try:
        if page_no < 1 or page_no > doc.page_count:
            raise InvalidDocument("Page not found", code="PAGE_NOT_FOUND")
        page = doc.load_page(page_no - 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=False, alpha=False)
        return bytes(pix.tobytes("png"))
    finally:
        doc.close()
