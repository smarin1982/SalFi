# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-03)

**Core value:** Un analista debe poder analizar la salud financiera de cualquier empresa — S&P 500 o LATAM — en segundos, con KPIs calculados automáticamente, red flags detectadas y un reporte ejecutivo listo para presentar.
**Current focus:** Milestone v2.0 — LATAM Financial Analysis Pipeline (defining requirements)

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements for milestone v2.0
Last activity: 2026-03-03 — Milestone v2.0 started

Progress: [░░░░░░░░░░] 0% (0 phases complete)

## Performance Metrics

**v1.0 Velocity (reference):**
- Total plans completed: 9
- Average duration: 4 min
- Total execution time: ~0.28 hours

**v2.0:**
- Plans completed: 0
- Status: Not started

## Accumulated Context

### Decisions (v1.0 — preserved)

- [Setup]: Parquet for local storage — faster reads, avoids re-scraping, survives schema migrations
- [Setup]: edgartools for EDGAR extraction — XBRL-native, returns DataFrames, SEC rate limiting built in
- [Setup]: Streamlit + Plotly for dashboard — local, interactive, fast to build
- [Setup]: Values nominal (no inflation adjustment) — direct comparability with SEC official reports
- [Setup]: Outliers preserved as real data — no artificial smoothing
- [01-01]: edgartools imported as `edgar` in Python code (pip name differs from import name)
- [01-01]: EDGAR_IDENTITY format is "Name email@domain" per SEC User-Agent policy
- [01-02]: set_rate_limit() removed in edgartools 5.x — use os.environ["EDGAR_RATE_LIMIT_PER_SEC"] = "8"
- [01-02]: BRK.B resolved via "BRK-B" key in SEC tickers.json
- [01-02]: Direct httpx.get() for companyfacts endpoint
- [Phase 02-01]: shares_outstanding added as 22nd CONCEPT_MAP field
- [Phase 02-01]: fiscal_year derived from end-date year not fy field
- [Phase 02]: safe_divide uses denominator.replace(0, np.nan)
- [Phase 02]: save_parquet unlinks before rename on Windows (NTFS atomic rename requirement)
- [Phase 03-01]: KPI_REGISTRY is module-level dict
- [Phase 03-01]: loguru replaces stdlib logging in processor.py
- [Phase 03-02]: FinancialAgent.run() calls processor.process() even on skipped_scrape
- [Phase 03-02]: GOOG and GOOGL both in BASE_TICKERS
- [Phase 04-01]: format_kpi() percentage: no cap on values >100%
- [Phase 04-01]: pio.templates.default set at module level
- [Phase 04-02]: width='stretch' on all st.plotly_chart calls
- [Phase 04-02]: st.cache_data.clear() after FinancialAgent.run()
- [Phase 05-01]: InteractiveToken logon type for Task Scheduler
- [Phase 05-01]: No conda activate in scheduler.bat
- [Phase 05-02]: Task AI2026_QuarterlyETL registered — Status: Ready, Next: 4/1/2026 6:00 AM

### Decisions (v2.0 — accumulating)

(None yet — added as phases execute)

### Pending Todos

None.

### Blockers/Concerns

- [v2.0]: pytesseract requires Tesseract binary installed on Windows — verify before Phase that uses OCR
- [v2.0]: weasyprint requires GTK libraries on Windows — validate install before PDF export phase
- [v2.0]: Playwright requires `playwright install chromium` after pip install

## Session Continuity

Last session: 2026-03-03
Stopped at: Milestone v2.0 initialization — requirements and roadmap pending
Resume file: None
