---
phase: 12-learned-synonyms
plan: "04"
subsystem: pdf-extraction
tags: [ocr, tesseract, multi-year, parquet, latam, ifrs, comparative-statements]

# Dependency graph
requires:
  - phase: 08-pdf-extraction-kpi-mapping
    provides: latam_extractor.py ExtractionResult, latam_processor.py process()
  - phase: 09-orchestration-red-flags
    provides: LatamAgent.run() pipeline orchestrator
provides:
  - _infer_fiscal_years() helper in latam_extractor.py
  - Two-column OCR capture (primary + comparative year) in _extract_ocr()
  - extract() returns list[ExtractionResult] (1 or 2 items per PDF)
  - latam_processor.process() accepts list[ExtractionResult] with backwards compat
  - LatamAgent.run() passes full extraction list to process()
affects: [latam-validation, app-dashboard, report-generator]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - _infer_fiscal_years scans first 500 chars of OCR text for year-pair via regex \b(20[12]\d)\b
    - _extract_ocr tracks fields + fields_comp dicts simultaneously per page
    - extract() returns list[ExtractionResult] uniformly; digital PDF path wraps single result in list
    - _build_row() extracted from process() for per-result row construction
    - process() normalises single ExtractionResult to list for backwards compatibility

key-files:
  created: []
  modified:
    - latam_extractor.py
    - latam_processor.py
    - LatamAgent.py

key-decisions:
  - "_infer_fiscal_years uses re.findall(\\b(20[12]\\d)\\b) on first 500 chars — two distinct years = (primary, comparative); one year = (year, year-1); none = (now-1, now-2)"
  - "OCR layer captures comparative value only when second distinct financial number exists on same line — no comparative value when line has only one column"
  - "extract() return type changed to list[ExtractionResult] — all callers must handle list; digital PDF path returns single-element list for uniform interface"
  - "process() accepts Union[ExtractionResult, list[ExtractionResult]] — single-result path is backwards-compat shim for validation panel and existing test code"
  - "LatamAgent keeps extraction_result = extraction_results[0] alias for _build_meta which reads .extraction_method and .confidence from a single ExtractionResult"

patterns-established:
  - "Multi-year extraction: _extract_ocr returns list; extract() always returns list; callers iterate results"
  - "Backwards compat: process() isinstance check normalises old single-result callers without breaking them"

requirements-completed: [MULTI-01, MULTI-02, MULTI-03]

# Metrics
duration: 26min
completed: 2026-03-11
---

# Phase 12 Plan 04: Multi-Year Extraction from Comparative PDFs Summary

**OCR extractor now captures both current-year and prior-year columns from comparative IFRS statements, returning two ExtractionResult objects and writing two rows to financials.parquet from a single PDF upload.**

## Performance

- **Duration:** 26 min
- **Started:** 2026-03-11T10:09:58Z
- **Completed:** 2026-03-11T10:35:34Z
- **Tasks:** 3 (MULTI-01, MULTI-02, MULTI-03)
- **Files modified:** 3

## Accomplishments

- Added `_infer_fiscal_years()` that detects the actual fiscal year pair from PDF header OCR text instead of hard-coding `now.year - 1`
- Updated `_extract_ocr()` to track two field dicts simultaneously (`fields` + `fields_comp`) and return `list[ExtractionResult]` with 1 or 2 items
- Changed `extract()` return type to `list[ExtractionResult]` uniformly; digital PDF path wraps existing single result
- Refactored `latam_processor.process()` to accept `list[ExtractionResult]`, building one Parquet row per result in a single write; backwards-compatible with single ExtractionResult
- Updated `LatamAgent.run()` to pass the full extraction list to `process()` and retain a `extraction_result[0]` alias for `_build_meta`

## Task Commits

All three tasks committed together as a single atomic commit (all changes in the same three files):

1. **MULTI-01: _infer_fiscal_years() helper** - `93f8c83` (feat)
2. **MULTI-02: two-column OCR capture, list return** - `93f8c83` (feat)
3. **MULTI-03: processor + agent multi-year support** - `93f8c83` (feat)

## Files Created/Modified

- `latam_extractor.py` - Added `_infer_fiscal_years()`; updated `_extract_ocr()` for dual-column capture and `list[ExtractionResult]` return; updated `extract()` return type and docstring
- `latam_processor.py` - Extracted `_build_row()` helper; updated `process()` to accept `Union[ExtractionResult, list[ExtractionResult]]`; updated module docstring
- `LatamAgent.py` - Updated Step 2 to use `extraction_results` list; passes list to `process()`; retains `extraction_result[0]` alias for `_build_meta`

## Decisions Made

- `_infer_fiscal_years` scans only the first 500 characters of OCR text — the fiscal year pair always appears in the document header/title section; scanning the full text would create false positives from body-text years.
- Comparative-column detection is OCR-only for now. Digital PDFs (pdfplumber/PyMuPDF) return a single-item list. Adding comparative detection to the table/text layers is future work.
- `process()` normalises a single `ExtractionResult` to a list via `isinstance` check — this preserves all existing callers (validation panel, tests) without modification.
- `LatamAgent._build_meta()` receives `extraction_result` (singular, from `extraction_results[0]`) because `_build_meta` only needs `confidence` and `extraction_method` from the primary year result.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Multi-year extraction fully wired into the pipeline; re-extracting any comparative LATAM PDF will produce two rows in `financials.parquet`
- YoY KPI calculations (`revenue_growth_yoy`, etc.) will now populate from single-upload data
- Verification script in the plan (`assert len(results) == 2`) is ready to run once Tesseract is installed (currently `TESSERACT_AVAILABLE=False`)

---
*Phase: 12-learned-synonyms*
*Completed: 2026-03-11*
