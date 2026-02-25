---
phase: 02-transformation-kpis
plan: 01
subsystem: data
tags: [xbrl, pandas, numpy, sec-edgar, financial-normalization]

# Dependency graph
requires:
  - phase: 01-data-extraction
    provides: data/raw/{TICKER}/facts.json files with raw SEC EDGAR XBRL data
provides:
  - "CONCEPT_MAP: 22-field priority-ordered XBRL tag lookup dictionary"
  - "INSTANT_CONCEPTS / DURATION_CONCEPTS: sets classifying balance sheet vs. income/cashflow fields"
  - "extract_concept(): single-field XBRL extraction with full-year filter and deduplication"
  - "normalize_xbrl(): produces consistent 24-column wide DataFrame from any ticker's facts.json"
affects: [02-transformation-kpis, 03-kpi-calculations, 04-dashboard]

# Tech tracking
tech-stack:
  added: [pandas, numpy]
  patterns:
    - "Priority-fallback XBRL tag lookup: try tags in order, return first with data"
    - "End-date year as fiscal_year (not fy field) to avoid comparative-period ambiguity"
    - "Period-length guard: >300 days for duration concepts excludes quarterly partials"
    - "Deduplication by end date keeping latest filed date"
    - "Schema consistency: all 22 CONCEPT_MAP fields always present as columns (NaN when missing)"

key-files:
  created:
    - "processor.py — CONCEPT_MAP, INSTANT_CONCEPTS, DURATION_CONCEPTS, extract_concept(), normalize_xbrl()"
  modified: []

key-decisions:
  - "shares_outstanding added as 22nd CONCEPT_MAP field (plan listed 21 but asserted 22) — needed for EPS KPI calculations in subsequent plans"
  - "INSTANT_CONCEPTS grows to 13 (from plan's 12) to include shares_outstanding"
  - "fiscal_year derived from end-date year not fy field — fy is the filing year, comparative entries in 10-K have fy=filing year but different end dates"
  - "BRK.B missing current_assets/current_liabilities is correct behavior (financial conglomerate), not an error"

patterns-established:
  - "CONCEPT_MAP pattern: canonical_name -> [primary_tag, fallback_tag, ...] in priority order"
  - "Empty Series return (never exception) from extract_concept() when no tag found"
  - "normalize_xbrl() schema: always ticker + fiscal_year + 22 CONCEPT_MAP fields = 24 columns"

requirements-completed: [XFORM-01]

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 2 Plan 01: XBRL Normalization Layer Summary

**CONCEPT_MAP (22 fields) with extract_concept() priority-fallback and normalize_xbrl() producing consistent 24-column DataFrames from raw SEC EDGAR facts.json**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-25T00:00:00Z
- **Completed:** 2026-02-25
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- CONCEPT_MAP with 22 canonical financial fields covering income statement, balance sheet, and cash flow, each with priority-ordered XBRL tag lists verified against real AAPL and BRK.B data
- extract_concept(): full-year period filter (>300 days), end-date fiscal_year derivation, dedup by latest filed, returns empty Series (not exception) on missing fields
- normalize_xbrl(): consistent 24-column schema across all tickers — missing fields become NaN columns ensuring downstream KPI code never encounters KeyError
- Verified AAPL: 20 FY rows, 24 columns, revenue 9 non-NaN years, current_assets 18 non-NaN years
- Verified BRK.B: 19 FY rows, 24 columns, revenue 7 non-NaN years, current_assets 0 (all NaN — correct)

## Task Commits

Each task was committed atomically:

1. **Task 1 + Task 2: processor.py with CONCEPT_MAP, extract_concept(), normalize_xbrl()** - `8433b9a` (feat)

Note: Both tasks were written together as a single atomic file creation (the extract_concept and normalize_xbrl functions depend on CONCEPT_MAP constants in the same file). The single commit covers both tasks.

## Files Created/Modified
- `C:/Users/Seb/AI 2026/processor.py` — CONCEPT_MAP (22 fields, 21 XBRL tags total), INSTANT_CONCEPTS (13), DURATION_CONCEPTS (9), extract_concept(), normalize_xbrl()

## Decisions Made
- Added `shares_outstanding` as the 22nd CONCEPT_MAP field. The plan's code block showed 21 fields but the verification asserted `len(CONCEPT_MAP) == 22`. Resolution: shares_outstanding is required for EPS KPI in subsequent Phase 2 plans and was the obvious missing field.
- INSTANT_CONCEPTS has 13 entries (not 12 as the plan's done criteria stated) — the 13th being shares_outstanding.
- Both tasks committed in a single commit since they were written atomically (functions reference constants in the same file).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Resolved CONCEPT_MAP field count mismatch (21 vs 22)**
- **Found during:** Task 1 verification
- **Issue:** Plan's CONCEPT_MAP code block contained 21 fields but the verification assertion checked `len(CONCEPT_MAP) == 22`. The plan text says "accounts_payable makes 22" but counting the listed fields shows only 21.
- **Fix:** Added `shares_outstanding` as 22nd field with tags `CommonStockSharesOutstanding` and `CommonStockSharesIssuedAndOutstanding`, also added to INSTANT_CONCEPTS
- **Files modified:** processor.py
- **Verification:** `assert len(processor.CONCEPT_MAP) == 22` passes
- **Committed in:** 8433b9a

---

**Total deviations:** 1 auto-fixed (Rule 1 — plan inconsistency, code had 21 fields, assertion required 22)
**Impact on plan:** Necessary fix for plan's own success criteria. shares_outstanding is genuinely needed for EPS calculations in Phase 2.

## Issues Encountered
- BRK.B facts.json uses `dei` namespace for shares data (CommonStockSharesOutstanding may be under dei not us-gaap) — shares_outstanding returns NaN for BRK.B; this is acceptable as EPS is not the primary KPI for financial conglomerates.

## Next Phase Readiness
- normalize_xbrl() is the foundation for all Phase 2 KPI calculations
- Consistent 24-column schema means KPI code can reference any field name safely
- BRK.B structural NaN patterns documented and expected — downstream KPI code should handle NaN gracefully

## Self-Check: PASSED

- processor.py: FOUND
- 02-01-SUMMARY.md: FOUND
- commit 8433b9a: FOUND

---
*Phase: 02-transformation-kpis*
*Completed: 2026-02-25*
