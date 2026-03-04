# Architecture Research

**Domain:** Financial data pipeline integration — LATAM extension onto existing Python/Streamlit dashboard
**Researched:** 2026-03-03
**Confidence:** HIGH

---

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          PRESENTATION LAYER                              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  app.py  (Streamlit — single unified dashboard)                  │   │
│  │  ┌────────────────────────┐  ┌───────────────────────────────┐   │   │
│  │  │  Section: S&P 500      │  │  Section: LATAM  [NEW]        │   │   │
│  │  │  (existing, unchanged) │  │  URL input, company cards,    │   │   │
│  │  │                        │  │  red flags, executive report  │   │   │
│  │  └────────────────────────┘  └───────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                         ORCHESTRATION LAYER                              │
│  ┌──────────────────────────┐  ┌──────────────────────────────────┐    │
│  │  FinancialAgent          │  │  LatamAgent.py  [NEW]            │    │
│  │  (agent.py — unchanged)  │  │  Orchestrates LATAM pipeline     │    │
│  └──────────────────────────┘  └──────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────────────┤
│                        TRANSFORMATION LAYER                              │
│  ┌─────────────────┐  ┌────────────────────┐  ┌───────────────────┐   │
│  │  processor.py   │  │  latam_processor.py │  │  currency.py      │   │
│  │  (unchanged)    │  │  [NEW]              │  │  [NEW]            │   │
│  └─────────────────┘  └────────────────────┘  └───────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                         EXTRACTION LAYER                                 │
│  ┌─────────────────┐  ┌────────────────────┐  ┌───────────────────┐   │
│  │  scraper.py     │  │  latam_scraper.py   │  │  web_search.py    │   │
│  │  (unchanged)    │  │  [NEW] Playwright   │  │  [NEW] DDG search │   │
│  └─────────────────┘  └────────────────────┘  └───────────────────┘   │
│                        ┌────────────────────┐                           │
│                        │  latam_extractor.py │                           │
│                        │  [NEW] PDF extract  │                           │
│                        └────────────────────┘                           │
├─────────────────────────────────────────────────────────────────────────┤
│                            DATA STORE                                    │
│  ┌──────────────────────────┐  ┌──────────────────────────────────┐    │
│  │  data/raw/{TICKER}/      │  │  data/latam/{country}/{slug}/    │    │
│  │  data/clean/{TICKER}/    │  │    financials.parquet  [NEW]     │    │
│  │  data/cache/             │  │    kpis.parquet        [NEW]     │    │
│  │  (existing, unchanged)   │  │    meta.json           [NEW]     │    │
│  └──────────────────────────┘  └──────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Status | Responsibility | Communicates With |
|-----------|--------|---------------|-------------------|
| `scraper.py` | EXISTING — no changes | SEC EDGAR extraction for US tickers | `agent.py` |
| `processor.py` | EXISTING — no changes | XBRL normalization + 20 KPI calculation | `agent.py` |
| `agent.py` (FinancialAgent) | EXISTING — no changes | US pipeline orchestration | `scraper.py`, `processor.py`, `app.py` |
| `latam_scraper.py` | NEW | Playwright web scraper — discovers PDF URLs on LATAM corporate sites | `LatamAgent.py` |
| `latam_extractor.py` | NEW | PDF extraction (pdfplumber + pytesseract + pymupdf) — returns structured financial tables | `LatamAgent.py` |
| `latam_processor.py` | NEW | Maps extracted LATAM financial data to the same KPI schema as `processor.py` | `LatamAgent.py` |
| `currency.py` | NEW | Frankfurter API — fetches period-average FX rates, converts local currency to USD | `latam_processor.py` |
| `web_search.py` | NEW | DuckDuckGo search — discovers regulatory source URLs and sector context | `LatamAgent.py` |
| `LatamAgent.py` | NEW | Orchestrates the full LATAM ETL pipeline for one company (mirrors FinancialAgent interface) | `app.py` |
| `app.py` | MODIFIED — LATAM section added | Unified Streamlit dashboard: existing S&P 500 section + new LATAM section | `agent.py`, `LatamAgent.py` |

---

## Recommended Project Structure

```
AI 2026/
├── scraper.py               # US: SEC EDGAR extraction (EXISTING — unchanged)
├── processor.py             # US: XBRL normalization + KPIs (EXISTING — unchanged)
├── agent.py                 # US: FinancialAgent orchestrator (EXISTING — unchanged)
├── app.py                   # Dashboard (EXISTING — add LATAM section)
│
├── latam_scraper.py         # LATAM: Playwright web scraper [NEW]
├── latam_extractor.py       # LATAM: PDF extraction pipeline [NEW]
├── latam_processor.py       # LATAM: Financial data → KPI schema mapping + USD normalize [NEW]
├── currency.py              # LATAM: Frankfurter FX API wrapper [NEW]
├── web_search.py            # LATAM: DuckDuckGo search wrapper [NEW]
├── LatamAgent.py            # LATAM: Orchestrator (mirrors FinancialAgent) [NEW]
│
├── data/
│   ├── raw/{TICKER}/        # US raw XBRL JSON (EXISTING — unchanged)
│   ├── clean/{TICKER}/      # US clean Parquet (EXISTING — unchanged)
│   ├── cache/               # US metadata + tickers.json (EXISTING — unchanged)
│   └── latam/               # LATAM storage root [NEW]
│       └── {country}/       # e.g., colombia/, peru/, chile/
│           └── {slug}/      # e.g., grupo-keralty/, clinica-bupa/
│               ├── financials.parquet   # same schema as US financials.parquet
│               ├── kpis.parquet         # same schema as US kpis.parquet
│               ├── meta.json            # company metadata (name, country, regulatory_id, source_url)
│               └── raw/                 # downloaded PDFs (optional, for audit trail)
│                   └── {year}_annual_report.pdf
│
├── requirements.txt         # EXISTING — add LATAM deps
├── scheduler.bat            # EXISTING — unchanged
└── tests/
    ├── test_scraper.py      # EXISTING
    └── test_latam_*.py      # NEW
```

### Structure Rationale

- **Parallel module structure:** Each new LATAM module has a clear US counterpart. `latam_scraper.py` mirrors `scraper.py`'s responsibility (extraction); `latam_processor.py` mirrors `processor.py`'s responsibility (transformation). This makes the codebase navigable for anyone who already understands the US pipeline.
- **`data/latam/{country}/{slug}/`:** Using country + slug (not ticker) as the directory key reflects how LATAM companies are identified: by name and country, not stock ticker. The slug is derived deterministically from `company_name.lower().replace(" ", "-")`.
- **Same Parquet schema in `data/latam/`:** `financials.parquet` and `kpis.parquet` use identical column schemas as the US equivalents. The dashboard reads both with the same loader functions. Only the source pipeline differs.
- **`meta.json` per company:** A lightweight JSON file (not Parquet) stores non-time-series metadata: company name, country, regulatory ID (NIT/RUC/RUT), source URL, regulatory authority, and last updated timestamp. JSON is chosen over Parquet here because this is a single-row record that changes rarely and needs to be human-readable.
- **`raw/` subfolder (optional):** Downloaded PDFs are stored for audit purposes — they are the source-of-truth equivalent of `data/raw/{TICKER}/facts.json` in the US pipeline. They allow re-extraction if the extractor logic improves without re-downloading.

---

## Architectural Patterns

### Pattern 1: Shared KPI Schema (Schema Compatibility Contract)

**What:** `latam_processor.py` produces `financials.parquet` and `kpis.parquet` with identical column names and dtypes as `processor.py` does for US companies. The dashboard reads both without knowing the source pipeline.

**When to use:** Any time two data sources need to share downstream consumers (dashboard, comparison logic).

**Trade-offs:** Forces LATAM data to fit the US KPI schema. Fields that don't exist in LATAM reports become `NaN` — the same graceful degradation pattern used for `BRK.B` in the US pipeline (e.g., `current_assets` is NaN for insurance companies). This is acceptable and consistent.

**Example:**
```python
# latam_processor.py — required output contract
def produce_financials(company_slug: str, country: str, data: dict) -> pd.DataFrame:
    """
    Must return DataFrame with columns matching processor.py's output:
    [ticker_or_slug, fiscal_year, revenue, gross_profit, cogs, operating_income,
     net_income, interest_expense, depreciation_amortization, total_assets,
     total_liabilities, total_equity, current_assets, current_liabilities,
     cash, short_term_investments, receivables, inventory, long_term_debt,
     short_term_debt, accounts_payable, shares_outstanding, operating_cash_flow, capex]
    All monetary values in USD (float). Missing fields: NaN, not 0.
    """
```

### Pattern 2: LatamAgent Mirrors FinancialAgent Interface

**What:** `LatamAgent.py` exposes the same public methods as `agent.py`'s `FinancialAgent` class: `run()`, `needs_update()`. The dashboard can call either agent through the same call pattern.

**When to use:** When two pipelines produce the same output type and need to be interchangeable from the caller's perspective.

**Trade-offs:** Enforces interface discipline on `LatamAgent`. The internal implementations differ significantly (no EDGAR, PDF-based extraction, FX conversion), but the contract from `app.py`'s perspective is identical.

**Example:**
```python
# LatamAgent.py
class LatamAgent:
    def __init__(self, company_name: str, country: str, source_url: str, data_dir: Path = DATA_DIR):
        self.slug = slugify(company_name)
        self.country = country.lower()
        self.source_url = source_url
        self.data_dir = data_dir

    def needs_update(self) -> bool:
        """Returns True if last_processed is not current-quarter (same logic as FinancialAgent)."""
        meta_path = self.data_dir / "latam" / self.country / self.slug / "meta.json"
        if not meta_path.exists():
            return True
        meta = json.loads(meta_path.read_text())
        last = pd.Timestamp(meta.get("last_processed", "2000-01-01"))
        return not _same_quarter(last, pd.Timestamp.now())

    def run(self, force_refresh: bool = False) -> dict:
        """Full LATAM ETL: scrape → extract → process → save. Returns status dict."""
        ...
```

### Pattern 3: Currency Normalization as a Pure Function Module

**What:** `currency.py` is a stateless module that takes `(amount, currency_code, fiscal_year)` and returns `amount_usd`. It fetches period-average rates from the Frankfurter API and caches results locally to avoid repeated API calls.

**When to use:** Any time monetary values from multiple currencies need to be compared or aggregated.

**Trade-offs:** Period-average rates (not year-end rates) are used by convention for income statement items. Balance sheet items ideally use year-end rates — but for this pipeline, period-average is applied uniformly across all statement types for simplicity. This is a documented approximation, not an error.

**Example:**
```python
# currency.py
import json
import requests
from pathlib import Path
from functools import lru_cache

CACHE_FILE = Path("data/cache/fx_rates.json")

@lru_cache(maxsize=256)
def get_period_average_rate(currency: str, year: int) -> float:
    """
    Returns USD/currency rate for the given calendar year (annual average).
    Uses frankfurter.app API. Results cached to disk.
    Raises ValueError if currency or year is not available.
    """
    url = f"https://api.frankfurter.app/{year}-01-01..{year}-12-31?from={currency}&to=USD"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    rates = resp.json()["rates"]
    # Average all daily rates for the year
    usd_rates = [day_rates["USD"] for day_rates in rates.values()]
    return sum(usd_rates) / len(usd_rates)

def to_usd(amount: float, currency: str, year: int) -> float:
    if currency == "USD":
        return amount
    rate = get_period_average_rate(currency, year)
    return amount * rate
```

---

## Data Flow

### US Pipeline (Existing — Unchanged)

```
SEC EDGAR API (rate-limited, 8 req/s)
    |
    v
scraper.py
    |  writes verbatim JSON
    v
data/raw/{TICKER}/facts.json
    |  reads raw JSON
    v
processor.py (XBRL normalize → clean → KPIs)
    |  writes atomic Parquet
    v
data/clean/{TICKER}/financials.parquet
data/clean/{TICKER}/kpis.parquet
data/cache/metadata.parquet
    |  reads Parquet (st.cache_data)
    v
app.py — S&P 500 section
```

### LATAM Pipeline (New)

```
User provides: company name + country + corporate website URL
    |
    v
web_search.py (optional: find regulatory source URL via DuckDuckGo)
    |
    v
latam_scraper.py (Playwright: navigate to URL, find PDF links, download PDFs)
    |  writes PDF files (optional)
    v
data/latam/{country}/{slug}/raw/{year}_report.pdf
    |  reads PDFs
    v
latam_extractor.py (pdfplumber → table extraction; pytesseract → OCR fallback; pymupdf → text)
    |  returns: dict of {fiscal_year: {field: value_in_local_currency}}
    v
latam_processor.py (map fields to KPI schema → currency.py → USD normalization → calculate KPIs)
    |  calls currency.py for each monetary field
    v
currency.py (frankfurter API → period-average FX rate → in-memory cache)
    |  returns: USD-normalized financial DataFrame
    v
latam_processor.py
    |  writes atomic Parquet (same save_parquet() pattern as processor.py)
    v
data/latam/{country}/{slug}/financials.parquet
data/latam/{country}/{slug}/kpis.parquet
data/latam/{country}/{slug}/meta.json
    |  reads Parquet (st.cache_data)
    v
app.py — LATAM section (company cards, red flags, executive report)
```

### Orchestration: LatamAgent coordinates the LATAM flow

```
app.py (user submits URL input)
    |
    v
LatamAgent.run()
    ├── needs_update()? → reads meta.json
    ├── latam_scraper.find_pdf_urls(source_url)
    ├── latam_extractor.extract_tables(pdf_paths)
    ├── latam_processor.process(extracted_data, company_slug, country)
    │       └── currency.to_usd(amount, currency, year) [per field per year]
    └── write financials.parquet, kpis.parquet, meta.json
```

### Key Data Flows

1. **On-demand LATAM ETL:** User enters URL in dashboard → `app.py` calls `LatamAgent.run()` → full pipeline executes → `st.cache_data.clear()` → dashboard re-renders with new LATAM company.
2. **Dashboard read path (LATAM):** `app.py` scans `data/latam/*/*/kpis.parquet` with glob → loads each → identical display logic as US section.
3. **Cross-pipeline comparison:** If a future feature compares US vs. LATAM, both pipelines already produce the same Parquet schema — no transformation needed.

---

## Integration Points

### New vs. Modified vs. Unchanged Components

| File | Action | What Changes |
|------|--------|-------------|
| `scraper.py` | UNCHANGED | None |
| `processor.py` | UNCHANGED | None |
| `agent.py` | UNCHANGED | None |
| `scheduler.bat` | UNCHANGED | None (LATAM runs on-demand, not scheduled in v2.0) |
| `requirements.txt` | MODIFIED | Add: playwright, pdfplumber, pytesseract, pymupdf, duckduckgo-search, weasyprint, requests |
| `app.py` | MODIFIED | Add LATAM section: URL input widget, company card rendering, red flag display, PDF report download button |
| `latam_scraper.py` | NEW | Playwright scraper |
| `latam_extractor.py` | NEW | PDF extraction pipeline |
| `latam_processor.py` | NEW | Financial mapping + KPI calculation + USD normalization |
| `currency.py` | NEW | Frankfurter FX wrapper |
| `web_search.py` | NEW | DuckDuckGo search wrapper |
| `LatamAgent.py` | NEW | LATAM orchestrator |

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| LATAM corporate websites | Playwright (headless Chromium) via `latam_scraper.py` | JS-rendered pages require Playwright, not requests+BeautifulSoup |
| Frankfurter API (`api.frankfurter.app`) | Simple REST GET in `currency.py` | Free, no API key, returns historical daily rates; cache results in `data/cache/fx_rates.json` to avoid repeated calls |
| DuckDuckGo Search | `duckduckgo-search` Python library in `web_search.py` | Free, no API key, rate-limit: add 1s delay between searches; used for regulatory source discovery |
| Regulatory portals (Supersalud, SMV, SFC, CMF, CNV, CNBV) | HTTP download via `requests` in `latam_scraper.py` | Static PDFs from government sites; simpler than corporate sites |
| SEC EDGAR | Unchanged — `scraper.py` handles this independently | US pipeline unaffected |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `latam_scraper.py` → `latam_extractor.py` | File paths to downloaded PDFs | Scraper writes PDFs to `data/latam/{country}/{slug}/raw/`; extractor reads them |
| `latam_extractor.py` → `latam_processor.py` | Python dict: `{fiscal_year: {field: (value, currency)}}` | Raw extracted values with original currency codes; processor handles USD conversion |
| `latam_processor.py` → `currency.py` | Function call: `to_usd(amount, currency, year)` | Pure function; `currency.py` has no knowledge of Parquet or company structure |
| `LatamAgent.py` → all LATAM modules | Direct Python imports (same pattern as `agent.py` → `scraper.py` + `processor.py`) | LatamAgent is the single caller; modules don't call each other directly |
| `app.py` → `LatamAgent.py` | `LatamAgent(name, country, url).run()` — mirrors `FinancialAgent(ticker).run()` | Same call pattern; app doesn't need to know which pipeline is being used |
| `app.py` → `data/latam/` | `pd.read_parquet()` via `st.cache_data` loader — same as US | `load_latam_kpis(slug, country)` mirrors existing `load_kpis(ticker)` function |

---

## Build Order

Dependencies between components determine what must exist before what can be built. The LATAM pipeline has its own internal dependency chain that is independent of the US pipeline.

### Recommended Build Order (LATAM v2.0)

**Step 1 — `currency.py`**
- No dependencies on other LATAM modules
- Tests with static inputs (e.g., `to_usd(1000, "COP", 2023)`) before any scraping is needed
- Unblocks: `latam_processor.py`

**Step 2 — `web_search.py`**
- No dependencies on other LATAM modules
- Simple wrapper; test with known company names
- Unblocks: `LatamAgent.py` (used for regulatory source discovery)

**Step 3 — `latam_scraper.py`**
- Depends on: a known corporate URL to test against
- Uses `currency.py` indirectly (not directly — scraper is extraction-only)
- Test: given a LATAM healthcare company URL, returns a list of PDF download URLs
- Unblocks: `latam_extractor.py`

**Step 4 — `latam_extractor.py`**
- Depends on: at least one real PDF downloaded by `latam_scraper.py`
- Three extraction modes in priority order: pdfplumber (structured tables), pymupdf (text extraction), pytesseract (OCR fallback)
- Test: given a real annual report PDF, extracts revenue, net income, total assets for at least one fiscal year
- Unblocks: `latam_processor.py`

**Step 5 — `latam_processor.py`**
- Depends on: `latam_extractor.py` (input data), `currency.py` (FX conversion), `processor.py`'s `KPI_REGISTRY` and `calculate_kpis()` (reused directly)
- Maps extracted fields to the canonical schema; calls `currency.py`; reuses `calculate_kpis()` from `processor.py` unchanged
- Writes `financials.parquet` and `kpis.parquet` with identical schema to US output
- Unblocks: `LatamAgent.py`, `app.py` LATAM section

**Step 6 — `LatamAgent.py`**
- Depends on: all LATAM modules above
- Mirrors `FinancialAgent` interface: `run()`, `needs_update()`
- Test end-to-end on one real LATAM healthcare company
- Unblocks: `app.py` LATAM section

**Step 7 — `app.py` LATAM section**
- Depends on: `LatamAgent.py`, at least one LATAM company with Parquet data written
- Add: URL input widget, `LatamAgent.run()` call, company card display, red flag engine, executive report + weasyprint PDF download
- Does not break existing S&P 500 section (additive modification only)

### Dependency Graph

```
currency.py
    └── latam_processor.py
            └── LatamAgent.py
                    └── app.py (LATAM section)

web_search.py
    └── LatamAgent.py

latam_scraper.py
    └── latam_extractor.py
            └── latam_processor.py

processor.py (existing)
    └── calculate_kpis() reused by latam_processor.py [import, not modification]
```

Each arrow is a hard dependency. The US pipeline (`scraper.py`, `processor.py`, `agent.py`) runs in parallel and has no dependency on any LATAM module.

---

## Storage Schema

### LATAM Storage: `data/latam/{country}/{slug}/`

**Backwards-compatible:** The LATAM storage tree lives under `data/latam/` — a new subtree that does not touch `data/raw/`, `data/clean/`, or `data/cache/`. The US pipeline cannot accidentally overwrite LATAM data.

**`financials.parquet` — identical column schema to US `data/clean/{TICKER}/financials.parquet`:**

| Column | Type | Notes |
|--------|------|-------|
| `ticker` | str | For LATAM: use `{slug}` (e.g., `grupo-keralty`) |
| `fiscal_year` | int | Calendar year of fiscal year end (same convention as US) |
| `revenue` | float (USD) | After FX conversion; NaN if not extractable |
| `gross_profit` | float (USD) | NaN if not in report |
| `cogs` | float (USD) | NaN if not in report |
| `operating_income` | float (USD) | NaN if not in report |
| `net_income` | float (USD) | NaN if not in report |
| `interest_expense` | float (USD) | NaN if not in report |
| `depreciation_amortization` | float (USD) | NaN if not in report |
| `total_assets` | float (USD) | |
| `total_liabilities` | float (USD) | |
| `total_equity` | float (USD) | |
| `current_assets` | float (USD) | NaN for companies that don't report separately |
| `current_liabilities` | float (USD) | NaN for companies that don't report separately |
| `cash` | float (USD) | |
| `short_term_investments` | float (USD) | NaN if not in report |
| `receivables` | float (USD) | |
| `inventory` | float (USD) | NaN for service companies |
| `long_term_debt` | float (USD) | |
| `short_term_debt` | float (USD) | |
| `accounts_payable` | float (USD) | |
| `shares_outstanding` | float | NaN for private companies |
| `operating_cash_flow` | float (USD) | |
| `capex` | float (USD) | |

**`kpis.parquet` — identical column schema to US `data/clean/{TICKER}/kpis.parquet`:**

Same 20 KPI columns. `calculate_kpis()` from `processor.py` is called directly on the LATAM `financials.parquet` — no separate KPI implementation needed.

**`meta.json` — LATAM-specific metadata (no US equivalent):**

```json
{
  "company_name": "Grupo Keralty",
  "slug": "grupo-keralty",
  "country": "colombia",
  "regulatory_id": "NIT 860.007.336-4",
  "regulatory_authority": "Supersalud",
  "source_url": "https://keralty.com/informes-financieros",
  "regulatory_url": "https://supersalud.gov.co/...",
  "currency_original": "COP",
  "last_scraped": "2026-03-03T10:00:00",
  "last_processed": "2026-03-03T10:05:00",
  "fiscal_years_available": [2020, 2021, 2022, 2023, 2024],
  "extraction_quality": "high",
  "fields_extracted": ["revenue", "net_income", "total_assets", "total_equity"],
  "fields_missing": ["shares_outstanding", "short_term_investments"]
}
```

---

## Anti-Patterns

### Anti-Pattern 1: Modifying `processor.py` to Handle LATAM Data

**What people do:** Add LATAM-specific logic (PDF parsing, FX conversion, name-based lookups) directly into `processor.py` to avoid creating a new module.

**Why it's wrong:** `processor.py` is the validated, working US KPI engine. Any modification risks breaking the existing S&P 500 pipeline. The separation of concerns is explicit and intentional: `processor.py` knows only XBRL JSON; `latam_processor.py` knows only LATAM financial tables.

**Do this instead:** Create `latam_processor.py` as a separate module. Have it `import processor` and call `processor.calculate_kpis()` — reusing the KPI calculation logic without touching the US module.

---

### Anti-Pattern 2: Using a Different Parquet Schema for LATAM Data

**What people do:** Add LATAM-specific columns (`currency_original`, `fx_rate_used`) to the `financials.parquet` schema so LATAM files have a different shape than US files.

**Why it's wrong:** The dashboard's data loaders expect a single consistent schema. Two different schemas require branching logic everywhere that reads Parquet — in chart builders, in KPI selectors, in comparison views. This doubles maintenance burden immediately and grows with every new feature.

**Do this instead:** Keep the identical schema. Store FX metadata in `meta.json` (not in the Parquet). The Parquet files contain USD-normalized values only. Any audit trail (original values, FX rate used) lives in `meta.json` or a separate audit log, not in the primary analytics tables.

---

### Anti-Pattern 3: Storing LATAM Data Under `data/clean/{SLUG}/`

**What people do:** Use the existing `data/clean/` tree to store LATAM output alongside US tickers (e.g., `data/clean/KERALTY/`).

**Why it's wrong:** `data/clean/` is populated exclusively by the US pipeline (via `processor.py` which uses `data/raw/{TICKER}/facts.json` as input). Putting LATAM data there creates a naming conflict risk, mixes the two pipelines' audit trails, and makes it impossible to determine which data came from EDGAR vs. PDF extraction.

**Do this instead:** Use `data/latam/{country}/{slug}/` as the LATAM storage root. The separation is explicit in the directory tree. `app.py` scans both trees separately with different glob patterns: `data/clean/*/kpis.parquet` for US and `data/latam/*/*/kpis.parquet` for LATAM.

---

### Anti-Pattern 4: Calling `LatamAgent.run()` Synchronously in the Dashboard for Slow Extractions

**What people do:** Call `LatamAgent.run()` directly in the Streamlit main thread, blocking the UI for the entire PDF download + OCR extraction time (potentially 30-120 seconds).

**Why it's wrong:** Streamlit's execution model re-runs the entire script. A blocking call of 30-120 seconds freezes the browser tab with a spinner and provides no progress feedback. Users assume it crashed.

**Do this instead:** Wrap the `LatamAgent.run()` call in `st.spinner()` with a descriptive message. For very long extractions, consider running `LatamAgent` as a subprocess or background thread and polling `meta.json` for completion status. At minimum, break the call into stages with intermediate `st.status()` updates (Playwright navigation, PDF download, extraction, processing).

---

## Scaling Considerations

This is a local professional tool, not a multi-tenant SaaS product. Scaling considerations are limited to practical file/performance limits on a single machine.

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1-10 LATAM companies | Current design is optimal. Per-company Parquet files, no aggregation needed. |
| 10-50 LATAM companies | Add `data/latam/cache/metadata.parquet` (mirrors US `data/cache/metadata.parquet`) to track LATAM company registry. Glob-based discovery becomes slower; a registry is faster. |
| 50+ LATAM companies | Consider a DuckDB layer that queries `data/latam/*/*/kpis.parquet` via glob for cross-company LATAM analysis — same pattern recommended in existing STACK.md research for US pipeline at scale. |

### Scaling Priorities

1. **First bottleneck:** PDF extraction time. OCR (pytesseract) is slow — 30-90 seconds per page for scanned documents. Mitigation: cache extracted tables (not just raw PDFs) in a `tables.json` alongside the PDF so re-extraction is not needed on re-runs.
2. **Second bottleneck:** Playwright startup time. Each `LatamAgent.run()` starts a new Playwright browser instance. If multiple LATAM companies are processed in a batch, reuse a single browser context across all scraping calls in the batch run.

---

## Sources

- Direct code analysis of existing `agent.py`, `processor.py`, `scraper.py`, `app.py` (HIGH confidence — source of truth)
- PROJECT.md milestone specification (HIGH confidence — authoritative requirements)
- Frankfurter API documentation: `api.frankfurter.app` — free REST API for historical FX rates (MEDIUM confidence — verified endpoint exists, rate limits not formally documented)
- Playwright Python docs: `playwright.dev/python` — headless browser automation (HIGH confidence — standard tool, well-documented)
- `duckduckgo-search` Python library: `pypi.org/project/duckduckgo-search` — DDG API wrapper (MEDIUM confidence — free, no API key, rate-limit behavior requires empirical testing)
- pdfplumber documentation: `github.com/jsvine/pdfplumber` — structured table extraction from PDFs (HIGH confidence — widely used, well-maintained)
- weasyprint documentation: `weasyprint.org` — HTML to PDF for Python (MEDIUM confidence — known Windows dependency complexity with GTK)

---

*Architecture research for: LATAM Financial Analysis Pipeline (v2.0) — integration with existing SP500 dashboard*
*Researched: 2026-03-03*
