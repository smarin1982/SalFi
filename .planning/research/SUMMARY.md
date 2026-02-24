# Project Research Summary

**Project:** SP500 Financial Dashboard
**Domain:** Financial data pipeline + local analytical dashboard (SEC EDGAR / Python)
**Researched:** 2026-02-24
**Confidence:** HIGH

## Executive Summary

This project is a local Python ETL pipeline that extracts audited financial data from SEC EDGAR 10-K filings for S&P 500 companies and surfaces it through a Streamlit dashboard for multi-company comparison and KPI analysis. Expert consensus is clear on the technology choices: `edgartools` for XBRL-native extraction, DuckDB for analytical storage, pandas for transformation, and Streamlit + Plotly for visualization. The stack is mature, well-integrated, and designed for exactly this workload. No exotic choices are needed.

The architecture must follow a strict layered order: scraper (raw JSON) -> processor (Parquet) -> orchestrator (FinancialAgent) -> dashboard (Streamlit). Every component depends on the one before it producing real output, which means the build order is non-negotiable. The most critical architectural decision — and highest source of future bugs — is XBRL concept normalization. Revenue alone has 7+ valid XBRL tags across different sectors; a priority-ordered concept alias map with graceful NaN degradation must be built before any KPI code is written.

The dominant risk throughout the project is silent data correctness failures: wrong XBRL concept picked (revenue shows as None for 10-30% of companies), instantaneous vs. duration concept confusion (balance sheet items summed across quarters), fiscal year heterogeneity (FY2023 ends in June for some companies, December for others), and partial ETL runs leaving inconsistent data. None of these produce runtime errors — they produce plausible-looking wrong numbers. Mitigation requires defensive design at the data model layer in Phase 2, before the dashboard is built.

---

## Key Findings

### Recommended Stack

The stack is high-confidence across all components. `edgartools` (imported as `edgar`) is the clear winner for EDGAR access — it wraps the SEC's official XBRL company facts JSON API and returns pandas DataFrames with normalized financial statement labels, eliminating all manual XBRL parsing. DuckDB replaces both SQLite (inadequate window functions for YoY/CAGR calculations) and pandas-as-database (no query capability at SP500 scale). The Parquet + DuckDB two-layer pattern — immutable Parquet archive as source of truth, DuckDB as the analytical query layer — is the key architectural insight for storage: it allows XBRL normalization bugs to be fixed by re-running the processor without re-hitting the SEC API.

**Core technologies:**
- `edgartools >= 2.0`: EDGAR XBRL extraction — XBRL-native, returns DataFrames, SEC rate limiting built in
- `duckdb >= 1.0`: Analytical storage — columnar, embedded, window functions, Parquet interop, zero server overhead
- `pyarrow >= 16.0`: Parquet archive layer — immutable raw data store, survives schema migrations
- `pandas >= 2.1`: Data transformation — native edgartools and Streamlit integration
- `streamlit >= 1.35` + `plotly >= 5.22`: Dashboard and charts — `@st.cache_data` is architecturally critical for performance
- `apscheduler >= 3.10, < 4.0`: Scheduling — pin to 3.x explicitly; 4.x was in breaking-change alpha as of mid-2025
- `tenacity >= 8.3` + `loguru >= 0.7`: Retry logic and structured logging for ETL reliability

**What not to use:** SQLite (no window functions), PostgreSQL (server overhead unjustified), `sec-edgar-downloader` (raw HTML only, no structured data), APScheduler 4.x (API rewrite), Celery/Airflow (massive overkill for 4 ETL runs per year).

### Expected Features

The feature dependency chain is: EDGAR pipeline -> normalized data store -> financial statements -> derived KPIs -> comparison views -> screener/analytics. Everything in the differentiators section is gated on the data store being designed correctly in Phase 2.

**Must have (table stakes):**
- Source attribution on every data point — exact filing, filing date, fiscal year (trust foundation; professional users will verify)
- Core financial statements from 10-K: income statement, balance sheet, cash flow (5-10 years history)
- Derived KPIs: profitability ratios, leverage ratios, liquidity ratios, YoY/CAGR growth rates
- Multi-company side-by-side comparison table with sector/industry filtering
- Time-series line charts with multi-company overlay (Plotly `px.line` with `color="ticker"`)
- Clearly labeled fiscal year vs. calendar year (non-December fiscal years affect 30%+ of S&P 500)

**Should have (competitive differentiators):**
- Company screener: filter entire S&P 500 by metric combinations (high margin + high ROIC + accelerating growth) — this is the highest analytical value per engineering effort
- Normalized comparison (% of revenue) — removes size distortion for true peer analysis
- Indexed growth charts (set any year as 100) — reveals compounding differences
- CSV/DataFrame export — underrated; Macrotrends has strong analyst adoption specifically because of clean CSV export
- Trend direction indicators (up/down/flat icons, 3-year and 5-year view)
- Data freshness indicators per company (from metadata.parquet)
- Persistent comparison sets via `st.session_state`

**Defer to v2+:**
- Quarterly 10-Q data (inconsistent XBRL tagging, doubles pipeline complexity)
- Valuation multiples requiring market cap (P/E, EV/EBITDA) — market cap is not in 10-K filings; requires separate data source
- Segment-level revenue/profit breakdown (high complexity, high value for conglomerates)
- Anomaly flagging and peer auto-suggestion (depend on full SP500 data being clean first)
- Real-time price feeds, earnings transcripts, analyst estimates — not 10-K data, out of scope

### Architecture Approach

The system decomposes into five components with strict separation of concerns: scraper (only talks to SEC EDGAR), processor (only transforms raw JSON to Parquet), FinancialAgent (orchestrates one ticker end-to-end), data store (`/data/raw/` + `/data/clean/` + `/data/cache/`), and app.py (only reads Parquet, never triggers ETL inline). No component reaches into another's internal structures — all cross-component communication is via stable Parquet files or well-defined Python interfaces. The FinancialAgent is stateless between instantiations; all state lives in `metadata.parquet`.

**Major components:**
1. `scraper.py` — Extraction only: fetches `data.sec.gov` XBRL JSON, enforces 10 req/s rate limit, writes verbatim `data/raw/{TICKER}/facts.json`
2. `processor.py` — Transformation only: XBRL concept normalization (CONCEPT_MAP with priority fallback), deduplication (prefer latest `filed` date per period), KPI calculation, Parquet writes to `data/clean/{TICKER}/`
3. `FinancialAgent` (`agent.py`) — Orchestration: coordinates scraper + processor per ticker, `needs_update()` check via `metadata.parquet`, supports `incremental` and `full_refresh` modes
4. `data/` store — Three-layer file system: raw verbatim JSON (re-scrape protection), clean Parquet (analysis-ready), cache metadata (freshness tracking)
5. `app.py` — Presentation: reads Parquet via `@st.cache_data`, renders Plotly charts, never triggers ETL directly

### Critical Pitfalls

1. **XBRL concept name fragmentation** — Revenue has 7+ valid tags; banks use `InterestAndDividendIncomeOperating` not `Revenues`. Build a `CONCEPT_MAP` with priority-ordered alias fallback and NaN degradation in Phase 2 before any KPI code. This is the #1 source of silently wrong data.

2. **SEC rate limit violations (IP ban risk)** — 500 companies fetched without a rate limiter will trigger an EDGAR block within minutes. Implement the token-bucket limiter and `User-Agent` header (`"Name name@email.com"` format) as the very first lines of scraper code, before any bulk fetch.

3. **Instant vs. duration concept confusion** — Balance sheet items (Assets, Equity) are instantaneous snapshots; income/cash flow items are duration accumulations. Summing four quarters of Assets produces 4x the actual value with no runtime error. Establish a concept-type registry classifying every concept as `instant` or `duration` in Phase 2 before any TTM calculation logic.

4. **Partial ETL run corruption** — Without atomic writes, an interrupted run leaves some companies current and others stale. Design staging-directory writes with atomic swap on success and a run manifest (`run_id`, `started_at`, `completed_at`, `status`) in Phase 4 before scheduling.

5. **Fiscal year heterogeneity in peer comparisons** — "FY2023" for Walmart ends January 2024; for Apple it ends September 2023; for most tech companies it ends December 2023. Store actual `period.startDate` and `period.endDate` from XBRL. Warn users in the UI when comparing companies with fiscal year ends differing by more than 3 months.

---

## Implications for Roadmap

Based on research, the build order is determined by hard dependencies. Nothing to the right of each arrow can be meaningfully built without everything to its left: `CIK resolution -> download_facts -> CONCEPT_MAP/extract_concept -> clean_financials -> calculate_kpis -> Parquet files -> FinancialAgent orchestration -> app.py`.

### Phase 1: Data Foundation

**Rationale:** All downstream work is blocked without local data to process. Rate limiting and User-Agent setup must be day-zero to avoid SEC bans during development.
**Delivers:** Working scraper producing `data/raw/{TICKER}/facts.json` for Top 20 tickers; ticker-to-CIK resolution via cached `tickers.json`
**Addresses:** Data sourcing, company universe definition (current S&P 500, survivorship bias documented)
**Avoids:** Rate limit ban (implement limiter first), CIK drift (store CIK as canonical key, not ticker), pagination gaps (iterate all `submissions/CIK-submissions-NNN.json` files), EDGAR API vs. full-text confusion
**Research flag:** Standard patterns — EDGAR HTTP API is well-documented; no additional research needed

### Phase 2: Transformation Core and Data Model

**Rationale:** This is the highest-leverage phase. XBRL normalization bugs discovered here can be fixed by re-running processor.py without re-scraping. Data model decisions (concept types, fiscal year convention, deduplication rules) made here cannot be cheaply changed later.
**Delivers:** `data/clean/{TICKER}/financials.parquet` and `kpis.parquet` for Top 20 tickers; 20 calculated KPIs; `metadata.parquet` with completeness tracking
**Uses:** `edgartools` XBRL patterns, `duckdb`, `pyarrow`, `pandas 2.x`
**Implements:** `processor.py` with `CONCEPT_MAP`, `extract_concept()`, `clean_financials()`, `calculate_kpis()` with `safe_ratio()` guards
**Critical decisions here:** concept-type registry (instant vs. duration), fiscal year convention (end-date based), deduplication rule (latest `filed` date wins), `safe_ratio()` for all KPI denominators, negative-equity ROE flagging
**Avoids:** Concept fragmentation (alias fallback), division-by-zero (safe_ratio), instant/duration confusion (concept-type registry), duplicate amended filings (deduplicate by latest filed date)
**Research flag:** No additional research needed — architecture file provides full CONCEPT_MAP and extraction patterns

### Phase 3: Orchestration and Batch Processing

**Rationale:** `FinancialAgent` can only be meaningfully tested once scraper and processor are independently verified on real data.
**Delivers:** `FinancialAgent` class with `run(mode="incremental")`, `needs_update()` logic, batch processing of all 20 base tickers end-to-end; full `metadata.parquet` for all companies
**Implements:** `agent.py`, incremental update logic, batch runner script
**Avoids:** Re-scraping already-fetched filings (needs_update check), stale data detection failure (metadata tracking last_year_available)
**Research flag:** Standard patterns — well-defined in architecture research

### Phase 4: Dashboard (Basic)

**Rationale:** Build app.py last, once all Parquet files exist and are verified correct. Static first (read existing Parquet), then dynamic (trigger FinancialAgent on demand).
**Delivers:** Working Streamlit dashboard with multi-company line charts, KPI comparison table, year filter, data freshness indicators; `@st.cache_data` applied from day one
**Uses:** `streamlit >= 1.35`, `plotly >= 5.22`, `st.cache_data`, `st.session_state` with namespaced keys
**Addresses:** Table stakes features: core financial statements display, multi-company comparison, source attribution, fiscal year labeling
**Avoids:** Full ETL re-run on every widget interaction (cache_data), session_state corruption (namespaced keys, init function), chart performance issues (cap default comparison at 10-20 companies)
**Research flag:** Standard patterns — Streamlit + Plotly patterns are well-documented

### Phase 5: Analytical Features and Differentiators

**Rationale:** Can only be built once Phase 4 dashboard is reliable and data quality is verified across the full company set.
**Delivers:** Company screener (filter S&P 500 by metric combinations), normalized % of revenue comparison, indexed growth charts, CSV/DataFrame export, trend direction indicators, restatement flagging, M&A event markers on time-series
**Addresses:** Differentiator features from FEATURES.md; the screener is the highest analytical value per engineering effort
**Avoids:** Fiscal year heterogeneity warnings in peer comparison UI (display fiscal year end dates, warn on 3+ month delta), survivorship bias disclosure
**Research flag:** Screener feature may need additional research on efficient DuckDB query patterns for cross-company metric filtering at scale

### Phase 6: Scheduling and Reliability

**Rationale:** ETL reliability infrastructure should come after the pipeline is proven correct on the base dataset.
**Delivers:** Atomic ETL writes with staging-swap, run manifest, Windows Task Scheduler trigger (or APScheduler 3.x), stale data detection with per-company "data as of" labels
**Uses:** `apscheduler >= 3.10, < 4.0` or Windows Task Scheduler; `tenacity` for retry logic
**Avoids:** Partial run corruption (staging-swap + run manifest), timezone confusion (UTC scheduling documented with ET equivalent), re-scraping (incremental high-water mark)
**Research flag:** Standard patterns — APScheduler 3.x is stable and well-documented; verify APScheduler version stability before pinning

### Phase Ordering Rationale

- Phases 1-3 follow the hard dependency chain in the architecture (scraper -> processor -> orchestrator -> dashboard). Attempting Phase 4 before Phase 2 is complete means building on placeholder data that masks real normalization problems.
- Phase 2 is the critical path gate: data model decisions here (concept types, deduplication, fiscal year convention) cannot be cheaply changed after the dashboard is built against them.
- Phase 5 differentiators are deliberately deferred until data quality across the full company set is verified — analytical features built on wrong data are worse than no features.
- Phase 6 scheduling is last because atomic writes require knowing the ETL is stable; scheduling an unstable pipeline amplifies data corruption.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 5 (Screener):** DuckDB query patterns for cross-company metric filtering with multiple concurrent conditions at scale — may need optimization research if performance degrades with full SP500 dataset
- **Phase 2 (Financial sector companies):** Banks and insurers have structurally different GAAP presentation; may need a `CONCEPT_MAP_FINANCIALS` variant once gaps are observed — research which companies require sector-specific concept maps

Phases with standard patterns (skip research-phase):
- **Phase 1:** EDGAR HTTP API is fully documented at data.sec.gov; edgartools has clear usage patterns
- **Phase 3:** FinancialAgent orchestration follows standard ETL coordinator patterns
- **Phase 4:** Streamlit + Plotly multi-company chart patterns are well-established
- **Phase 6:** APScheduler 3.x and atomic file swap patterns are standard

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All core libraries are mature, well-integrated, and the dominant choices for this category. Single uncertainty: verify APScheduler has not hit a stable 4.x release since Aug 2025 cutoff. |
| Features | HIGH | Based on domain knowledge of Bloomberg, Koyfin, Macrotrends, and financial analyst workflows. Feature dependencies well-reasoned. |
| Architecture | HIGH | EDGAR XBRL API structure is well-documented. Component boundaries and CONCEPT_MAP patterns are grounded in real API behavior. |
| Pitfalls | HIGH | Pitfalls are grounded in specific XBRL API behaviors (instant vs. duration, concept fragmentation) and are well-evidenced. |

**Overall confidence:** HIGH

### Gaps to Address

- **Market cap data source for valuation multiples:** P/E, EV/EBITDA, P/B require market cap, which is not in 10-K filings. Recommendation is to defer to v2 or add as optional manual input. If included in Phase 5, decide on data source (yfinance for historical market cap is imprecise; no free authoritative source exists) before committing to the feature.

- **APScheduler 4.x release status:** The research knowledge cutoff is August 2025; as of that date APScheduler 4.x was in alpha/beta with breaking changes from 3.x. Run `pip index versions apscheduler` before Phase 6 to confirm whether stable 4.x has released and whether migration is worthwhile. Default: pin to `< 4.0`.

- **Financial sector company coverage:** Banks (JPM), insurers (BRK.B), and diversified financials use fundamentally different GAAP statement structures. The base CONCEPT_MAP covers most tech, consumer, healthcare, and industrial companies. Financial sector coverage will need validation in Phase 2 against real data and may require `CONCEPT_MAP_FINANCIALS` in Phase 5.

- **Survivorship bias decision:** The project currently scopes to current S&P 500 members. Historical analysis will have survivorship bias (all current members survived to present). This is a scope decision, not a bug — but must be disclosed in the dashboard UI.

---

## Sources

### Primary (HIGH confidence)
- SEC EDGAR XBRL company facts API (`data.sec.gov/api/xbrl/companyfacts/{cik}.json`) — direct API structure analysis
- SEC EDGAR submissions API (`data.sec.gov/submissions/{cik}.json`) — filing history structure
- `edgartools` library documentation and design patterns — XBRL extraction approach
- `duckdb` 1.x documentation — columnar storage, Parquet interop, window functions
- Streamlit documentation — `@st.cache_data`, `st.session_state`, multipage apps

### Secondary (MEDIUM confidence)
- Bloomberg Terminal, Koyfin, Macrotrends feature comparison — features and UX patterns
- US-GAAP XBRL taxonomy — concept name structures and sector variations
- APScheduler 3.x documentation — scheduling patterns (4.x status needs runtime verification)

### Tertiary (requires runtime validation)
- APScheduler 4.x release status — verify with `pip index versions apscheduler` before Phase 6
- Financial sector CONCEPT_MAP completeness — validate against real JPM, BRK.B, BAC data in Phase 2
- yfinance market cap data quality — validate before committing to valuation multiples feature

---
*Research completed: 2026-02-24*
*Ready for roadmap: yes*
