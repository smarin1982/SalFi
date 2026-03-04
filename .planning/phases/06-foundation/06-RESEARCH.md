# Phase 6: Foundation - Research

**Researched:** 2026-03-04
**Domain:** FX normalization, company slug registry, Parquet schema parity, Playwright thread isolation
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FX-01 | Convert LATAM values to USD using period-average FX with tiered strategy: Frankfurter (BRL/MXN) → secondary API (COP/PEN/CLP/ARS) | Frankfurter coverage confirmed; open.er-api.com confirmed free+covers all 6; tiered fallback pattern documented |
| FX-02 | ARS companies show a baja-confianza warning flag in metadata | `meta.json` schema includes `low_confidence_fx` boolean; ARS detection logic researched |
| COMP-01 | Name + country → deterministic URL-safe slug for filesystem storage | `python-slugify` 8.0.4 with `text-unidecode` backend confirmed; unicodedata stdlib fallback also researched |
| COMP-02 | Store regulatory ID (NIT/RUC/RUT) as secondary identifier in registry | meta.json schema documented; no external library needed |
| COMP-03 | `data/latam/{country}/{slug}/` directories with same Parquet schema as US `data/clean/{TICKER}/` | Exact schema verified from live files: 24 columns financials, 22 columns KPIs |
</phase_requirements>

---

## Summary

Phase 6 builds the four infrastructure pillars that all subsequent LATAM phases depend on: the FX normalizer (`currency.py`), the company registry with slug generation (`company_registry.py`), the storage layout (`data/latam/{country}/{slug}/`), and a Playwright thread-isolation smoke test. Every implementation decision is constrained by the locked v2.0 architecture decisions documented in STATE.md.

The most critical discovery is the **Frankfurter API limitation**: only BRL and MXN are covered of the six required LATAM currencies. ARS, CLP, COP, and PEN return 404 errors. The `open.er-api.com` endpoint (from exchangerate-api.com) covers all six with no API key, but returns only current rates — not historical. This means historical annual-average rates for ARS/CLP/COP/PEN must be computed from current-day single-point rates cached at the time of first use, or handled by requesting the most recent available rate. This is a known approximation and must be flagged in `currency.py` comments.

The **Playwright thread isolation** pattern is confirmed working: each thread must create its own `sync_playwright()` instance. The official Playwright docs state "Playwright's API is not thread-safe. If you are using Playwright in a multi-threaded environment, you should create a playwright instance per thread." Using `ThreadPoolExecutor` with one `sync_playwright().start()` per thread is the correct approach for the Streamlit integration.

**Primary recommendation:** Build `currency.py` first (no external dependencies, pure logic + HTTP), then `company_registry.py` (slug + meta.json schema), then storage layout verification, then the Playwright smoke test last (requires browser install step).

---

## Standard Stack

### Core (Phase 6 specific)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `requests` | 2.32.4 (already installed) | HTTP calls to Frankfurter and open.er-api.com | Already present via edgartools; synchronous, simple, no new dependency |
| `python-slugify` | 8.0.4 | Convert Unicode company names to URL-safe filesystem-safe slugs | Handles all Spanish/Portuguese characters; uses text-unidecode for transliteration; MIT license; no native dependencies |
| `playwright` | >=1.48 (not yet installed) | Headless browser for Playwright thread-isolation smoke test | Required by Phase 7 scraper; Phase 6 smoke test validates the thread pattern before building on it |
| `functools.lru_cache` | stdlib | In-process FX rate cache | Eliminates redundant API calls within a session; pairs with disk cache for cross-session persistence |
| `json` + `pathlib` | stdlib | meta.json read/write, path manipulation | No new dependency; consistent with existing agent.py pattern |
| `unicodedata` | stdlib | Unicode normalization (NFKD) as backup slug path | stdlib fallback if python-slugify causes issues |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pandas` | >=3.0.1 (already installed) | Parquet schema validation, DataFrame operations | Verifying LATAM Parquet columns/dtypes match US schema |
| `pyarrow` | >=23.0.1 (already installed) | Parquet read/write | Atomic Parquet writer — use same `save_parquet()` pattern as `processor.py` |
| `loguru` | >=0.7 (already installed) | Logging FX fallback events, slug generation | Consistent with existing pipeline logging |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `python-slugify` | `unicodedata.normalize("NFKD")` + `re.sub()` (stdlib only) | stdlib approach is fine for ASCII transliteration but misses some Unicode edge cases; python-slugify handles them robustly; given this is a one-time foundation module, the extra dep is worth it |
| `open.er-api.com` (secondary FX) | `exchangerate.host` | exchangerate.host requires API key for historical data; open.er-api.com is truly no-key. Neither provides true historical time-series for free. Both return current rates only on free tier — use caching to persist rates at time of first encounter |
| `ThreadPoolExecutor` + sync_playwright | subprocess | Subprocess approach adds latency and IPC complexity; ThreadPoolExecutor with per-thread instances is simpler and confirmed working |

**Installation (new deps for Phase 6):**
```bash
pip install "python-slugify>=8.0.4"
pip install "playwright>=1.48"
playwright install chromium
```

---

## Architecture Patterns

### Recommended Project Structure (Phase 6 files)

```
AI 2026/
├── currency.py              # NEW: FX normalizer — Frankfurter + open.er-api.com fallback
├── company_registry.py      # NEW: make_slug(), CompanyRecord dataclass, registry I/O
├── data/
│   └── latam/               # NEW: LATAM storage root
│       └── {country}/       # e.g., "colombia", "peru", "chile" (lowercase)
│           └── {slug}/      # e.g., "grupo-keralty"
│               ├── financials.parquet   # identical schema to data/clean/{TICKER}/financials.parquet
│               ├── kpis.parquet         # identical schema to data/clean/{TICKER}/kpis.parquet
│               └── meta.json            # company metadata + FX warning flag
├── data/cache/
│   └── fx_rates.json        # NEW: disk cache for FX rates (keyed by currency+year)
└── tests/
    ├── test_kpi_registry.py # EXISTING (4 tests, all passing)
    └── test_currency.py     # NEW (Phase 6 Wave 0 gap)
    └── test_company_registry.py  # NEW (Phase 6 Wave 0 gap)
```

### Pattern 1: Tiered FX API with lru_cache + Disk Cache

**What:** `currency.py` routes by currency code — BRL/MXN go to Frankfurter; ARS/CLP/COP/PEN go to open.er-api.com. Results are cached in-process with `lru_cache` and persisted to `data/cache/fx_rates.json` for cross-session reuse.

**When to use:** Any monetary value in a LATAM currency needs USD conversion before writing to Parquet.

**Example:**
```python
# currency.py
# Source: Confirmed via live API testing (2026-03-04)
import json
import requests
from functools import lru_cache
from pathlib import Path
from loguru import logger

FRANKFURTER_CURRENCIES = {"BRL", "MXN"}  # Only LATAM currencies ECB tracks
SECONDARY_API_BASE = "https://open.er-api.com/v6/latest/{base}"
CACHE_FILE = Path("data/cache/fx_rates.json")

def _load_disk_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}

def _save_disk_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))

@lru_cache(maxsize=256)
def get_annual_avg_rate(currency: str, year: int) -> float:
    """
    Return annual-average USD/{currency} rate for fiscal year.
    BRL/MXN: Frankfurter time-series (true annual average from daily ECB data).
    ARS/CLP/COP/PEN: open.er-api.com current rate (approximation — cached at
    first call time; flag in comments that this is NOT a true historical average).
    """
    cache_key = f"{currency}_{year}"
    disk_cache = _load_disk_cache()
    if cache_key in disk_cache:
        return disk_cache[cache_key]

    if currency in FRANKFURTER_CURRENCIES:
        rate = _frankfurter_annual_avg(currency, year)
    else:
        rate = _secondary_api_rate(currency)
        logger.warning(
            f"FX: {currency} not in Frankfurter — using open.er-api.com spot rate "
            f"as proxy for year {year}. Rate may not reflect {year} annual average."
        )

    disk_cache[cache_key] = rate
    _save_disk_cache(disk_cache)
    return rate

def _frankfurter_annual_avg(currency: str, year: int) -> float:
    """True annual average from Frankfurter time-series endpoint."""
    url = f"https://api.frankfurter.app/{year}-01-01..{year}-12-31"
    resp = requests.get(url, params={"from": currency, "to": "USD"}, timeout=10)
    resp.raise_for_status()
    rates = resp.json()["rates"]  # {"2020-01-02": {"USD": 0.22}, ...}
    usd_values = [v["USD"] for v in rates.values()]
    return sum(usd_values) / len(usd_values)

def _secondary_api_rate(currency: str) -> float:
    """Current spot rate from open.er-api.com — no API key required."""
    url = SECONDARY_API_BASE.format(base=currency)
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()["rates"]["USD"]

def to_usd(amount: float, currency: str, fiscal_year: int) -> float:
    """Convert amount in currency to USD. Returns float. Never returns None."""
    if currency == "USD":
        return amount
    rate = get_annual_avg_rate(currency, fiscal_year)
    return amount * rate

def is_low_confidence_currency(currency: str) -> bool:
    """ARS is flagged as low confidence due to Argentina FX volatility."""
    return currency == "ARS"
```

### Pattern 2: Deterministic Slug Generation

**What:** Company name + country code → lowercase hyphenated ASCII slug with no special characters, safe for Windows NTFS paths.

**When to use:** Any time a LATAM company is registered in the system. The slug is the permanent filesystem key.

**Example:**
```python
# company_registry.py
# Source: python-slugify 8.0.4 PyPI docs + unicodedata stdlib
from slugify import slugify  # python-slugify package

def make_slug(company_name: str) -> str:
    """
    'Clínica Las Américas' → 'clinica-las-americas'
    'EPS Sánitas (NUEVA)' → 'eps-sanitas-nueva'
    Deterministic: same input always produces same output.
    Windows NTFS safe: no chars from <>:"/\\|?*
    """
    return slugify(company_name, allow_unicode=False, separator="-")
    # allow_unicode=False forces ASCII transliteration via text-unidecode
    # Result is always lowercase hyphenated ASCII — safe on all platforms

def make_storage_path(base_dir: Path, country: str, slug: str) -> Path:
    """Returns data/latam/{country}/{slug}/ — creates directories on demand."""
    path = base_dir / "latam" / country.lower() / slug
    path.mkdir(parents=True, exist_ok=True)
    return path
```

### Pattern 3: Playwright Thread Isolation from Streamlit

**What:** All Playwright operations run inside a `ThreadPoolExecutor` worker function that creates its own `sync_playwright()` instance. The Streamlit main thread never touches Playwright directly.

**When to use:** Every Playwright call triggered from a Streamlit button or any asyncio context.

**Example:**
```python
# latam_scraper.py (smoke test version for Phase 6)
# Source: Official Playwright Python docs + github.com/microsoft/playwright-python/issues/470
import concurrent.futures
from playwright.sync_api import sync_playwright

def _playwright_worker(url: str) -> str:
    """
    Runs in its own thread. Each thread MUST create its own playwright instance.
    Never call sync_playwright() from the Streamlit main thread.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        title = page.title()
        browser.close()
    return title

def scrape_url_title(url: str) -> str:
    """Thread-safe Playwright call from any context including Streamlit."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_playwright_worker, url)
        return future.result(timeout=60)

# In Streamlit app.py (for smoke test button):
# if st.button("Playwright Smoke Test", key="latam_playwright_test"):
#     with st.spinner("Testing Playwright thread isolation..."):
#         title = scrape_url_title("https://example.com")
#     st.success(f"OK — page title: {title}")
```

### Pattern 4: Parquet Schema Parity Validation

**What:** Verify that LATAM Parquet output has identical columns and dtypes to US Parquet output. This is a gate that must pass before the schema is considered "locked in."

**When to use:** At the end of Phase 6, before declaring the storage schema complete.

**Exact schema to match (verified from live AAPL data 2026-03-04):**

`financials.parquet` — 24 columns:
```
ticker: object, fiscal_year: int64,
revenue: float64, gross_profit: float64, cogs: float64,
operating_income: float64, net_income: float64, interest_expense: float64,
depreciation_amortization: float64, total_assets: float64, total_liabilities: float64,
total_equity: float64, current_assets: float64, current_liabilities: float64,
cash: float64, short_term_investments: float64, receivables: float64,
inventory: float64, long_term_debt: float64, short_term_debt: float64,
accounts_payable: float64, shares_outstanding: float64,
operating_cash_flow: float64, capex: float64
```

`kpis.parquet` — 22 columns:
```
ticker: object, fiscal_year: int64,
revenue_growth_yoy: float64, revenue_cagr_10y: float64,
gross_profit_margin: float64, operating_margin: float64,
net_profit_margin: float64, ebitda_margin: float64,
roe: float64, roa: float64, current_ratio: float64, quick_ratio: float64,
cash_ratio: float64, working_capital: float64, debt_to_equity: float64,
debt_to_ebitda: float64, interest_coverage: float64, debt_to_assets: float64,
asset_turnover: float64, inventory_turnover: float64, dso: float64,
cash_conversion_cycle: float64
```

### Anti-Patterns to Avoid

- **Using Frankfurter for ARS/CLP/COP/PEN:** Returns HTTP 404 (not 422 as sometimes reported). These currencies are absent from ECB tracking. Code defensively: check `resp.status_code` before parsing.
- **Calling `sync_playwright()` in the Streamlit main thread:** Raises `RuntimeError: It looks like you are using Playwright Sync API inside the asyncio loop`. Always use `ThreadPoolExecutor`.
- **Sharing a single playwright instance across threads:** Playwright is not thread-safe. Each `ThreadPoolExecutor` worker must call `sync_playwright()` independently.
- **Using raw company names as directory paths:** Spanish characters like `ñ`, `á`, `é` can cause `OSError` on Windows. Always use slugs for paths; store display names in `meta.json`.
- **Storing FX metadata inside Parquet:** Keep Parquet identical to US schema. FX rate used, original currency, and low-confidence flag go in `meta.json` only.
- **Using `open.er-api.com` without caching:** The free tier rate-limits if called repeatedly. Always check and populate `fx_rates.json` first.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Unicode-to-ASCII slug for Spanish company names | Custom regex + encode/decode chain | `python-slugify` 8.0.4 | Handles ñ, á, ü, º, ª, ligatures, and dozens of edge cases that a simple `normalize("NFKD").encode("ascii","ignore")` misses (e.g., "ß" → "ss", ligatures, symbols) |
| FX rate caching across sessions | Custom pickle/shelve implementation | `json` dict in `data/cache/fx_rates.json` + `lru_cache` | Simple, human-readable, compatible with the existing `data/cache/metadata.parquet` pattern; no extra dependency |
| Windows-safe path creation | `os.makedirs()` with custom error handling | `pathlib.Path.mkdir(parents=True, exist_ok=True)` | Already in use throughout the codebase; handles all edge cases |
| Thread pool for Playwright | `threading.Thread` subclass with manual join | `concurrent.futures.ThreadPoolExecutor` | Cleaner API, proper exception propagation via `.result(timeout=N)`, consistent with Python stdlib concurrency patterns |

**Key insight:** The slug generation problem is deceptively complex — a simple `unicodedata.normalize("NFKD", name).encode("ascii", "ignore")` handles accented characters but not ligatures, symbols, or locale-specific transliterations. Use `python-slugify` which is purpose-built for this.

---

## Common Pitfalls

### Pitfall 1: Frankfurter Returns 404 for ARS/CLP/COP/PEN (Not 422)

**What goes wrong:** Code checks for HTTP 422 as the Frankfurter failure signal but the actual response is HTTP 404 (or a JSON `{"message": "not found"}` depending on the endpoint path). The fallback never triggers.

**Why it happens:** The original roadmap research mentioned 422, but the Frankfurter API confirmed via live testing returns 404 for unsupported currencies. The `/currencies` endpoint lists exactly 32 currencies with no LATAM ones except BRL and MXN.

**How to avoid:** Handle `requests.exceptions.HTTPError` generically, or check `resp.status_code != 200`, rather than checking for a specific 422 code. Both 404 and invalid responses should trigger the secondary API fallback.

**Warning signs:** Secondary API fallback never runs despite ARS being queried.

---

### Pitfall 2: open.er-api.com Returns Only Current Rates, Not Historical

**What goes wrong:** For fiscal year 2021 ARS data, `open.er-api.com/v6/latest/ARS` returns today's rate (2026), not the 2021 annual average. Financial values are converted using wrong-year exchange rates, producing incorrect USD figures.

**Why it happens:** The free tier of `open.er-api.com` (and most free FX APIs) only provides current/spot rates. Historical time-series requires a paid API key.

**How to avoid:** Cache the rate at first request and log clearly that the stored rate is a spot rate captured at caching time, not a true historical annual average. Flag all non-BRL/MXN currencies with `approximated_fx: true` in `meta.json`. The project requirements document this as an accepted limitation for the free tier.

**Warning signs:** Same rate returned for year 2019 and year 2025 for ARS (the cached current rate is reused without acknowledging the approximation).

---

### Pitfall 3: Playwright NotImplementedError on Windows When Called from Streamlit

**What goes wrong:** Calling `sync_playwright()` from a Streamlit button callback raises `NotImplementedError` (from the Windows SelectorEventLoop) or `RuntimeError: It looks like you are using Playwright Sync API inside the asyncio loop`.

**Why it happens:** Streamlit's Tornado server runs an asyncio event loop. Windows SelectorEventLoop cannot handle subprocess communication (which Playwright requires). The collision between Streamlit's loop and Playwright's subprocess requirements causes the failure.

**How to avoid:** Always wrap Playwright in `ThreadPoolExecutor`. Each worker thread gets its own `sync_playwright()` instance and its own event loop. Never call Playwright from the Streamlit render path directly.

**Warning signs:** `NotImplementedError` or silent hang on first Playwright call from a button; works fine when called from a plain `python script.py` outside Streamlit.

---

### Pitfall 4: python-slugify with `allow_unicode=True` Produces Non-ASCII Paths

**What goes wrong:** `slugify("Clínica Las Américas", allow_unicode=True)` → `"clínica-las-américas"` — preserves Unicode, which NTFS technically supports but can cause encoding issues with older Python tools and conda environments that use CP1252.

**Why it happens:** `allow_unicode=True` is the default for some slugify versions and is appropriate for URLs but not for filesystem paths that must be portable across Windows code pages.

**How to avoid:** Always pass `allow_unicode=False` to force ASCII-only slugs. The display name is preserved in `meta.json["company_name"]` with full Unicode.

**Warning signs:** Path contains accented characters; `OSError` on machines with non-UTF-8 system locale.

---

### Pitfall 5: FX Cache File Not Created Before First Write Causes Race

**What goes wrong:** Two concurrent FX lookups (in tests or batch processing) both find the cache file absent, both compute the rate, and one overwrites the other's write.

**Why it happens:** The `_save_disk_cache()` function does a read-modify-write cycle without locking. In single-threaded use this is fine; in concurrent use it creates a race.

**How to avoid:** Phase 6 runs single-threaded by design (currency.py is called from processor contexts, not concurrently). Document this limitation in `currency.py` comments. If concurrency is needed later, use file locking via `filelock` library.

---

## Code Examples

Verified patterns from official sources:

### FX Rate Lookup — Frankfurter Time-Series (BRL, MXN)
```python
# Source: api.frankfurter.app live endpoint — verified 2026-03-04
# Returns daily rates for the full year; average is computed in Python
url = f"https://api.frankfurter.app/{year}-01-01..{year}-12-31"
resp = requests.get(url, params={"from": "BRL", "to": "USD"}, timeout=10)
data = resp.json()
# data["rates"] = {"2023-01-02": {"USD": 0.1943}, "2023-01-03": {"USD": 0.1951}, ...}
usd_rates = [v["USD"] for v in data["rates"].values()]
annual_avg = sum(usd_rates) / len(usd_rates)
```

### FX Rate Lookup — Secondary API (ARS, CLP, COP, PEN)
```python
# Source: open.er-api.com verified live 2026-03-04 — no API key required
# Returns current spot rate — NOT historical annual average
# Must be flagged as approximated_fx=true in meta.json
resp = requests.get("https://open.er-api.com/v6/latest/ARS", timeout=10)
# resp.json()["rates"]["USD"] = 0.000688... (spot rate, today)
rate_usd_per_ars = resp.json()["rates"]["USD"]
```

### Slug Generation
```python
# Source: python-slugify 8.0.4 PyPI — verified API
from slugify import slugify

make_slug = lambda name: slugify(name, allow_unicode=False, separator="-")
# "Clínica Las Américas" → "clinica-las-americas"
# "EPS Sánitas (NUEVA)" → "eps-sanitas-nueva"
# "Organización Sanitas S.A." → "organizacion-sanitas-s-a"
```

### Playwright Thread Isolation (confirmed pattern)
```python
# Source: Official Playwright Python docs — playwright.dev/python/docs/library
# "If you are using Playwright in a multi-threaded environment, you should
#  create a playwright instance per thread."
import concurrent.futures
from playwright.sync_api import sync_playwright

def _worker(url: str) -> str:
    with sync_playwright() as p:          # Each thread: own instance
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=30_000)
        result = page.title()
        browser.close()
    return result

def run_playwright(url: str) -> str:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_worker, url).result(timeout=60)
```

### meta.json Schema (locked for Phase 6)
```json
{
  "company_name": "Clínica Las Américas",
  "slug": "clinica-las-americas",
  "country": "colombia",
  "regulatory_id": "NIT 800.058.016-0",
  "regulatory_authority": "Supersalud",
  "source_url": "https://clinicalasamericas.com.co",
  "currency_original": "COP",
  "approximated_fx": false,
  "low_confidence_fx": false,
  "last_scraped": null,
  "last_processed": null,
  "fiscal_years_available": [],
  "extraction_quality": null,
  "fields_extracted": [],
  "fields_missing": []
}
```

ARS companies get `"low_confidence_fx": true` and `"approximated_fx": true` in this schema.

### Parquet Schema Validation (verifying parity)
```python
# Source: Direct inspection of data/clean/AAPL/financials.parquet — 2026-03-04
import pandas as pd

EXPECTED_FINANCIALS_COLS = [
    "ticker", "fiscal_year", "revenue", "gross_profit", "cogs",
    "operating_income", "net_income", "interest_expense",
    "depreciation_amortization", "total_assets", "total_liabilities",
    "total_equity", "current_assets", "current_liabilities", "cash",
    "short_term_investments", "receivables", "inventory", "long_term_debt",
    "short_term_debt", "accounts_payable", "shares_outstanding",
    "operating_cash_flow", "capex"
]  # 24 columns

def validate_latam_schema(parquet_path: str) -> bool:
    df = pd.read_parquet(parquet_path)
    return list(df.columns) == EXPECTED_FINANCIALS_COLS
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `duckduckgo-search` package | `ddgs` package (same author, renamed) | 2024-2025 | Old package shows RuntimeWarning; new package is `ddgs>=9.0` |
| `playwright install` (all browsers, ~600MB) | `playwright install chromium` (~130MB) | N/A — always was a flag | Must specify `chromium` explicitly; omitting downloads all browsers |
| `frankfurter.app` URL | `api.frankfurter.app` URL | Service moved; both work as of 2026-03 | Either URL pattern works; use `api.frankfurter.app` as it's the primary documented endpoint |

**Deprecated/outdated:**
- `duckduckgo-search`: deprecated package; use `ddgs>=9.0` instead
- Frankfurter currency `v1/` path prefix: PITFALLS.md shows `api.frankfurter.app/{year}...` (no `/v1/` prefix) — confirmed working via live test; some examples online incorrectly use `/v1/` path which returns 404

---

## Open Questions

1. **Historical ARS/CLP/COP/PEN annual averages on free tier**
   - What we know: `open.er-api.com` free tier returns current spot rates only; no historical data without API key
   - What's unclear: Whether there is a genuinely free, no-key API that provides LATAM historical annual averages
   - Recommendation: Use spot rate as proxy; cache at first call; document as `approximated_fx: true` in meta.json; this is acceptable per project constraints (nominal values, local tool)

2. **Frankfurter exact error code for unsupported currencies**
   - What we know: Live test to `api.frankfurter.app/2023-01-01..2023-12-31?from=ARS&to=USD` returns HTTP 404; currencies page confirms ARS not listed
   - What's unclear: Whether the error is 404 vs. 422 depending on endpoint variant (some community reports say 422 for `/latest?from=ARS`)
   - Recommendation: Catch both 404 and 422 in the fallback logic; catch any `HTTPError` with status 4xx as trigger for secondary API

3. **Playwright chromium install location in conda environment**
   - What we know: `playwright install chromium` downloads to `%LOCALAPPDATA%\ms-playwright` by default; must be run inside the active conda env
   - What's unclear: Whether the Phase 6 smoke test environment already has chromium installed (playwright is not yet in requirements.txt)
   - Recommendation: Phase 6 Wave 0 task must include `playwright install chromium` as a setup step before the smoke test

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none (rootdir auto-detected as `C:\Users\Seb\AI 2026`) |
| Quick run command | `python -m pytest tests/test_currency.py tests/test_company_registry.py -v` |
| Full suite command | `python -m pytest tests/ -v` |
| Estimated runtime | ~5-10 seconds (no network mocking needed for unit tests; integration tests with live APIs ~15s) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FX-01 | `to_usd(1000, "BRL", 2023)` returns float via Frankfurter | unit/integration | `python -m pytest tests/test_currency.py::test_to_usd_brl -x` | Wave 0 gap |
| FX-01 | `to_usd(1000, "MXN", 2023)` returns float via Frankfurter | unit/integration | `python -m pytest tests/test_currency.py::test_to_usd_mxn -x` | Wave 0 gap |
| FX-01 | `to_usd(1000, "ARS", 2023)` returns float via secondary API | unit/integration | `python -m pytest tests/test_currency.py::test_to_usd_ars -x` | Wave 0 gap |
| FX-01 | `to_usd(1000, "CLP", 2023)` returns float via secondary API | unit/integration | `python -m pytest tests/test_currency.py::test_to_usd_clp -x` | Wave 0 gap |
| FX-01 | `to_usd(1000, "COP", 2023)` returns float via secondary API | unit/integration | `python -m pytest tests/test_currency.py::test_to_usd_cop -x` | Wave 0 gap |
| FX-01 | `to_usd(1000, "PEN", 2023)` returns float via secondary API | unit/integration | `python -m pytest tests/test_currency.py::test_to_usd_pen -x` | Wave 0 gap |
| FX-01 | Frankfurter fallback path: when Frankfurter returns 4xx for ARS, secondary API is called | unit (mock) | `python -m pytest tests/test_currency.py::test_fallback_triggered -x` | Wave 0 gap |
| FX-02 | `is_low_confidence_currency("ARS")` returns True | unit | `python -m pytest tests/test_currency.py::test_ars_low_confidence -x` | Wave 0 gap |
| FX-02 | `is_low_confidence_currency("BRL")` returns False | unit | `python -m pytest tests/test_currency.py::test_brl_not_low_confidence -x` | Wave 0 gap |
| COMP-01 | `make_slug("Clínica Las Américas")` returns `"clinica-las-americas"` | unit | `python -m pytest tests/test_company_registry.py::test_slug_with_accents -x` | Wave 0 gap |
| COMP-01 | `make_slug("EPS Sánitas (NUEVA)")` returns `"eps-sanitas-nueva"` or similar slug | unit | `python -m pytest tests/test_company_registry.py::test_slug_with_parens -x` | Wave 0 gap |
| COMP-01 | Slug is deterministic: same input always returns same output | unit | `python -m pytest tests/test_company_registry.py::test_slug_deterministic -x` | Wave 0 gap |
| COMP-01 | Path created from slug succeeds on Windows (no OSError) | unit | `python -m pytest tests/test_company_registry.py::test_slug_windows_path -x` | Wave 0 gap |
| COMP-02 | `CompanyRecord` stores NIT/RUC/RUT as `regulatory_id` field | unit | `python -m pytest tests/test_company_registry.py::test_regulatory_id_stored -x` | Wave 0 gap |
| COMP-03 | `data/latam/{country}/{slug}/financials.parquet` columns match EXPECTED_FINANCIALS_COLS | unit | `python -m pytest tests/test_company_registry.py::test_parquet_schema_parity -x` | Wave 0 gap |
| COMP-03 | Playwright `scrape_url_title("https://example.com")` from ThreadPoolExecutor returns string without NotImplementedError | smoke | `python -m pytest tests/test_playwright_thread.py::test_thread_isolation -x` | Wave 0 gap |

### Nyquist Sampling Rate

- **Minimum sample interval:** After every committed task → run: `python -m pytest tests/test_currency.py tests/test_company_registry.py -v`
- **Full suite trigger:** Before merging final task of any plan wave → `python -m pytest tests/ -v`
- **Phase-complete gate:** All tests green including Playwright smoke test before moving to Phase 7
- **Estimated feedback latency per task:** ~10-15 seconds (unit tests fast; integration tests with live API calls add ~5s per currency)

### Wave 0 Gaps (must be created before implementation)

- [ ] `tests/test_currency.py` — covers FX-01, FX-02: unit tests for all 6 currencies, fallback trigger test, ARS low-confidence flag
- [ ] `tests/test_company_registry.py` — covers COMP-01, COMP-02, COMP-03: slug generation with Unicode, Windows path creation, Parquet schema parity validation
- [ ] `tests/test_playwright_thread.py` — covers Playwright thread isolation smoke test (success criterion 4)
- [ ] Framework install: `pip install "python-slugify>=8.0.4" && pip install "playwright>=1.48" && playwright install chromium`

---

## Sources

### Primary (HIGH confidence)

- `https://api.frankfurter.app/currencies` — live endpoint, confirmed only BRL + MXN of 6 required LATAM currencies (2026-03-04)
- `https://api.frankfurter.app/2023-01-01..2023-06-30?from=BRL&to=USD` — live endpoint, confirmed response structure (2026-03-04)
- `https://open.er-api.com/v6/latest/USD` — live endpoint, confirmed ARS/CLP/COP/PEN/BRL/MXN all present, no API key (2026-03-04)
- `https://playwright.dev/python/docs/library` — official Playwright Python docs, confirmed "create a playwright instance per thread" (2026-03-04)
- `data/clean/AAPL/financials.parquet` — live file, confirmed 24-column schema and dtypes (2026-03-04)
- `data/clean/AAPL/kpis.parquet` — live file, confirmed 22-column schema (2026-03-04)
- `tests/test_kpi_registry.py` — existing test file, 4 tests passing with pytest 9.0.2 (2026-03-04)

### Secondary (MEDIUM confidence)

- `https://pypi.org/project/python-slugify/` — version 8.0.4, Feb 2024, `allow_unicode=False` forces ASCII transliteration (2026-03-04)
- `https://github.com/microsoft/playwright-python/issues/470` — thread safety confirmed: "not thread-safe; create instance per thread"
- `https://github.com/lineofflight/frankfurter/issues/144` — ARS/CLP/COP/PEN not tracked by ECB, confirmed absent from Frankfurter

### Tertiary (LOW confidence)

- `open.er-api.com` historical rates limitation — based on search results and free tier documentation; historical data confirmed unavailable; not verified via API call

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — libraries verified live (requests installed at 2.32.4, pytest at 9.0.2, python-slugify at 8.0.4 on PyPI); Playwright docs official
- Architecture: HIGH — Parquet schemas verified from live files; Playwright threading pattern from official docs
- FX API coverage: HIGH — Frankfurter currency list verified live; open.er-api.com response verified live
- Pitfalls: HIGH — Frankfurter gap and Playwright asyncio conflict previously documented in PITFALLS.md and now cross-validated with live endpoints and official docs

**Research date:** 2026-03-04
**Valid until:** 2026-04-04 (Frankfurter currency list is stable; open.er-api.com free tier terms could change)
