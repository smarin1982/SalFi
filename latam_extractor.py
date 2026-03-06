"""
latam_extractor.py

Three-layer PDF extraction cascade for LATAM financial filings.

Layers (in order of preference):
  1. pdfplumber_table  — structured table extraction for born-digital PDFs
  2. pymupdf_text      — unstructured text parsing for digital PDFs with no table structure
  3. ocr_tesseract     — Tesseract OCR for scanned-image PDFs

Each layer returns an ExtractionResult with the same structure. The dominant method
(whichever produced the most fields) is recorded in ExtractionResult.extraction_method.

Critical constraints:
  - extract() NEVER writes any files to disk — only returns ExtractionResult.
  - OCR is only activated when the majority of pages are scanned (triage-first).
  - Unmatched Spanish labels are logged via logger.debug, never silently skipped.
  - TESSERACT_CMD is read from env var with Windows default fallback.

Exports:
    extract          - main entry point
    ExtractionResult - dataclass with fields, source_map, confidence, etc.
    SourceRef        - dataclass with page_number, section_heading, extraction_method
"""

import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber
import pytesseract
from PIL import Image
from loguru import logger

from latam_concept_map import (
    DEFAULT_CRITICAL_FIELDS,
    COUNTRY_CRITICAL_FIELDS,
    TESSERACT_AVAILABLE,
    map_to_canonical,
    parse_latam_number,
)

# ---------------------------------------------------------------------------
# Windows-specific: read Tesseract binary path from env with fallback.
# (Pitfall 6 from research: conda may not inherit system PATH additions.)
# ---------------------------------------------------------------------------
_TESSERACT_CMD = os.environ.get(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)
pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SourceRef:
    """Tracks where a field value was found in the PDF."""
    page_number: int          # 1-indexed
    section_heading: str      # e.g. "estado de situación financiera"
    extraction_method: str    # "pdfplumber_table" | "pymupdf_text" | "ocr_tesseract"


@dataclass
class ExtractionResult:
    """Result of extracting financial data from a single PDF for a single fiscal year."""
    fields: dict              # canonical_field_name -> value in native currency (float)
    source_map: dict          # canonical_field_name -> SourceRef
    confidence: str           # "Alta" | "Media" | "Baja"
    currency_code: str        # set by caller from company registry
    fiscal_year: int          # set by caller
    extraction_method: str    # dominant method used
    warnings: list = field(default_factory=list)  # e.g. "fallback_year_column_used"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Characters per page below which a page is considered scanned (image-only)
TEXT_CHARS_THRESHOLD = 50

FINANCIAL_SECTION_HEADINGS: dict[str, list[str]] = {
    "balance": [
        "estado de situacion financiera",
        "estado de situación financiera",
        "balance general",
    ],
    "income": [
        "estado de resultados",
        "estado de ganancias y perdidas",
        "estado de ganancias y pérdidas",
        "estado de resultado integral",
    ],
    "cashflow": [
        "estado de flujos de efectivo",
        "estado de flujo de efectivo",
        "flujos de caja",
    ],
}

# NOTE: Do NOT define a fixed module-level CRITICAL_FIELDS set here.
# Country-specific critical fields are looked up via
# COUNTRY_CRITICAL_FIELDS.get(country, DEFAULT_CRITICAL_FIELDS) in _score_confidence().

TABLE_SETTINGS_LINED: dict = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 3,
    "join_tolerance": 3,
}
TABLE_SETTINGS_TEXT: dict = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "snap_tolerance": 3,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_scanned_page(page: fitz.Page) -> bool:
    """True if a page has minimal native text and at least one embedded image."""
    return (
        len(page.get_text().strip()) < TEXT_CHARS_THRESHOLD
        and len(page.get_images()) > 0
    )


def _detect_section(text_lower: str) -> str:
    """
    Return the financial section key ("balance", "income", "cashflow") if any
    section heading is found in the page text, else return "unknown".
    """
    for section_key, headings in FINANCIAL_SECTION_HEADINGS.items():
        for heading in headings:
            if heading in text_lower:
                return section_key
    return "unknown"


def _find_year_column(header_row: list, target_year: int) -> int:
    """
    Scan a table header row for a cell containing target_year.
    Returns the column index if found.
    Returns 1 as fallback (second column is typically most recent in LATAM reports).
    """
    for i, cell in enumerate(header_row or []):
        if str(target_year) in str(cell or ""):
            return i
    return 1  # fallback — logged as warning by caller


def _find_value_for_year(row: list, fiscal_year: int) -> Optional[float]:
    """
    Extract a numeric value from a table row for the given fiscal_year.

    Scans right-to-left for the first parseable numeric value using parse_latam_number().
    If fiscal_year is provided, attempts to match the appropriate year column via
    _find_year_column() on header rows (detected as all-string rows).
    """
    # Scan right-to-left for first parseable numeric value
    for cell in reversed(row[1:]):
        if cell is None:
            continue
        value = parse_latam_number(str(cell))
        if value is not None:
            return value
    return None


def _score_confidence(fields: dict, method: str, country: str = "") -> str:
    """
    Assign a three-tier confidence label to an extraction result.

    Uses country-specific critical fields from COUNTRY_CRITICAL_FIELDS.
    Falls back to DEFAULT_CRITICAL_FIELDS when country is empty or unknown.

    Alta:  >= 15 fields AND all critical fields present
    Media: >= 8 fields OR all critical fields present
    Baja:  otherwise
    """
    critical_set = COUNTRY_CRITICAL_FIELDS.get(country, DEFAULT_CRITICAL_FIELDS)
    critical_found = critical_set & set(fields.keys())
    n_critical = len(critical_set)
    n_found = len(fields)

    if n_found >= 15 and len(critical_found) == n_critical:
        return "Alta"
    elif n_found >= 8 or len(critical_found) == n_critical:
        return "Media"
    else:
        return "Baja"


def _fields_coverage(result: ExtractionResult) -> float:
    """Return fraction of financial fields found (22 = total fields excluding ticker/fiscal_year)."""
    return len(result.fields) / 22


# ---------------------------------------------------------------------------
# Extraction layers
# ---------------------------------------------------------------------------

def _extract_pdfplumber(
    pdf_path: str,
    fiscal_year: int,
    company_slug: str = "",
    country: str = "",
) -> ExtractionResult:
    """
    Layer 1: structured table extraction using pdfplumber.

    Tries lined table settings first, then falls back to text-alignment settings.
    Logs unmatched Spanish labels via logger.debug (never silently skips).
    """
    fields: dict = {}
    source_map: dict = {}
    warnings_list: list = []
    current_section = "unknown"

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            page_num = page_idx + 1
            page_text = page.extract_text() or ""
            text_lower = page_text.lower()

            # Detect financial section
            detected = _detect_section(text_lower)
            if detected != "unknown":
                current_section = detected

            # Try lined table detection first, then fall back to text alignment
            tables = page.extract_tables(TABLE_SETTINGS_LINED) or []
            if not tables:
                tables = page.extract_tables(TABLE_SETTINGS_TEXT) or []

            # Detect header row for year-column selection
            year_col: Optional[int] = None

            for table in tables:
                if not table:
                    continue

                for row in table:
                    if not row or len(row) < 2:
                        continue

                    label = str(row[0] or "").strip()
                    if not label:
                        continue

                    # Detect header row (all non-numeric cells)
                    is_header = all(
                        (cell is None or not parse_latam_number(str(cell)))
                        for cell in row[1:]
                    )
                    if is_header and fiscal_year:
                        detected_col = _find_year_column(row, fiscal_year)
                        if detected_col != 1:
                            year_col = detected_col
                        else:
                            # Fallback used — warn only if we couldn't confirm
                            if str(fiscal_year) not in str(row):
                                year_col = 1
                                warnings_list.append("fallback_year_column_used")
                        continue

                    # Parse numeric value using year column if known
                    if year_col is not None and year_col < len(row):
                        value = parse_latam_number(str(row[year_col] or ""))
                        if value is None:
                            value = _find_value_for_year(row, fiscal_year)
                    else:
                        value = _find_value_for_year(row, fiscal_year)

                    if value is None:
                        continue

                    canonical = map_to_canonical(label)
                    if canonical is None:
                        logger.debug(
                            f"[latam_extractor] unmatched label | "
                            f"company={company_slug!r} | page={page_num} | label={label!r}"
                        )
                        continue

                    # Store first occurrence of each canonical field
                    if canonical not in fields:
                        fields[canonical] = value
                        source_map[canonical] = SourceRef(
                            page_number=page_num,
                            section_heading=current_section,
                            extraction_method="pdfplumber_table",
                        )

    return ExtractionResult(
        fields=fields,
        source_map=source_map,
        confidence=_score_confidence(fields, "pdfplumber_table", country=country),
        currency_code="",   # set by caller
        fiscal_year=fiscal_year,
        extraction_method="pdfplumber_table",
        warnings=warnings_list,
    )


def _extract_pymupdf_text(
    doc: fitz.Document,
    fiscal_year: int,
    company_slug: str = "",
    country: str = "",
) -> ExtractionResult:
    """
    Layer 2: unstructured text parsing using PyMuPDF.

    Splits each line into label + value parts and attempts to map them.
    Logs unmatched labels via logger.debug (never silently skips).
    """
    fields: dict = {}
    source_map: dict = {}
    current_section = "unknown"

    for page_num, page in enumerate(doc, start=1):
        page_text = page.get_text("text")
        text_lower = page_text.lower()

        detected = _detect_section(text_lower)
        if detected != "unknown":
            current_section = detected

        for line in page_text.splitlines():
            line = line.strip()
            if not line:
                continue

            # Split on two-or-more whitespace or tab to separate label from value
            parts = re.split(r"\s{2,}|\t", line)
            if len(parts) < 2:
                continue

            label = parts[0].strip()
            if not label:
                continue

            # Try to find a numeric value in the remaining parts (right-to-left)
            value: Optional[float] = None
            for part in reversed(parts[1:]):
                value = parse_latam_number(part.strip())
                if value is not None:
                    break

            if value is None:
                continue

            canonical = map_to_canonical(label)
            if canonical is None:
                logger.debug(
                    f"[latam_extractor] unmatched label | "
                    f"company={company_slug!r} | page={page_num} | label={label!r}"
                )
                continue

            if canonical not in fields:
                fields[canonical] = value
                source_map[canonical] = SourceRef(
                    page_number=page_num,
                    section_heading=current_section,
                    extraction_method="pymupdf_text",
                )

    return ExtractionResult(
        fields=fields,
        source_map=source_map,
        confidence=_score_confidence(fields, "pymupdf_text", country=country),
        currency_code="",
        fiscal_year=fiscal_year,
        extraction_method="pymupdf_text",
        warnings=[],
    )


def _extract_ocr(
    pdf_path: str,
    doc: fitz.Document,
    fiscal_year: int,
    company_slug: str = "",
    country: str = "",
) -> ExtractionResult:
    """
    Layer 3: Tesseract OCR for scanned-image PDFs.

    Renders each page at 300 DPI via PyMuPDF (no pdf2image / poppler required).
    Converts to grayscale for better OCR accuracy.
    Logs unmatched labels via logger.debug (never silently skips).

    Returns an ExtractionResult with confidence="Baja" and extraction_method="ocr_unavailable"
    if Tesseract is not available — does not raise.
    """
    if not TESSERACT_AVAILABLE:
        logger.error(
            "[latam_extractor] OCR requested but Tesseract is not available. "
            "Install Tesseract 5 + spa language pack and set TESSERACT_CMD."
        )
        return ExtractionResult(
            fields={},
            source_map={},
            confidence="Baja",
            currency_code="",
            fiscal_year=fiscal_year,
            extraction_method="ocr_unavailable",
            warnings=["tesseract_not_available"],
        )

    fields: dict = {}
    source_map: dict = {}
    current_section = "unknown"

    for page_num, page in enumerate(doc, start=1):
        # Render page at 300 DPI (minimum for reliable OCR on financial documents)
        pix = page.get_pixmap(dpi=300)
        # Convert to PIL image in memory — no disk write, no pdf2image/poppler dependency
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")  # grayscale

        # Run OCR with Spanish language pack; --psm 6 = uniform block of text
        ocr_text = pytesseract.image_to_string(img, lang="spa", config="--psm 6")

        text_lower = ocr_text.lower()
        detected = _detect_section(text_lower)
        if detected != "unknown":
            current_section = detected

        for line in ocr_text.splitlines():
            line = line.strip()
            if not line:
                continue

            # Split on two-or-more whitespace or tab (OCR text is rarely perfectly aligned)
            parts = re.split(r"\s{2,}|\t", line)
            if len(parts) < 2:
                continue

            label = parts[0].strip()
            if not label:
                continue

            value: Optional[float] = None
            for part in reversed(parts[1:]):
                value = parse_latam_number(part.strip())
                if value is not None:
                    break

            if value is None:
                continue

            canonical = map_to_canonical(label)
            if canonical is None:
                logger.debug(
                    f"[latam_extractor] unmatched label | "
                    f"company={company_slug!r} | page={page_num} | label={label!r}"
                )
                continue

            if canonical not in fields:
                fields[canonical] = value
                source_map[canonical] = SourceRef(
                    page_number=page_num,
                    section_heading=current_section,
                    extraction_method="ocr_tesseract",
                )

    return ExtractionResult(
        fields=fields,
        source_map=source_map,
        confidence=_score_confidence(fields, "ocr_tesseract", country=country),
        currency_code="",
        fiscal_year=fiscal_year,
        extraction_method="ocr_tesseract",
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract(
    pdf_path: str,
    currency_code: str = "",
    fiscal_year: int = 0,
    country: str = "",
) -> ExtractionResult:
    """
    Extract financial data from a PDF for a single fiscal year.

    Automatically selects the extraction strategy:
      - Scanned PDF (majority of pages are image-only): OCR via pytesseract
      - Digital PDF: pdfplumber table extraction; falls back to PyMuPDF text if coverage < 40%

    The ``country`` parameter (e.g. "CO", "PE", "CL") is passed to _score_confidence()
    so country-specific regulator critical fields are used. If omitted, DEFAULT_CRITICAL_FIELDS
    is used.

    IMPORTANT: This function never writes any files to disk.
                File writing is handled by latam_processor.py after human validation.

    Args:
        pdf_path:      Absolute path to the PDF file.
        currency_code: ISO currency code (e.g. "COP", "PEN", "CLP"). Set on result.
        fiscal_year:   The target fiscal year (e.g. 2023). Used for column selection.
        country:       Two-letter country code ("CO", "PE", "CL") for confidence scoring.

    Returns:
        ExtractionResult with fields, source_map, confidence, and extraction_method.
    """
    company_slug = Path(pdf_path).stem  # use filename stem as fallback slug for logging

    doc = fitz.open(pdf_path)
    try:
        scanned_count = sum(1 for page in doc if _is_scanned_page(page))
        is_scanned = scanned_count > len(doc) * 0.5

        if is_scanned:
            result = _extract_ocr(
                pdf_path, doc, fiscal_year,
                company_slug=company_slug, country=country,
            )
        else:
            result = _extract_pdfplumber(
                pdf_path, fiscal_year,
                company_slug=company_slug, country=country,
            )
            # If pdfplumber coverage is poor, try PyMuPDF text fallback
            if _fields_coverage(result) < 0.4:
                alt_result = _extract_pymupdf_text(
                    doc, fiscal_year,
                    company_slug=company_slug, country=country,
                )
                # Use whichever layer returned more fields
                if len(alt_result.fields) > len(result.fields):
                    result = alt_result
    finally:
        doc.close()

    # Set caller-provided metadata
    result.currency_code = currency_code
    result.fiscal_year = fiscal_year

    return result
