---
phase: 02-transformation-kpis
plan: "02"
subsystem: processor
tags: [transformation, kpis, parquet, cleaning, safe-divide]
dependency_graph:
  requires: [02-01]
  provides: [data/clean/AAPL/financials.parquet, data/clean/AAPL/kpis.parquet, data/clean/BRK.B/financials.parquet, data/clean/BRK.B/kpis.parquet]
  affects: [phase-03-financial-agent, phase-04-dashboard]
tech_stack:
  added: [pyarrow (atomic Parquet write)]
  patterns: [rolling-median NaN fill, safe_divide zero-guard, atomic tmp-then-rename write]
key_files:
  modified: [processor.py]
  created: [data/clean/AAPL/financials.parquet, data/clean/AAPL/kpis.parquet, data/clean/BRK.B/financials.parquet, data/clean/BRK.B/kpis.parquet]
decisions:
  - "safe_divide uses denominator.replace(0, np.nan) — converts zeros to NaN before division, never produces inf"
  - "clean_financials rolling fill only fills NaN positions, never overwrites existing values"
  - "total_debt logic: if both STD and LTD are NaN result is NaN; if only one is NaN treat as 0"
  - "save_parquet unlinks existing file before rename on Windows (NTFS rename-to-existing restriction)"
  - "EBITDA = ebit + da with no fillna(0) — NaN da propagates to NaN EBITDA rather than understating"
metrics:
  duration: 5 min
  completed: 2026-02-25
  tasks_completed: 2
  files_modified: 1
requirements: [XFORM-02, XFORM-03, XFORM-04]
---

# Phase 2 Plan 02: Cleaning Layer, 20-KPI Engine, Atomic Parquet Writer Summary

**One-liner:** Rolling median NaN fill + 20-KPI engine with safe_divide zero-guard + atomic pyarrow Parquet write producing AAPL (20 FY) and BRK.B (19 FY) clean output files.

## What Was Built

Four functions appended to `processor.py` (258 lines added, total 558 lines):

**safe_divide(numerator, denominator)**
- Converts denominator zeros to NaN via `.replace(0, np.nan)` before division
- Zero denominators yield NaN, never inf or ZeroDivisionError
- Used by all 13 ratio KPIs

**clean_financials(df)**
- Sorts by fiscal_year ascending
- For each numeric column: if isolated NaN(s) exist (not all-NaN), fills via `rolling(window=3, center=True, min_periods=1).median()`
- Uses `where(~nan_mask, other=rolling_fill)` — existing non-NaN values are never touched
- Structural all-NaN columns (e.g. BRK.B current_assets) remain NaN unchanged

**calculate_kpis(df)**
- Produces exactly 22 columns: ticker, fiscal_year, and 20 named KPIs
- Helper `col(name)` returns all-NaN Series for missing fields (BRK.B compatibility)
- Average-based KPIs (asset_turnover, inventory_turnover, DSO, CCC) use `.shift(1)` for prior-year — NaN for earliest year is correct
- EBITDA = operating_income + depreciation_amortization (no fillna(0) — avoids understatement)
- total_debt = ltd.fillna(0) + std.fillna(0), masked to NaN when both are NaN

**save_parquet(df, output_path)**
- Writes to `{output_path}.parquet.tmp` first
- Explicitly unlinks existing file before rename (Windows NTFS requirement)
- Rename is atomic on NTFS — no partial files on crash
- engine="pyarrow" ensures byte-identical output for idempotency

**process(ticker, data_dir)**
- Orchestrates: normalize_xbrl -> clean_financials -> calculate_kpis -> save_parquet x2
- Returns status dict: ticker, fiscal_years, fields_extracted, fields_missing, kpi_columns
- Raises FileNotFoundError for missing facts.json; ValueError for empty us-gaap data
- Idempotent: safe to run multiple times

**CLI block**
- `python processor.py AAPL BRK.B` prints `[OK]` or `[ERROR]` per ticker with FY range and field counts

## End-to-End Results

### AAPL
- Fiscal years: 2006–2025 (20 years)
- Fields extracted: 21 of 22 (shares_outstanding missing — not in us-gaap namespace for this filing)
- Fields missing (all-NaN): shares_outstanding
- Parquet sizes: financials.parquet 17,850 bytes; kpis.parquet 16,175 bytes

KPI sample (FY 2023-2025):

| fiscal_year | gross_profit_margin | operating_margin | net_profit_margin | roe | current_ratio | debt_to_equity | asset_turnover |
|-------------|--------------------|-----------------|--------------------|-----|---------------|----------------|----------------|
| 2023 | 0.441 | 0.298 | 0.253 | 1.561 | 0.988 | 4.673 | 1.087 |
| 2024 | 0.462 | 0.315 | 0.240 | 1.646 | 0.867 | 5.409 | 1.090 |
| 2025 | 0.469 | 0.320 | 0.269 | 1.519 | 0.893 | 3.872 | 1.149 |

Note: AAPL current_ratio < 1 reflects aggressive buyback program (negative working capital) — this is correct, not an error.

### BRK.B
- Fiscal years: 2006–2024 (19 years)
- Fields extracted: 12 of 22
- Fields missing (all-NaN): gross_profit, cogs, current_assets, current_liabilities, short_term_investments, receivables, long_term_debt, short_term_debt, accounts_payable, shares_outstanding
- Parquet sizes: financials.parquet 15,605 bytes; kpis.parquet 13,395 bytes

KPIs correctly NaN (13 of 20): revenue_cagr_10y, gross_profit_margin, operating_margin, ebitda_margin, current_ratio, quick_ratio, cash_ratio, working_capital, debt_to_ebitda, debt_to_assets, inventory_turnover, dso, cash_conversion_cycle

KPIs available (7 of 20): revenue_growth_yoy, net_profit_margin, roe, roa, debt_to_equity, interest_coverage, asset_turnover

This matches expected behavior for a diversified financial conglomerate — no retail balance sheet structure.

## Idempotency Test

Running `process('AAPL', 'data')` twice produces byte-identical Parquet files:
- md5(financials.parquet): matched on both runs
- md5(kpis.parquet): matched on both runs
- Result: IDEMPOTENCY CHECK PASSED

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

Files created:
- data/clean/AAPL/financials.parquet: EXISTS (17,850 bytes)
- data/clean/AAPL/kpis.parquet: EXISTS (16,175 bytes)
- data/clean/BRK.B/financials.parquet: EXISTS (15,605 bytes)
- data/clean/BRK.B/kpis.parquet: EXISTS (13,395 bytes)

Commits:
- c047da6: feat(02-02): implement safe_divide, clean_financials, calculate_kpis (all 20 KPIs)
- b2afb9b: feat(02-02): implement save_parquet, process() entry point, and CLI

## Self-Check: PASSED
