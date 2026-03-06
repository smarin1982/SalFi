---
phase: 09-orchestration-red-flags
plan: 01
subsystem: red-flags-engine
tags: [web-search, ddgs, red-flags, yaml-config, financial-analysis]
dependency_graph:
  requires: []
  provides: [web_search.search_sector_context, web_search.search_comparable_companies, red_flags.evaluate_flags, red_flags.load_config, red_flags.RedFlag, config/red_flags.yaml]
  affects: [LatamAgent.py (plan 09-02)]
tech_stack:
  added: [PyYAML>=6.0]
  patterns: [tenacity-retry-decorator, yaml-safe-load, dataclass-value-object, severity-sorted-list]
key_files:
  created:
    - web_search.py
    - red_flags.py
    - config/red_flags.yaml
  modified:
    - requirements.txt
decisions:
  - "ddgs 9.11.2 uses DDGSException not DuckDuckGoSearchException — exception class renamed in this version; tenacity retry uses (RatelimitException, DDGSException)"
  - "load_config() returns {} when YAML missing (never raises) — evaluate_flags() returns [] when config is empty; graceful degradation required per must-haves"
  - "evaluate_flags() accepts both kpis_df and financials_df — FLAG-S01 uses operating_cash_flow from financials_df; FLAG-S02 uses net_profit_margin from kpis_df"
metrics:
  duration: 4min
  completed: 2026-03-06
  tasks_completed: 2
  files_created: 3
  files_modified: 1
---

# Phase 9 Plan 1: web_search.py + red_flags.py Foundation Summary

**One-liner:** ddgs web search wrapper with tenacity retry (DDGSException fix) and YAML-configurable healthcare red flags engine with 7 single-KPI flags and 2 multi-year special flags.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | web_search.py — ddgs wrapper | 52f9b60 | web_search.py |
| 2 | red_flags.py + config/red_flags.yaml | 42e8089 | red_flags.py, config/red_flags.yaml, requirements.txt |

## What Was Built

### web_search.py (SCRAP-03)

ddgs web search wrapper providing two public functions:

- `search_sector_context(company_name, country, sector)` — searches for sector context with tenacity retry (3 attempts, 4-30s exponential backoff)
- `search_comparable_companies(sector, country, max_results)` — searches for comparable companies

Both functions:
- Return `list[dict]` (keys: title, href, body) or `[]` on failure
- NEVER raise — catch-all except returns `[]` and logs warning
- Guard against ddgs ImportError with `_DDGS_AVAILABLE` flag

### red_flags.py (FLAG-01, FLAG-02)

YAML-configurable rules engine:

- `RedFlag` dataclass: flag_id, name, description, severity, kpi, kpi_value, fiscal_year, threshold_triggered
- `load_config(config_path)` — loads YAML, returns `{}` with warning if missing (never raises FileNotFoundError)
- `_evaluate_threshold(value, threshold)` — evaluates gt/lt/gte/lte threshold dict
- `_evaluate_special_flags(kpis_sorted, financials_sorted, config)` — FLAG-S01 (FCO negativo) and FLAG-S02 (consecutive losses)
- `evaluate_flags(kpis_df, financials_df, sector, config_path)` — main entry point, returns list sorted Alta-first

### config/red_flags.yaml (FLAG-02)

Healthcare sector threshold file:
- 7 single-KPI flags with Alta/Media/Baja thresholds: FLAG-001 through FLAG-007
- 2 special multi-year flags: FLAG-S01 (FCO negativo), FLAG-S02 (perdidas consecutivas)
- Analyst-editable — changing a threshold value takes effect on next `evaluate_flags()` call without Python changes

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed DuckDuckGoSearchException import in ddgs 9.11.2**
- **Found during:** Task 1 verification
- **Issue:** Plan specified `from ddgs.exceptions import DuckDuckGoSearchException` but ddgs 9.11.2 renamed this exception to `DDGSException`. The ImportError caused `_DDGS_AVAILABLE = False`, making the module behave as if ddgs was not installed.
- **Fix:** Changed import to `from ddgs.exceptions import DDGSException, RatelimitException` and updated tenacity `retry_if_exception_type` tuple accordingly.
- **Files modified:** web_search.py
- **Commit:** 52f9b60

## Must-Haves Verification

| Truth | Status |
|-------|--------|
| search_sector_context() returns list (possibly empty) and never raises | PASS — tested with missing ddgs and rate limit simulation |
| evaluate_flags() returns sorted list of RedFlag objects (Alta first) | PASS — smoke test: 3 flags, Alta first (Deuda/EBITDA elevado) |
| Changing threshold in YAML changes flag behavior without Python edits | PASS — confirmed by design (load_config() called per evaluate_flags() call) |
| Three mandatory flags evaluated: FLAG-001, FLAG-S01, FLAG-S02 | PASS — all three present in smoke test result |
| evaluate_flags() returns [] when config/red_flags.yaml missing | PASS — tested with nonexistent config path |

## Self-Check: PASSED

- FOUND: web_search.py
- FOUND: red_flags.py
- FOUND: config/red_flags.yaml
- FOUND: .planning/phases/09-orchestration-red-flags/09-01-SUMMARY.md
- FOUND commit: 52f9b60 (web_search.py)
- FOUND commit: 42e8089 (red_flags.py + config)
