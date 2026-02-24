# Architecture Research: SP500 Financial Dashboard

*Research type: Greenfield — Architecture dimension*
*Date: 2026-02-24*
*Project: SEC EDGAR financial ETL + Streamlit dashboard*

---

## Component Map

The system decomposes into five distinct components with explicit ownership boundaries. No component should reach into another's internal data structures directly; all cross-component communication happens through stable file formats or well-defined Python interfaces.

### 1. `scraper.py` — Extraction Layer

**Sole responsibility:** Talk to SEC EDGAR. Nothing else.

- Downloads the official `company_tickers.json` from `https://data.sec.gov/submissions/` at startup and saves it to `data/cache/tickers.json`
- Resolves `ticker → CIK` using the cached map (zero network calls for known tickers)
- Fetches 10-K filing index pages for a given CIK via `https://data.sec.gov/submissions/CIK{:010d}.json`
- Downloads raw XBRL JSON facts from `https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json`
- Enforces SEC rate limit: max 10 requests/second using a token-bucket or `time.sleep(0.1)` between calls
- Sets `User-Agent` header as required: `"YourName yourname@email.com"` (SEC policy)
- Writes raw output to `data/raw/{TICKER}/facts.json` — untouched, verbatim from SEC
- Has NO knowledge of KPIs, Parquet, or Streamlit

**What it does NOT do:** parse, transform, calculate, or render anything.

---

### 2. `processor.py` — Transformation + Load Layer

**Sole responsibility:** Turn raw SEC facts into clean, analysis-ready Parquet tables.

Sub-responsibilities within this file:

- **XBRL Normalizer**: Maps inconsistent XBRL concept names to canonical field names (see XBRL section below)
- **Cleaner**: Handles missing values (rolling median for gaps ≤ 2 years, propagation for structural gaps), deduplicates overlapping fiscal periods, selects annual (`10-K`) frames over quarterly ones
- **KPI Calculator**: Computes the 20 financial KPIs from cleaned base fields
- **Loader**: Writes three output Parquet files per company:
  - `data/clean/{TICKER}/financials.parquet` — normalized annual statements (10 years)
  - `data/clean/{TICKER}/kpis.parquet` — 20 calculated KPIs per year
  - `data/cache/metadata.parquet` — run timestamps, last-updated year per ticker, data completeness flags

Has NO knowledge of SEC HTTP endpoints or Streamlit widgets.

---

### 3. `app.py` — Presentation Layer

**Sole responsibility:** Read Parquet files, render the Streamlit dashboard. Never triggers ETL directly.

- Reads `data/clean/*/kpis.parquet` and `data/clean/*/financials.parquet` at session start
- Reads `data/cache/metadata.parquet` to show data freshness indicators
- Provides ticker input widget → delegates to `FinancialAgent` for on-demand ETL (via subprocess or direct call)
- Renders multi-company line charts (Plotly), KPI comparison tables, and year filters
- Caches Parquet reads with `@st.cache_data` to avoid re-reading on every interaction

Has NO knowledge of SEC URLs, XBRL concepts, or raw JSON formats.

---

### 4. `FinancialAgent` class — Orchestration Layer

**Sole responsibility:** Coordinate scraper and processor for a given ticker. The single entry point for adding a new company.

Lives in its own module: `agent.py` (or as a class within `scraper.py` if the project stays small — see Build Order).

```python
class FinancialAgent:
    def __init__(self, ticker: str, api_key: str, data_dir: Path):
        self.ticker = ticker
        self.cik = resolve_cik(ticker)          # uses cached tickers.json
        self.data_dir = data_dir

    def run(self, mode: str = "incremental") -> None:
        """mode: 'incremental' | 'full_refresh'"""
        ...

    def needs_update(self) -> bool:
        """Check metadata.parquet for last-updated year vs current year"""
        ...

    def extract(self) -> Path:
        """Calls scraper functions, returns path to raw facts.json"""
        ...

    def transform(self) -> None:
        """Calls processor functions on raw facts.json"""
        ...
```

---

### 5. Data Store — `/data/` directory

Not a running process, but a first-class architectural component:

```
data/
  raw/
    {TICKER}/
      facts.json          # verbatim XBRL company facts from SEC
  clean/
    {TICKER}/
      financials.parquet  # normalized base statements (10 years)
      kpis.parquet        # 20 KPIs per year
  cache/
    tickers.json          # SEC ticker→CIK map (refreshed quarterly)
    metadata.parquet      # run log: ticker, last_run, last_year_available, completeness %
```

---

## Data Flow

```
SEC EDGAR API
    |
    | HTTP (rate-limited, 10 req/s)
    v
scraper.py
    |
    | writes verbatim JSON
    v
data/raw/{TICKER}/facts.json
    |
    | reads raw JSON
    v
processor.py (XBRL Normalizer)
    |
    | normalized DataFrame (in memory)
    v
processor.py (Cleaner)
    |
    | clean DataFrame (in memory)
    v
processor.py (KPI Calculator)
    |
    | writes Parquet
    v
data/clean/{TICKER}/financials.parquet
data/clean/{TICKER}/kpis.parquet
data/cache/metadata.parquet
    |
    | reads Parquet (cached)
    v
app.py (Streamlit)
    |
    | renders
    v
Browser (localhost:8501)
```

The raw→clean split is intentional and critical: if the XBRL normalizer logic needs to be fixed (common), you re-run only `processor.py` without hitting SEC again. Raw JSON is a local checkpoint that protects against re-scraping.

### Incremental Update Logic

`metadata.parquet` stores `last_year_available` per ticker. On each run:

1. `FinancialAgent.needs_update()` compares `last_year_available` with `current_year - 1` (10-K for year N is filed in early N+1)
2. If stale: re-download `facts.json` (single file, contains all years) → re-run processor
3. If current: skip extraction, optionally re-run processor only if KPI definitions changed

Because EDGAR's `companyfacts` endpoint returns ALL historical years in one JSON file, "incremental" in this system means "re-download and re-process only the tickers that are stale" — not streaming row-level deltas. This is simpler and correct for annual data.

### Full Refresh

Deletes `data/raw/{TICKER}/facts.json` and `data/clean/{TICKER}/` before running. Triggered manually or when a schema change in `processor.py` requires reprocessing all data.

---

## FinancialAgent Design

### Design Goals

- **Extensible**: Adding a new KPI = add one function to the KPI calculator module, zero changes to `FinancialAgent`
- **Testable**: Each stage (extract, normalize, clean, calculate) is independently callable
- **Transparent**: Every step logs what it wrote and why it skipped

### Recommended Class Structure

```python
# agent.py
from pathlib import Path
from scraper import download_facts, resolve_cik
from processor import normalize_xbrl, clean_financials, calculate_kpis, save_parquet
from metadata import load_metadata, update_metadata

class FinancialAgent:
    """
    Orchestrates the full ETL pipeline for one ticker.
    Stateless between instantiations — all state lives in /data/.
    """

    DEFAULT_YEARS = 10  # 10-K lookback window

    def __init__(self, ticker: str, api_key: str, data_dir: Path = Path("data")):
        self.ticker = ticker.upper()
        self.api_key = api_key
        self.data_dir = data_dir
        self.cik = resolve_cik(ticker, cache_path=data_dir / "cache" / "tickers.json")

    def run(self, mode: str = "incremental", force: bool = False) -> dict:
        """
        Returns a result dict: {status, ticker, years_processed, errors}
        mode: 'incremental' skips up-to-date tickers
              'full_refresh' reprocesses regardless
        """
        if mode == "incremental" and not force and not self.needs_update():
            return {"status": "skipped", "ticker": self.ticker, "reason": "up_to_date"}

        raw_path = self.extract()
        df_clean = self.transform(raw_path)
        update_metadata(self.ticker, df_clean, self.data_dir)
        return {"status": "success", "ticker": self.ticker, "years_processed": len(df_clean)}

    def needs_update(self) -> bool:
        meta = load_metadata(self.data_dir / "cache" / "metadata.parquet")
        if self.ticker not in meta.index:
            return True
        last_year = meta.loc[self.ticker, "last_year_available"]
        return last_year < (pd.Timestamp.now().year - 1)

    def extract(self) -> Path:
        out_path = self.data_dir / "raw" / self.ticker / "facts.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        download_facts(self.cik, self.api_key, out_path)
        return out_path

    def transform(self, raw_path: Path) -> pd.DataFrame:
        raw = load_json(raw_path)
        df_norm = normalize_xbrl(raw, self.ticker)
        df_clean = clean_financials(df_norm)
        df_kpis = calculate_kpis(df_clean)
        save_parquet(df_clean, self.data_dir / "clean" / self.ticker / "financials.parquet")
        save_parquet(df_kpis,  self.data_dir / "clean" / self.ticker / "kpis.parquet")
        return df_clean
```

### Extensibility Patterns

**Adding a new KPI** (e.g., Free Cash Flow Yield):
- Add one function `def calc_fcf_yield(df) -> pd.Series` in `processor.py`
- Register it in a `KPI_REGISTRY` dict: `{"fcf_yield": calc_fcf_yield}`
- `calculate_kpis()` iterates the registry — no other changes needed

**Adding a new data source** (e.g., quarterly data from a different endpoint):
- Subclass `FinancialAgent`:
  ```python
  class QuarterlyAgent(FinancialAgent):
      def extract(self) -> Path:
          # override to hit quarterly endpoint
          ...
  ```

**Batch processing** (all 20 base companies):
```python
agents = [FinancialAgent(t, api_key) for t in TOP_20_TICKERS]
results = [a.run(mode="incremental") for a in agents]  # sequential, respects rate limit
```

---

## XBRL Concept Normalization

### The Problem

SEC XBRL filings use US-GAAP taxonomy concept names, but companies have discretion in which specific concept they use for the same economic quantity. Revenue alone has 7+ valid XBRL tags:

| Company | XBRL Tag Used |
|---------|---------------|
| Apple | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` |
| ExxonMobil | `us-gaap:Revenues` |
| JPMorgan | `us-gaap:InterestAndDividendIncomeOperating` (banking) |
| Berkshire | `us-gaap:Revenues` + segment overrides |

### Solution: Priority-Order Concept Lookup

Define a `CONCEPT_MAP` dictionary that maps canonical field names to an ordered list of XBRL concepts, tried in order until one is found with data:

```python
# processor.py
CONCEPT_MAP = {
    # --- Income Statement ---
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenueFromRelatedParties",  # last resort
    ],
    "net_income": [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ],
    "gross_profit": [
        "GrossProfit",
    ],
    "ebitda_proxy": [
        # No direct EBITDA in XBRL — must calculate: OperatingIncome + D&A
        # Flag this field as "calculated", not "extracted"
    ],

    # --- Balance Sheet ---
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "long_term_debt": [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "LongTermNotesPayable",
    ],

    # --- Cash Flow Statement ---
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
    ],

    # --- Share Data ---
    "shares_outstanding": [
        "CommonStockSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
}
```

### Extraction Function

```python
def extract_concept(facts: dict, concept_name: str, form: str = "10-K") -> pd.Series:
    """
    Try each XBRL tag in priority order.
    Returns annual values indexed by fiscal year end date.
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in CONCEPT_MAP.get(concept_name, []):
        if tag in us_gaap:
            units = us_gaap[tag].get("units", {})
            # Most financial values are in USD
            for unit_key in ["USD", "shares", "USD/shares"]:
                if unit_key in units:
                    entries = [
                        e for e in units[unit_key]
                        if e.get("form") == form and e.get("fp") == "FY"
                    ]
                    if entries:
                        return _entries_to_series(entries, concept_name)
    return pd.Series(dtype=float, name=concept_name)  # empty — log warning
```

### Handling Financial Sector Companies

Banks (JPM), insurers (BRK.B), and diversified financials have fundamentally different statement structures. Their "revenue" is `NetInterestIncome` or `PremiumsEarned`, not `RevenueFromContractWithCustomer`. Two approaches:

1. **Sector-aware CONCEPT_MAP**: Add a `CONCEPT_MAP_FINANCIALS` dict with bank-specific tags, select based on SIC code from the submission JSON
2. **Graceful degradation**: If all tags for a concept return empty, set the field to `NaN` and flag `completeness` in metadata — the KPI that depends on it will also be `NaN` but won't crash

Recommendation: Start with graceful degradation (simpler), add sector-specific maps in phase 2 once you see which companies have the most gaps.

### Period Deduplication

EDGAR facts include data from multiple filings (annual + amended). For each concept, multiple entries may cover the same fiscal year. Deduplication rule:

1. Filter to `form == "10-K"` and `fp == "FY"` (fiscal year, full period)
2. Among duplicates for the same `fy` year, prefer the entry with the latest `filed` date (most recent amendment)
3. Convert `end` date to `fiscal_year` integer (`end.year` or `end.year - 1` if `end.month < 6`)

---

## Suggested Build Order

Dependencies between components determine what must exist before what can be built.

### Phase 1: Data Foundation (build first)

**Build `scraper.py` core first** because all other components depend on having local data to work with.

1. `resolve_cik()` function + tickers.json download
   - Unblocks: all subsequent work
   - Test: `resolve_cik("AAPL")` returns `"0000320193"`

2. `download_facts()` function for a single ticker
   - Unblocks: processor development with real data
   - Test: `data/raw/AAPL/facts.json` exists and is ~5MB

3. Batch download for the Top 20 tickers
   - Unblocks: full-scale processor testing

### Phase 2: Transformation Core

**Build `processor.py` XBRL normalizer second**, once you have real `facts.json` files to test against.

4. `CONCEPT_MAP` + `extract_concept()` for 5-6 key fields (revenue, net_income, total_assets, cash, operating_cash_flow, capex)
   - Test against AAPL and JPM — two structurally different companies
   - Unblocks: KPI calculation

5. `clean_financials()` — deduplication, missing value handling, year selection
   - Unblocks: reliable KPI inputs

6. `calculate_kpis()` — implement all 20 KPIs
   - Unblocks: dashboard development

7. Parquet write/read round-trip verification
   - Unblocks: app.py reads

### Phase 3: Orchestration

**Build `FinancialAgent` third**, after scraper and processor are independently verified.

8. `FinancialAgent` class with `run()`, `needs_update()`, `extract()`, `transform()`
9. `metadata.parquet` write/read for incremental logic
10. Batch run of all 20 base tickers end-to-end

### Phase 4: Dashboard

**Build `app.py` last**, because it depends on all Parquet files existing.

11. Static dashboard: load existing Parquet files, render basic charts
12. Multi-company line chart with year filter (Plotly)
13. KPI comparison table
14. Dynamic ticker input → trigger `FinancialAgent.run()` → refresh dashboard data
15. Data freshness indicators from `metadata.parquet`

### Dependency Graph Summary

```
tickers.json resolution
    → download_facts()
        → CONCEPT_MAP + extract_concept()
            → clean_financials()
                → calculate_kpis()
                    → Parquet files
                        → FinancialAgent orchestration
                            → app.py dashboard
```

Each arrow is a hard dependency. Nothing to the right can be meaningfully built without everything to its left.

---

## Key Findings

- **The raw/clean split is the single most important architectural decision**: storing `facts.json` verbatim before transformation means XBRL normalization bugs (which will happen) can be fixed by re-running `processor.py` alone, with zero SEC API calls. Without this, every bug fix requires re-scraping.

- **XBRL concept inconsistency is the primary technical risk**: The 20 companies in scope span tech, energy, banking, healthcare, and retail — sectors with fundamentally different GAAP presentation choices. A priority-ordered `CONCEPT_MAP` with graceful degradation to `NaN` (rather than crashing) is the correct response; it makes gaps visible in the dashboard rather than silent.

- **`FinancialAgent` should be stateless and file-backed**: all state (last run, years available, completeness) lives in `metadata.parquet`, not in memory. This means the dashboard can inspect pipeline state without running the agent, and the agent can be safely re-run without in-memory coordination.

- **Incremental updates in this system mean ticker-level skipping, not row-level deltas**: EDGAR's `companyfacts` endpoint returns all years in one JSON blob. "Incremental" = only re-download and re-process tickers whose last available year is behind the current fiscal year. This is simpler and correct for annual-only data.

- **Build scraper → processor → agent → dashboard in strict order**: each layer can only be tested meaningfully once the layer below it produces real output. Attempting to build `app.py` before `processor.py` produces Parquet files leads to placeholder data that masks real normalization problems.

---

*Research conducted: 2026-02-24. Based on SEC EDGAR XBRL API structure, edgartools library design patterns, and established ETL pipeline architecture for financial data systems.*
