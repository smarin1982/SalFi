# Pitfalls Research: SP500 Financial Dashboard

> Research Type: Pitfalls — Greenfield project
> Domain: SEC EDGAR financial data pipeline + Streamlit dashboard
> Date: 2026-02-24

---

## SEC EDGAR Scraping Pitfalls

### 1. Rate Limit Violations (Hard Ban Risk)
**Warning signs:** HTTP 429 responses, sudden connection resets, requests silently returning empty responses.
**Details:** The SEC EDGAR EFTS and data APIs enforce a limit of **10 requests per second** per IP. Exceeding this triggers a temporary block; repeated violations escalate to longer bans. Many implementations use async fetching with a thread pool and forget that all threads share the same outbound IP.
**Prevention strategy:**
- Use a token-bucket or leaky-bucket rate limiter (e.g., `aiohttp` + `asyncio.Semaphore` capped at 8 req/s to leave headroom).
- Always include a `User-Agent` header identifying your app and contact email (required by SEC policy; missing header is itself grounds for blocking).
- Implement exponential backoff with jitter on 429/503 responses (start at 2 s, max 60 s).
- Never parallelize more than one concurrent connection per IP to EDGAR full-text endpoints.
**Phase:** Phase 1 (initial scraper) — build the limiter before any bulk fetch.

---

### 2. Missing or Malformed `User-Agent` Header
**Warning signs:** 403 Forbidden responses right from the start; works fine in browser but fails in code.
**Details:** SEC explicitly requires `User-Agent: CompanyName AppName contact@email.com`. Requests with generic agents (e.g., `python-requests/2.x`) are increasingly blocked.
**Prevention strategy:** Set `User-Agent` once at the session level. Add an integration test that verifies the header is present before any production run.
**Phase:** Phase 1 — day-zero configuration.

---

### 3. CIK Lookup Failures and CIK-Ticker Drift
**Warning signs:** Companies not found; CIK lookup returns a CIK that does not match the expected ticker.
**Details:** The `company_tickers.json` endpoint maps tickers to CIKs, but tickers change (post-merger, post-spin-off, symbol change). CIK is stable; ticker is not. Also, some companies have multiple CIK entries (subsidiaries filing separately).
**Prevention strategy:**
- Store CIK as the canonical identifier; never use ticker as a primary key in your data model.
- Cache `company_tickers.json` locally but refresh weekly; detect changes via hash diff.
- Cross-validate CIK against company name for any bulk operation.
- Handle the case where a ticker maps to zero or multiple CIKs — log and skip rather than fail silently.
**Phase:** Phase 1 (company universe setup).

---

### 4. EDGAR Full-Text Search vs. Structured Data API Confusion
**Warning signs:** XBRL data missing for a company that clearly filed; data exists in EDGAR but not via the structured API.
**Details:** EDGAR has two relevant APIs: the **submissions API** (`data.sec.gov/submissions/CIK.json`) and the **XBRL company facts API** (`data.sec.gov/api/xbrl/companyfacts/CIK.json`). Some filings are only in the submissions API (e.g., older non-XBRL filings). XBRL-tagged facts are only available via the companyfacts endpoint. Mixing these two leads to gaps.
**Prevention strategy:**
- Clearly separate your data-access layer: one module for submission listings, one for XBRL facts.
- For companies with filings before ~2009, expect XBRL gaps — document this as a known limitation.
- Use the `accessionNumber` as a stable join key between the two APIs.
**Phase:** Phase 1 (architecture decision).

---

### 5. Pagination and Incomplete Filing Lists
**Warning signs:** You only get the most recent N filings; historical data appears truncated.
**Details:** The submissions endpoint paginates older filings into separate `submissions/CIK-submissions-NNN.json` files linked from the main response. Many implementations only fetch the root file and miss years of history.
**Prevention strategy:**
- Parse the `files` array in the root submissions JSON and iterate all `data.sec.gov/submissions/` files for that CIK.
- Write a test that checks a known long-history company (e.g., $AAPL) returns filings going back to at least 2010.
**Phase:** Phase 1 (scraper completeness).

---

### 6. SSL Certificate and Network Retry Edge Cases
**Warning signs:** Occasional `SSLError` or `ConnectionResetError` in production; fails overnight but works during business hours.
**Details:** EDGAR servers occasionally drop connections, especially during off-peak maintenance windows. One-shot requests fail silently in scheduled jobs.
**Prevention strategy:**
- Use `requests.Session` with a `HTTPAdapter` configured with `max_retries=Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])`.
- Log every retry attempt with timestamp and URL for post-mortem analysis.
**Phase:** Phase 1-2 (infrastructure hardening).

---

## Financial Data Pitfalls

### 7. Missing XBRL Concept Names (Custom Taxonomies)
**Warning signs:** Revenue is `None` for a company even though it clearly has revenue; KPI calculations silently return NaN.
**Details:** US GAAP XBRL requires standard concept names (e.g., `us-gaap:Revenues`), but companies frequently use custom extensions (`dei:RevenueFromContractWithCustomerExcludingAssessedTax` vs `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`). Banks and financial companies are especially prone to this — they use `us-gaap:InterestAndDividendIncomeOperating` instead of `us-gaap:Revenues`.
**Prevention strategy:**
- Maintain a concept alias map: `{"Revenues": ["us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:SalesRevenueNet", ...]}`.
- Fall back through the alias list in priority order; log which alias was used so the map can be improved.
- Accept that some KPIs will be unavailable for some companies — surface this explicitly in the UI rather than showing `0` or a misleading value.
**Phase:** Phase 2 (KPI engine design).

---

### 8. Division by Zero in KPI Calculations
**Warning signs:** `inf`, `-inf`, or `NaN` values propagating into charts; entire dashboard breaks on one bad company.
**Details:** ROE = Net Income / Equity. ROA = Net Income / Assets. Gross Margin = Gross Profit / Revenue. Each denominator can legally be zero or negative (startup with no equity, quarter with $0 revenue due to discontinued ops).
**Prevention strategy:**
- Never use bare `/` for financial ratios. Always use a guarded function:
  ```python
  def safe_ratio(numerator, denominator, floor=None):
      if denominator is None or denominator == 0:
          return None
      result = numerator / denominator
      return result if floor is None else max(result, floor)
  ```
- Store KPIs as `Optional[float]` (nullable), never as 0 when undefined.
- In the dashboard, distinguish "value is zero" from "value is unavailable" with distinct visual treatment (e.g., `—` vs `0.0%`).
**Phase:** Phase 2 (KPI engine).

---

### 9. Negative Equity Makes ROE Meaningless
**Warning signs:** ROE chart shows -2000% for a company — technically correct but visually/analytically misleading.
**Details:** Companies like McDonald's carry negative book equity due to aggressive buybacks. ROE = Net Income / Negative Equity produces a negative ROE even when the company is highly profitable — the opposite of the intuitive interpretation.
**Prevention strategy:**
- Flag negative-equity ROE as analytically unreliable; display a warning in the dashboard.
- Offer an alternative metric (e.g., Return on Invested Capital / ROIC) that handles this case better.
- Do not include negative-equity ROE in cross-company ranking comparisons without disclosure.
**Phase:** Phase 2 (KPI engine) + Phase 3 (visualization warnings).

---

### 10. Fiscal Year vs. Calendar Year Misalignment in Period Comparisons
**Warning signs:** "Full Year 2023" for one company is actually Jan–Dec; for another it is Jul 2022–Jun 2023 — but both are labeled "FY2023".
**Details:** XBRL period labels use the end date of the fiscal year (`period.endDate`). A company with a June fiscal year end reports its FY2023 as ending 2023-06-30, but an investor comparing "FY2023" across companies assumes December.
**Prevention strategy:**
- Store the actual `period.startDate` and `period.endDate` from XBRL, never infer fiscal year from the year in the end date alone.
- Define `fiscal_year` as the *calendar year in which the fiscal year ends* (FY2023 = fiscal year ending in CY2023, regardless of month).
- When comparing companies for a given fiscal year, surface the actual end dates to the user.
- For TTM (trailing twelve months) calculations, always use 4 rolling quarters anchored to exact dates, not fiscal year labels.
**Phase:** Phase 2 (data model) — must be settled before KPI calculations.

---

### 11. Duplicate Facts from Amended Filings (10-K/A, 10-Q/A)
**Warning signs:** Revenue for Q3 2022 appears twice in your database with different values; charts show spikes.
**Details:** When a company restates financials, it files a 10-K/A or 10-Q/A. The XBRL facts API may return both the original and amended values for the same period. If you don't deduplicate, aggregations double-count.
**Prevention strategy:**
- Prefer the most recent filing for any given `(CIK, concept, period)` triple.
- Track the `accessionNumber` and `filed` date alongside every fact; when deduplicating, keep the fact from the highest `filed` date.
- Log when an amendment overrides an original value — this is also useful for detecting material restatements.
**Phase:** Phase 1-2 (data ingestion + storage schema).

---

### 12. Annualized vs. Point-in-Time Concepts
**Warning signs:** Balance sheet items (Assets, Equity) added across four quarters, producing 4x the actual value.
**Details:** XBRL has two concept types: **instantaneous** (balance sheet items, reported at a point in time — `Assets`, `LiabilitiesAndStockholdersEquity`) and **duration** (income/cash flow items, accumulated over a period — `NetIncomeLoss`, `Revenues`). Summing four quarters of `Assets` is nonsensical.
**Prevention strategy:**
- For TTM income statement aggregation: sum 4 quarterly duration values.
- For balance sheet: use the most recent quarter's instantaneous value — never sum.
- Maintain a concept-type registry that classifies every concept as `instant` or `duration`.
**Phase:** Phase 2 (KPI engine — critical architectural decision).

---

## Streamlit/Visualization Pitfalls

### 13. Re-Running Entire ETL on Every Page Interaction
**Warning signs:** Dashboard takes 10-30 seconds to respond to any filter change; users see loading spinners constantly.
**Details:** Streamlit reruns the entire script on every widget interaction. Without caching, this means re-reading Parquet files, re-computing KPIs, and re-filtering datasets on every click.
**Prevention strategy:**
- Use `@st.cache_data` for data loading and KPI computation functions. Set appropriate `ttl` (e.g., `ttl=3600` for hourly refresh).
- Load the full dataset once at startup; use Pandas/Polars filtering in-memory for user selections rather than re-reading from disk.
- For large Parquet datasets, use **predicate pushdown** via PyArrow: read only the columns and row groups needed for the current view.
**Phase:** Phase 3 (dashboard architecture).

---

### 14. `st.session_state` Corruption Across Page Navigations
**Warning signs:** Filters applied on page A bleed into page B; resetting a filter on one company affects another company's view.
**Details:** Streamlit's multi-page apps share `session_state` across pages. Widget keys that are not unique cause state collisions. Mutable objects (lists, dicts) stored in session_state and mutated in-place bypass Streamlit's change detection.
**Prevention strategy:**
- Use fully namespaced keys: `st.session_state["company_filter_page1"]` not `st.session_state["filter"]`.
- Never mutate session_state values in-place; always replace: `st.session_state["key"] = new_value`.
- Initialize all session_state keys in a single `init_session_state()` function called at the top of each page.
**Phase:** Phase 3 (dashboard architecture).

---

### 15. Parquet File Size and Column Bloat
**Warning signs:** First load takes 5+ seconds even with caching; memory usage spikes to multi-GB.
**Details:** Storing all XBRL facts (hundreds of concept names) for 500+ companies across 10+ years in a single wide Parquet file creates a massive dataset. Most users only view 5-10 KPIs at a time.
**Prevention strategy:**
- Use a **narrow fact table** schema: `(cik, ticker, concept, period_end, value, unit, filing_date)` rather than a wide pivoted table with one column per concept.
- Partition Parquet files by `cik` or `year` to enable partition pruning.
- Pre-compute and store the specific KPIs (Revenue, NetIncome, ROE, etc.) in a separate summary Parquet — load this for the dashboard; use the raw fact table only for drill-down.
- Use Polars instead of Pandas for filtering — significantly faster for large DataFrames.
**Phase:** Phase 2 (data storage design) — fixing this post-hoc is expensive.

---

### 16. Plotly/Altair Chart Performance with Many Data Points
**Warning signs:** Time-series chart with 500 companies x 40 quarters = 20,000 points causes browser lag.
**Details:** Client-side rendering in Plotly/Altair becomes slow above ~10,000 data points in a single chart. Streamlit sends the entire dataset to the browser as JSON.
**Prevention strategy:**
- Default charts to a max of 10-20 companies; require explicit "compare all" action.
- For trend charts, consider pre-aggregating to annual from quarterly for overview views.
- Use `st.plotly_chart(fig, use_container_width=True)` with `config={"displayModeBar": False}` for simpler rendering.
- Consider server-side rendering with Matplotlib for static snapshots of large comparison grids.
**Phase:** Phase 3 (visualization implementation).

---

### 17. Streamlit Deployment Memory Limits
**Warning signs:** App crashes or restarts on Streamlit Cloud after loading large datasets; works fine locally.
**Details:** Streamlit Community Cloud has a ~1 GB RAM limit per app. A 500-company, 10-year XBRL dataset can easily exceed this if loaded naively into a DataFrame.
**Prevention strategy:**
- Use `@st.cache_resource` for heavy singleton objects (database connections, large lookup tables).
- Consider a DuckDB in-process database instead of loading all Parquet data into RAM — DuckDB can query Parquet files on disk with SQL, returning only the slice needed.
- Set dtype precision appropriately: use `float32` instead of `float64` for financial ratios; use `int32` for counts.
**Phase:** Phase 3 (deployment planning).

---

## ETL/Scheduling Pitfalls

### 18. Timezone Confusion in Quarterly Scheduling
**Warning signs:** ETL runs at wrong time after daylight saving time change; "daily" job runs twice on one day.
**Details:** SEC filing deadlines are in US Eastern Time (ET). Cron jobs on UTC servers appear to shift relative to ET twice a year. A cron job set to `0 6 * * *` UTC means 1 AM ET in winter and 2 AM ET in summer — fine for overnight runs, but problematic if you're targeting a specific window after market close.
**Prevention strategy:**
- Express all scheduled times in **UTC** in cron/scheduler configuration, then document the ET equivalent.
- Use `pytz` or `zoneinfo` for any ET-aware date logic; never use naive `datetime.now()`.
- For quarterly earnings season (approx Jan, Apr, Jul, Oct), increase ETL run frequency to daily.
**Phase:** Phase 4 (scheduler setup).

---

### 19. Partial Run Corruption (Non-Atomic Writes)
**Warning signs:** Dashboard shows some companies with data through Q3 2024 and others only through Q1 2024 after an ETL run; inconsistent data mid-run.
**Details:** If the ETL writes company-by-company to Parquet and a run is interrupted (OOM, network timeout, crash), you end up with a partially updated dataset. Future runs that skip already-processed companies will perpetuate the partial state.
**Prevention strategy:**
- Write ETL output to a staging directory/file; atomically swap to production only on full success (rename/replace, not in-place write).
- Maintain a run manifest: `{run_id, started_at, completed_at, companies_processed, status}`. Only mark `status=success` on full completion.
- On restart, process companies in alphabetical/CIK order and use idempotent upsert logic rather than overwrite.
**Phase:** Phase 4 (ETL reliability).

---

### 20. Stale Data Detection Failure
**Warning signs:** Dashboard shows Q2 data labeled as "current" in November, when Q3 has already been filed; users trust outdated numbers.
**Details:** SEC filing deadlines: 10-Q is due 40 days after quarter end for large accelerated filers, 45 days for accelerated filers. Many pipelines check "did we run today?" rather than "is the data actually fresh relative to what should be available?"
**Prevention strategy:**
- Track `last_filing_date` per company; compare against the theoretical filing deadline for the most recent quarter end.
- Raise an alert if a company's most recent data is more than 60 days behind the expected filing deadline.
- In the dashboard, display a "Data as of [date]" label per company, not a global "Updated today" label.
**Phase:** Phase 4 (data freshness monitoring).

---

### 21. Re-Scraping Already-Fetched Filings (Wasteful and Ban-Prone)
**Warning signs:** ETL always re-fetches all filings from scratch; run time grows linearly with history depth.
**Details:** Fetching 10 years of 10-K/10-Q filings for 500 companies from scratch on every run wastes bandwidth, risks rate-limiting, and takes hours.
**Prevention strategy:**
- Maintain a local cache of `accessionNumber -> filing_data`; only fetch accession numbers that are not already cached.
- Use the `filed` date from the submissions API as a high-water mark: only fetch filings newer than `max(filed_date)` in your cache.
- For XBRL facts, use the `companyfacts` bulk download ZIP (available quarterly from SEC) as the baseline; layer incremental API calls on top.
**Phase:** Phase 1-4 (incremental design — must be planned upfront).

---

### 22. EDGAR Bulk Download vs. API Inconsistency
**Warning signs:** Bulk download has more/different data than the real-time API; reprocessing bulk gives different KPIs than live scraping.
**Details:** SEC provides quarterly bulk XBRL data dumps at `https://www.sec.gov/dera/data`. These dumps are point-in-time snapshots and may lag amendments filed after the dump date. The live API reflects the current state including amendments.
**Prevention strategy:**
- Use bulk downloads for historical backfill (faster, less rate-limit risk); use the live API for incremental updates.
- Document which data source was used for each filing in your manifest.
- For auditing, always be able to trace a KPI value back to its source `accessionNumber` and API endpoint.
**Phase:** Phase 1 (data architecture decision).

---

## Multi-Company Comparison Pitfalls

### 23. Fiscal Year End Heterogeneity Breaking Peer Comparisons
**Warning signs:** "FY2023 Revenue" for a retail company (Jan fiscal year) includes January 2024 sales; comparison to a calendar-year company is misleading.
**Details:** S&P 500 companies have fiscal year ends spread across all 12 months. Retail companies commonly use late January (Walmart: Jan 31). Tech companies commonly use December 31. A "same year" comparison can be 12 months apart in actual economic reality.
**Prevention strategy:**
- Always expose fiscal year end month in company metadata and in comparison tables.
- Offer two comparison modes: (1) by fiscal year label (FY2023 vs FY2023), (2) by calendar year overlap (actual dates overlapping a calendar year).
- Warn users when comparing companies whose fiscal year ends differ by more than 3 months.
**Phase:** Phase 3 (dashboard UX design).

---

### 24. Restatements Silently Changing Historical Comparables
**Warning signs:** "Revenue growth" calculation for a company changes overnight without a new quarter filing; historical chart shifts.
**Details:** Companies restate prior-period financials in subsequent filings. The amended 10-K will contain restated figures for prior years within its comparative financial statements. If you ingest these figures, your database now has revised historical data — but your dashboard may show this as a "change" in old data rather than a restatement.
**Prevention strategy:**
- Track data provenance: every financial fact has a `source_accession_number` and `source_filed_date`.
- When a new filing updates a prior-period value, log the delta as a restatement event.
- In the dashboard, show a "restatement flag" icon on data points that have been revised from their original values.
**Phase:** Phase 2 (data model) + Phase 3 (visualization).

---

### 25. M&A Events Breaking Time-Series Continuity
**Warning signs:** Revenue chart for an acquiring company jumps 40% in one quarter due to acquisition, falsely appearing as organic growth.
**Details:** Mergers, acquisitions, and divestitures create structural breaks in time-series financials. An acquisition adds the target's revenue immediately from the acquisition date. Organic growth rates cannot be calculated across these boundaries without pro-forma adjustment.
**Prevention strategy:**
- Flag quarters where a company filed an 8-K with Item 2.01 (Completion of Acquisition/Disposition) — this is available via the submissions API's form type filter.
- Show a visual indicator on the time-series chart at M&A event dates.
- Do not attempt to calculate YoY growth rates across acquisition quarters without explicitly labeling them as inorganic.
**Phase:** Phase 3 (visualization) + Phase 2 (data enrichment).

---

### 26. Survivorship Bias in S&P 500 Universe
**Warning signs:** All companies in your dataset show historically healthy performance; no bankruptcies or delistings appear.
**Details:** The S&P 500 index membership changes over time. If you use the *current* S&P 500 list as your universe and fetch historical data, you are implicitly selecting for companies that survived to the present — biasing any historical analysis.
**Prevention strategy:**
- Use a point-in-time S&P 500 membership list (available from data providers or via historical press releases) if historical accuracy is required.
- Clearly document in the dashboard that the universe is "current S&P 500 members" and that historical data for these companies may exhibit survivorship bias.
- If a company is delisted (e.g., acquired out of the index), retain its historical data rather than deleting it.
**Phase:** Phase 1 (scope definition) — decide upfront if point-in-time membership matters.

---

### 27. Sector/Industry Classification Inconsistency
**Warning signs:** Comparing "Retail" companies includes both pure-play retailers and conglomerates; peer benchmarks are meaningless.
**Details:** GICS sector classifications change over time (e.g., Meta moved from IT to Communication Services in 2018). Using current GICS for historical peer comparisons creates anachronistic groupings.
**Prevention strategy:**
- Store both current and historical GICS codes if sector-based peer analysis is a feature.
- For the MVP, use the current GICS code and disclose the limitation.
- Cross-reference with SIC codes from EDGAR DEI (Document and Entity Information) as a secondary classification.
**Phase:** Phase 1-2 (company metadata model).

---

## Key Findings

### Top 5 Most Critical Risks

**Risk 1 — XBRL Concept Name Fragmentation (Severity: Critical)**
Revenue and other core KPIs will silently return `None` for 10-30% of companies due to custom taxonomy extensions if you hardcode a single concept name. This is the #1 source of incorrect-looking data in financial dashboards built on EDGAR. Fix: build a concept alias fallback chain in Phase 2 before any KPI code is written.

**Risk 2 — Rate Limiting and IP Ban (Severity: Critical)**
A bulk fetch of 500 companies without a proper rate limiter will trigger an EDGAR IP ban within minutes of the first run. This blocks all development and testing. Fix: implement the rate limiter and `User-Agent` header as the very first line of scraper code in Phase 1.

**Risk 3 — Instant vs. Duration Concept Confusion (Severity: High)**
Summing four quarters of balance sheet items (instantaneous concepts) is a silent error that produces plausible-looking but completely wrong numbers. There is no runtime error — the aggregation just multiplies balance sheet figures by 4. Fix: establish the concept-type registry in Phase 2 before any TTM calculation logic.

**Risk 4 — Partial ETL Run Data Corruption (Severity: High)**
Without atomic writes, any interrupted ETL run leaves the production dataset in an inconsistent state where some companies are days or quarters behind others. Debugging this without a run manifest is extremely difficult. Fix: design atomic staging-swap writes and run manifests in Phase 4 before scheduling anything in production.

**Risk 5 — Fiscal Year Heterogeneity in Peer Comparisons (Severity: Medium-High)**
Users will naturally compare "FY2023" across companies without realizing they are comparing periods that may differ by up to 11 months of actual calendar time. This produces misleading conclusions in any peer benchmarking feature. Fix: expose fiscal year end dates in all comparison views and add a warning when fiscal year ends differ by more than 3 months (Phase 3, UX design gate).
