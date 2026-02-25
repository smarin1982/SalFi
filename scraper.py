"""
scraper.py — Phase 1: Data Extraction
Sole responsibility: Talk to SEC EDGAR. Fetch, rate-limit, persist raw facts.json.
Nothing else. No KPI calculation, no Parquet, no Streamlit.
"""

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from edgar import set_identity
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DATA_DIR = Path(__file__).parent / "data"

# Populated by _init_edgar() at module load
HEADERS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Initialization — MUST run before any SEC API call
# ---------------------------------------------------------------------------

def _init_edgar() -> None:
    """
    Configure edgartools identity and rate limit.
    Called once at module load. Sets User-Agent header for all direct httpx calls.
    XTRCT-02: rate limit set to 8 req/s (conservatively under SEC's 10 req/s policy).
    """
    load_dotenv(Path(__file__).parent / ".env")
    identity = os.getenv("EDGAR_IDENTITY")
    if not identity:
        raise EnvironmentError(
            "EDGAR_IDENTITY not set. Add to .env: EDGAR_IDENTITY='Name email@domain.com'"
        )
    # XTRCT-02: set rate limit to 8 req/s (conservatively under SEC's 10 req/s policy)
    # edgartools 5.x uses EDGAR_RATE_LIMIT_PER_SEC env var (set_rate_limit() was removed)
    os.environ["EDGAR_RATE_LIMIT_PER_SEC"] = "8"
    set_identity(identity)
    HEADERS["User-Agent"] = identity
    logger.debug(f"edgartools initialized — identity: {identity[:30]}... rate_limit: 8 req/s")


# ---------------------------------------------------------------------------
# XTRCT-01: Ticker → CIK resolution with local cache
# ---------------------------------------------------------------------------

def build_ticker_map(cache_path: Path | None = None) -> dict[str, str]:
    """
    Download company_tickers.json from SEC (once) and build {TICKER: CIK} map.
    Returns {ticker_upper: zero_padded_10d_cik_string}.
    Reads from cache_path if file exists — zero network calls per resolution.
    XTRCT-01: downloads at startup, caches locally.
    """
    if cache_path is None:
        cache_path = DATA_DIR / "cache" / "tickers.json"

    if cache_path.exists():
        logger.debug(f"Loading ticker map from cache: {cache_path}")
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        logger.info(f"Downloading ticker→CIK map from SEC: {TICKERS_URL}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        resp = httpx.get(TICKERS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        cache_path.write_text(json.dumps(raw), encoding="utf-8")
        logger.info(f"Ticker map cached: {cache_path} ({len(raw)} entries)")

    # Structure: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}


def resolve_cik(ticker: str, ticker_map: dict[str, str]) -> str:
    """
    Resolve ticker to zero-padded 10-digit CIK string.
    Handles BRK.B / BRK-B normalization (SEC may use either dot or dash).
    Raises ValueError for unknown tickers.
    """
    normalized = ticker.upper()
    cik = ticker_map.get(normalized)

    if cik is None:
        # BRK.B edge case: try alternative notation
        alt = normalized.replace(".", "-") if "." in normalized else normalized.replace("-", ".")
        cik = ticker_map.get(alt)
        if cik is not None:
            logger.debug(f"Ticker '{ticker}' resolved via alternative notation '{alt}' → CIK {cik}")
        else:
            raise ValueError(
                f"Ticker '{ticker}' not found in SEC tickers.json. "
                f"Verify it is a valid S&P 500 ticker (tried '{normalized}' and '{alt}')."
            )

    return cik


# ---------------------------------------------------------------------------
# XTRCT-03: Raw companyfacts JSON download with retry
# XTRCT-04: Existence check — use local copy if already present
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    reraise=True,
)
def fetch_companyfacts(cik: str) -> dict:
    """
    Download raw XBRL company facts JSON from SEC EDGAR companyfacts endpoint.
    cik: zero-padded 10-digit string, e.g. "0000320193"
    Returns verbatim parsed JSON dict.
    Retries up to 5 times with exponential backoff on HTTP/transport errors.
    Does NOT retry 404 (deterministic failure — no XBRL data for this CIK).
    XTRCT-03: uses official EDGAR XBRL companyfacts endpoint.
    """
    url = COMPANYFACTS_URL.format(cik=cik)
    logger.debug(f"Fetching companyfacts: {url}")

    with httpx.Client(timeout=60.0) as client:
        resp = client.get(url, headers=HEADERS)

    if resp.status_code == 404:
        raise ValueError(
            f"No XBRL companyfacts found for CIK {cik}. "
            f"Company may not file XBRL (foreign filer or pre-XBRL era), or CIK is incorrect."
        )
    resp.raise_for_status()
    return resp.json()


def download_facts(
    ticker: str,
    cik: str,
    force_refresh: bool = False,
) -> Path:
    """
    Download and persist facts.json for a ticker to data/raw/{TICKER}/facts.json.
    Skips download if file already exists and force_refresh is False.
    Returns path to facts.json.
    XTRCT-04: local copy takes precedence over re-fetching.
    """
    out_path = DATA_DIR / "raw" / ticker.upper() / "facts.json"

    if out_path.exists() and not force_refresh:
        logger.info(f"Using cached facts.json for {ticker}: {out_path}")
        return out_path  # XTRCT-04: use local copy

    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Downloading facts for {ticker} (CIK {cik})...")
    facts = fetch_companyfacts(cik)
    out_path.write_text(json.dumps(facts, indent=2), encoding="utf-8")
    size_kb = out_path.stat().st_size // 1024
    logger.info(f"Facts saved: {out_path} ({size_kb} KB)")
    return out_path


# ---------------------------------------------------------------------------
# Validation — smoke-test after download
# ---------------------------------------------------------------------------

def validate_facts(facts_path: Path) -> dict:
    """
    Smoke-test a downloaded facts.json for usable 10-K data.
    Returns {"ok": bool, "fy_count": int, "earliest_fy": int, "latest_fy": int}
    Does NOT hit SEC — reads local file only.
    """
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    if not us_gaap:
        return {"ok": False, "fy_count": 0, "reason": "No us-gaap facts found in JSON"}

    all_fy: set[int] = set()
    for concept_data in us_gaap.values():
        for unit_entries in concept_data.get("units", {}).values():
            for entry in unit_entries:
                if entry.get("form") == "10-K" and entry.get("fp") == "FY":
                    fy = entry.get("fy")
                    if fy is not None:
                        all_fy.add(fy)

    if not all_fy:
        return {"ok": False, "fy_count": 0, "reason": "No 10-K FY entries in us-gaap"}

    return {
        "ok": True,
        "fy_count": len(all_fy),
        "earliest_fy": min(all_fy),
        "latest_fy": max(all_fy),
        "entity": facts.get("entityName", "unknown"),
    }


# ---------------------------------------------------------------------------
# Main entry point
# XTRCT-01+02+03+04: orchestrates all steps for a single ticker
# ---------------------------------------------------------------------------

def scrape(ticker: str, force_refresh: bool = False) -> Path:
    """
    Main entry point for Phase 1.
    Resolves ticker → CIK → downloads facts.json (or uses cached copy).
    Returns path to data/raw/{TICKER}/facts.json.
    Raises ValueError for invalid tickers or companies with no XBRL data.
    """
    ticker = ticker.upper()
    logger.info(f"Scraping {ticker} (force_refresh={force_refresh})")

    ticker_map = build_ticker_map()  # loads from cache if exists (XTRCT-01)
    cik = resolve_cik(ticker, ticker_map)
    logger.debug(f"{ticker} → CIK {cik}")

    facts_path = download_facts(ticker, cik, force_refresh=force_refresh)

    validation = validate_facts(facts_path)
    if validation["ok"]:
        logger.info(
            f"{ticker} ({validation['entity']}): "
            f"{validation['fy_count']} fiscal years available "
            f"({validation['earliest_fy']}–{validation['latest_fy']})"
        )
    else:
        logger.warning(f"{ticker}: facts.json validation warning — {validation.get('reason')}")

    return facts_path


# ---------------------------------------------------------------------------
# Module initialization — runs on import
# ---------------------------------------------------------------------------

_init_edgar()


# ---------------------------------------------------------------------------
# CLI usage: python scraper.py AAPL [--force]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scraper.py TICKER [--force]")
        print("Example: python scraper.py AAPL")
        print("         python scraper.py BRK.B --force")
        sys.exit(1)

    ticker_arg = sys.argv[1]
    force_arg = "--force" in sys.argv

    try:
        path = scrape(ticker_arg, force_refresh=force_arg)
        print(f"Success: {path}")
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
