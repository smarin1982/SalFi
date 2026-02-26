---
phase: 04-dashboard
plan: 02
subsystem: ui
tags: [streamlit, plotly, dashboard, kpi, parquet]

# Dependency graph
requires:
  - phase: 04-01
    provides: app.py foundation with KPI_META, KPI_GROUPS, load_kpis(), format_kpi(), format_delta(), COMPANY_COLORS

provides:
  - Full Streamlit dashboard UI with sidebar, company selector, KPI picker, year slider
  - Dynamic grid layout engine (1 full-width, 2/3/4 equal columns, 5 as 2+3 rows)
  - Executive Card renderer (st.metric + Plotly trend chart per KPI)
  - Comparativo overlay mode (two Plotly traces HD #1f4e79 + PG #2e7d32 on same figure)
  - Dynamic ticker input with FinancialAgent.run() + st.cache_data.clear() (DASH-03)

affects: [04-03, 05-scheduling]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Global KPI cap via remaining budget: recalculate `remaining = MAX_KPIS - len(selected_kpis)` before each group's multiselect"
    - "Dynamic grid: 1=direct render, 2/3/4=st.columns(n), 5=st.columns(2)+st.columns(3)"
    - "Executive Card: st.metric(border=True) + st.plotly_chart(fig, width='stretch')"
    - "Comparativo: go.Figure() + fig.add_trace(go.Scatter()) twice with COMPANY_COLORS"
    - "Lazy import of agent module inside button handler to avoid ETL on page load"

key-files:
  created: []
  modified:
    - app.py

key-decisions:
  - "width='stretch' used in all st.plotly_chart calls — use_container_width deprecated in Streamlit 1.40+ and removed 2025-12-31"
  - "5-KPI layout uses two separate st.columns() calls (2+3) not one call with 5 — Streamlit stacks them as two rows"
  - "Rentabilidad expander defaults to expanded=True — most commonly used KPI group for CFO workflows"
  - "config={'displayModeBar': False} on all Plotly charts — removes toolbar chrome for Bloomberg aesthetic"
  - "st.cache_data.clear() after FinancialAgent.run() — invalidates all cached parquet reads so new ticker appears immediately"
  - "Lazy import of agent module inside button handler — avoids ETL initialization on every page load"

patterns-established:
  - "Executive Card pattern: st.metric(label, value, delta, border=True) + st.plotly_chart(fig, width='stretch')"
  - "KPI accumulation pattern: selected_kpis list built across expander groups with remaining budget enforcement"
  - "Never cache go.Figure objects — always create inside render function to prevent trace accumulation across reruns"

requirements-completed: [DASH-01, DASH-02, DASH-03]

# Metrics
duration: 2min
completed: 2026-02-26
---

# Phase 4 Plan 02: Dashboard UI Summary

**Full Streamlit dashboard with company selector, 5-group KPI sidebar (global 5-cap), dynamic 1-5 column grid, Executive Cards (st.metric + Plotly), and HD/PG Comparativo overlay mode**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-26T14:53:56Z
- **Completed:** 2026-02-26T14:55:45Z
- **Tasks:** 2 (executed as one atomic edit to app.py)
- **Files modified:** 1

## Accomplishments
- Complete Streamlit UI replacing the Plan 04-01 placeholder skeleton
- Sidebar with 5 st.expander KPI category groups, each with st.multiselect and global 5-KPI cap enforced via `remaining` budget recalculated per group
- Year range slider (2007–2025, default 2015–2025) controlling all chart views
- Dynamic grid layout: 1 KPI = full width, 2/3/4 = equal columns, 5 = 2+3 two-row layout
- Executive Card: st.metric(border=True) with big number + delta pill + Plotly trend chart
- Comparativo mode: build_comparativo_figure() creates a single go.Figure with two go.Scatter traces (HD navy, PG green)
- Dynamic ticker input: FinancialAgent.run() + st.cache_data.clear() + st.rerun() for zero-restart company loading (DASH-03)

## Task Commits

Each task was committed atomically (Tasks 1 and 2 combined in single app.py edit):

1. **Task 1 + Task 2: Complete dashboard UI** - `59659f4` (feat)

**Plan metadata:** (pending — created in final commit below)

## Files Created/Modified
- `C:/Users/Seb/AI 2026/app.py` - Full Streamlit dashboard: sidebar controls, chart builders, render_kpi_card(), build_comparativo_figure(), main canvas with dynamic layout (473 lines total)

## Decisions Made
- `width="stretch"` used on all 4 `st.plotly_chart` calls — `use_container_width=True` deprecated in Streamlit 1.40+ (removed after 2025-12-31); 0 occurrences of deprecated API confirmed by grep
- 5-KPI layout uses two separate `st.columns()` calls (2 then 3) — Streamlit does not support a single `st.columns(5)` call that produces a 2+3 layout; two calls stack vertically as designed
- `remaining = MAX_KPIS - len(selected_kpis)` recalculated before each expander group's multiselect — enforces global cap across all groups without per-widget coordination
- `st.cache_data.clear()` called after FinancialAgent.run() — ensures newly created parquet file is immediately readable without TTL expiry
- `agent` module imported lazily inside button handler — prevents ETL initialization overhead on every Streamlit page load

## Deviations from Plan

None - plan executed exactly as written. Both tasks (sidebar + main canvas) were appended to app.py in a single edit pass and committed atomically.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- app.py is fully functional; `streamlit run app.py` will launch the dashboard (requires HD and PG parquet files in data/clean/)
- Plan 04-03 checkpoint: visual QA of dashboard with real data — verify Executive Cards, Comparativo overlay, dynamic layout
- All DASH-01, DASH-02, DASH-03 requirements delivered

---
*Phase: 04-dashboard*
*Completed: 2026-02-26*
