# Stack Research: SP500 Financial Dashboard

> Research date: 2026-02-24
> Scope: Python ETL pipeline for SEC EDGAR 10-K filings + local financial KPI dashboard via Streamlit
> Note: Web search and live PyPI verification were unavailable during this research session.
> Versions cited are based on training data through August 2025. Verify with `pip index versions <package>`
> before pinning in requirements.txt.

---

## Recommended Stack

### Data Extraction

#### Primary: `edgartools` (aka `edgar`) ~= 2.x

**Rationale:**
`edgartools` (installed as `pip install edgartools`, imported as `edgar`) is the clear winner for
2025/2026 EDGAR work. It wraps the full SEC EDGAR XBRL inline viewer API and the company facts
JSON endpoints in a Pythonic ORM-style interface. Key advantages:

- **XBRL-native**: `Company("AAPL").get_filings(form="10-K").latest().xbrl()` returns a parsed
  `XBRLData` object with `.financials` already structured — no manual XBRL parsing required.
- **Financial statement extraction**: Direct `.income_statement`, `.balance_sheet`,
  `.cash_flow_statement` properties return pandas DataFrames with normalized labels.
- **Company facts API**: Uses `https://data.sec.gov/api/xbrl/companyfacts/{cik}.json` which is the
  official EDGAR structured data endpoint — far more reliable than screen-scraping HTML filings.
- **Active maintenance**: Consistent releases through 2024–2025, responsive to EDGAR API changes.
- **SEC rate limiting built-in**: Respects the 10 requests/second SEC fair-use policy automatically.

**Version to pin:** `edgartools>=2.0` (verify latest: `pip index versions edgartools`)

**Confidence:** HIGH — this library has dominated EDGAR Python tooling since 2023 and has not been
displaced by a competitor as of August 2025.

#### Supplementary: Direct EDGAR XBRL API (no library)

For bulk SP500 data pulls, the SEC's own structured data endpoints are extremely useful alongside
edgartools:

- `https://data.sec.gov/submissions/{cik}.json` — filing history
- `https://data.sec.gov/api/xbrl/companyfacts/{cik}.json` — all reported XBRL facts
- `https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2023Q4I.json` — cross-company frame

Use `httpx` (async-capable) or `requests` with a `User-Agent` header (SEC requirement) for direct
calls. For SP500-scale batch downloads, the frames endpoint lets you pull a single concept across
all filers in one request — extremely efficient.

**Version to pin:** `httpx>=0.27` or `requests>=2.32`

#### What edgartools replaces:
- `sec-edgar-downloader`: Downloads raw filing documents (HTML/XML files to disk). Useful only if
  you need the full text of filings. For structured financial data extraction, it requires you to
  then parse XBRL yourself — a significant additional burden. Skip it for this use case.
- `python-xbrl`, `arelle`: Low-level XBRL parsers. Powerful but require deep XBRL taxonomy
  knowledge. Overkill when edgartools already handles this layer.

---

### Data Storage

#### Primary: `duckdb` ~= 1.x

**Rationale:**
DuckDB is the correct choice for a local financial data pipeline in 2025/2026. It is an embedded
analytical database (no server process) that outperforms SQLite on analytical queries by 10–100x
for the workloads this project requires (multi-year, multi-company aggregations and comparisons).

Key advantages for this project:

- **Columnar storage**: Financial time series (revenue by quarter across 500 companies over 10 years)
  maps perfectly to columnar layout. Scans are dramatically faster than row-oriented SQLite.
- **SQL interface with pandas/polars integration**: `duckdb.sql("SELECT ...").df()` returns a
  DataFrame directly. No ORM needed.
- **Parquet interop**: Can query Parquet files directly with `SELECT * FROM 'data/*.parquet'`
  without importing them — hybrid storage is seamless.
- **Zero dependencies, embedded**: Single binary, no server, works on Windows/Mac/Linux.
- **Window functions**: Essential for YoY growth rates, rolling averages, rank-within-sector KPIs.
  DuckDB has full SQL:2003 window function support; SQLite does not.
- **ATTACH multiple databases**: Can separate raw facts from processed KPIs cleanly.

**Version to pin:** `duckdb>=1.0` (1.0 was a major milestone release in 2024; as of Aug 2025 the
1.x series is stable)

**Confidence:** HIGH — DuckDB has become the de facto standard for local analytical workloads in
Python data pipelines. Strong community consensus.

#### Secondary: Parquet via `pyarrow` for archival/interchange

Use Parquet files as the raw data archive layer (immutable source-of-truth for scraped EDGAR data)
and DuckDB as the analytical layer on top. This gives you:

- Raw data that survives schema migrations (just re-process from Parquet)
- DuckDB queries directly over Parquet without a separate import step

**Version to pin:** `pyarrow>=16.0`

**Confidence:** HIGH

#### What NOT to use for storage:
- **SQLite**: Inadequate for analytical queries. Lacks window functions in older versions, slow on
  column scans, no native Parquet support. Fine for transactional data; wrong for this workload.
- **Pandas-only (CSV/pickle)**: No query capability, poor memory efficiency at SP500 scale, no
  concurrent access.
- **PostgreSQL/MySQL**: Overkill for local-only dashboard. Server process overhead unjustified.

---

### Data Processing

#### Primary: `pandas` ~= 2.x + `polars` ~= 1.x (situational)

**Rationale:**
Pandas 2.x (with the PyArrow backend via `pd.options.mode.dtype_backend = "pyarrow"`) is the
standard for financial data transformation. It integrates natively with DuckDB and edgartools.

- Use **pandas** as the default: edgartools returns DataFrames, Streamlit accepts DataFrames,
  DuckDB reads DataFrames. Staying in pandas minimizes conversion overhead.
- Use **polars** for heavy batch processing: If you are computing KPIs across all 500 companies
  simultaneously, Polars is 3–10x faster than pandas for group-by aggregations. Polars 1.x has a
  stable API as of 2025.

**Versions to pin:**
- `pandas>=2.1`
- `polars>=1.0` (optional, for batch ETL performance)
- `numpy>=1.26`

**Confidence:** HIGH

#### KPI calculation: `pandas-ta` or manual

For financial ratios (P/E, ROE, debt/equity, current ratio, etc.), implement them manually in
pandas/DuckDB SQL rather than using a specialized library. The calculations are simple enough that
a dedicated TA library is unnecessary overhead. Store KPI definitions in a central `kpis.py`
module for maintainability.

---

### Visualization

#### Primary: `streamlit` ~= 1.3x + `plotly` ~= 5.x

**Rationale:**

**Streamlit:**
- Industry standard for Python data dashboards in 2025. Zero front-end code required.
- `st.cache_data` decorator is essential for this project — cache DuckDB query results so
  switching between companies does not re-query the database.
- `st.session_state` for persisting selected companies, date ranges, and comparison state across
  widget interactions.
- Multipage apps (`pages/` directory) allow clean separation: overview page, single-company drill-
  down page, comparison page, ETL status page.

**Plotly:**
- Best choice for interactive financial charts. Native Streamlit support via `st.plotly_chart()`.
- Key patterns for multi-company time-series comparisons:
  - `px.line()` with `color="company"` parameter handles multi-company overlays automatically.
  - `go.Figure()` with multiple `go.Scatter()` traces for custom styling per company.
  - `fig.update_layout(hovermode="x unified")` for synchronized crosshair across all companies.
  - Faceted charts: `px.line(facet_col="metric")` to show Revenue, Net Income, EPS side-by-side.
  - Use `secondary_y=True` in `make_subplots()` for charts combining absolute values with ratios
    (e.g., Revenue bars + Gross Margin % line).

**Versions to pin:**
- `streamlit>=1.35`
- `plotly>=5.22`

**Confidence:** HIGH — Streamlit + Plotly is the dominant combination for this category of app.

#### Supplementary patterns:

```python
# Multi-company comparison — canonical pattern
import plotly.express as px
import streamlit as st

@st.cache_data(ttl=3600)
def load_metric(metric: str, tickers: list[str]) -> pd.DataFrame:
    return duckdb.sql(f"""
        SELECT ticker, fiscal_year, fiscal_quarter, {metric}
        FROM kpis
        WHERE ticker IN ({', '.join(f"'{t}'" for t in tickers)})
        ORDER BY ticker, fiscal_year, fiscal_quarter
    """).df()

tickers = st.multiselect("Companies", sp500_tickers, default=["AAPL", "MSFT", "GOOGL"])
metric = st.selectbox("Metric", ["revenue", "net_income", "gross_margin_pct", "roe"])
df = load_metric(metric, tickers)
fig = px.line(df, x="fiscal_year", y=metric, color="ticker",
              title=f"{metric} Comparison", markers=True)
fig.update_layout(hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)
```

---

### Scheduling

#### Primary: `APScheduler` ~= 3.x (local) or simple cron/Task Scheduler

**Rationale:**

For a **local** dashboard, the scheduling needs are minimal: run the ETL once per quarter when new
10-K filings become available (roughly Feb, May, Aug, Nov). Three options in order of preference:

**Option A: Windows Task Scheduler (recommended for local)**
For a purely local Windows machine, the OS scheduler is the most reliable option. Create a
`.bat` or Python script trigger. No Python dependency, survives reboots, visible in Task Scheduler
UI. This is the simplest and most robust approach for a personal tool.

**Option B: `APScheduler` 3.x (if in-process scheduling needed)**

```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(run_etl, 'cron', month='2,5,8,11', day='1', hour='6')
scheduler.start()
```

APScheduler is the standard Python library for in-process scheduling. Version 3.x has a stable,
well-documented API. Version 4.x (alpha/beta as of 2025) is a significant rewrite — **avoid 4.x**
until it reaches stable release.

**Option C: `schedule` library**

The `schedule` library (e.g., `schedule.every().monday.do(job)`) is simpler than APScheduler but
requires a long-running process and has no persistence. Not recommended for quarterly ETL that
needs to survive machine restarts.

**Versions to pin:**
- `apscheduler>=3.10,<4.0` (pin to 3.x explicitly to avoid APScheduler 4.x alpha)

**Confidence:** MEDIUM — for a local personal tool, OS-level scheduling is arguably better than
any Python library. APScheduler 3.x is the correct Python choice if in-process scheduling is
preferred.

#### What NOT to use for scheduling:
- **APScheduler 4.x**: Major API rewrite, was in alpha/beta as of mid-2025. Breaking changes from
  3.x. Do not use until stable release.
- **Celery/Redis**: Massively over-engineered for a local quarterly job. Requires a Redis server.
- **Airflow/Prefect/Dagster**: Workflow orchestration tools designed for production data
  engineering teams. The operational overhead (web server, database, worker processes) is
  completely unjustified for a personal local dashboard running 4 jobs per year.
- **`schedule` library for quarterly jobs**: Requires the process to be always running; not
  appropriate for jobs that run 4 times a year on a personal machine.

---

## Full Dependency Summary

```
# requirements.txt (pinned ranges)
edgartools>=2.0
httpx>=0.27
duckdb>=1.0
pyarrow>=16.0
pandas>=2.1
numpy>=1.26
polars>=1.0          # optional, for batch ETL performance
streamlit>=1.35
plotly>=5.22
apscheduler>=3.10,<4.0

# Dev/utility
python-dotenv>=1.0
loguru>=0.7          # structured logging for ETL pipeline
tenacity>=8.3        # retry logic for SEC API calls
tqdm>=4.66           # progress bars for bulk downloads
```

---

## What NOT to Use

| Library / Approach | Why to Avoid |
|---|---|
| `sec-edgar-downloader` | Downloads raw HTML/XML filing documents, not structured data. Requires manual XBRL parsing afterward. Use edgartools instead. |
| `python-xbrl` | Low-level XBRL parser, requires taxonomy expertise. Superseded by edgartools for this use case. |
| `arelle` | Full XBRL validation tool, enormous dependency footprint. Appropriate for XBRL authoring, not consumption. |
| `SQLite` for analytics | No columnar storage, limited window functions, slow on multi-company aggregations. Use DuckDB. |
| PostgreSQL/MySQL | Server process overhead unjustified for local-only tool. DuckDB gives 90% of the capability with 0% of the ops burden. |
| `APScheduler` 4.x | API rewrite in alpha/beta as of mid-2025. Stick to stable 3.x. |
| `Celery` + Redis | Production-grade task queue. Massive overkill for 4 ETL runs per year on a personal machine. |
| Airflow / Prefect / Dagster | Workflow orchestrators built for teams and production pipelines. Wrong scale for this project. |
| `bokeh` or `matplotlib` for charts | Plotly has better Streamlit integration, superior interactivity, and better multi-series support. Bokeh adds complexity without benefit. Matplotlib produces static charts. |
| `yfinance` as primary data source | Does not provide 10-K financial statement line items with XBRL precision. Good for price data supplement; wrong for fundamental analysis. |
| `BeautifulSoup` / `scrapy` for EDGAR | Screen-scraping HTML filings is fragile and violates the spirit of EDGAR's structured data APIs. The XBRL JSON endpoints are official, stable, and structured. |

---

## Key Findings

- **edgartools is the clear winner for EDGAR data extraction.** Its XBRL-native interface
  eliminates the need to write any XBRL parsing code, returning pandas DataFrames with normalized
  financial statement labels. The SEC's own company facts JSON API (which edgartools wraps) is
  the official, stable, structured data channel — far more reliable than HTML scraping.

- **DuckDB should replace both SQLite and pandas-as-database for this project.** The analytical
  query patterns required (multi-company, multi-year, cross-metric comparisons with window
  functions for YoY growth) map directly to DuckDB's columnar, SQL-first design. The performance
  difference over SQLite for these workloads is order-of-magnitude, not marginal.

- **Streamlit's `@st.cache_data` is architecturally critical.** Without it, every widget
  interaction triggers a DuckDB query and a full Python re-run. With it, the dashboard feels
  instant. Cache TTL of 1–24 hours is appropriate since EDGAR data changes only quarterly.

- **APScheduler 4.x is a trap.** It was undergoing a major API rewrite with breaking changes as
  of mid-2025. Pin explicitly to `>=3.10,<4.0`. For a Windows local machine, Windows Task
  Scheduler calling a Python script is actually the most robust approach and has zero Python
  dependencies.

- **Store raw EDGAR data as Parquet, process into DuckDB.** This two-layer architecture (immutable
  Parquet archive + DuckDB analytical layer) gives you schema evolution safety: if you add new KPI
  calculations, you re-process from the original Parquet without re-hitting the SEC API. DuckDB
  can query Parquet files directly, making the boundary seamless.

---

## Confidence Levels Summary

| Component | Recommendation | Confidence |
|---|---|---|
| EDGAR scraping | `edgartools` | HIGH |
| Storage (analytical) | `duckdb` | HIGH |
| Storage (archive) | Parquet via `pyarrow` | HIGH |
| Data processing | `pandas` 2.x | HIGH |
| Visualization | `streamlit` + `plotly` | HIGH |
| Scheduling (Python) | `apscheduler` 3.x | MEDIUM |
| Scheduling (OS) | Windows Task Scheduler | HIGH |

> MEDIUM confidence on APScheduler reflects the uncertainty around whether 4.x reached stable
> release between August 2025 and February 2026. Verify with `pip index versions apscheduler`
> and pin to `<4.0` as a precaution regardless.

---

*Generated by gsd-project-researcher | Knowledge cutoff: August 2025 | Live version verification
was not available during this session — run `pip index versions <package>` to confirm latest
stable releases before pinning.*
