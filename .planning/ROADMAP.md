# Roadmap: SP500 Financial Dashboard

## Overview

Build a local Python ETL pipeline and Streamlit dashboard that extracts audited 10-K financial data from SEC EDGAR for the Top 20 S&P 500 companies, calculates 20 KPIs per company per year, and surfaces everything in an interactive multi-company comparison dashboard. The build order is non-negotiable: scraper produces raw JSON, processor turns it into clean Parquet, orchestrator batches the pipeline, dashboard reads from Parquet, and scheduling keeps data current. Every phase depends on the previous delivering verified output.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Data Extraction** - Scraper that fetches 10-K facts from SEC EDGAR for any ticker, with CIK resolution and rate limiting (completed 2026-02-25)
- [x] **Phase 2: Transformation & KPIs** - Processor that normalizes XBRL concepts, handles missing values, and calculates all 20 KPIs into clean Parquet files (completed 2026-02-25)
- [x] **Phase 3: Orchestration & Batch** - FinancialAgent that coordinates extraction + transformation per ticker, with incremental update logic and batch processing of all 20 base companies (completed 2026-02-26)
- [x] **Phase 4: Dashboard** - Streamlit app with multi-company KPI comparison charts, temporal filter, dynamic ticker input, and caching (completed 2026-02-26)
- [ ] **Phase 5: Scheduling** - Quarterly ETL automation via Windows Task Scheduler

## Phase Details

### Phase 1: Data Extraction
**Goal**: The scraper can fetch, rate-limit, and persist raw 10-K financial data from SEC EDGAR for any S&P 500 ticker
**Depends on**: Nothing (first phase)
**Requirements**: XTRCT-01, XTRCT-02, XTRCT-03, XTRCT-04
**Success Criteria** (what must be TRUE):
  1. Running the scraper for any valid S&P 500 ticker produces a `data/raw/{TICKER}/facts.json` file containing 10 years of 10-K financial facts
  2. The scraper resolves any ticker to its SEC CIK using the downloaded `tickers.json` without a network call per resolution
  3. The scraper never exceeds 10 requests/second to SEC EDGAR across any burst of activity
  4. If a `facts.json` file already exists, the scraper uses the local copy instead of re-fetching
**Plans**: 2 plans

Plans:
- [x] 01-01-PLAN.md — Bootstrap project dependencies (.env, requirements.txt, data/ directories)
- [ ] 01-02-PLAN.md — Implement scraper.py with ticker→CIK resolution, rate limiting, and raw facts.json persistence

### Phase 2: Transformation & KPIs
**Goal**: The processor transforms raw EDGAR facts into clean, analysis-ready Parquet files with all 20 KPIs calculated for every company/year combination
**Depends on**: Phase 1
**Requirements**: XFORM-01, XFORM-02, XFORM-03, XFORM-04
**Success Criteria** (what must be TRUE):
  1. Running the processor on any Top 20 ticker produces `data/clean/{TICKER}/financials.parquet` and `data/clean/{TICKER}/kpis.parquet` with no silent NaN for revenue (the most fragmented XBRL concept)
  2. All 20 KPIs (Revenue Growth YoY, CAGR, Gross Profit Margin, Operating Margin, Net Profit Margin, EBITDA Margin, ROE, ROA, Current Ratio, Quick Ratio, Cash Ratio, Working Capital, Debt-to-Equity, Debt-to-EBITDA, Interest Coverage, Debt-to-Assets, Asset Turnover, Inventory Turnover, DSO, Cash Conversion Cycle) are present as columns in `kpis.parquet`
  3. Companies with genuinely missing data have NaN rather than wrong values; no division-by-zero exceptions occur; outliers are preserved as-is
  4. Running the processor twice on the same raw data produces identical output (idempotent)
**Plans**: 2 plans

Plans:
- [ ] 02-01-PLAN.md — XBRL normalizer: CONCEPT_MAP (22 fields) + extract_concept() + normalize_xbrl()
- [ ] 02-02-PLAN.md — Cleaning + 20 KPI engine + atomic Parquet writer + process() entry point + end-to-end verification

### Phase 3: Orchestration & Batch
**Goal**: The FinancialAgent coordinates the full ETL pipeline per ticker with staleness detection, and can batch-process all 20 base companies in one command
**Depends on**: Phase 2
**Requirements**: ORCHS-01, ORCHS-02, ORCHS-03
**Success Criteria** (what must be TRUE):
  1. Calling `FinancialAgent(ticker).run()` on a ticker with no existing data produces complete `data/raw/` and `data/clean/` artifacts end-to-end without manual steps
  2. Calling `FinancialAgent(ticker).run()` on a ticker whose data is current for this quarter skips all SEC network requests and completes immediately
  3. Running the batch initializer produces clean Parquet files for all 20 base companies (AAPL, MSFT, NVDA, AMZN, META, GOOGL, GOOG, BRK.B, TSLA, LLY, AVGO, JPM, V, UNH, XOM, MA, JNJ, WMT, PG, HD)
  4. Adding a new KPI to `KPI_REGISTRY` does not require changes to the scraper, agent, or dashboard code
**Plans**: 3 plans

Plans:
- [x] 03-01-PLAN.md — KPI_REGISTRY refactor in processor.py (TDD: registry iteration + per-KPI error isolation)
- [x] 03-02-PLAN.md — FinancialAgent class with run() + needs_update() staleness detection + metadata.parquet
- [ ] 03-03-PLAN.md — run_batch() function + CLI entry point + full 20-ticker batch verification

### Phase 4: Dashboard
**Goal**: The Streamlit dashboard lets an analyst visually compare any combination of S&P 500 companies across all 20 KPIs over up to 10 years, and add new companies on demand
**Depends on**: Phase 3
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04
**Success Criteria** (what must be TRUE):
  1. An analyst can select any subset of the loaded companies and any of the 20 KPIs, and see a multi-line time-series chart that updates without page reload
  2. An analyst can adjust a year-range slider to restrict the chart to any window within the available 10-year history
  3. An analyst can type any valid S&P 500 ticker into the input field and see that company's data added to all charts within the same session, without restarting the app
  4. Switching between KPIs or adjusting filters does not re-query Parquet files on disk (Streamlit cache is active)
**Plans**: 3 plans

Plans:
- [x] 04-01-PLAN.md — App foundation: requirements.txt, app.py skeleton (page_config, @st.cache_data loaders, KPI_META registry, format_kpi)
- [ ] 04-02-PLAN.md — Full UI: sidebar controls + main canvas with Executive Cards (Plotly trend) + Comparativo overlay + dynamic layout
- [ ] 04-03-PLAN.md — Human verification checkpoint: automated smoke checks + browser validation of all DASH requirements

### Phase 5: Scheduling
**Goal**: The ETL pipeline runs automatically at the start of each quarter, keeping all loaded company data current without manual intervention
**Depends on**: Phase 4
**Requirements**: SCHED-01
**Success Criteria** (what must be TRUE):
  1. The scheduler triggers a full ETL run for all loaded companies at the start of each calendar quarter (January, April, July, October) without a human running a command
  2. After the scheduled run completes, the dashboard reflects updated data on the next page load
  3. If a scheduled run is triggered when data is already current for the quarter, the run completes quickly by skipping re-scraping (uses `needs_update()` logic from Phase 3)
**Plans**: 2 plans

Plans:
- [ ] 05-01-PLAN.md — Create scheduler.bat, quarterly_etl_task.xml, and register_task.bat infrastructure files
- [ ] 05-02-PLAN.md — Register task via schtasks CLI, trigger test run, human verify log output and Task Scheduler GUI

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Extraction | 2/2 | Complete    | 2026-02-25 |
| 2. Transformation & KPIs | 2/2 | Complete    | 2026-02-25 |
| 3. Orchestration & Batch | 2/3 | Complete    | 2026-02-26 |
| 4. Dashboard | 3/3 | Complete   | 2026-02-26 |
| 5. Scheduling | 0/2 | Not started | - |
