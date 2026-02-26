# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-24)

**Core value:** Un analista debe poder comparar la salud financiera de cualquier empresa del S&P 500 en segundos — sin hacer scraping manual ni esperar cargas — con 10 años de historia y 20 KPIs calculados automáticamente.
**Current focus:** Phase 5 — Scheduling

## Current Position

Phase: 4 of 5 (Dashboard) — COMPLETE
Plan: 3 of 4 in current phase — COMPLETE
Status: Phase 4 complete — human-verified dashboard: Executive Cards, Comparativo dual-trace, year-range filter, 2+3 grid layout, global 5-KPI cap, sub-second cache switching (DASH-01/02/03/04 all confirmed)
Last activity: 2026-02-26 — Plan 04-03 complete: human visual verification approved, all 6 browser tests passed

Progress: [██████████] 100% (Phase 4 complete)

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: 4 min
- Total execution time: 0.14 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. Data Extraction | 2/2 | 7 min | 4 min |
| 2. Transformation & KPIs | 2/2 | 10 min | 5 min |
| 3. Orchestration & Batch | 3/3 | ~15 min | 5 min |
| 4. Dashboard | 3/4 | 10 min | 3.3 min |

**Recent Trend:**
- Last 5 plans: 2 min, 5 min, 5 min, 3 min, 2 min
- Trend: stable

*Updated after each plan completion*
| Phase 02 P02 | 5 | 2 tasks | 1 files |
| Phase 03 P01 | 8 | 2 tasks | 3 files |
| Phase 03 P02 | 5 | 2 tasks | 2 files |
| Phase 04 P01 | 3 | 2 tasks | 2 files |
| Phase 04 P02 | 2 | 2 tasks | 1 files |
| Phase 04 P03 | 5 | 2 tasks | 0 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Setup]: Parquet for local storage — faster reads, avoids re-scraping, survives schema migrations
- [Setup]: edgartools for EDGAR extraction — XBRL-native, returns DataFrames, SEC rate limiting built in
- [Setup]: Streamlit + Plotly for dashboard — local, interactive, fast to build
- [Setup]: Values nominal (no inflation adjustment) — direct comparability with SEC official reports
- [Setup]: Outliers preserved as real data — no artificial smoothing
- [01-01]: edgartools imported as `edgar` in Python code (pip name differs from import name)
- [01-01]: EDGAR_IDENTITY format is "Name email@domain" per SEC User-Agent policy
- [01-01]: data/clean/ added now to avoid deviation in Plan 02 (Phase 2 Parquet output path)
- [01-02]: set_rate_limit() removed in edgartools 5.x — use os.environ["EDGAR_RATE_LIMIT_PER_SEC"] = "8" before set_identity()
- [01-02]: BRK.B resolved via "BRK-B" key in SEC tickers.json — SEC uses dash, not dot; resolve_cik() fallback handles transparently
- [01-02]: Direct httpx.get() for companyfacts endpoint — guarantees verbatim JSON storage vs. edgartools ORM
- [Phase 02-01]: shares_outstanding added as 22nd CONCEPT_MAP field — plan inconsistency (21 fields listed, 22 asserted); needed for EPS KPI
- [Phase 02-01]: fiscal_year derived from end-date year not fy field — fy is filing year, comparative entries all share fy of filing year
- [Phase 02]: safe_divide uses denominator.replace(0, np.nan) — never produces inf
- [Phase 02]: save_parquet unlinks before rename on Windows (NTFS atomic rename requirement)
- [Phase 03-01]: KPI_REGISTRY is module-level dict — adding one entry causes new KPI in kpis.parquet with no other file changes (ORCHS-01)
- [Phase 03-01]: loguru replaces stdlib logging in processor.py — consistent with scraper.py pattern
- [Phase 03-01]: _col() and _cagr_10y() are module-level private functions — required for lambda scope in KPI_REGISTRY
- [Phase 03-02]: FinancialAgent.run() calls processor.process() even on skipped_scrape — picks up KPI_REGISTRY changes without re-scraping
- [Phase 03-02]: metadata last_downloaded preserved when scraped=False — skipped run does not reset staleness clock
- [Phase 03-02]: GOOG and GOOGL both in BASE_TICKERS; share CIK but produce separate files — both valid dashboard tickers
- [Phase 04-01]: format_kpi() percentage: no cap on values >100% (HD ROE legitimately 222.9%); negative values get "-" prefix naturally
- [Phase 04-01]: pio.templates.default set at module level — all dashboard figures inherit plotly_white without per-figure parameter
- [Phase 04-01]: load_kpis() returns empty DataFrame on missing file — caller (Plan 04-02) handles df.empty before rendering
- [Phase 04-01]: streamlit 1.54.0 pins pandas to 2.3.3 (downgrade from 3.0.1); no pandas 3.x APIs used in dashboard code
- [Phase 04-02]: width='stretch' used on all st.plotly_chart calls — use_container_width deprecated in Streamlit 1.40+, removed 2025-12-31
- [Phase 04-02]: 5-KPI layout uses two separate st.columns() calls (2 then 3) — produces stacked 2+3 rows as designed
- [Phase 04-02]: remaining = MAX_KPIS - len(selected_kpis) recalculated per expander group — global 5-KPI cap across all groups
- [Phase 04-02]: st.cache_data.clear() after FinancialAgent.run() — new parquet immediately readable without TTL wait
- [Phase 04-02]: agent module imported lazily inside button handler — no ETL initialization on page load
- [Phase 04-03]: Human approval required before Phase 4 marked complete — dashboard is CFO-facing and must be visually verified in a real browser

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 2]: Financial sector companies (JPM, BRK.B) use different GAAP statement structures — may require `CONCEPT_MAP_FINANCIALS` variant; validate in Phase 2 against real data
- [Phase 5]: APScheduler 4.x release status unknown (knowledge cutoff Aug 2025; was in alpha then) — run `pip index versions apscheduler` before Phase 5 planning and pin to `< 4.0` by default

## Session Continuity

Last session: 2026-02-26
Stopped at: Completed 04-03-PLAN.md (human verification — Phase 4 complete)
Resume file: None
