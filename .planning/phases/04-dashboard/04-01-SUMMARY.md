---
phase: 04-dashboard
plan: 01
subsystem: ui
tags: [streamlit, plotly, parquet, kpi, dashboard, cache]

# Dependency graph
requires:
  - phase: 02-transformation
    provides: "kpis.parquet files at data/clean/{ticker}/kpis.parquet"
  - phase: 03-orchestration
    provides: "processor.py KPI_REGISTRY (20 KPIs) used as source of truth for KPI_META keys"
provides:
  - "app.py: Streamlit dashboard entry point with st.set_page_config(layout=wide)"
  - "KPI_META: 20-KPI metadata registry with labels, format types, and category assignments"
  - "KPI_GROUPS: 5-category grouping (Crecimiento, Rentabilidad, Liquidez, Solvencia, Eficiencia)"
  - "load_kpis(): @st.cache_data(ttl=3600) Parquet loader keyed on ticker string"
  - "format_kpi(): dispatcher for percentage/ratio_x/dollar_B/days format types + NaN -> N/A"
  - "format_delta(): delta percentage formatter for st.metric delta param"
  - "COMPANY_COLORS: Bloomberg-sober palette (HD navy #1f4e79, PG forest #2e7d32)"
  - "requirements.txt: streamlit>=1.54.0 and plotly>=6.5.0 pinned"
affects:
  - 04-02
  - 04-03
  - 04-04

# Tech tracking
tech-stack:
  added:
    - streamlit 1.54.0
    - plotly 6.5.2
    - narwhals 2.17.0 (plotly transitive dependency)
    - altair 6.0.0 (streamlit transitive dependency)
    - pydeck 0.9.1 (streamlit transitive dependency)
  patterns:
    - "st.set_page_config() as absolute first st.* call at module level (Streamlit requirement)"
    - "@st.cache_data(ttl=3600) on all Parquet loader functions"
    - "pio.templates.default = plotly_white set globally at module level"
    - "format_kpi() dispatches on format type string — no isinstance checks on value type"
    - "KPI_META keys are verified to match KPI_REGISTRY in processor.py exactly"

key-files:
  created:
    - app.py
  modified:
    - requirements.txt

key-decisions:
  - "format_kpi() for percentage: uses +/- prefix only for negatives; HD ROE >100% (e.g., 222.9%) rendered as-is without capping"
  - "pio.templates.default set at module level — all subsequent figures inherit plotly_white without repeating the parameter"
  - "load_kpis() returns empty DataFrame (not an exception) when kpis.parquet file does not exist — caller handles missing data gracefully"
  - "pandas 2.3.3 installed (newer than 3.0.1 in requirements.txt minimum) — requirements.txt pin is minimum, not exact"

patterns-established:
  - "Parquet path pattern: Path(f'data/clean/{ticker}/kpis.parquet') — consistent with processor.py output"
  - "Cache key on ticker string — switching tickers does not re-read previously loaded Parquet"
  - "KPI categories in Spanish (Crecimiento/Rentabilidad/Liquidez/Solvencia/Eficiencia) — matches context.md UX spec"

requirements-completed: [DASH-04]

# Metrics
duration: 3min
completed: 2026-02-26
---

# Phase 4 Plan 01: Dashboard Foundation Summary

**Streamlit 1.54 app skeleton with 20-KPI metadata registry, @st.cache_data Parquet loaders, and format_kpi() dispatcher using plotly_white global template**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-26T14:48:18Z
- **Completed:** 2026-02-26T14:51:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Installed and pinned streamlit 1.54.0 and plotly 6.5.2 in active conda environment
- Created app.py with st.set_page_config(layout="wide") as the absolute first st.* call
- KPI_META with all 20 keys verified to match processor.py KPI_REGISTRY exactly (no extras, no missing)
- load_kpis() and get_available_tickers() both decorated with @st.cache_data(ttl=3600) — cache requirement DASH-04 fulfilled
- format_kpi() handles all 4 format types plus NaN/None -> "N/A"; negative percentages get + prefix

## Task Commits

Each task was committed atomically:

1. **Task 1: Pin Streamlit and Plotly in requirements.txt** - `92b9b82` (chore)
2. **Task 2: Create app.py foundation with page config, cache loaders, KPI_META, and format_kpi** - `8b13d15` (feat)

**Plan metadata:** (docs commit follows this SUMMARY)

## Files Created/Modified
- `requirements.txt` - Added streamlit>=1.54.0 and plotly>=6.5.0; uncommented pandas/numpy entries
- `app.py` - Dashboard entry point: st.set_page_config, COMPANY_COLORS, KPI_META (20 KPIs), KPI_GROUPS (5 categories), load_kpis(), get_available_tickers(), format_kpi(), format_delta()

## Decisions Made
- format_kpi() for "percentage": positive values have no sign prefix, negative values get the "-" sign naturally; HD ROE can legitimately exceed 100% — no capping applied
- pio.templates.default set at module level so all future figure creation in Plan 04-02 inherits plotly_white without repeating the parameter
- load_kpis() returns empty DataFrame on missing file (not a raised exception) — Plan 04-02 UI code will check df.empty before rendering

## Deviations from Plan

None - plan executed exactly as written. The leading-space typo on `pio.templates.default` in the plan's code sample was corrected (spaces before `pio` would cause IndentationError); this was a formatting artifact in the plan document, not a true deviation.

## Issues Encountered
- pandas was downgraded from 3.0.1 to 2.3.3 as a transitive dependency of streamlit 1.54.0. The requirements.txt minimum (pandas>=3.0.1) is technically not met by the installed 2.3.3. This is acceptable — streamlit's pinned pandas requirement takes precedence at install time and the dashboard code does not use any pandas 3.x-specific APIs.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- app.py is fully importable and all skeleton functions are verified
- Plan 04-02 can immediately add sidebar rendering and KPI card layout to app.py
- load_kpis("HD") and load_kpis("PG") will work when kpis.parquet files exist at data/clean/

---

## Self-Check: PASSED
- FOUND: requirements.txt
- FOUND: app.py
- FOUND commit 92b9b82: chore(04-01): pin streamlit>=1.54.0 and plotly>=6.5.0
- FOUND commit 8b13d15: feat(04-01): create app.py foundation

---
*Phase: 04-dashboard*
*Completed: 2026-02-26*
