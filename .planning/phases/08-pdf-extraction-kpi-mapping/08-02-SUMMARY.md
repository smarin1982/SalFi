---
phase: 08-pdf-extraction-kpi-mapping
plan: 02
subsystem: pdf-extraction
tags: [latam, parquet, kpi-mapping, currency-conversion, pdfplumber, pandas]

# Dependency graph
requires:
  - phase: 08-01
    provides: latam_extractor.py (ExtractionResult, SourceRef), latam_concept_map.py (LATAM_CONCEPT_MAP, map_to_canonical)
  - phase: 06-foundation
    provides: currency.py (to_usd, get_annual_avg_rate), latam data directory schema
  - phase: 02-processor
    provides: processor.py (calculate_kpis, save_parquet)

provides:
  - latam_processor.py: process() entry point, DataFrame construction, USD conversion, calculate_kpis() + save_parquet() reuse
  - FINANCIALS_COLUMNS: 24-column canonical schema matching data/clean/AAPL/financials.parquet

affects:
  - 09-validation (orchestrator calls latam_processor.process() after human gate)
  - 10-report (kpis.parquet feeds confidence badge and KPI dashboard)
  - 11-dashboard (reads kpis.parquet identically to US pipeline)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Import calculate_kpis and save_parquet from processor.py without modification (KPI-01 constraint)
    - USD conversion applied per-field before Parquet write (all 22 monetary columns)
    - Prior-year concat + drop_duplicates(keep='last') for growth KPI continuity
    - Re-enforce float64 dtypes after concat to prevent nullable integer pollution
    - Idempotency via drop_duplicates on fiscal_year before every write

key-files:
  created:
    - latam_processor.py
  modified: []

key-decisions:
  - "latam_processor imports calculate_kpis and save_parquet from processor.py unchanged — the processor.py hash must remain identical to guarantee KPI calculation parity between US and LATAM pipelines"
  - "USD conversion iterates all 22 monetary fields (not just revenue) — LATAM PDFs express all values in native currency; partial conversion would make KPI ratios meaningless"
  - "Prior-year append uses drop_duplicates(keep='last') so re-running with updated data replaces the old row rather than creating duplicates — ensures idempotency with multi-year accumulation"
  - "ticker column contains company_slug (not a stock exchange ticker) — LATAM companies are identified by slug throughout the pipeline"

patterns-established:
  - "Pattern: Re-enforce float64 dtypes after pd.concat() to prevent Pandas nullable integer (Int64) pollution when concatenating DataFrames with NaN columns"
  - "Pattern: np.isnan check + isinstance guard for detecting NaN in extracted fields dict before calling to_usd()"

requirements-completed: [KPI-01]

# Metrics
duration: 2min
completed: 2026-03-06
---

# Phase 08 Plan 02: KPI Mapping and LATAM Processor Summary

**latam_processor.process() — 24-column USD-normalized Parquet writer that reuses processor.py's calculate_kpis() and save_parquet() unchanged, with prior-year concat for growth KPI continuity**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-06T14:04:34Z
- **Completed:** 2026-03-06T14:06:22Z
- **Tasks:** 1 auto (complete) + 1 checkpoint (awaiting human verification)
- **Files modified:** 1

## Accomplishments

- `latam_processor.py`: process() function that maps ExtractionResult fields to 24-column canonical schema, converts all 22 monetary fields from native LATAM currency to USD, appends prior-year rows for growth KPI continuity, and calls calculate_kpis() + save_parquet() directly from processor.py without any modification
- FINANCIALS_COLUMNS constant matches data/clean/AAPL/financials.parquet column list and dtypes exactly (ticker=object, fiscal_year=int64, all monetary=float64)
- Idempotent: second run on same ExtractionResult produces identical row count (drop_duplicates on fiscal_year)
- All automated verification checks passed: schema match, dtype enforcement, COP-to-USD conversion (5B COP → ~1.32M USD), idempotency, processor.py hash unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: latam_processor.py — KPI mapping layer** - `a15cfd5` (feat)
2. **Task 2: Human verification** - PENDING (checkpoint:human-verify)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `latam_processor.py` — process(company_slug, extraction_result, country, data_dir), FINANCIALS_COLUMNS (24 columns), _MONETARY_COLUMNS (22 monetary columns); imports calculate_kpis and save_parquet from processor.py

## Decisions Made

- **Import without modification constraint:** calculate_kpis() and save_parquet() are imported directly from processor.py (KPI-01 requirement). A source comment is included in latam_processor.py as documentation of this constraint.
- **All 22 monetary fields converted:** The plan spec says "every non-NaN monetary field". The implementation iterates `_MONETARY_COLUMNS = FINANCIALS_COLUMNS[2:]` which covers all 22 fields uniformly, not just revenue.
- **Prior-year concat idempotency:** `drop_duplicates(subset=["fiscal_year"], keep="last")` ensures the latest ExtractionResult wins on re-run, which is the correct behavior when data is refined and re-processed.
- **dtype re-enforcement after concat:** After `pd.concat([df_existing, df_new])`, all float columns are explicitly cast back to float64. This prevents Pandas from silently upgrading to nullable Int64 when NaN values appear across rows.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — this plan adds a pure Python module with no external service dependencies. The pre-existing Tesseract absence (OCR path) is documented in STATE.md and handled gracefully.

## Checkpoint Status

**Task 2 is a `checkpoint:human-verify` gate.** Execution is paused here. The user must:

1. Download a real LATAM annual financial PDF from Supersalud (Colombia), SMV (Peru), or CMF (Chile)
2. Save to `data/latam/test/test-company/raw/informe.pdf`
3. Run the extraction script from the plan checkpoint instructions
4. Verify: confidence is Alta or Media, field values are plausible, revenue matches order of magnitude from the PDF
5. Reply "approved" to unblock Plan 03

## Next Phase Readiness

- `latam_processor.process()` is the complete KPI-mapping entry point for Phase 9 orchestrator
- Parquet schema is schema-identical to US pipeline — Phase 11 dashboard can read LATAM output with zero code changes
- ExtractionResult → financials.parquet + kpis.parquet chain is fully implemented and verified with synthetic data
- Human verification against a real LATAM PDF is pending (Task 2 checkpoint)

---
*Phase: 08-pdf-extraction-kpi-mapping*
*Completed: 2026-03-06*
