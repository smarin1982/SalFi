"""
latam_scraper.py — LATAM PDF discovery and download (Phase 7+).
Phase 6: ThreadPoolExecutor smoke test pattern only.

CRITICAL: Never call async_playwright() from the Streamlit main thread.
Streamlit runs a Tornado event loop; on Windows, Tornado may override the
asyncio policy to SelectorEventLoop, which cannot launch subprocesses.

Fix: Use async_playwright (not sync_playwright) inside a ThreadPoolExecutor
worker that creates its own ProactorEventLoop via loop.run_until_complete().
This bypasses any process-level policy overrides entirely.
"""
import asyncio
import concurrent.futures
import sys
from loguru import logger


async def _async_playwright_worker(url: str) -> str:
    """Async implementation — runs inside an explicitly created ProactorEventLoop."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        title = await page.title()
        await browser.close()
    return title


def _thread_worker(url: str) -> str:
    """
    Runs in its own ThreadPoolExecutor thread.
    Creates a fresh ProactorEventLoop explicitly — bypasses any policy set
    by Streamlit/Tornado on the main thread.
    """
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_async_playwright_worker(url))
    finally:
        loop.close()


def scrape_url_title(url: str) -> str:
    """
    Thread-safe Playwright call. Safe to call from Streamlit buttons.
    Returns the page title string or raises on timeout/error.
    """
    logger.info(f"Playwright: fetching title for {url}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_thread_worker, url)
        return future.result(timeout=60)
