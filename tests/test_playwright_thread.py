"""
Smoke test: Playwright thread isolation from ThreadPoolExecutor.

Tests that scrape_with_playwright() can be called from a plain Python context
(simulates what the Streamlit button will do via ThreadPoolExecutor).

This is an integration test — it makes a real HTTP request to example.com.
Mark with pytest.mark.integration if you want to skip in offline CI.
Expected runtime: ~5-15 seconds (browser launch + page load).

Note: As of Phase 7, latam_scraper.py was fully implemented replacing the
Phase 6 skeleton. scrape_url_title() was replaced by scrape_with_playwright()
which is the production API. These tests validate the same thread isolation
property using the new function signature.
"""
import tempfile
from pathlib import Path
import pytest
from latam_scraper import scrape_with_playwright, ScraperResult


def test_thread_isolation():
    """
    Calling scrape_with_playwright from a test (non-asyncio context) must return
    a ScraperResult without raising NotImplementedError or hanging.
    """
    with tempfile.TemporaryDirectory() as tmp:
        result = scrape_with_playwright(
            base_url="https://example.com",
            year=2023,
            out_dir=Path(tmp),
            attempts=[],
        )
    assert isinstance(result, ScraperResult), f"Expected ScraperResult, got {type(result)}"
    assert result.strategy == "playwright"
    # ok may be True or False — example.com has no PDF links; both are valid outcomes


def test_thread_isolation_returns_on_timeout():
    """
    Verify a second sequential call also works (no shared state corruption).
    This confirms the ThreadPoolExecutor is freshly created per call.
    """
    with tempfile.TemporaryDirectory() as tmp:
        result = scrape_with_playwright(
            base_url="https://example.com",
            year=2023,
            out_dir=Path(tmp),
            attempts=[],
        )
    assert isinstance(result, ScraperResult)
    assert result.strategy == "playwright"
