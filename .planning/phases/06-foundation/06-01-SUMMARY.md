---
phase: 06-foundation
plan: "01"
subsystem: fx-normalizer
tags: [currency, fx, frankfurter, open-er-api, lru_cache, json-cache, requests, loguru, python-slugify, playwright]

# Dependency graph
requires: []
provides:
  - "currency.py: to_usd(amount, currency, fiscal_year) -> float for all 6 LATAM currencies"
  - "currency.py: is_low_confidence_currency(currency) -> bool (ARS flagged)"
  - "currency.py: get_annual_avg_rate(currency, year) -> float with lru_cache + disk persistence"
  - "data/cache/fx_rates.json: populated with BRL/MXN/ARS/CLP/COP/PEN 2023 rates"
  - "requirements.txt: python-slugify>=8.0.4 and playwright>=1.48 added"
affects:
  - phase 06-02 (company_registry uses currency.is_low_confidence_currency)
  - all LATAM scraper phases (07-10) use currency.to_usd before writing Parquet
  - any phase writing financials.parquet for LATAM companies

# Tech tracking
tech-stack:
  added:
    - "python-slugify 8.0.4 (installed, already present in env)"
    - "playwright 1.58.0 (installed via pip install)"
    - "requests (stdlib pattern via get, used in currency.py)"
  patterns:
    - "Tiered FX fallback: Frankfurter for ECB-tracked currencies, open.er-api.com for others"
    - "lru_cache(maxsize=256) + disk JSON cache for cross-session rate persistence"
    - "raise_for_status() + catch HTTPError/RequestException for automatic fallback trigger"
    - "loguru warning on non-Frankfurter currency lookup (approximated_fx flag reminder)"

key-files:
  created:
    - currency.py
    - tests/test_currency.py
    - data/cache/fx_rates.json
  modified:
    - requirements.txt

key-decisions:
  - "Frankfurter annual average (true mean of daily ECB rates) used for BRL/MXN — not spot rate"
  - "open.er-api.com spot rate used as proxy for ARS/CLP/COP/PEN historical annual average — approximated_fx=true required in meta.json"
  - "is_low_confidence_currency() flags only ARS (extreme volatility, parallel rates); CLP/COP/PEN not flagged"
  - "Disk cache is NOT thread-safe by design — single-threaded processor context; filelock deferred"
  - "lru_cache on get_annual_avg_rate prevents duplicate HTTP calls within a session"

patterns-established:
  - "Pattern: All LATAM monetary values converted to USD via currency.to_usd() before Parquet write"
  - "Pattern: approximated_fx=True set in meta.json for any non-Frankfurter currency"
  - "Pattern: Cache key format is {CURRENCY}_{YEAR} (e.g. BRL_2023)"

requirements-completed: [FX-01, FX-02]

# Metrics
duration: 25min
completed: 2026-03-05
---

# Phase 6 Plan 01: FX Normalizer Summary

**Tiered FX normalizer with Frankfurter annual averages for BRL/MXN and open.er-api.com spot fallback for ARS/CLP/COP/PEN, backed by lru_cache and disk persistence in fx_rates.json**

## Performance

- **Duration:** 25 min
- **Started:** 2026-03-05T00:00:00Z
- **Completed:** 2026-03-05T00:25:00Z
- **Tasks:** 2 (RED phase + GREEN phase)
- **Files modified:** 4 (currency.py created, tests/test_currency.py created, requirements.txt updated, data/cache/fx_rates.json created)

## Accomplishments

- `currency.py` fully implemented: `to_usd()`, `is_low_confidence_currency()`, `get_annual_avg_rate()` all exported and working
- 11/11 tests pass in `tests/test_currency.py` covering all 6 LATAM currencies, fallback, low-confidence flag, disk cache, and mock-based fallback trigger
- `data/cache/fx_rates.json` created on test run with live rates for all 6 currencies (BRL, MXN, ARS, CLP, COP, PEN for year 2023)
- `python-slugify>=8.0.4` and `playwright>=1.48` added to `requirements.txt` for upcoming phases
- 4 existing `test_kpi_registry.py` tests unaffected (no regressions)

## Task Commits

Each task committed atomically (TDD pattern):

1. **Task 1: RED phase — failing tests + requirements update** - `e5ec473` (test)
2. **Task 2: GREEN phase — currency.py implementation + fx_rates.json** - `140972d` (feat)

**Plan metadata:** (final commit — see below)

_Note: TDD tasks have two commits: test (RED) then feat (GREEN). Refactor not needed — implementation was clean on first pass._

## Files Created/Modified

- `currency.py` - FX normalizer; exports `to_usd`, `is_low_confidence_currency`, `get_annual_avg_rate`; 89 lines
- `tests/test_currency.py` - 11 tests: 6 currency integration tests, 2 flag tests, 1 cache test, 1 fallback mock test; 120 lines
- `data/cache/fx_rates.json` - Disk cache seeded with 2023 rates for all 6 LATAM currencies; keyed by `{CURRENCY}_{YEAR}`
- `requirements.txt` - Added `python-slugify>=8.0.4` and `playwright>=1.48` after pyarrow line

## Decisions Made

- **Frankfurter for BRL/MXN only:** ECB tracks these two currencies reliably with daily data from 1999. The annual average is computed by fetching `{year}-01-01..{year}-12-31` and averaging all `rates["USD"]` values — true historical average.
- **open.er-api.com for ARS/CLP/COP/PEN:** Frankfurter does not cover these currencies. open.er-api.com requires no API key and returns a spot rate. This is cached at first call, so every Parquet write uses the same rate — consistent within a session. Limitation documented in module comment.
- **Only ARS flagged as low_confidence:** ARS has extreme volatility (official vs. parallel rates diverge 50-100%). CLP, COP, PEN are more stable and not flagged, reducing false-positive warnings in the dashboard.
- **Disk cache not thread-safe:** Python's single-threaded processor context makes locking unnecessary. The limitation is documented in module docstring for future reference.

## Deviations from Plan

None — plan executed exactly as written. All implementation steps followed RESEARCH.md Pattern 1 as specified.

## Issues Encountered

- `tests/test_company_registry.py` already present in tests/ (from a prior session starting Plan 02 work). This causes `python -m pytest tests/ -v` to fail at collection with `ModuleNotFoundError: No module named 'company_registry'`. This is expected TDD RED state for Plan 02 — not a regression. Tests were run as `python -m pytest tests/test_currency.py tests/test_kpi_registry.py -v` to confirm Plan 01 scope: 15/15 passed.

## User Setup Required

None — no external service configuration required. `playwright install chromium` is a noted blocker in STATE.md for Phase 7+ but is not needed for Plan 01.

## Next Phase Readiness

- `currency.py` is the validated single source of truth for all LATAM FX conversions — ready for Plan 02 (company_registry.py) to import `is_low_confidence_currency`
- `fx_rates.json` pre-seeded; subsequent phases will use cached rates (no duplicate API calls)
- `python-slugify` and `playwright` are installed and importable

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `currency.py` exists | FOUND |
| `tests/test_currency.py` exists | FOUND |
| `data/cache/fx_rates.json` exists | FOUND |
| `06-01-SUMMARY.md` exists | FOUND |
| Commit `e5ec473` (RED) | FOUND |
| Commit `140972d` (GREEN) | FOUND |
| 11/11 tests pass | CONFIRMED |
| 4/4 kpi_registry tests unaffected | CONFIRMED |

---
*Phase: 06-foundation*
*Completed: 2026-03-05*
