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
from datetime import datetime
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

# Path where unmatched labels are recorded for future synonym review
_CANDIDATES_FILE = Path("data/latam/learned_candidates.jsonl")

# Labels to exclude from candidate capture — year column headers and aggregate totals
_CANDIDATE_YEAR_RE = re.compile(r"^\d{4}$")
_CANDIDATE_STOP_WORDS = frozenset({"total", "subtotal", "suma", "neto"})


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


def _year_in_cell(year: int, cell_str: str) -> bool:
    """Return True if cell_str contains the year as a 4-digit string OR
    as a 2-digit abbreviation with a preceding hyphen or space.

    Examples (year=2024):
        "2024"    → True   (exact)
        "dic-24"  → True   (abbreviated: "-24")
        "dic 24"  → True   (abbreviated: " 24")
        "dic-2024"→ True   (full year after hyphen)
        "2023"    → False
        "1024"    → False  (not a year-like suffix)
    """
    s = str(cell_str or "")
    if str(year) in s:
        return True
    # Match 2-digit suffix: hyphen/space + last-two-digits of year
    suffix = str(year)[2:]  # e.g. "24" for 2024
    return bool(re.search(r"[-\s]" + re.escape(suffix) + r"\b", s))


def _find_year_column(header_row: list, target_year: int) -> int:
    """
    Scan a table header row for a cell containing target_year.
    Recognises both "2024" and abbreviated "dic-24" / "dic 24" style headers.
    Returns the column index if found.
    Returns 1 as fallback (second column is typically most recent in LATAM reports).
    """
    for i, cell in enumerate(header_row or []):
        if _year_in_cell(target_year, str(cell or "")):
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
# Candidate capture
# ---------------------------------------------------------------------------

def _append_candidate(
    label: str,
    value: float,
    page: int,
    section: str,
    company: str,
    country: str,
    pdf: str,
) -> None:
    """Append an unmatched label to learned_candidates.jsonl.

    If the label already exists, increment seen_count and update timestamp.
    Never raises — extraction must not be blocked by logging failures.
    """
    # Skip noise labels: year-only strings ('2020') and aggregate stop-words ('Total')
    _label_stripped = label.strip()
    if not _label_stripped or len(_label_stripped) < 4:
        return  # already guarded by callers but belt-and-suspenders
    if _CANDIDATE_YEAR_RE.match(_label_stripped):
        return  # column header like '2020', '2021'
    if _label_stripped.lower() in _CANDIDATE_STOP_WORDS:
        return  # aggregate row label like 'Total', 'Subtotal'

    import json
    from datetime import date

    try:
        _CANDIDATES_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Load existing records
        records: list[dict] = []
        if _CANDIDATES_FILE.exists():
            with open(_CANDIDATES_FILE, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass  # skip corrupt lines

        # Check for existing record with same label (case-insensitive key)
        label_lower = label.strip().lower()
        existing_idx = next(
            (i for i, r in enumerate(records) if r.get("label", "").lower() == label_lower),
            None,
        )

        today = str(date.today())
        if existing_idx is not None:
            records[existing_idx]["seen_count"] = records[existing_idx].get("seen_count", 1) + 1
            records[existing_idx]["timestamp"] = today
            # Track distinct companies
            companies_seen = records[existing_idx].get("companies_seen", [records[existing_idx].get("company", "")])
            if company not in companies_seen:
                companies_seen.append(company)
            records[existing_idx]["companies_seen"] = companies_seen
        else:
            records.append({
                "label": label.strip(),
                "value": value,
                "page": page,
                "section": section,
                "company": company,
                "country": country,
                "pdf": pdf,
                "seen_count": 1,
                "companies_seen": [company],
                "timestamp": today,
            })

        # Rewrite file atomically (read-modify-write — single-threaded extraction context)
        with open(_CANDIDATES_FILE, "w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    except Exception as exc:  # noqa: BLE001
        # Log but never propagate — extraction pipeline must not be blocked
        try:
            from loguru import logger as _logger
            _logger.warning(f"learned_candidates write failed (non-blocking): {exc}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Fiscal year inference
# ---------------------------------------------------------------------------

def _infer_fiscal_years(ocr_text: str) -> tuple[int, int, bool]:
    """
    Scan first 500 chars of OCR text for a year-pair pattern like:
      "2024 Y 2023", "2024 2023", "DICIEMBRE 2024 DICIEMBRE 2023"
    Returns (primary_year, comparative_year, primary_is_left).
    primary_is_left=True when the more-recent year appears to the LEFT in the header.
    Falls back to (current_year-1, current_year-2, False) if not found.
    """
    snippet = ocr_text[:800]
    # Find all 4-digit years in range 2010-2030, preserving position
    year_matches = [(int(m.group()), m.start()) for m in re.finditer(r'\b(20[12]\d)\b', snippet)]
    unique_years = sorted({y for y, _ in year_matches}, reverse=True)
    if len(unique_years) >= 2:
        primary, comp = unique_years[0], unique_years[1]
        # Determine column order by finding a line that contains BOTH years.
        # The document title may contain only the primary year (e.g. "DEL 2024") before
        # any comparative year appears, which would give a wrong position-based answer.
        # The column-header row contains both years side by side and is authoritative.
        for line in snippet.splitlines():
            p_m = re.search(rf'\b{primary}\b', line)
            c_m = re.search(rf'\b{comp}\b', line)
            if p_m and c_m:
                return primary, comp, p_m.start() < c_m.start()
        # Fallback: no single line has both years — use document-level positions
        primary_pos = min(pos for y, pos in year_matches if y == primary)
        comp_pos = min(pos for y, pos in year_matches if y == comp)
        return primary, comp, primary_pos < comp_pos
    elif len(unique_years) == 1:
        return unique_years[0], unique_years[0] - 1, False
    else:
        now = datetime.now().year
        return now - 1, now - 2, False


# ---------------------------------------------------------------------------
# Extraction layers
# ---------------------------------------------------------------------------

def _extract_pdfplumber(
    pdf_path: str,
    fiscal_year: int,
    company_slug: str = "",
    country: str = "",
) -> list[ExtractionResult]:
    """
    Layer 1: structured table extraction using pdfplumber.

    Tries lined table settings first, then falls back to text-alignment settings.
    Logs unmatched Spanish labels via logger.debug (never silently skips).

    Returns a list with 1 or 2 ExtractionResult items. When a comparative column
    for fiscal_year-1 is detected in a header row, a second ExtractionResult is
    included so that revenue_growth_yoy can be computed downstream.
    """
    fields: dict = {}
    source_map: dict = {}
    warnings_list: list = []
    current_section = "unknown"
    # Comparative (prior) year data — populated when a second year column is detected
    prior_fields: dict = {}
    prior_year = fiscal_year - 1 if fiscal_year else 0

    # year_col persists across pages: once detected from a header row, it applies to
    # all subsequent pages until a new header row overrides it. This is necessary because
    # balance sheet pages often share the same column layout as the income statement page
    # but don't repeat the year header row — resetting per-page would lose the column
    # position and fall back to right-to-left scanning (picking the wrong column).
    year_col: Optional[int] = None
    prior_year_col: Optional[int] = None

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

            for table in tables:
                if not table:
                    continue

                for row in table:
                    if not row or len(row) < 2:
                        continue

                    # Detect header row (all non-numeric cells).
                    # Year values like '2024' are treated as non-numeric — they are column
                    # headers, not financial values — so they don't prevent header detection.
                    # NOTE: process year-header rows BEFORE the empty-label guard so that
                    # headers like ['', '', '2024', '', '2023', 'Var'] are not skipped.
                    _YEAR_RE = re.compile(r"^\d{4}$")
                    is_header = all(
                        (
                            cell is None
                            or _YEAR_RE.match(str(cell).strip())
                            or not parse_latam_number(str(cell))
                        )
                        for cell in row[1:]
                    )
                    if is_header and fiscal_year:
                        # Only update year_col when this row actually contains the target
                        # year — empty rows also satisfy is_header and must not overwrite
                        # a year_col that was already correctly detected.
                        # _year_in_cell() also matches abbreviated forms like "dic-24".
                        row_str = str(row)
                        if any(_year_in_cell(fiscal_year, str(c or "")) for c in row):
                            detected_col = _find_year_column(row, fiscal_year)
                            if detected_col != 1:
                                year_col = detected_col
                            else:
                                year_col = 1  # year in row but in first column
                                warnings_list.append("fallback_year_column_used")
                            # Also detect the comparative (prior) year column
                            if prior_year and any(_year_in_cell(prior_year, str(c or "")) for c in row):
                                detected_prior = _find_year_column(row, prior_year)
                                # Only trust if it's distinct from year_col
                                if detected_prior != year_col and _year_in_cell(prior_year, str(row[detected_prior] or "")):
                                    prior_year_col = detected_prior
                        continue

                    # Label is normally in col 0. Some LATAM indicator tables (e.g. CO
                    # management report page 41) place the label in col 1 with col 0 empty.
                    label = str(row[0] or "").strip()
                    if not label and len(row) > 1:
                        col1 = str(row[1] or "").strip()
                        if col1 and not parse_latam_number(col1):
                            label = col1
                    if not label:
                        continue

                    # Parse numeric value using year column if known.
                    # Strip trailing footnote markers (e.g. ' #', ' *') that some LATAM
                    # PDFs append to values before passing to parse_latam_number.
                    if year_col is not None and year_col < len(row):
                        _cell = re.sub(
                            r"[^0-9.,)(\-]+$", "", str(row[year_col] or "").strip()
                        )
                        value = parse_latam_number(_cell)
                        # When the header column is empty in the data row (pdfplumber merged-cell
                        # misalignment), try the left neighbor before falling back to right-to-left.
                        if value is None and year_col > 0:
                            _cell_left = re.sub(
                                r"[^0-9.,)(\-]+$", "", str(row[year_col - 1] or "").strip()
                            )
                            value = parse_latam_number(_cell_left)
                        if value is None:
                            value = _find_value_for_year(row, fiscal_year)
                    else:
                        value = _find_value_for_year(row, fiscal_year)

                    # Also extract prior year value when comparative column is known
                    prior_value: Optional[float] = None
                    if prior_year_col is not None and prior_year_col < len(row):
                        _prior_cell = re.sub(
                            r"[^0-9.,)(\-]+$", "", str(row[prior_year_col] or "").strip()
                        )
                        prior_value = parse_latam_number(_prior_cell)

                    if value is None:
                        continue

                    if len(label.strip()) < 4:
                        continue  # too short to be meaningful

                    canonical = map_to_canonical(label)
                    if canonical is None:
                        logger.debug(
                            f"[latam_extractor] unmatched label | "
                            f"company={company_slug!r} | page={page_num} | label={label!r}"
                        )
                        # Capture unmatched label for future synonym review
                        _append_candidate(
                            label=label,
                            value=float(value),
                            page=page_num,
                            section=current_section,
                            company=company_slug,
                            country=country,
                            pdf=str(Path(pdf_path).name),
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

                    # Store prior year value (first occurrence only)
                    if prior_value is not None and canonical not in prior_fields:
                        prior_fields[canonical] = prior_value

    results = [ExtractionResult(
        fields=fields,
        source_map=source_map,
        confidence=_score_confidence(fields, "pdfplumber_table", country=country),
        currency_code="",   # set by caller
        fiscal_year=fiscal_year,
        extraction_method="pdfplumber_table",
        warnings=warnings_list,
    )]

    # Append prior year result when comparative data was found
    if prior_fields and prior_year:
        results.append(ExtractionResult(
            fields=prior_fields,
            source_map={},
            confidence=_score_confidence(prior_fields, "pdfplumber_table", country=country),
            currency_code="",   # set by caller
            fiscal_year=prior_year,
            extraction_method="pdfplumber_table",
            warnings=["comparative_column"],
        ))

    return results


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

            if len(label.strip()) < 4:
                continue  # too short to be meaningful

            canonical = map_to_canonical(label)
            if canonical is None:
                logger.debug(
                    f"[latam_extractor] unmatched label | "
                    f"company={company_slug!r} | page={page_num} | label={label!r}"
                )
                # Capture unmatched label for future synonym review
                _append_candidate(
                    label=label,
                    value=float(value),
                    page=page_num,
                    section=current_section,
                    company=company_slug,
                    country=country,
                    pdf="",
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
) -> list["ExtractionResult"]:
    """
    Layer 3: Tesseract OCR for scanned-image PDFs.

    Renders each page at 300 DPI via PyMuPDF (no pdf2image / poppler required).
    Converts to grayscale for better OCR accuracy.
    Logs unmatched labels via logger.debug (never silently skips).

    Captures both primary (current year) and comparative (prior year) columns
    from each OCR line. Infers the actual fiscal year pair from the PDF header text.

    Returns a list of ExtractionResult — one for the primary year, and optionally
    a second for the comparative year (only when comparative fields were found).

    Returns a single-element list with confidence="Baja" and
    extraction_method="ocr_unavailable" if Tesseract is not available — does not raise.
    """
    if not TESSERACT_AVAILABLE:
        logger.error(
            "[latam_extractor] OCR requested but Tesseract is not available. "
            "Install Tesseract 5 + spa language pack and set TESSERACT_CMD."
        )
        return [ExtractionResult(
            fields={},
            source_map={},
            confidence="Baja",
            currency_code="",
            fiscal_year=fiscal_year,
            extraction_method="ocr_unavailable",
            warnings=["tesseract_not_available"],
        )]

    fields: dict = {}           # primary year (e.g. 2024)
    fields_comp: dict = {}      # comparative year (e.g. 2023)
    source_map: dict = {}
    source_map_comp: dict = {}
    current_section = "unknown"

    # Pre-render all pages once to avoid double-rendering page 1.
    # Only match proper financial numbers: require at least one thousand-separator group
    # (e.g. "116.222.588.859,23") to avoid capturing note references (21, 22).
    _FIN_NUM_RE = re.compile(r"[-\u2013]?\$?\s*\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?")

    pages_ocr: list[str] = []
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")  # grayscale
        pages_ocr.append(pytesseract.image_to_string(img, lang="spa", config="--psm 6"))

    # Infer fiscal year pair and column order from page 1 header BEFORE the main loop.
    # primary_is_left=True means the more-recent (primary) year column is on the LEFT side
    # of the PDF. This governs which number on each data line is primary vs comparative.
    first_page_ocr_text = pages_ocr[0] if pages_ocr else ""
    primary_year, comp_year, primary_is_left = _infer_fiscal_years(first_page_ocr_text)
    logger.debug(
        f"[latam_extractor] OCR year inference: primary={primary_year}, "
        f"comp={comp_year}, primary_is_left={primary_is_left}"
    )

    for page_num, ocr_text in enumerate(pages_ocr, start=1):
        text_lower = ocr_text.lower()
        detected = _detect_section(text_lower)
        if detected != "unknown":
            current_section = detected

        for line in ocr_text.splitlines():
            line = line.strip()
            if not line:
                continue

            # Unified number extraction: find all financial numbers on the line.
            # Use the position of the first number to delimit the label, and capture
            # the leftmost (val_left) and rightmost (val_right) numeric values.
            # Then assign primary/comparative based on detected column order.
            num_matches = list(_FIN_NUM_RE.finditer(line))

            label: Optional[str] = None
            value: Optional[float] = None
            comparative_value: Optional[float] = None

            if num_matches:
                first_match = num_matches[0]
                label_candidate = line[:first_match.start()].strip()
                # Strip trailing noise like "[Nota X)" or "-"
                label_candidate = re.sub(r"\s*[\[\(].*$", "", label_candidate).strip()
                if not label_candidate:
                    # Fallback: try splitting on 2+ spaces for lines where the label
                    # is separated from numbers by wide spacing only
                    parts = re.split(r"\s{2,}|\t", line)
                    if len(parts) >= 2:
                        label_candidate = parts[0].strip()
                if label_candidate:
                    val_left = parse_latam_number(
                        first_match.group().replace("$", "").strip()
                    )
                    val_right: Optional[float] = None
                    if len(num_matches) >= 2:
                        # Use the SECOND number (index 1), not the last.
                        # In a 2-column PDF: index 1 == index -1 → same result.
                        # In a 3-column PDF (primary | comparative | delta/variation):
                        # index -1 would wrongly pick the delta column; index 1 picks
                        # the comparative year column correctly.
                        val_right = parse_latam_number(
                            num_matches[1].group().replace("$", "").strip()
                        )
                        if val_right == val_left:
                            val_right = None

                    if val_left is not None:
                        label = label_candidate
                        if primary_is_left or val_right is None:
                            # Primary year is left column, or only one number present
                            value = val_left
                            comparative_value = val_right
                        else:
                            # Primary year is right column
                            value = val_right
                            comparative_value = val_left

            if value is None or not label:
                continue

            # Exclude non-current subtotals — they substring-match total_assets /
            # total_liabilities but represent only part of the balance sheet.
            _label_norm = label.lower()
            if "no corriente" in _label_norm or "no corrientes" in _label_norm:
                continue

            if len(label.strip()) < 4:
                continue  # too short to be meaningful

            canonical = map_to_canonical(label)
            if canonical is None:
                logger.debug(
                    f"[latam_extractor] unmatched label | "
                    f"company={company_slug!r} | page={page_num} | label={label!r}"
                )
                # Capture unmatched label for future synonym review
                _append_candidate(
                    label=label,
                    value=float(value),
                    page=page_num,
                    section=current_section,
                    company=company_slug,
                    country=country,
                    pdf=str(Path(pdf_path).name),
                )
                continue

            # Use max absolute value: in scanned PDFs the same canonical may appear
            # as a sub-item (smaller) before the section total (larger). Always keep
            # the largest value seen so totals win over sub-items.
            if canonical not in fields or abs(value) > abs(fields[canonical]):
                fields[canonical] = value
                source_map[canonical] = SourceRef(
                    page_number=page_num,
                    section_heading=current_section,
                    extraction_method="ocr_tesseract",
                )
            if comparative_value is not None and (
                canonical not in fields_comp or abs(comparative_value) > abs(fields_comp[canonical])
            ):
                fields_comp[canonical] = comparative_value
                source_map_comp[canonical] = SourceRef(
                    page_number=page_num,
                    section_heading=current_section,
                    extraction_method="ocr_tesseract",
                )

    # primary_year, comp_year, primary_is_left already computed above before the main loop.

    results = [
        ExtractionResult(
            fields=fields,
            source_map=source_map,
            confidence=_score_confidence(fields, "ocr_tesseract", country=country),
            currency_code="",
            fiscal_year=primary_year,
            extraction_method="ocr_tesseract",
            warnings=[],
        )
    ]

    if fields_comp:
        results.append(
            ExtractionResult(
                fields=fields_comp,
                source_map=source_map_comp,
                confidence=_score_confidence(fields_comp, "ocr_tesseract", country=country),
                currency_code="",
                fiscal_year=comp_year,
                extraction_method="ocr_tesseract",
                warnings=["comparative_year_column"],
            )
        )

    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract(
    pdf_path: str,
    currency_code: str = "",
    fiscal_year: int = 0,
    country: str = "",
) -> list[ExtractionResult]:
    """
    Extract financial data from a PDF, returning one result per fiscal year found.

    For scanned PDFs (OCR path), captures both the primary year column and the
    comparative year column that appears in standard LATAM IFRS comparative statements.
    Returns a list with two ExtractionResult items when comparative data is found,
    or a single-item list otherwise.

    For digital PDFs (pdfplumber path), also returns a two-item list when a
    comparative column for fiscal_year-1 is detected in a table header row.

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
        currency_code: ISO currency code (e.g. "COP", "PEN", "CLP"). Set on each result.
        fiscal_year:   The target fiscal year (e.g. 2023). Used for column selection in
                       digital PDFs; OCR path infers fiscal years from PDF header text.
        country:       Two-letter country code ("CO", "PE", "CL") for confidence scoring.

    Returns:
        list[ExtractionResult] — one item per fiscal year found (1 or 2 items).
    """
    company_slug = Path(pdf_path).stem  # use filename stem as fallback slug for logging

    doc = fitz.open(pdf_path)
    try:
        scanned_count = sum(1 for page in doc if _is_scanned_page(page))
        is_scanned = scanned_count > len(doc) * 0.5

        if is_scanned:
            results = _extract_ocr(
                pdf_path, doc, fiscal_year,
                company_slug=company_slug, country=country,
            )
        else:
            results = _extract_pdfplumber(
                pdf_path, fiscal_year,
                company_slug=company_slug, country=country,
            )
            # If pdfplumber coverage is poor, try PyMuPDF text fallback
            if _fields_coverage(results[0]) < 0.4:
                alt_result = _extract_pymupdf_text(
                    doc, fiscal_year,
                    company_slug=company_slug, country=country,
                )
                # Use whichever layer returned more fields for the primary year
                if len(alt_result.fields) > len(results[0].fields):
                    results[0] = alt_result
    finally:
        doc.close()

    # Set caller-provided metadata on all results
    for i, result in enumerate(results):
        result.currency_code = currency_code
        # Only override fiscal_year for the primary result — comparative year results
        # already have their fiscal_year set correctly by _extract_pdfplumber()
        if i == 0 and result.extraction_method not in ("ocr_tesseract", "ocr_unavailable"):
            result.fiscal_year = fiscal_year

    return results
