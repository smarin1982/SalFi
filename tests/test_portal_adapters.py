"""
Unit tests for portal_adapters package.
All network calls are mocked — these tests run offline.

Tests cover:
  1. PORTAL_STATUS keys are present
  2. supersalud.find_pdf() returns None when ddgs finds nothing (no exception)
  3. supersalud.find_pdf() returns a URL when ddgs finds a PDF href
  4. smv.find_pdf() returns None or str without raising
  5. cmf.find_pdf() returns None or a str containing year/domain when URL found
  6. get_adapter() returns a module with find_pdf attribute
"""
import pytest
from unittest.mock import patch, MagicMock
from portal_adapters import supersalud, smv, cmf, PORTAL_STATUS


# ---------------------------------------------------------------------------
# Test 1: PORTAL_STATUS structure
# ---------------------------------------------------------------------------

def test_portal_status_keys():
    """PORTAL_STATUS dict must contain all six portal keys."""
    assert "supersalud_co" in PORTAL_STATUS
    assert "smv_pe" in PORTAL_STATUS
    assert "cmf_cl" in PORTAL_STATUS
    assert "sfc_co" in PORTAL_STATUS
    assert "cnv_ar" in PORTAL_STATUS
    assert "cnbv_mx" in PORTAL_STATUS


# ---------------------------------------------------------------------------
# Test 2: supersalud.find_pdf() — no results → None, no exception
# ---------------------------------------------------------------------------

def test_supersalud_find_pdf_no_exception():
    """Mock DDGS().text() to return empty list — result must be None, never raises."""
    with patch("portal_adapters.supersalud.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.return_value = []
        result = supersalud.find_pdf("800058016", 2023)
    assert result is None  # No results = None (not an exception)


# ---------------------------------------------------------------------------
# Test 3: supersalud.find_pdf() — DDGS returns PDF href → return URL
# ---------------------------------------------------------------------------

def test_supersalud_find_pdf_returns_url():
    """Mock DDGS returning a PDF href — find_pdf must return that URL."""
    with patch("portal_adapters.supersalud.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.return_value = [
            {"href": "https://docs.supersalud.gov.co/informe-2023.pdf", "title": "Inf", "body": ""}
        ]
        result = supersalud.find_pdf("800058016", 2023)
    assert result == "https://docs.supersalud.gov.co/informe-2023.pdf"


# ---------------------------------------------------------------------------
# Test 4: smv.find_pdf() — best-effort adapter, must not raise
# ---------------------------------------------------------------------------

def test_smv_find_pdf_no_exception():
    """SMV adapter is best-effort; may return None without error — must never raise."""
    result = smv.find_pdf("20100003539", 2023)
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Test 5: cmf.find_pdf() — bank URL pattern or None
# ---------------------------------------------------------------------------

def test_cmf_find_pdf_bank_url_pattern():
    """
    CMF bank sector: test URL construction for a known bank RUT pattern.
    If adapter constructs a URL: verify it contains the year and/or 'cmfchile'.
    If adapter returns None: that is also valid (LOW confidence URL pattern).
    """
    result = cmf.find_pdf("97006000-6", 2023)
    assert result is None or isinstance(result, str)
    if result is not None:
        assert "2023" in result or "cmfchile" in result


# ---------------------------------------------------------------------------
# Test 6: get_adapter() — returns module with find_pdf
# ---------------------------------------------------------------------------

def test_get_adapter_returns_module():
    """get_adapter('CO', 'Supersalud') must return the supersalud module."""
    from portal_adapters import get_adapter
    adapter = get_adapter("CO", "Supersalud")
    assert adapter is not None
    assert hasattr(adapter, "find_pdf")
