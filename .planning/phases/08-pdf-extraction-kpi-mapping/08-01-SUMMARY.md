---
phase: 08-pdf-extraction-kpi-mapping
plan: 01
subsystem: pdf-extraction
tags: [pdfplumber, pymupdf, pytesseract, ocr, spanish-nlp, latam, concept-map]

# Dependency graph
requires:
  - phase: 06-foundation
    provides: currency.py, company_registry.py, latam data directory schema
  - phase: 07-latam-scraper
    provides: downloaded PDF files in data/latam/{country}/{slug}/raw/

provides:
  - latam_concept_map.py: LATAM_CONCEPT_MAP (22 fields), map_to_canonical(), parse_latam_number(), validate_tesseract(), TESSERACT_AVAILABLE, COUNTRY_CRITICAL_FIELDS, DEFAULT_CRITICAL_FIELDS
  - latam_extractor.py: extract(), ExtractionResult, SourceRef — three-layer PDF extraction cascade

affects:
  - 08-02 (latam_processor.py imports ExtractionResult from latam_extractor)
  - 09-validation (ExtractionResult.confidence and source_map surfaced in UI)
  - 10-report (ExtractionResult feeds confidence badge and field traceability)

# Tech tracking
tech-stack:
  added:
    - pdfplumber==0.11.9 (table extraction from digital PDFs)
    - PyMuPDF==1.27.1 / fitz (scanned-page triage + pixmap rendering)
    - pytesseract==0.3.13 (OCR wrapper for Tesseract 5 binary)
    - Pillow>=10.0 (PIL image preprocessing for OCR pipeline)
  patterns:
    - Three-layer PDF cascade: pdfplumber_table -> pymupdf_text -> ocr_tesseract
    - Scanned-page triage before OCR (TEXT_CHARS_THRESHOLD=50 chars)
    - Longest-synonym-first matching to prevent substring false positives
    - TESSERACT_AVAILABLE flag set at import time (fail-safe, no crash)
    - All unmatched labels logged via logger.debug (never silently skipped)

key-files:
  created:
    - latam_concept_map.py
    - latam_extractor.py
  modified: []

key-decisions:
  - "map_to_canonical iterates synonyms longest-first to prevent short synonyms (e.g. 'efectivo') from incorrectly matching labels that contain them as substrings (e.g. 'flujo de efectivo de operaciones')"
  - "label_in_synonym direction only applies when len(label) >= len(synonym) — prevents short input from false-matching a longer synonym"
  - "_score_confidence() uses COUNTRY_CRITICAL_FIELDS.get(country, DEFAULT_CRITICAL_FIELDS) — country-specific regulator requirements per CO/PE/CL"
  - "extract() never writes files — ExtractionResult is in-memory only; file writing deferred to latam_processor.py after human validation gate"
  - "TESSERACT_CMD read from TESSERACT_CMD env var with Windows default fallback — conda PATH isolation workaround"
  - "pytesseract and pdfplumber/PyMuPDF installed during Task 1 execution (Rule 3 — missing dependency for verification)"

patterns-established:
  - "Pattern: Synonym longest-first iteration for accent-insensitive Spanish label matching"
  - "Pattern: Module-level TESSERACT_AVAILABLE flag checked before any OCR call"
  - "Pattern: ExtractionResult is single-year; caller calls extract() once per year (aligned with latam_processor concat)"

requirements-completed: [PDF-01, PDF-02, PDF-03, PDF-04, KPI-03]

# Metrics
duration: 6min
completed: 2026-03-06
---

# Phase 08 Plan 01: PDF Extraction and Concept Map Summary

**22-field Spanish healthcare concept map + three-layer PDF extraction cascade (pdfplumber / PyMuPDF text / pytesseract OCR) with country-aware confidence scoring and per-field SourceRef traceability**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-06T13:54:05Z
- **Completed:** 2026-03-06T14:00:31Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `latam_concept_map.py`: 22-field LATAM_CONCEPT_MAP with 13 revenue synonyms satisfying KPI-03; accent-insensitive map_to_canonical() with longest-first ordering; LATAM number format parser; Tesseract validator; COUNTRY_CRITICAL_FIELDS for CO/PE/CL
- `latam_extractor.py`: Full three-layer extraction cascade with scanned-page triage; ExtractionResult and SourceRef dataclasses; _score_confidence() with country-specific critical field sets; all three paths log unmatched labels; extract() never writes files
- Installed required packages: PyMuPDF==1.27.1, pdfplumber==0.11.9, pytesseract==0.3.13, Pillow (Rule 3 — missing dependencies for verification)

## Task Commits

Each task was committed atomically:

1. **Task 1: latam_concept_map.py** - `1734142` (feat)
2. **Task 2: latam_extractor.py** - `2b64440` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `latam_concept_map.py` — LATAM_CONCEPT_MAP (22 fields, 13 revenue synonyms), COUNTRY_CRITICAL_FIELDS (CO/PE/CL), DEFAULT_CRITICAL_FIELDS, map_to_canonical(), parse_latam_number(), validate_tesseract(), TESSERACT_AVAILABLE
- `latam_extractor.py` — extract(), ExtractionResult, SourceRef; pdfplumber/pymupdf_text/ocr_tesseract layers; _score_confidence(country=); _is_scanned_page(); _find_year_column(); _find_value_for_year()

## Decisions Made

- **Synonym matching direction fix:** The plan spec uses bidirectional substring matching (`synonym in label OR label in synonym`). This caused `'total activos'` to match `current_assets` (via synonym `'total activos corrientes'` containing the input). Fix: sort candidates by synonym length descending (longer = more specific first), AND restrict the `label in synonym` direction to only trigger when `len(label) >= len(synonym)`. This eliminates short-input false positives.
- **Country-aware confidence:** `_score_confidence()` uses `COUNTRY_CRITICAL_FIELDS.get(country, DEFAULT_CRITICAL_FIELDS)` so CO/PE/CL each have regulator-specific critical field requirements. Country is passed through from `extract()` all the way to each internal layer.
- **Tesseract not installed:** Tesseract 5 binary is not installed on this Windows machine (known blocker from STATE.md). `TESSERACT_AVAILABLE = False` at import time; OCR path returns `ExtractionResult(confidence="Baja", extraction_method="ocr_unavailable")` gracefully.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing Python packages (pytesseract, pdfplumber, PyMuPDF, Pillow)**
- **Found during:** Task 1 verification
- **Issue:** `import pytesseract` failed with `No module named 'pytesseract'`; same for pdfplumber and fitz
- **Fix:** `pip install pytesseract pdfplumber PyMuPDF Pillow`
- **Files modified:** requirements handled by pip (not tracked in repo requirements.txt)
- **Verification:** All imports succeed; verification scripts pass
- **Committed in:** Part of Task 1 workflow (not a separate commit — env setup)

**2. [Rule 1 - Bug] Fixed bidirectional substring matching causing wrong field mapping**
- **Found during:** Task 1 verification (`map_to_canonical('Total Activos')` returned `current_assets`)
- **Issue:** When checking `label in synonym`, the short input `'total activos'` matched the longer synonym `'total activos corrientes'` (a `current_assets` synonym) when candidates were sorted longest-first
- **Fix:** Added guard: `label_in_synonym` only True when `len(normalized_plain) >= len(synonym_plain)`. This preserves the plan's bidirectional intent while preventing short-input false positives.
- **Files modified:** `latam_concept_map.py`
- **Verification:** `map_to_canonical('Total Activos') == 'total_assets'` passes; `map_to_canonical('Flujo de efectivo de operaciones') == 'operating_cash_flow'` passes
- **Committed in:** 1734142 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 missing dependency, 1 bug in matching logic)
**Impact on plan:** Both essential for correctness. The matching fix ensures Spanish labels map to the correct canonical fields — without it the concept map would produce incorrect financial data.

## Issues Encountered

- Tesseract 5 binary not installed on this machine. `TESSERACT_AVAILABLE = False`. OCR path is implemented and gracefully handles absence — returns `ocr_unavailable` result instead of crashing. This is a pre-existing blocker documented in STATE.md.

## User Setup Required

To enable OCR for scanned PDFs, Tesseract 5 must be installed:
1. Download from https://github.com/UB-Mannheim/tesseract/releases (Windows installer)
2. Install `spa.traineddata` language pack to `C:\Program Files\Tesseract-OCR\tessdata\`
3. Optionally set `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` in `.env`
4. Verify: `python -c "from latam_concept_map import TESSERACT_AVAILABLE; print(TESSERACT_AVAILABLE)"`

## Next Phase Readiness

- `latam_extractor.extract()` is the entry point for Phase 8 Plan 02 (`latam_processor.py`)
- `latam_concept_map.LATAM_CONCEPT_MAP` and `map_to_canonical()` are ready for use by any processor or validator
- ExtractionResult schema is stable: fields, source_map, confidence, currency_code, fiscal_year, extraction_method, warnings
- Tesseract absent is handled gracefully — digital PDF path (pdfplumber/pymupdf) is fully functional

---
*Phase: 08-pdf-extraction-kpi-mapping*
*Completed: 2026-03-06*
