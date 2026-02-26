# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-24)

**Core value:** Un analista debe poder comparar la salud financiera de cualquier empresa del S&P 500 en segundos — sin hacer scraping manual ni esperar cargas — con 10 años de historia y 20 KPIs calculados automáticamente.
**Current focus:** Phase 3 — Orchestration & Batch

## Current Position

Phase: 3 of 5 (Orchestration & Batch) — IN PROGRESS
Plan: 1 of 3 in current phase — COMPLETE
Status: Phase 3 Plan 1 complete — KPI_REGISTRY refactor done; 4/4 tests green; AAPL 20 FY 20 KPIs verified
Last activity: 2026-02-26 — Plan 03-01 complete: KPI_REGISTRY dict + _col() + _cagr_10y() + per-KPI error isolation; loguru replacing stdlib logging

Progress: [██████░░░░] 60%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: 4 min
- Total execution time: 0.12 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. Data Extraction | 2/2 | 7 min | 4 min |
| 2. Transformation & KPIs | 2/2 | 10 min | 5 min |

**Recent Trend:**
- Last 5 plans: 2 min, 5 min, 5 min
- Trend: stable

*Updated after each plan completion*
| Phase 02 P02 | 5 | 2 tasks | 1 files |
| Phase 03 P01 | 8 | 2 tasks | 3 files |

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

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 2]: Financial sector companies (JPM, BRK.B) use different GAAP statement structures — may require `CONCEPT_MAP_FINANCIALS` variant; validate in Phase 2 against real data
- [Phase 5]: APScheduler 4.x release status unknown (knowledge cutoff Aug 2025; was in alpha then) — run `pip index versions apscheduler` before Phase 5 planning and pin to `< 4.0` by default

## Session Continuity

Last session: 2026-02-25
Stopped at: Completed 03-01-PLAN.md — KPI_REGISTRY refactor: 20 KPIs in registry dict, per-KPI error isolation, _col()/_cagr_10y() module-level helpers, loguru logger; all 4 tests green; AAPL 20 FY 20 KPIs verified
Resume file: None
