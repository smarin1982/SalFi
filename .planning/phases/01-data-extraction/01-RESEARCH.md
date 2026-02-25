# Phase 1: Data Extraction - Research

**Researched:** 2026-02-25
**Domain:** SEC EDGAR XBRL data extraction — edgartools, rate limiting, ticker-CIK resolution, raw JSON persistence
**Confidence:** HIGH

---

## Summary

Phase 1 establishes the data foundation for the entire pipeline. Its sole output is a verified `data/raw/{TICKER}/facts.json` file per ticker, containing the verbatim XBRL company facts JSON from SEC EDGAR. All subsequent phases (processor, agent, dashboard) depend on this file existing. The phase has zero upstream dependencies.

The primary library is `edgartools` (version 5.17.1 as of 2026-02-25, `pip install edgartools`), which wraps the SEC EDGAR XBRL company facts endpoint (`https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json`) and handles rate limiting internally at 9 req/s using a token bucket algorithm. The library enforces the SEC-required `User-Agent` header via `set_identity()` or the `EDGAR_IDENTITY` environment variable. edgartools also caches `company_tickers.json` locally at `~/.edgar/_tcache/` with a 30-second TTL, meaning ticker-to-CIK resolution requires no extra network call per lookup once the cache is warm.

The critical design choice for this phase: do NOT rely on edgartools' internal caching for the project's persistence contract. Instead, explicitly download the raw companyfacts JSON and write it verbatim to `data/raw/{TICKER}/facts.json`. This raw checkpoint is the insurance policy — it allows re-running `processor.py` without hitting SEC again whenever XBRL normalization logic changes, which will happen. edgartools provides `Company.get_facts()` which returns a `CompanyFacts` object backed by the same JSON; the raw JSON can also be fetched directly via `httpx` with the same `User-Agent` header. The recommended approach is to use edgartools for ticker resolution and `company_tickers.json` management, but fetch the raw companyfacts JSON via `httpx` directly so the verbatim payload is preserved without library-imposed transformation.

**Primary recommendation:** Use `edgartools` for identity/rate-limiting infrastructure and ticker→CIK resolution, but fetch and persist the raw `companyfacts` JSON directly via `httpx` to guarantee verbatim storage.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| XTRCT-01 | Download official SEC ticker→CIK JSON at startup; resolve any ticker without a per-resolution network call | `https://www.sec.gov/files/company_tickers.json` is the official URL; edgartools caches this at `~/.edgar/_tcache/`; project must also cache at `data/cache/tickers.json` for portability |
| XTRCT-02 | Rate limiter max 10 req/s with correct User-Agent header | edgartools enforces 9 req/s via token bucket in `httpxthrottlecache`; set via `EDGAR_RATE_LIMIT_PER_SEC` env var or `set_rate_limit()`; `set_identity()` required for User-Agent |
| XTRCT-03 | Extract 10-K filings for last 10 years per CIK using edgartools; use XBRL EDGAR endpoints | `Company(ticker).get_facts()` hits `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json` which returns ALL historical years in one response; no pagination needed for facts |
| XTRCT-04 | Store raw facts.json in `/data/raw/{TICKER}/` as checkpoint; use local copy if already exists | Explicit `httpx` GET of companyfacts endpoint + `json.dump()` to `data/raw/{TICKER}/facts.json`; existence check at scraper entry point |
</phase_requirements>

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| edgartools | >=5.0 (latest: 5.17.1) | Rate limiting, User-Agent, ticker→CIK resolution, Company API | Official SEC data library, built-in 9 req/s token bucket, handles `company_tickers.json` caching, returns CompanyFacts from companyfacts endpoint |
| httpx | >=0.27 | Direct HTTP GET for raw companyfacts JSON | async-capable, used internally by edgartools; needed for verbatim JSON download without edgartools transformation |
| tenacity | >=8.3 | Retry logic for network failures | Production retry with exponential backoff + jitter; edgartools uses `stamina` internally but project-level retry around external calls needs tenacity |
| python-dotenv | >=1.0 | Load `EDGAR_IDENTITY` from `.env` | Keeps API credentials out of source code |
| loguru | >=0.7 | Structured logging for scraper | Replaces stdlib logging with structured output; useful for retry events and rate-limit warnings |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tqdm | >=4.66 | Progress bars for batch ticker download | When running initial TOP-20 bulk download |
| pathlib | stdlib | Path operations for data/raw/cache directories | Always — use `Path` not string concatenation |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| edgartools | Direct `httpx` only | edgartools provides `company_tickers.json` management, CIK formatting, and rate limiter for free; rolling everything from scratch adds 100+ lines with no benefit |
| edgartools | `sec-edgar-downloader` | sec-edgar-downloader fetches raw HTML/XML filing documents — wrong for this use case which needs structured XBRL JSON facts |
| tenacity | edgartools' built-in `stamina` | stamina is internal to edgartools and not accessible for project-level retry logic around the scraper module |

**Installation:**
```bash
pip install "edgartools>=5.0" "httpx>=0.27" "tenacity>=8.3" "python-dotenv>=1.0" "loguru>=0.7" "tqdm>=4.66"
```

---

## Architecture Patterns

### Recommended Project Structure

```
data/
  raw/
    {TICKER}/
      facts.json          # verbatim XBRL company facts from SEC — single file, all years
  cache/
    tickers.json          # SEC ticker→CIK map (downloaded once, refreshed quarterly)
src/
  scraper.py              # only file in Phase 1 — talks to SEC, nothing else
.env                      # EDGAR_IDENTITY="Name email@example.com"
```

### Pattern 1: Identity and Rate Limiter Setup

**What:** Configure edgartools once at process startup. Set `EDGAR_IDENTITY` via env or `set_identity()`. edgartools' internal rate limiter (9 req/s token bucket) then applies to all subsequent calls automatically.

**When to use:** Always — must be the first step before any SEC API call.

```python
# Source: edgartools docs (https://edgartools.readthedocs.io/en/stable/configuration/)
import os
from dotenv import load_dotenv
from edgar import set_identity, set_rate_limit

load_dotenv()  # loads EDGAR_IDENTITY from .env

identity = os.getenv("EDGAR_IDENTITY")
if not identity:
    raise EnvironmentError("EDGAR_IDENTITY must be set in .env — SEC requires User-Agent")

set_identity(identity)
set_rate_limit(8)  # Stay conservatively under 10 req/s; edgartools default is 9
```

### Pattern 2: Ticker → CIK Resolution with Local Cache

**What:** Download `company_tickers.json` once and resolve any S&P 500 ticker to a zero-padded 10-digit CIK string. Store in `data/cache/tickers.json`. Subsequent resolutions read from disk only — zero network calls.

**When to use:** Every scraper invocation before the first SEC API call.

```python
# Source: SEC official endpoint (https://www.sec.gov/files/company_tickers.json)
# confirmed by multiple sources; structure: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
import json
import httpx
from pathlib import Path

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

def load_ticker_map(cache_path: Path, headers: dict) -> dict[str, str]:
    """
    Returns {ticker_upper: cik_padded_10d} from local cache.
    Downloads from SEC if cache does not exist.
    cache_path: e.g. Path("data/cache/tickers.json")
    """
    if cache_path.exists():
        data = json.loads(cache_path.read_text())
    else:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        resp = httpx.get(TICKERS_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        cache_path.write_text(json.dumps(data))

    # Build ticker → 10-digit padded CIK lookup
    return {
        entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
        for entry in data.values()
    }

def resolve_cik(ticker: str, ticker_map: dict[str, str]) -> str:
    """Raises ValueError for unknown tickers."""
    cik = ticker_map.get(ticker.upper())
    if cik is None:
        raise ValueError(f"Ticker '{ticker}' not found in SEC tickers.json. "
                         f"Verify it is a valid S&P 500 ticker.")
    return cik
```

### Pattern 3: Raw CompanyFacts JSON Download

**What:** Fetch the full XBRL company facts JSON for a CIK and write it verbatim to `data/raw/{TICKER}/facts.json`. This single endpoint returns all years of data (XBRL filings typically go back to 2009). No pagination required — it is one JSON blob per company.

**When to use:** After resolving CIK. Skip entirely if `facts.json` already exists (XTRCT-04).

```python
# Source: SEC EDGAR structured data endpoint
# (https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json)
import json
import httpx
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    reraise=True,
)
def fetch_companyfacts(cik: str, headers: dict) -> dict:
    """
    Download raw XBRL company facts JSON from SEC EDGAR.
    cik: zero-padded 10-digit string, e.g. "0000320193"
    Returns parsed JSON dict.
    Raises after 5 retries with exponential backoff.
    """
    url = COMPANYFACTS_URL.format(cik=cik)
    resp = httpx.get(url, headers=headers, timeout=60)
    if resp.status_code == 404:
        raise ValueError(f"No XBRL companyfacts found for CIK {cik}. "
                         f"Company may not file XBRL or CIK is incorrect.")
    resp.raise_for_status()
    return resp.json()

def download_facts(ticker: str, cik: str, data_dir: Path, headers: dict,
                   force_refresh: bool = False) -> Path:
    """
    Download and persist facts.json for a ticker.
    Skips download if file exists and force_refresh is False (XTRCT-04).
    Returns path to facts.json.
    """
    out_path = data_dir / "raw" / ticker.upper() / "facts.json"

    if out_path.exists() and not force_refresh:
        return out_path  # XTRCT-04: use local copy

    out_path.parent.mkdir(parents=True, exist_ok=True)
    facts = fetch_companyfacts(cik, headers)
    out_path.write_text(json.dumps(facts, indent=2))
    return out_path
```

### Pattern 4: CompanyFacts JSON Internal Structure

**What:** The raw `facts.json` structure that Phase 2 (processor.py) will consume. Understanding this is required to write XBRL extraction correctly.

**When to use:** Reference when building the Phase 2 XBRL normalizer.

```python
# Verified structure from SEC EDGAR XBRL API
# Source: https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json (AAPL example)
{
  "cik": 320193,
  "entityName": "Apple Inc.",
  "facts": {
    "us-gaap": {
      "RevenueFromContractWithCustomerExcludingAssessedTax": {
        "label": "Revenue from Contract with Customer, Excluding Assessed Tax",
        "description": "...",
        "units": {
          "USD": [
            {
              "end": "2023-09-30",
              "val": 383285000000,
              "accn": "0000320193-23-000106",
              "fy": 2023,
              "fp": "FY",       # "FY" = full fiscal year; "Q1"-"Q4" = quarters
              "form": "10-K",   # filter to 10-K only for annual data
              "filed": "2023-11-02",
              "frame": "CY2023Q3I"
            },
            # ... more entries for prior years and quarterly filings
          ]
        }
      },
      # ... hundreds more XBRL concepts
    },
    "dei": {
      # Document and Entity Information — company metadata, shares outstanding, etc.
    }
  }
}

# Key filter for Phase 2: keep only entries where form == "10-K" AND fp == "FY"
# Deduplication: among duplicates for same (concept, fy), keep entry with latest "filed" date
# 10-year filter: keep entries where fy >= (current_year - 10)
```

### Pattern 5: Full Scraper Entry Point

**What:** The top-level `scrape(ticker)` function that orchestrates all patterns above.

```python
# src/scraper.py — complete entry point
import os
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv
from edgar import set_identity, set_rate_limit

load_dotenv()

DATA_DIR = Path("data")
HEADERS = {}  # populated by _init_edgar()

def _init_edgar() -> None:
    """Initialize edgartools identity and rate limit. Call once at module load."""
    identity = os.getenv("EDGAR_IDENTITY")
    if not identity:
        raise EnvironmentError("EDGAR_IDENTITY not set")
    set_identity(identity)
    set_rate_limit(8)
    HEADERS["User-Agent"] = identity  # also used for direct httpx calls

def scrape(ticker: str, force_refresh: bool = False) -> Path:
    """
    Main entry point for Phase 1.
    Returns path to data/raw/{TICKER}/facts.json.
    Raises ValueError for invalid tickers or missing XBRL data.
    """
    ticker = ticker.upper()
    logger.info(f"Scraping {ticker} (force_refresh={force_refresh})")

    ticker_map = load_ticker_map(DATA_DIR / "cache" / "tickers.json", HEADERS)
    cik = resolve_cik(ticker, ticker_map)
    logger.debug(f"{ticker} → CIK {cik}")

    facts_path = download_facts(ticker, cik, DATA_DIR, HEADERS, force_refresh)
    logger.info(f"Facts saved: {facts_path} ({facts_path.stat().st_size // 1024} KB)")
    return facts_path

_init_edgar()
```

### Anti-Patterns to Avoid

- **Fetching tickers.json on every scrape call**: Load it once per process (or check file existence). It is a ~1MB file; re-downloading it for each of 20 tickers wastes 20 requests of your SEC quota.
- **Using `edgartools` `.get_facts().to_pandas()` as the persistence mechanism**: This loses the raw JSON structure that Phase 2's XBRL extractor reads directly. Always persist the verbatim JSON first.
- **Async concurrency without rate-limiter awareness**: edgartools' rate limiter applies to its internal HTTP client. If you make direct `httpx` calls in parallel threads alongside edgartools calls, you double-count requests against the SEC limit. Keep all SEC HTTP calls in one code path.
- **Storing CIK as integer**: CIKs in `company_tickers.json` are integers (`cik_str: 320193`). Always zero-pad to 10 digits immediately: `str(cik_int).zfill(10)`. The companyfacts endpoint URL requires `CIK0000320193` format.
- **Ignoring 404 responses for companyfacts**: A 404 means the company either does not file XBRL or the CIK is wrong. Do not retry 404s — they are deterministic failures. Raise `ValueError` and log clearly.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rate limiting (10 req/s) | Custom token bucket with threading.Lock | edgartools' built-in limiter via `set_rate_limit()` | edgartools uses httpxthrottlecache with verified token bucket; 9 req/s default with burst handling |
| Retry with exponential backoff | Manual `while` loop + `time.sleep()` | `tenacity` `@retry` decorator | tenacity handles jitter, exception filtering, max attempts, and reraise correctly; hand-rolled loops miss edge cases |
| HTTP client with User-Agent | Bare `requests.get()` | edgartools identity system + `httpx` | SEC blocks requests without correct User-Agent; `set_identity()` injects it into edgartools' HTTP client automatically |
| CIK lookup from ticker | Scraping EDGAR search or caching ticker→CIK in code | `company_tickers.json` from `https://www.sec.gov/files/company_tickers.json` | Official SEC source; covers all ~12,000 filers; edgartools also caches this internally |

**Key insight:** The rate limiting and retry infrastructure in this domain has real production edge cases (token bucket burst behavior, 429 vs 503 handling, SSL errors on SEC servers). These are solved by edgartools + tenacity. Hand-rolled solutions routinely miss the burst-vs-average rate distinction and cause IP bans.

---

## Common Pitfalls

### Pitfall 1: Exceeding Rate Limit and Getting IP-Banned

**What goes wrong:** The scraper sends more than 10 requests/second to `data.sec.gov`. SEC temporarily blocks the IP. All subsequent requests fail silently or return 429.

**Why it happens:** Running async fetches in parallel without a centralized rate limiter. Or calling both edgartools methods and direct httpx calls simultaneously, doubling the request rate.

**How to avoid:** Call `set_rate_limit(8)` at startup (edgartools default is already 9). Route ALL SEC API calls through edgartools' HTTP infrastructure OR ensure your direct `httpx` calls go through the same token bucket. Never use ThreadPoolExecutor with more than 1 concurrent SEC connection.

**Warning signs:** HTTP 429 responses; sudden ConnectionResetError after a burst of requests; requests succeeding then failing unpredictably.

---

### Pitfall 2: Missing or Malformed User-Agent Header

**What goes wrong:** 403 Forbidden responses immediately; works fine manually but fails in code.

**Why it happens:** Not calling `set_identity()` before any edgartools call. Or calling `set_identity()` after edgartools has already initialized its HTTP client.

**How to avoid:** Call `set_identity()` as the FIRST line of your scraper module, before any imports that trigger edgartools initialization. The SEC format requirement is: `"Full Name email@domain.com"` — include both name and email. For direct `httpx` calls, set `headers={"User-Agent": identity}` explicitly.

**Warning signs:** Immediate 403 on any SEC URL; works for a few requests then fails (suggests partial initialization race condition).

---

### Pitfall 3: CIK-Ticker Drift After Corporate Actions

**What goes wrong:** A ticker lookup returns a CIK that corresponds to the wrong company, or returns no result for a recently changed ticker.

**Why it happens:** `company_tickers.json` uses current tickers. Post-merger or post-symbol-change tickers may not match. BRK.B is a common edge case (Berkshire Hathaway's B shares).

**How to avoid:** Log the `entityName` from the companyfacts JSON alongside the CIK. Verify name matches expected company on first download. For BRK.B specifically: the CIK maps to Berkshire Hathaway Inc; the companyfacts JSON will have `entityName: "BERKSHIRE HATHAWAY INC"` — this is correct.

**Warning signs:** `ValueError: Ticker 'BRK.B' not found` — the `.` in tickers can cause lookup issues; normalize to uppercase before lookup and note that `company_tickers.json` may store as `BRK-B` or `BRK.B` depending on SEC filing.

---

### Pitfall 4: tickers.json Stale CIK for Historical Companies

**What goes wrong:** `company_tickers.json` is cached indefinitely; a ticker changes post-refresh but the scraper still resolves to the old CIK.

**Why it happens:** No TTL on the local `data/cache/tickers.json` file.

**How to avoid:** Add a metadata file `data/cache/tickers_downloaded_at.txt` with a timestamp. Refresh `tickers.json` if it is older than 30 days. For the 20-company baseline, this is low-risk — these are stable large-cap tickers. The risk increases when dynamic ticker input (DASH-03) is added in Phase 4.

---

### Pitfall 5: companyfacts Returns No 10-K Data (Pre-XBRL Company)

**What goes wrong:** The `facts.json` exists but has empty `us-gaap` or missing entries for years before ~2009.

**Why it happens:** SEC XBRL mandates began phased rollout in 2009 (large accelerated filers). Data before that will be absent from companyfacts even though paper 10-Ks exist.

**How to avoid:** After download, validate that `facts["facts"]["us-gaap"]` is non-empty. Log a warning but do not fail — Phase 2 will handle the 10-year window gracefully. Add a `completeness_check(facts_path)` function that logs how many unique `fy` values exist in the `us-gaap` section.

---

### Pitfall 6: 404 on companyfacts for Valid Ticker

**What goes wrong:** `CIK` is correctly resolved from `tickers.json` but the companyfacts endpoint returns 404.

**Why it happens:** The company recently went public (pre-XBRL filing), is a foreign filer (20-F not 10-K), or the CIK maps to a holding company that does not file consolidated XBRL.

**How to avoid:** Catch `ValueError` from `fetch_companyfacts`. Log the failure and return `None` from `scrape()`. The orchestrator in Phase 3 can skip tickers with no XBRL data. Do NOT retry 404s.

---

## Code Examples

Verified patterns from official sources:

### Identity Setup (edgartools official)

```python
# Source: https://edgartools.readthedocs.io/en/stable/configuration/
from edgar import set_identity, set_rate_limit

# Option 1: from environment variable (set EDGAR_IDENTITY in .env)
# edgartools auto-reads EDGAR_IDENTITY env var on import if set before import

# Option 2: explicit call (must be called before any Company() or get_filings() call)
set_identity("Seb Analyst seb@example.com")

# Option 3: lower rate limit for safety (default is 9, max is 10 per SEC policy)
set_rate_limit(8)
```

### Getting 10 Years of 10-K Filings via XBRLS (edgartools multi-period stitching)

```python
# Source: https://edgartools.readthedocs.io/en/latest/getting-xbrl/
# Use for Phase 2 — XBRLS gives normalized DataFrames across multiple years
from edgar import Company
from edgar.xbrl import XBRLS

company = Company("AAPL")
# head(10) = last 10 annual 10-K filings
filings = company.get_filings(form="10-K").head(10)
xbrls = XBRLS.from_filings(filings)

# Stitched financial statements spanning 10 years
income_trend = xbrls.statements.income_statement()
balance_sheet_trend = xbrls.statements.balance_sheet()
cashflow_trend = xbrls.statements.cashflow_statement()

# Export to pandas DataFrame
df = income_trend.to_dataframe()
```

### Getting Company Facts (raw companyfacts approach, for Phase 1 persistence)

```python
# Source: https://edgartools.readthedocs.io/en/latest/guides/company-facts/
# edgartools wraps: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json
from edgar import Company

company = Company("AAPL")
facts = company.get_facts()  # returns CompanyFacts object (pyarrow.Table backed)

# Query specific concept
revenue_df = facts.to_pandas("us-gaap:Revenues")

# Get all available concept names
print(facts.facts_meta)
```

### Direct Raw JSON for Phase 1 Persistence

```python
# Source: SEC EDGAR API documentation + edgartools configuration docs
# Use this pattern (not get_facts()) to persist the verbatim JSON
import httpx
import json
from pathlib import Path

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

def download_raw_companyfacts(cik: str, identity: str, out_path: Path) -> Path:
    """
    Fetches verbatim companyfacts JSON and writes to out_path.
    cik: zero-padded 10-digit string.
    """
    url = COMPANYFACTS_URL.format(cik=cik)
    headers = {"User-Agent": identity}
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(resp.json(), indent=2))
    return out_path
```

### Ticker-to-CIK Mapping

```python
# Source: https://www.sec.gov/files/company_tickers.json (official SEC endpoint)
# Confirmed structure: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
import json, httpx
from pathlib import Path

def build_ticker_map(cache_path: Path, identity: str) -> dict[str, str]:
    """Returns {TICKER: "0000320193"} for all SEC filers."""
    if not cache_path.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        resp = httpx.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": identity},
            timeout=30,
        )
        resp.raise_for_status()
        cache_path.write_text(json.dumps(resp.json()))

    raw = json.loads(cache_path.read_text())
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
```

### Validate Facts.json Has Useful Data

```python
def validate_facts(facts_path: Path) -> dict:
    """
    Returns {"ok": bool, "fy_count": int, "earliest_fy": int, "latest_fy": int}
    Useful for smoke-testing after download without hitting SEC again.
    """
    import json
    facts = json.loads(facts_path.read_text())
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return {"ok": False, "fy_count": 0, "reason": "No us-gaap facts found"}

    # Collect all fiscal year values across all concepts
    all_fy = set()
    for concept_data in us_gaap.values():
        for unit_entries in concept_data.get("units", {}).values():
            for entry in unit_entries:
                if entry.get("form") == "10-K" and entry.get("fp") == "FY":
                    all_fy.add(entry.get("fy"))

    all_fy.discard(None)
    if not all_fy:
        return {"ok": False, "fy_count": 0, "reason": "No 10-K FY entries in us-gaap"}

    return {
        "ok": True,
        "fy_count": len(all_fy),
        "earliest_fy": min(all_fy),
        "latest_fy": max(all_fy),
    }
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `sec-edgar-downloader` + manual XBRL parsing | `edgartools` with XBRL-native API | 2023 onwards | Eliminates 200+ lines of XBRL parsing code; returns DataFrames directly |
| `requests` with manual rate limiting | edgartools with `httpxthrottlecache` token bucket | edgartools v4.x+ | Built-in 9 req/s limit with burst handling; no manual `time.sleep()` needed |
| Separate CIK lookup API call per ticker | `company_tickers.json` bulk download + local cache | Always available | One download caches all ~12,000 filers; zero network calls per lookup |
| `python-xbrl` / `arelle` | `edgartools` | 2023+ | edgartools wraps both XBRL parsing AND the SEC API; no taxonomy expertise needed |
| edgartools 2.x | edgartools 5.x | Released ~2025-2026 | Major API rewrite; `XBRLS.from_filings()` for multi-period stitching; `facts.query()` interface; version 5.17.1 as of 2026-02-24 |

**Deprecated/outdated:**
- edgartools 2.x API examples (e.g., `.get_filings().latest().xbrl()` returning `XBRLData` with `.financials`): The library has evolved to 5.x with `XBRLS`, `facts.query()`, and a more structured statement API. Do not copy 2.x examples without verifying against current docs.
- `requests.Session` with `HTTPAdapter` + manual `Retry`: edgartools now uses `httpx` + `stamina` internally. For project-level retry, use `tenacity`.

---

## Open Questions

1. **edgartools 5.x API for `Company.get_facts()` persistence path**
   - What we know: `Company("AAPL").get_facts()` returns a `CompanyFacts` object backed by pyarrow.Table; the underlying JSON comes from `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json`
   - What's unclear: Whether `CompanyFacts` exposes a `.raw_json` or `.json()` property to get the verbatim dict without re-fetching, or whether a direct `httpx.get()` is required for raw persistence
   - Recommendation: Use direct `httpx.get()` to companyfacts URL for raw JSON persistence (guaranteed verbatim); use `Company.get_facts()` only for Phase 2 where the pyarrow-backed query interface is valuable

2. **BRK.B CIK resolution**
   - What we know: `company_tickers.json` may list as `BRK-B` (NYSE convention) or `BRK.B`
   - What's unclear: Exact key used in SEC's JSON vs brokerage ticker notation
   - Recommendation: Test `build_ticker_map()` against `BRK.B` and `BRK-B` during Wave 1 development; add a ticker normalization step that tries both formats on KeyError

3. **tickers.json refresh strategy for XTRCT-01**
   - What we know: XTRCT-01 requires downloading the JSON "at startup" and caching; edgartools caches it internally at 30-second TTL
   - What's unclear: Whether the project's own `data/cache/tickers.json` should be refreshed on every run or only when absent
   - Recommendation: Download on first run (file absent) and add optional `--refresh-tickers` flag. For Phase 1, absence-only is sufficient. Add TTL (30 days) in Phase 3 when the orchestrator is built.

---

## Sources

### Primary (HIGH confidence)

- edgartools ReadTheDocs (https://edgartools.readthedocs.io/en/stable/configuration/) — configuration options, EDGAR_IDENTITY, rate limit env vars, `set_identity()` API
- edgartools ReadTheDocs (https://edgartools.readthedocs.io/en/latest/getting-xbrl/) — XBRLS multi-period stitching, `XBRL.from_filing()`, `facts.query()` interface
- DeepWiki edgartools HTTP client analysis (https://deepwiki.com/dgunning/edgartools/7.3-http-client-and-caching) — internal rate limiter (9 req/s token bucket via httpxthrottlecache), caching TTLs, retry via stamina, SSL handling
- PyPI edgartools (https://pypi.org/project/edgartools/) — latest version 5.17.1, released 2026-02-24, Python >=3.10
- SEC EDGAR API (https://www.sec.gov/files/company_tickers.json) — official ticker→CIK JSON URL confirmed
- SEC EDGAR companyfacts endpoint — confirmed structure `{"cik": ..., "facts": {"us-gaap": {...}}}`
- ARCHITECTURE.md (project file) — confirmed data flow, `scraper.py` responsibilities, data/raw/{TICKER}/facts.json output path, token bucket pattern

### Secondary (MEDIUM confidence)

- WebSearch results confirming SEC 10 req/s policy (multiple sources including official SEC announcement at https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits)
- WebSearch results confirming `company_tickers.json` structure: `{"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}}`
- edgartools GitHub discussions confirming `Company.get_facts()` wraps `data.sec.gov/api/xbrl/companyfacts/CIK{cik:010}.json`

### Tertiary (LOW confidence)

- BRK.B CIK resolution behavior: not directly verified; flag for validation in Wave 1

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — edgartools 5.17.1 verified on PyPI, httpx widely used, all versions confirmed current
- Architecture: HIGH — data flow and file paths confirmed against ARCHITECTURE.md and official SEC API structure
- Pitfalls: HIGH — rate limit policy confirmed against official SEC announcement; CIK/ticker drift confirmed from multiple practical sources; pre-XBRL gap well-documented

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (edgartools releases frequently; verify version before pinning; SEC policy stable)
