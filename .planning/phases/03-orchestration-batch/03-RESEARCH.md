# Phase 3: Orchestration & Batch — Research

**Researched:** 2026-02-26
**Domain:** Python ETL orchestration — FinancialAgent class, staleness detection, KPI_REGISTRY, batch runner, metadata.parquet
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ORCHS-01 | Implement a `FinancialAgent` extensible class that orchestrates extraction + transformation for a ticker, with `KPI_REGISTRY` for adding KPIs without structural changes | Agent class design (stateless, file-backed); KPI_REGISTRY iterator pattern in `calculate_kpis()`; integration contract with scraper.py and processor.py |
| ORCHS-02 | Detect if ticker data is current-quarter (`needs_update()`) and skip re-scraping if current | Staleness logic using `datetime` + quarter math; `metadata.parquet` schema with `last_downloaded` timestamp; `force_refresh` parameter on `download_facts()` |
| ORCHS-03 | Execute ETL for 20 base S&P 500 companies in one command | Sequential batch runner; per-ticker error isolation; result accumulation; metadata upsert strategy |
</phase_requirements>

---

## Summary

Phase 3 builds `agent.py` as a thin coordination layer over the already-verified `scraper.py` and `processor.py`. The FinancialAgent class is intentionally stateless between instantiations — all persistent state lives in `data/cache/metadata.parquet`. This keeps the class simple and safe to re-run from any state.

The staleness check (`needs_update()`) must use calendar-quarter logic, not fiscal-year logic. A ticker is "current" if its `last_downloaded` timestamp falls within the current calendar quarter (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec). This is simpler and more reliable than tracking fiscal-year availability because the facts.json endpoint always returns all years — the question is only whether we downloaded it recently enough.

The batch runner runs sequentially (not in parallel) to respect the 8 req/s SEC rate limit already enforced by scraper.py. Errors per ticker are caught and recorded; a failed ticker does not abort the batch. The metadata.parquet is updated per ticker immediately after each successful run, so partial batch completion is durable and resumable.

**Primary recommendation:** Build `agent.py` with `FinancialAgent` class + `run_batch()` function. Keep it strictly a coordinator — call `scraper.scrape()` and `processor.process()` directly. No business logic in the agent itself.

---

## Standard Stack

### Core (already in project — no new installs needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | installed (Phase 2) | metadata.parquet read/write | Already used throughout processor.py |
| pyarrow | installed (Phase 2) | Parquet engine for metadata | Same engine as all other Parquet files in project |
| pathlib.Path | stdlib | File path management | Already pattern throughout scraper.py + processor.py |
| datetime / zoneinfo | stdlib | Quarter detection, timestamp tracking | No external dependency; zoneinfo in Python 3.9+ |
| loguru | installed (Phase 1) | Structured logging per ticker | Already in scraper.py; consistent logging pattern |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tqdm | installed (Phase 1) | Progress bar for batch of 20 | Wrap `BASE_TICKERS` iteration in batch runner |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Sequential batch loop | concurrent.futures ThreadPoolExecutor | Parallel would violate 8 req/s rate limit — SEC bans by IP. Sequential is correct here. |
| metadata.parquet | SQLite | Parquet consistent with project pattern; SQLite adds dependency; overkill for 20 rows |
| datetime.now() | pd.Timestamp.now() | Either works; pd.Timestamp integrates cleanly with pandas metadata DataFrame |

**Installation:** No new packages required. All dependencies from Phase 1 and Phase 2 are sufficient.

---

## Architecture Patterns

### Recommended Project Structure

```
C:/Users/Seb/AI 2026/
├── scraper.py          # Phase 1 — unchanged
├── processor.py        # Phase 2 — unchanged (KPI_REGISTRY added here)
├── agent.py            # Phase 3 — NEW: FinancialAgent + run_batch()
└── data/
    ├── raw/{TICKER}/facts.json
    ├── clean/{TICKER}/financials.parquet
    ├── clean/{TICKER}/kpis.parquet
    └── cache/
        ├── tickers.json
        └── metadata.parquet   # NEW: run log for 20+ tickers
```

### Pattern 1: Stateless FinancialAgent

**What:** The agent holds no mutable state. All state is read from / written to `metadata.parquet` on each call. The agent is safe to instantiate multiple times, re-run after crashes, and call from the dashboard without coordination.

**When to use:** Always. Any in-memory state would make the class non-resumable.

```python
# agent.py — Source: derived from ARCHITECTURE.md design + actual scraper.py/processor.py APIs
from pathlib import Path
import pandas as pd
from datetime import datetime
from loguru import logger

import scraper   # uses: scraper.build_ticker_map(), scraper.resolve_cik(), scraper.scrape()
import processor # uses: processor.process()

DATA_DIR = Path(__file__).parent / "data"
METADATA_PATH = DATA_DIR / "cache" / "metadata.parquet"

BASE_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG",
    "BRK.B", "TSLA", "LLY", "AVGO", "JPM", "V", "UNH",
    "XOM", "MA", "JNJ", "WMT", "PG", "HD",
]

class FinancialAgent:
    """
    Orchestrates scraper.py + processor.py for one ticker.
    Stateless between instantiations — all state in metadata.parquet.
    """

    def __init__(self, ticker: str, data_dir: Path = DATA_DIR):
        self.ticker = ticker.upper()
        self.data_dir = data_dir

    def run(self, force_refresh: bool = False) -> dict:
        """
        Full ETL for this ticker. Returns result dict.
        Skips scraping if current-quarter data exists (unless force_refresh=True).
        """
        if not force_refresh and not self.needs_update():
            logger.info(f"{self.ticker}: data is current-quarter, skipping scrape")
            # Still re-process to pick up any KPI_REGISTRY changes
            result = processor.process(self.ticker, self.data_dir)
            _update_metadata(self.ticker, result, scraped=False, data_dir=self.data_dir)
            return {"status": "skipped_scrape", "ticker": self.ticker, **result}

        # Full ETL: scrape + process
        scraper.scrape(self.ticker, force_refresh=force_refresh)
        result = processor.process(self.ticker, self.data_dir)
        _update_metadata(self.ticker, result, scraped=True, data_dir=self.data_dir)
        return {"status": "success", "ticker": self.ticker, **result}

    def needs_update(self) -> bool:
        """
        Returns True if ticker is NOT in current calendar quarter.
        'Current quarter' = same year AND same quarter (1-4) as today.
        A ticker with no metadata row always needs update.
        """
        meta = _load_metadata(self.data_dir)
        if self.ticker not in meta.index:
            return True
        last_dl = pd.Timestamp(meta.loc[self.ticker, "last_downloaded"])
        return not _same_quarter(last_dl, pd.Timestamp.now())
```

### Pattern 2: Calendar-Quarter Staleness Detection

**What:** Compare the quarter of `last_downloaded` timestamp to the current quarter. Two timestamps are in the same quarter if `(year, quarter_number)` matches. Python's `datetime` provides `month` but not `quarter` directly — compute it as `(month - 1) // 3 + 1`.

**When to use:** In `needs_update()`. This is the correct staleness check for ORCHS-02.

```python
# Source: stdlib datetime — verified pattern
from datetime import datetime

def _same_quarter(ts1: pd.Timestamp, ts2: pd.Timestamp) -> bool:
    """
    Returns True if both timestamps are in the same calendar quarter and year.
    Q1: Jan-Mar, Q2: Apr-Jun, Q3: Jul-Sep, Q4: Oct-Dec.
    """
    def quarter(ts: pd.Timestamp) -> tuple:
        return (ts.year, (ts.month - 1) // 3 + 1)
    return quarter(ts1) == quarter(ts2)
```

**Why this beats year-only comparison:** A ticker downloaded in Q1 2026 (January) would incorrectly appear "current" in Q4 2026 (December) under year-only logic. Quarter-granularity means at most 3 months of staleness, which aligns with SEC's quarterly filing cycle.

**Edge case — quarter boundary:** If the current date is the first day of a new quarter and no companies have yet filed, data from the prior quarter is still the most current available. The staleness check is still correct — the next run will trigger a download, which will return the same data (facts.json is stable until a new 10-K is filed). The re-download cost is low: one HTTP call, ~5-8 MB.

### Pattern 3: KPI_REGISTRY in processor.py

**What:** Replace the implicit list of KPI calculations in `calculate_kpis()` with an explicit registry dict: `{kpi_name: callable}`. The agent calls `calculate_kpis()` unchanged — the registry is internal to processor.py.

**When to use:** This enables ORCHS-01's requirement that "adding a new KPI requires no changes to scraper, agent, or dashboard."

**Current state (Phase 2):** `calculate_kpis()` computes 20 KPIs inline. There is no formal `KPI_REGISTRY` dict yet — all KPIs are hard-coded in the function body.

**Phase 3 change:** Refactor `calculate_kpis()` to iterate a `KPI_REGISTRY` dict. The agent calls `processor.process()` unchanged. The dashboard reads `kpis.parquet` columns unchanged. Only `processor.py` changes when a new KPI is added.

```python
# processor.py addition — KPI_REGISTRY pattern
# Source: derived from existing calculate_kpis() structure in processor.py

# Each entry: kpi_name -> callable(df: pd.DataFrame) -> pd.Series
KPI_REGISTRY: dict[str, callable] = {
    "revenue_growth_yoy":     lambda df: _col(df, "revenue").pct_change(),
    "gross_profit_margin":    lambda df: safe_divide(_col(df, "gross_profit"), _col(df, "revenue")),
    "operating_margin":       lambda df: safe_divide(_col(df, "operating_income"), _col(df, "revenue")),
    "net_profit_margin":      lambda df: safe_divide(_col(df, "net_income"), _col(df, "revenue")),
    # ... all 20 KPIs registered here ...
}

def calculate_kpis(df: pd.DataFrame) -> pd.DataFrame:
    """Iterate KPI_REGISTRY — adding a new KPI = add one entry to KPI_REGISTRY."""
    d = df.set_index("fiscal_year").copy()
    kpis = pd.DataFrame(index=d.index)
    for kpi_name, kpi_fn in KPI_REGISTRY.items():
        try:
            kpis[kpi_name] = kpi_fn(d)
        except Exception as e:
            logger.warning(f"KPI '{kpi_name}' failed: {e} — setting to NaN")
            kpis[kpi_name] = np.nan
    kpis = kpis.reset_index()
    kpis.insert(0, "ticker", df["ticker"].iloc[0])
    return kpis
```

**Key insight:** The try/except per KPI prevents a single bad KPI formula from failing all 20 KPIs. The existing `safe_divide()` handles the zero-denominator case; the try/except handles structural errors in new KPI formulas during development.

### Pattern 4: metadata.parquet Schema and Upsert

**What:** A single Parquet file at `data/cache/metadata.parquet` tracks ETL run state for all tickers. It is the agent's only persistent state.

**Schema (one row per ticker):**

```python
# metadata.parquet columns
{
    "ticker":           str,      # PRIMARY KEY — e.g. "AAPL"
    "last_downloaded":  datetime, # timestamp of last scraper.scrape() call
    "last_processed":   datetime, # timestamp of last processor.process() call
    "fy_count":         int,      # number of fiscal years in financials.parquet
    "status":           str,      # "success" | "error" | "skipped_scrape"
    "error_message":    str,      # null if status == "success"
    "fields_missing":   str,      # comma-joined list from processor result
}
```

**Upsert pattern (no pandas merge complexity):**

```python
# Source: stdlib + pandas — verified pattern
def _load_metadata(data_dir: Path) -> pd.DataFrame:
    path = data_dir / "cache" / "metadata.parquet"
    if path.exists():
        return pd.read_parquet(path).set_index("ticker")
    return pd.DataFrame(columns=[
        "ticker", "last_downloaded", "last_processed",
        "fy_count", "status", "error_message", "fields_missing"
    ]).set_index("ticker")

def _update_metadata(ticker: str, result: dict, scraped: bool, data_dir: Path) -> None:
    meta = _load_metadata(data_dir)
    now = pd.Timestamp.now()
    meta.loc[ticker] = {
        "last_downloaded":  now if scraped else meta.loc[ticker, "last_downloaded"] if ticker in meta.index else now,
        "last_processed":   now,
        "fy_count":         len(result.get("fiscal_years", [])),
        "status":           result.get("status", "success"),
        "error_message":    result.get("error", None),
        "fields_missing":   ",".join(result.get("fields_missing", [])),
    }
    path = data_dir / "cache" / "metadata.parquet"
    meta.reset_index().to_parquet(path, index=False, engine="pyarrow")
```

**Critical:** When `scraped=False` (skip scrape path), preserve the existing `last_downloaded` value. Do NOT update it to now — that would make an unscraped ticker appear current indefinitely.

### Pattern 5: Batch Runner with Per-Ticker Error Isolation

**What:** `run_batch()` iterates all 20 tickers sequentially, catches exceptions per ticker, accumulates results, and writes a final summary log. A single ticker failure does not abort the batch.

**When to use:** ORCHS-03 — batch initialization.

```python
# agent.py — run_batch() function
# Source: derived from processor.py CLI pattern (lines 543-558)
from tqdm import tqdm

def run_batch(
    tickers: list[str] = BASE_TICKERS,
    force_refresh: bool = False,
    data_dir: Path = DATA_DIR,
) -> dict:
    """
    Run ETL for all tickers in list. Sequential — respects 8 req/s rate limit.
    Returns summary: {success: [...], skipped: [...], failed: [...]}
    """
    results = {"success": [], "skipped": [], "failed": []}

    for ticker in tqdm(tickers, desc="Batch ETL"):
        agent = FinancialAgent(ticker, data_dir)
        try:
            result = agent.run(force_refresh=force_refresh)
            if result["status"] == "skipped_scrape":
                results["skipped"].append(ticker)
            else:
                results["success"].append(ticker)
        except Exception as e:
            logger.error(f"[FAILED] {ticker}: {e}")
            # Write error to metadata so partial runs are visible
            _update_metadata_error(ticker, str(e), data_dir)
            results["failed"].append(ticker)

    # Summary log
    logger.info(
        f"Batch complete — "
        f"success: {len(results['success'])}, "
        f"skipped: {len(results['skipped'])}, "
        f"failed: {len(results['failed'])}"
    )
    if results["failed"]:
        logger.warning(f"Failed tickers: {results['failed']}")

    return results
```

### Anti-Patterns to Avoid

- **Parallel scraping in batch:** Using `ThreadPoolExecutor` or `asyncio` for the batch violates the 8 req/s SEC rate limit. scraper.py's `os.environ["EDGAR_RATE_LIMIT_PER_SEC"] = "8"` only controls edgartools internals — direct `httpx` calls in `fetch_companyfacts()` are not rate-limited at the concurrent level. Sequential loop is correct.
- **Importing scraper at agent.py module level without handling `_init_edgar()`:** `scraper.py` calls `_init_edgar()` at module load (line 249: `_init_edgar()`). This requires `.env` to exist. If `.env` is missing, importing `scraper` raises `EnvironmentError`. The agent should let this propagate — it is not an agent bug.
- **Updating `last_downloaded` on skip path:** If `needs_update()` returns False and we skip scraping, do NOT update `last_downloaded` to now. Doing so would mark stale data as current. Only update `last_downloaded` when `scraper.scrape()` actually runs.
- **Putting business logic in the agent:** The agent calls `scraper.scrape()` and `processor.process()`. It does NOT re-implement XBRL parsing, KPI formulas, or rate limiting. All that stays in Phase 1 and Phase 2 files.
- **Circular imports:** `agent.py` imports `scraper` and `processor`. Neither `scraper.py` nor `processor.py` imports `agent`. The dependency graph is strictly one-directional: `agent → scraper`, `agent → processor`. Never the reverse.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Quarter detection | Custom month-to-quarter mapping | `(month - 1) // 3 + 1` one-liner | stdlib arithmetic; no library needed; verified against all 12 months |
| Parquet upsert | Custom merge/diff logic | Load → `df.loc[ticker] = row` → save | pandas index-based assignment handles upsert in 3 lines |
| Progress tracking | Custom progress counter | `tqdm` (already installed from Phase 1) | Zero cost; already in requirements.txt |
| Retry on scrape failure | Custom retry loop in agent | `tenacity` already in `fetch_companyfacts()` | scraper.py already retries 5x with exponential backoff; agent should not add a second retry layer |
| Rate limiting | Custom sleep in batch loop | Let scraper.py handle it | `EDGAR_RATE_LIMIT_PER_SEC=8` already enforced; adding sleep in agent would double-throttle |

**Key insight:** The agent's value is coordination, not capability. Every hard problem (rate limiting, retry, XBRL parsing, atomic writes) is already solved in Phase 1 and Phase 2. The agent just calls the right functions in the right order.

---

## Common Pitfalls

### Pitfall 1: Year-Only Staleness Check Returns False Positives

**What goes wrong:** `needs_update()` checks `last_year_available < current_year - 1`. A ticker processed in January 2026 would be considered "stale" because 2025 data is available and was just filed — but the facts.json already contains 2025 data (latest_fy from validate_facts). This creates unnecessary re-downloads in Q1.

**Why it happens:** The ARCHITECTURE.md design uses year comparison, but that conflates "did we download recently" with "is there new data available." The facts.json already contains the latest year even if we downloaded it yesterday.

**How to avoid:** Use calendar-quarter comparison on the download timestamp, not year comparison on the data content. A download in Q1 2026 is current for all of Q1 2026, regardless of what years are in the file.

**Warning signs:** Batch runner always re-downloads all 20 tickers on every run, even when run twice in the same week.

### Pitfall 2: Metadata Grows Unbounded on Column Mismatch

**What goes wrong:** First run writes metadata with 7 columns. A code change adds an 8th column. Second run reads the old Parquet (7 columns), tries to assign a row with 8 fields — pandas silently drops the new field or raises a KeyError.

**Why it happens:** Parquet schema is fixed at write time. New columns require schema migration.

**How to avoid:** In `_load_metadata()`, after reading the existing Parquet, add any missing columns with `None` defaults before returning. Use a canonical `METADATA_COLUMNS` list to detect mismatches.

```python
METADATA_COLUMNS = ["ticker", "last_downloaded", "last_processed",
                     "fy_count", "status", "error_message", "fields_missing"]

def _load_metadata(data_dir: Path) -> pd.DataFrame:
    path = data_dir / "cache" / "metadata.parquet"
    if path.exists():
        df = pd.read_parquet(path).set_index("ticker")
        # Forward-compatible: add new columns if schema evolved
        for col in METADATA_COLUMNS[1:]:  # skip "ticker" (it's the index)
            if col not in df.columns:
                df[col] = None
        return df
    return pd.DataFrame(columns=METADATA_COLUMNS).set_index("ticker")
```

### Pitfall 3: scraper._init_edgar() Runs on Import — Fails Without .env

**What goes wrong:** `agent.py` does `import scraper` at module level. scraper.py runs `_init_edgar()` at module load. If `.env` doesn't exist or `EDGAR_IDENTITY` is unset, the import raises `EnvironmentError` before any agent code runs.

**Why it happens:** `scraper.py` line 249: `_init_edgar()` is a module-level call.

**How to avoid:** This is expected behavior — the agent should not catch or suppress this error. Document it clearly: `agent.py` requires `.env` with `EDGAR_IDENTITY` set, same as `scraper.py`. The error message from `_init_edgar()` is clear enough.

**Warning signs:** `ImportError` or `EnvironmentError` when running `agent.py` in a new environment.

### Pitfall 4: GOOG and GOOGL — Same CIK, Different Tickers

**What goes wrong:** GOOGL (Class A) and GOOG (Class C) are both in BASE_TICKERS. They share the same CIK in SEC EDGAR. Running both in batch downloads the same facts.json twice and writes two identical Parquet files.

**Why it happens:** SEC files at the entity level (Alphabet Inc.), not the share class level. Both tickers map to the same CIK via `resolve_cik()`.

**How to avoid:** In batch runner, after resolving CIKs, skip duplicate CIKs for the scrape step. Reuse the same facts.json for both tickers' processing step. Or simply accept the duplication — GOOG and GOOGL will have identical Parquet files, which is correct financial data (same company). The 18 remaining tickers are distinct.

**Warning signs:** `data/raw/GOOG/facts.json` and `data/raw/GOOGL/facts.json` are byte-identical.

### Pitfall 5: Batch Failure After Partial Completion Loses Progress

**What goes wrong:** Batch runs 12/20 tickers successfully, then crashes (network timeout, OOM). On restart, the batch re-runs all 20 tickers, re-downloading the 12 already-completed.

**Why it happens:** Without metadata updates per-ticker, completed tickers are indistinguishable from not-yet-run tickers.

**How to avoid:** Call `_update_metadata()` immediately after each successful ticker in the batch loop — not at the end. On restart, `needs_update()` returns False for the 12 completed tickers (they are current-quarter), so they are skipped automatically. The batch resumes from ticker 13.

**Warning signs:** Batch always takes the same amount of time regardless of how many tickers already have current metadata.

---

## Code Examples

### Complete agent.py Structure

```python
# agent.py — Source: synthesized from scraper.py + processor.py APIs (verified in Phase 1-2)
"""
agent.py — Phase 3: Orchestration & Batch
Sole responsibility: coordinate scraper.py + processor.py per ticker.
No XBRL parsing, no SEC API calls, no KPI formulas — those stay in their modules.
"""
from pathlib import Path
import pandas as pd
import numpy as np
from loguru import logger
from tqdm import tqdm

import scraper
import processor

DATA_DIR = Path(__file__).parent / "data"
METADATA_PATH = DATA_DIR / "cache" / "metadata.parquet"
METADATA_COLUMNS = [
    "ticker", "last_downloaded", "last_processed",
    "fy_count", "status", "error_message", "fields_missing"
]

BASE_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG",
    "BRK.B", "TSLA", "LLY", "AVGO", "JPM", "V", "UNH",
    "XOM", "MA", "JNJ", "WMT", "PG", "HD",
]
```

### Correct Quarter Comparison (verified against all edge cases)

```python
# Source: stdlib datetime — no external dependency
def _same_quarter(ts1: pd.Timestamp, ts2: pd.Timestamp) -> bool:
    q1 = (ts1.year, (ts1.month - 1) // 3 + 1)
    q2 = (ts2.year, (ts2.month - 1) // 3 + 1)
    return q1 == q2

# Verification:
# Jan 1, 2026  → (2026, 1)
# Mar 31, 2026 → (2026, 1)  — same quarter ✓
# Apr 1, 2026  → (2026, 2)  — different quarter ✓
# Dec 31, 2026 → (2026, 4)
# Jan 1, 2027  → (2027, 1)  — different year + quarter ✓
```

### scraper.py Integration — Actual Function Signatures

```python
# From scraper.py (Phase 1 — verified):
# scraper.scrape(ticker: str, force_refresh: bool = False) -> Path
#   - Builds ticker map, resolves CIK, downloads facts.json (or uses cache)
#   - Returns path to data/raw/{TICKER}/facts.json
#   - Raises ValueError for unknown tickers or companies with no XBRL data

# Usage in agent:
facts_path = scraper.scrape(self.ticker, force_refresh=force_refresh)
```

### processor.py Integration — Actual Function Signatures

```python
# From processor.py (Phase 2 — verified):
# processor.process(ticker: str, data_dir: Path | str = "data") -> dict
#   - Reads data/raw/{TICKER}/facts.json
#   - Writes data/clean/{TICKER}/financials.parquet + kpis.parquet
#   - Returns: {ticker, fiscal_years, fields_extracted, fields_missing, kpi_columns}
#   - Raises FileNotFoundError if facts.json not found
#   - Raises ValueError if facts.json has no us-gaap data

# Usage in agent:
result = processor.process(self.ticker, self.data_dir)
```

### KPI_REGISTRY Refactor — Minimal Viable Pattern

The current `calculate_kpis()` in processor.py (lines 304-434) computes all 20 KPIs inline. The Phase 3 refactor wraps each KPI in the registry without changing any KPI math:

```python
# processor.py — add above calculate_kpis()
# Source: derived from existing calculate_kpis() inline logic

def _col(d: pd.DataFrame, name: str) -> pd.Series:
    """Get column from indexed DataFrame, return all-NaN Series if missing."""
    if name in d.columns:
        return d[name].astype(float)
    return pd.Series(np.nan, index=d.index, dtype=float)

KPI_REGISTRY: dict[str, callable] = {
    "revenue_growth_yoy": lambda d: _col(d, "revenue").pct_change(),
    "revenue_cagr_10y":   lambda d: _cagr_10y(_col(d, "revenue")),
    "gross_profit_margin": lambda d: safe_divide(_col(d, "gross_profit"), _col(d, "revenue")),
    "operating_margin":    lambda d: safe_divide(_col(d, "operating_income"), _col(d, "revenue")),
    "net_profit_margin":   lambda d: safe_divide(_col(d, "net_income"), _col(d, "revenue")),
    "ebitda_margin":       lambda d: safe_divide(
                               _col(d, "operating_income") + _col(d, "depreciation_amortization"),
                               _col(d, "revenue")),
    "roe":  lambda d: safe_divide(_col(d, "net_income"), _col(d, "total_equity")),
    "roa":  lambda d: safe_divide(_col(d, "net_income"), _col(d, "total_assets")),
    # ... remaining 12 KPIs follow same pattern
}

def calculate_kpis(df: pd.DataFrame) -> pd.DataFrame:
    d = df.set_index("fiscal_year").copy()
    kpis = pd.DataFrame(index=d.index)
    kpis.index.name = "fiscal_year"
    for kpi_name, kpi_fn in KPI_REGISTRY.items():
        try:
            kpis[kpi_name] = kpi_fn(d)
        except Exception as e:
            logger.warning(f"KPI '{kpi_name}' failed for {df['ticker'].iloc[0]}: {e}")
            kpis[kpi_name] = np.nan
    kpis = kpis.reset_index()
    kpis.insert(0, "ticker", df["ticker"].iloc[0])
    return kpis
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Inline KPI calculations | KPI_REGISTRY dict + iterator | Phase 3 (this phase) | New KPI = 1 line added, zero other file changes |
| Year-only staleness check (from ARCHITECTURE.md draft) | Calendar-quarter staleness check | Phase 3 decision | Prevents unnecessary re-downloads within a quarter |
| No metadata tracking | metadata.parquet per-ticker | Phase 3 | Batch is resumable; dashboard can show data freshness |

---

## Open Questions

1. **GOOG vs GOOGL CIK collision**
   - What we know: Both tickers are in BASE_TICKERS; both resolve to the same CIK (Alphabet Inc.); both will produce identical facts.json
   - What's unclear: Whether to deduplicate at batch level or accept the duplication
   - Recommendation: Accept the duplication in Phase 3. GOOG and GOOGL are legitimate separate tickers that the dashboard needs to handle. The 7-8 MB double download cost is negligible. Document the known duplication in code comments.

2. **BRK.B processor result — 13/20 KPIs are NaN**
   - What we know: BRK.B structural NaN in 9 CONCEPT_MAP fields causes most KPIs to be NaN (verified in Phase 2 VERIFICATION.md). This is correct financial data, not a processing error.
   - What's unclear: Whether `status` in metadata should be "success" or "partial" for BRK.B
   - Recommendation: Use `status="success"` and populate `fields_missing` in metadata. The dashboard will need to handle NaN KPIs gracefully regardless. A "partial" status would complicate batch-completion logic.

3. **CAGR-10Y KPI — only computable for tickers with 10+ years of data**
   - What we know: `revenue_cagr_10y` requires `yr - 10` to be in the index. Most top-20 companies have 15-20 years of XBRL data. AAPL has 17 FY (2009-2025), so CAGR is computable from 2019 onward.
   - What's unclear: Whether KPI_REGISTRY should include the `_cagr_10y` helper as a standalone function or inline lambda
   - Recommendation: Extract `_cagr_10y` as a module-level private function (not a lambda) — it's too complex for a one-liner and needs to be testable.

---

## Integration Contract Summary

This is the exact API surface the agent must use — verified against the actual Phase 1 and Phase 2 code:

### From scraper.py (use these, nothing else)

```
scraper.scrape(ticker, force_refresh=False) → Path
    - Handles: build_ticker_map(), resolve_cik(), download_facts(), validate_facts()
    - Raises: ValueError (unknown ticker, no XBRL data), EnvironmentError (no .env)
    - Side effect: writes data/raw/{TICKER}/facts.json
```

### From processor.py (use these, nothing else)

```
processor.process(ticker, data_dir="data") → dict
    - Handles: normalize_xbrl(), clean_financials(), calculate_kpis(), save_parquet()
    - Raises: FileNotFoundError (no facts.json), ValueError (no us-gaap data)
    - Side effect: writes data/clean/{TICKER}/financials.parquet + kpis.parquet
    - Returns: {ticker, fiscal_years: list[int], fields_extracted: list[str],
                fields_missing: list[str], kpi_columns: list[str]}
```

### No other imports from Phase 1/2 files

Do not import `scraper.fetch_companyfacts`, `scraper.build_ticker_map`, `processor.normalize_xbrl`, `processor.calculate_kpis`, etc. directly. The top-level functions `scrape()` and `process()` are the stable public API. Internal functions are implementation details.

---

## Sources

### Primary (HIGH confidence)
- `scraper.py` (lines 1-272) — Verified Phase 1 artifact; function signatures confirmed by 01-VERIFICATION.md
- `processor.py` (lines 1-558) — Verified Phase 2 artifact; all 8 functions confirmed by 02-VERIFICATION.md
- `ARCHITECTURE.md` — Project architecture research; FinancialAgent design pattern and metadata.parquet schema
- Python stdlib `datetime` docs — `(month - 1) // 3 + 1` quarter arithmetic; verified against all 12 months

### Secondary (MEDIUM confidence)
- `PITFALLS.md` pitfall #19 (Partial Run Corruption) — per-ticker metadata update strategy
- `PITFALLS.md` pitfall #21 (Re-Scraping) — motivates quarter-based staleness check
- `STATE.md` decisions — Windows NTFS atomic rename (unlink before rename), edgartools 5.x patterns

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed and verified in Phases 1-2; no new dependencies
- Architecture: HIGH — derived directly from verified scraper.py + processor.py code, not hypothetical
- Staleness logic: HIGH — stdlib datetime arithmetic; verified with concrete examples
- KPI_REGISTRY pattern: HIGH — mechanical refactor of existing calculate_kpis(); logic unchanged
- Pitfalls: HIGH — pitfalls 1, 3, 5 derived from actual code; pitfall 4 (GOOG/GOOGL) verified against SEC ticker lookup behavior from Phase 1

**Research date:** 2026-02-26
**Valid until:** 2026-05-26 (stable domain — stdlib + existing project code; no fast-moving dependencies)
