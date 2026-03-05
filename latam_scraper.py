"""
latam_scraper.py — LATAM PDF discovery and download (Phase 7+).
Phase 6: ThreadPoolExecutor smoke test pattern only.

CRITICAL: Never call sync_playwright() from the Streamlit main thread.
Streamlit runs an asyncio (Tornado) event loop; Windows SelectorEventLoop
cannot handle subprocess communication. Always use ThreadPoolExecutor.
Each worker thread MUST create its own sync_playwright() instance.
Source: playwright.dev/python/docs/library — "create a playwright instance per thread"
"""
import concurrent.futures
from loguru import logger


def _playwright_worker(url: str) -> str:
    """
    Runs in its own thread. Each thread creates its own playwright instance.
    Do NOT share playwright/browser instances across threads.
    """
    from playwright.sync_api import sync_playwright  # lazy import inside thread
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        title = page.title()
        browser.close()
    return title


def scrape_url_title(url: str) -> str:
    """
    Thread-safe Playwright call. Safe to call from Streamlit buttons.
    Returns the page title string or raises on timeout/error.
    """
    logger.info(f"Playwright: fetching title for {url}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_playwright_worker, url)
        return future.result(timeout=60)
