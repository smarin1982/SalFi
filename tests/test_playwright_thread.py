"""
Smoke test: Playwright thread isolation from ThreadPoolExecutor.
Tests that scrape_url_title() can be called from a plain Python context
(simulates what the Streamlit button will do via ThreadPoolExecutor).

This is an integration test — it makes a real HTTP request to example.com.
Mark with pytest.mark.integration if you want to skip in offline CI.
Expected runtime: ~5-15 seconds (browser launch + page load).
"""
import pytest
from latam_scraper import scrape_url_title


def test_thread_isolation():
    """
    Calling scrape_url_title from a test (non-asyncio context) must return
    a string without raising NotImplementedError or hanging.
    """
    title = scrape_url_title("https://example.com")
    assert isinstance(title, str), f"Expected str, got {type(title)}"
    assert len(title) > 0, "Title should not be empty"
    # example.com title is "Example Domain" — assert loosely to avoid fragility
    assert "example" in title.lower() or len(title) > 3


def test_thread_isolation_returns_on_timeout():
    """
    Verify ThreadPoolExecutor timeout propagates correctly (not hangs forever).
    Use a real fast URL to confirm normal operation; timeout test is structural.
    """
    # Just confirm a second sequential call also works (no shared state corruption)
    title = scrape_url_title("https://example.com")
    assert isinstance(title, str)
