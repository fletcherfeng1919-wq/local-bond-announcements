"""Turn a downloaded PDF into text + tables, per page.

Text-native PDFs (most provinces) go through pdfplumber directly. Some
provinces publish flattened/scanned PDFs with no text layer at all --
pdfplumber returns empty strings for those, so we fall back to OCR
(page rasterization + pytesseract chi_sim) when every page comes back empty.
OCR'd output is materially less trustworthy for numeric fields (bond
amounts, dates), so callers must propagate `method == "ocr"` into a warning
on any row built from it -- never silently trust an OCR'd number the same as
a text-extracted one.
"""
import json
from pathlib import Path

import pdfplumber

try:
    import pytesseract
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


def _ocr_pages(pdf_path, resolution: int = 150) -> list[str]:
    # Two settings confirmed 2026-08-12 to dramatically outperform the
    # previous defaults on this project's actual document class (a bordered
    # grid table -- province/amount/term/rate cells -- often overlapped by a
    # red official seal stamp):
    #   1. Render via pdfplumber's own `page.to_image()` (a palette-mode /
    #      "P" mode PIL image), NOT PyMuPDF's `get_pixmap()` (RGB mode) --
    #      tested side by side at matched effective resolution, the
    #      palette-mode render OCRs dramatically better on this seal+grid
    #      document class. Counterintuitively, pdfplumber's default
    #      resolution=150 outperformed higher settings (200/300) when
    #      rendered this way -- higher DPI made characters too large for
    #      Tesseract's expected range on this template. Don't "fix" this by
    #      bumping resolution back up without re-testing both axes together
    #      (renderer AND resolution both matter, independently).
    #   2. `--psm 4` ("assume a single column of text of variable sizes")
    #      instead of Tesseract's default PSM 3 (fully automatic layout
    #      analysis, which gets confused by the seal + grid lines and
    #      returns near-garbage on this template).
    # Verified across 5 previously-low-yield documents (上海 issuance plan,
    # 内蒙古/河南/重庆 issuance results): 重庆 in particular went from 0/6
    # usable bond rows to nearly all fields readable on the same source PDF.
    # If a future source regresses under this combo, that's worth its own
    # investigation rather than reverting this default wholesale.
    texts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            img = page.to_image(resolution=resolution).original
            texts.append(pytesseract.image_to_string(img, lang="chi_sim", config="--psm 4"))
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
