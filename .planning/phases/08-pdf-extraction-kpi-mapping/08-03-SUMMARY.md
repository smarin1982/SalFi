---
phase: 08-pdf-extraction-kpi-mapping
plan: 03
subsystem: ui
tags: [latam, streamlit, confidence-badge, pdf-download, kpi-display]

# Dependency graph
requires:
  - phase: 08-01
    provides: latam_concept_map.py (COUNTRY_CRITICAL_FIELDS, DEFAULT_CRITICAL_FIELDS), latam_extractor.py (ExtractionResult.confidence)
  - phase: 08-02
    provides: latam_processor.py (writes kpis.parquet with confidence column)
  - phase: 07-latam-scraper
    provides: render_latam_upload_section() in app.py (integration point)

provides:
  - _latam_confidence_badge(): Streamlit helper that reads kpis.parquet and displays warning badge when confidence==Baja or critical fields are missing
  - PDF download button in app.py: analyst access to raw PDF for manual verification when confidence is Baja

affects:
  - 09-validation (orchestrator calls latam_processor after gate; badge will show post-processing)
  - 10-report (confidence score already surfaced in dashboard; badge closes the loop for analysts)
  - 11-dashboard (reads kpis.parquet identically; badge is isolated to LATAM section)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Lazy LATAM imports inside function body (try/except ImportError) — import failure does not reach S&P 500 section
    - st.download_button keyed with latam_pdf_download_{slug}_{country} — avoids DuplicateWidgetID across re-renders
    - PDF discovery via raw_dir.glob("*.pdf") sorted — deterministic first-PDF selection without hardcoded filename
    - Graceful degradation: kpis.parquet missing → return; confidence column absent → confidence=None; OSError on PDF read → silent skip

key-files:
  created: []
  modified:
    - app.py

key-decisions:
  - "PDF download button placed inside _latam_confidence_badge() — no new function needed, consistent with plan constraint"
  - "PDF discovery uses raw_dir = data/latam/{country}/{slug}/raw/ glob('*.pdf') sorted() — mirrors latam_scraper.py storage convention"
  - "download_button key scoped as latam_pdf_download_{slug}_{country} — safe for multiple companies across reruns"
  - "Positive confidence branch shows st.info (not st.success) to remain visually subtle when extraction is clean"

patterns-established:
  - "Pattern: _latam_confidence_badge() degrades in four layers: ImportError -> return silently; kpis.parquet missing -> return; exception -> st.caption with error; PDF OSError -> pass"
  - "Pattern: session-state guard for second call site (st.session_state.get checks) prevents KeyError on cold load"

requirements-completed: [PDF-03]

# Metrics
duration: ~4min
completed: 2026-03-06
---

# Phase 08 Plan 03: Confidence Badge Checker Summary

**st.warning badge + st.download_button PDF access in app.py when ExtractionResult confidence is Baja or country-specific critical fields are absent from kpis.parquet**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-06T15:00:03Z
- **Completed:** 2026-03-06T15:03:47Z
- **Tasks:** 1 (auto)
- **Files modified:** 1

## Accomplishments

- `_latam_confidence_badge(company_slug, country, data_dir)` added to app.py — reads kpis.parquet, checks confidence column and COUNTRY_CRITICAL_FIELDS, renders warning badge or clean info indicator
- When confidence is "Baja": a `st.download_button` ("Ver PDF original") appears below the warning, letting the analyst download the raw PDF from `data/latam/{country}/{slug}/raw/` for manual cross-check
- Two call sites in `render_latam_upload_section()`: immediately after successful upload (re-upload scenario), and on section re-entry via session state (analyst returning to previously uploaded company)
- All LATAM imports remain lazy (inside `try/except ImportError`) — S&P 500 section entirely unaffected

## Task Commits

Each task was committed atomically:

1. **Task 1: _latam_confidence_badge() helper + render_latam_upload_section() integration** - `3851179` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `app.py` — `_latam_confidence_badge()` function (lines 553-631), two call sites inside `render_latam_upload_section()` (lines 691 and 703)

## Decisions Made

- **PDF download button inside badge function:** The user confirmed "cuando la confiabilidad sea baja, demos acceso al PDF". The simplest implementation that satisfies the requirement is a `st.download_button` inside `_latam_confidence_badge()`, keyed by slug+country. No new function needed.
- **PDF discovery via glob:** `raw_dir.glob("*.pdf")` finds the first PDF in the raw directory. This mirrors how `latam_scraper.handle_upload()` saves files — the PDF will always be the uploaded file. `sorted()` ensures deterministic selection if multiple files exist.
- **OSError silently skipped:** If the PDF file disappears between upload and badge render (e.g., manual deletion), the download button is silently omitted. The warning badge still shows — the analyst sees the data quality warning even if the PDF is gone.
- **Second call site placement:** The session-state guard (`if st.session_state.get("latam_company_slug") and ...`) is placed at the bottom of the `with st.expander(...)` block so it runs on every expander open, regardless of whether a new PDF was uploaded in this session.

## Deviations from Plan

### Auto-added Enhancement

**1. [Rule 2 - Missing Critical] Added PDF download button for Baja confidence**

- **Found during:** Task 1 — user provided explicit additional requirement before execution
- **Issue:** Plan defined the badge but the user's confirmed UX requirement adds PDF access when confidence is Baja
- **Fix:** Added `st.download_button` inside the `if confidence == "Baja":` branch; discovers PDF via `raw_dir.glob("*.pdf")` sorted; uses OSError guard for missing file
- **Files modified:** app.py
- **Verification:** Automated checks pass (syntax valid, badge text present, lazy imports, two call sites confirmed); button key uses `latam_` prefix per architecture decision
- **Committed in:** `3851179` (Task 1 commit)

---

**Total deviations:** 1 enhancement (user-confirmed requirement added pre-execution)
**Impact on plan:** Extends badge function with PDF access as explicitly requested by user. No scope creep beyond stated requirement.

## Issues Encountered

- Plan's automated verification script slices only 2000 chars of `render_latam_upload_section()` to check for badge call sites. The function body is ~3270 chars — both call sites exist beyond the 2000-char slice. Extended verification with full-body search confirmed both call sites are present.

## User Setup Required

None — no external service configuration required. PDF download uses local file system only.

## Next Phase Readiness

- Phase 08 is now fully complete: latam_concept_map.py (08-01) + latam_extractor.py (08-01) + latam_processor.py (08-02) + confidence badge in app.py (08-03)
- Phase 09 orchestrator can call `latam_processor.process()` after human gate; the badge will automatically surface in the dashboard on next section load
- PDF-03 requirement satisfied: confidence score is visible to the analyst as a warning badge with direct PDF access for verification
- Remaining blocker (unchanged): Tesseract 5 absent on Windows — OCR path disabled; digital PDFs work without it

---
*Phase: 08-pdf-extraction-kpi-mapping*
*Completed: 2026-03-06*
