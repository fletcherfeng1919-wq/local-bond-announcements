"""Turn a downloaded PDF into text + tables, per page.

Text-native PDFs (most provinces) go through pdfplumber directly. Some
provinces publish flattened/scanned PDFs with no text layer at all --
pdfplumber returns empty strings for those, so we fall back to OCR
(PyMuPDF page rasterization + pytesseract chi_sim) when every page comes back
empty. OCR'd output is materially less trustworthy for numeric fields (bond
amounts, dates), so callers must propagate `method == "ocr"` into a warning
on any row built from it -- never silently trust an OCR'd number the same as
a text-extracted one.
"""
import json
from pathlib import Path

import pdfplumber

try:
    import fitz  # PyMuPDF
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


def _extract_text_layer(pdf_path) -> tuple[list[str], list[list[list]]]:
    page_texts = []
    page_tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_texts.append(page.extract_text() or "")
            page_tables.append(page.extract_tables() or [])
    return page_texts, page_tables


def _ocr_pages(pdf_path, dpi: int = 300) -> list[str]:
    texts = []
    doc = fitz.open(pdf_path)
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            texts.append(pytesseract.image_to_string(img, lang="chi_sim"))
    finally:
        doc.close()
    return texts


def _extract_pdf_uncached(pdf_path) -> dict:
    page_texts, page_tables = _extract_text_layer(pdf_path)
    combined_text = "\n".join(page_texts)
    tables = [t for pt in page_tables for t in pt]

    if combined_text.strip():
        return {"text": combined_text, "tables": tables, "method": "text"}

    if not OCR_AVAILABLE:
        return {"text": "", "tables": [], "method": "failed"}

    try:
        ocr_texts = _ocr_pages(pdf_path)
        ocr_text = "\n".join(ocr_texts)
    except Exception:
        return {"text": "", "tables": [], "method": "failed"}

    if not ocr_text.strip():
        return {"text": "", "tables": [], "method": "failed"}
    return {"text": ocr_text, "tables": [], "method": "ocr"}


def extract_pdf(pdf_path, use_cache: bool = True) -> dict:
    """Returns {"text": str, "tables": list[list[list]], "method": "text"|"ocr"|"failed"}.
    `tables` is a flat list of tables (each a list of rows) pooled across all
    pages -- OCR mode never populates it (OCR gives plain text only, no
    structured table geometry), so per-tranche table parsing is skipped for
    OCR'd documents and callers must fall back to whole-document regexes.

    Result is cached to a JSON sidecar next to the PDF: OCR in particular is
    slow (10-30s for a multi-page scanned doc), and if a long incremental run
    gets interrupted before its batch is flushed to the state CSV, a naive
    rerun would silently redo that OCR work on every retry without this.
    """
    cache_path = Path(str(pdf_path) + ".extract.json")
    if use_cache and cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    result = _extract_pdf_uncached(pdf_path)
    try:
        cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return result
