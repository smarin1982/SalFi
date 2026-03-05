# currency.py
#
# FX Normalizer — tiered Frankfurter + open.er-api.com fallback strategy.
#
# ARS/CLP/COP/PEN: open.er-api.com spot rate used as proxy for historical annual
# average. Cached at first call time. Flag approximated_fx=true in meta.json.
#
# Limitation: disk cache (_load_disk_cache / _save_disk_cache) is NOT thread-safe.
# Designed for single-threaded processor contexts. If concurrency is needed,
# add file locking via the `filelock` library.
#
# Phase 6 Plan 01 — GREEN implementation.

import json
import requests
from functools import lru_cache
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRANKFURTER_CURRENCIES = {"BRL", "MXN"}  # Only LATAM currencies ECB tracks
SECONDARY_API_BASE = "https://open.er-api.com/v6/latest/{base}"
CACHE_FILE = Path("data/cache/fx_rates.json")


# ---------------------------------------------------------------------------
# Disk cache helpers
# ---------------------------------------------------------------------------

def _load_disk_cache() -> dict:
    """Load FX rate disk cache. Returns empty dict if file does not exist."""
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_disk_cache(cache: dict) -> None:
    """Persist FX rate disk cache to JSON. Creates parent dirs if needed."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Internal API helpers
# ---------------------------------------------------------------------------

def _frankfurter_annual_avg(currency: str, year: int) -> float:
    """
    True annual average from Frankfurter time-series endpoint.
    Fetches daily BRL/USD or MXN/USD rates for the full calendar year,
    then computes the arithmetic mean.

    Source: api.frankfurter.app — confirmed live 2026-03-04.
    Returns float (USD per 1 unit of currency).
    """
    url = f"https://api.frankfurter.app/{year}-01-01..{year}-12-31"
    resp = requests.get(url, params={"from": currency, "to": "USD"}, timeout=10)
    resp.raise_for_status()
    rates = resp.json()["rates"]  # {"2023-01-02": {"USD": 0.1943}, ...}
    usd_values = [v["USD"] for v in rates.values()]
    return sum(usd_values) / len(usd_values)


def _secondary_api_rate(currency: str) -> float:
    """
    Current spot rate from open.er-api.com — no API key required.
    NOTE: This is NOT a historical annual average. The rate reflects the
    market price at the time of first request and is cached to disk.
    All callers of non-Frankfurter currencies must set approximated_fx=true
    in meta.json to document this limitation.

    Source: open.er-api.com — confirmed live 2026-03-04.
    Returns float (USD per 1 unit of currency).
    """
    url = SECONDARY_API_BASE.format(base=currency)
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()["rates"]["USD"]


# ---------------------------------------------------------------------------
# Core cached rate lookup
# ---------------------------------------------------------------------------

@lru_cache(maxsize=256)
def get_annual_avg_rate(currency: str, year: int) -> float:
    """
    Return annual-average USD/{currency} exchange rate for the given fiscal year.

    Routing:
      BRL / MXN  → Frankfurter time-series (true annual average from ECB daily data)
      ARS / CLP / COP / PEN → open.er-api.com current spot rate (approximation;
          cached at first call time; NOT a true historical annual average)

    Results are cached in-process via lru_cache and persisted to
    data/cache/fx_rates.json for cross-session reuse.

    Fallback: any HTTP 4xx error from Frankfurter triggers the secondary API.
    This handles both 404 (currency not listed) and 422 responses per RESEARCH.md.
    """
    cache_key = f"{currency}_{year}"
    disk_cache = _load_disk_cache()
    if cache_key in disk_cache:
        return disk_cache[cache_key]

    if currency in FRANKFURTER_CURRENCIES:
        try:
            rate = _frankfurter_annual_avg(currency, year)
        except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as exc:
            # Fallback: Frankfurter 4xx or network error — use secondary API
            logger.warning(
                f"FX: Frankfurter failed for {currency}/{year} ({exc}) "
                f"— falling back to open.er-api.com spot rate."
            )
            rate = _secondary_api_rate(currency)
    else:
        rate = _secondary_api_rate(currency)
        logger.warning(
            f"FX: {currency} not in Frankfurter — using open.er-api.com spot rate "
            f"as proxy for year {year}. Rate may not reflect {year} annual average. "
            f"Set approximated_fx=true in meta.json for this company."
        )

    disk_cache[cache_key] = rate
    _save_disk_cache(disk_cache)
    return rate


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def to_usd(amount: float, currency: str, fiscal_year: int) -> float:
    """
    Convert amount in the given currency to USD for the specified fiscal year.

    Args:
        amount:      Monetary value in the original currency.
        currency:    ISO 4217 currency code (e.g. "BRL", "ARS", "USD").
        fiscal_year: Calendar year used to select the correct annual FX rate.

    Returns:
        float — USD equivalent. Never returns None.
        If currency is already "USD", returns amount unchanged.
    """
    if currency == "USD":
        return float(amount)
    rate = get_annual_avg_rate(currency, fiscal_year)
    return float(amount) * rate


def is_low_confidence_currency(currency: str) -> bool:
    """
    Return True if the currency's FX conversion is considered low-confidence.

    ARS (Argentine Peso) is flagged due to:
    - Extreme volatility relative to USD
    - Parallel exchange rates (official vs. blue-chip swap)
    - open.er-api.com returns spot rate, not controlled official rate

    All other supported currencies (BRL, MXN, CLP, COP, PEN, USD) return False.
    """
    return currency == "ARS"
