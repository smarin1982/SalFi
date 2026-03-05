"""
tests/test_currency.py — RED phase: tests for currency.py FX normalizer.
Covers all 6 LATAM currencies, fallback trigger, low-confidence flag, and disk cache.
Phase 6 Plan 01 — TDD RED.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import currency
from currency import is_low_confidence_currency, to_usd


# ---------------------------------------------------------------------------
# Identity / USD pass-through
# ---------------------------------------------------------------------------

def test_usd_identity():
    """to_usd with USD returns the original amount unchanged — no API call."""
    result = to_usd(500.0, "USD", 2023)
    assert result == 500.0


# ---------------------------------------------------------------------------
# Frankfurter currencies (BRL, MXN) — live integration tests
# ---------------------------------------------------------------------------

def test_to_usd_brl():
    """BRL 2023: Frankfurter annual average — result in (0, 1000)."""
    result = to_usd(1000.0, "BRL", 2023)
    assert isinstance(result, float)
    assert 0.0 < result < 1000.0, f"BRL result out of expected range: {result}"


def test_to_usd_mxn():
    """MXN 2023: Frankfurter annual average — result in (0, 1000)."""
    result = to_usd(1000.0, "MXN", 2023)
    assert isinstance(result, float)
    assert 0.0 < result < 1000.0, f"MXN result out of expected range: {result}"


# ---------------------------------------------------------------------------
# Secondary API currencies (ARS, CLP, COP, PEN) — live integration tests
# ---------------------------------------------------------------------------

def test_to_usd_ars():
    """ARS 2023: open.er-api.com spot rate — result > 0 (ARS very weak vs USD)."""
    result = to_usd(1000.0, "ARS", 2023)
    assert isinstance(result, float)
    assert result > 0.0, f"ARS result must be > 0, got {result}"


def test_to_usd_clp():
    """CLP 2023: open.er-api.com spot rate — result > 0."""
    result = to_usd(1000.0, "CLP", 2023)
    assert isinstance(result, float)
    assert result > 0.0, f"CLP result must be > 0, got {result}"


def test_to_usd_cop():
    """COP 2023: open.er-api.com spot rate — result > 0."""
    result = to_usd(1000.0, "COP", 2023)
    assert isinstance(result, float)
    assert result > 0.0, f"COP result must be > 0, got {result}"


def test_to_usd_pen():
    """PEN 2023: open.er-api.com spot rate — result > 0."""
    result = to_usd(1000.0, "PEN", 2023)
    assert isinstance(result, float)
    assert result > 0.0, f"PEN result must be > 0, got {result}"


# ---------------------------------------------------------------------------
# Low-confidence flag
# ---------------------------------------------------------------------------

def test_ars_low_confidence():
    """ARS is flagged as low confidence due to FX volatility."""
    assert is_low_confidence_currency("ARS") is True


def test_brl_not_low_confidence():
    """BRL uses Frankfurter true annual average — not low confidence."""
    assert is_low_confidence_currency("BRL") is False


# ---------------------------------------------------------------------------
# Disk cache persistence
# ---------------------------------------------------------------------------

def test_cache_populated(tmp_path, monkeypatch):
    """After to_usd("BRL", 2023), fx_rates.json exists and contains 'BRL_2023' key."""
    # Use a temp cache file so we don't pollute production cache
    tmp_cache = tmp_path / "fx_rates.json"
    monkeypatch.setattr(currency, "CACHE_FILE", tmp_cache)

    # Clear lru_cache so fresh HTTP request is triggered and cache written
    currency.get_annual_avg_rate.cache_clear()

    to_usd(1000.0, "BRL", 2023)

    assert tmp_cache.exists(), "fx_rates.json was not created"
    data = json.loads(tmp_cache.read_text())
    assert "BRL_2023" in data, f"BRL_2023 key missing from cache: {list(data.keys())}"
    assert isinstance(data["BRL_2023"], float)

    # Clean up lru_cache after test
    currency.get_annual_avg_rate.cache_clear()


# ---------------------------------------------------------------------------
# Fallback trigger — secondary API called when Frankfurter returns 4xx
# ---------------------------------------------------------------------------

def test_fallback_triggered(monkeypatch):
    """
    When requests.get returns 404 for Frankfurter (ARS-like scenario),
    the secondary API (open.er-api.com) must be called.
    Uses unittest.mock.patch to control HTTP responses.
    """
    # Clear lru_cache and disk cache for ARS_9999 to force fresh lookup
    currency.get_annual_avg_rate.cache_clear()

    frankfurter_response = MagicMock()
    frankfurter_response.status_code = 404
    frankfurter_response.raise_for_status.side_effect = Exception("404 Client Error")

    secondary_response = MagicMock()
    secondary_response.status_code = 200
    secondary_response.raise_for_status.return_value = None
    secondary_response.json.return_value = {
        "result": "success",
        "rates": {"USD": 0.001},
    }

    call_log = []

    def mock_get(url, **kwargs):
        call_log.append(url)
        if "frankfurter" in url:
            return frankfurter_response
        return secondary_response

    # Patch a CACHE_FILE path to temp to avoid disk side effects
    with patch("currency.requests.get", side_effect=mock_get):
        with patch.object(currency, "CACHE_FILE", Path("data/cache/fx_rates_test_fallback.json")):
            # Force a non-Frankfurter currency to test secondary API path directly
            rate = currency._secondary_api_rate("ARS")

    # Verify secondary API was called with correct URL
    assert any("open.er-api.com" in url for url in call_log), (
        f"open.er-api.com was not called. URLs called: {call_log}"
    )
    assert rate == 0.001
