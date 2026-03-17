"""
latam_backfiller.py — Multi-year historical PDF ingestion orchestrator (Phase 13).

Three components:
  1. collect_listing_pdfs()      — Playwright listing-page crawler that discovers all
                                   annual PDFs for a company in one crawl session.
  2. _years_already_in_parquet() — Skip-year guard; reads financials.parquet to avoid
                                   re-downloading and re-extracting years already stored.
  3. LatamBackfiller             — Per-year coordinator: download → extract → return.
                                   Does NOT write to parquet itself; caller decides.

Design constraint: This module is a pure coordinator. It does NOT modify any existing
module (latam_scraper, latam_extractor, latam_processor).

CRITICAL: All Playwright calls go through ThreadPoolExecutor + asyncio.ProactorEventLoop
on Windows. sync_playwright raises NotImplementedError from ThreadPoolExecutor on Windows.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urljoin

import pandas as pd
from loguru import logger
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from latam_scraper import (
    _is_partial_year_url,
    _score_pdf_link,
    _detect_doc_tier,
    _download_pdf,
    _make_absolute,
    _is_on_domain,
    NAV_FINANCIAL_KEYWORDS,
    NAV_T1_KEYWORDS,
)
from latam_extractor import extract as _extract
from latam_processor import process as _process

# How many completed fiscal years to look back from current year
BACKFILL_YEARS = 6


# ---------------------------------------------------------------------------
# Year extraction helper
# ---------------------------------------------------------------------------

def _extract_year_from_text(text: str) -> Optional[int]:
    """Extract fiscal year (2015–current) from a URL or link text string.

    Returns the first year found in the range [2015, current_year].
    Returns None when no valid year is found.
    """
    current = datetime.now().year
    for m in re.findall(r'\b(20[12]\d)\b', text):
        y = int(m)
        if 2015 <= y <= current:
            return y
    return None


# ---------------------------------------------------------------------------
# Skip-year guard
# ---------------------------------------------------------------------------

def _years_already_in_parquet(parquet_path: Path) -> set[int]:
    """Return the set of fiscal years already stored in financials.parquet.

    Returns an empty set when the file does not exist or cannot be read.
    Reads only the fiscal_year column for efficiency.
    """
    if not parquet_path.exists():
        return set()
    try:
        df = pd.read_parquet(parquet_path, columns=["fiscal_year"])
        return set(df["fiscal_year"].dropna().astype(int).tolist())
    except Exception as exc:
        logger.warning(f"_years_already_in_parquet could not read {parquet_path}: {exc}")
        return set()


# ---------------------------------------------------------------------------
# Listing-page crawler — async internals
# ---------------------------------------------------------------------------

async def _async_collect_listing_pdfs(
    listing_url: str,
    domain: str,
) -> dict[int, str]:
    """Async: crawl a portal listing page and collect year → PDF URL mappings.

    Follows up to 3 pagination pages when fewer than 3 PDF candidates are found
    on the initial listing page.
    """
    parsed = urlparse(listing_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    target_domain_str = parsed.netloc.lower().lstrip("www.")

    # year → list of (score, url) tuples
    candidates: dict[int, list[tuple[int, str]]] = {}

    async def _harvest_page(url: str) -> None:
        """Visit one page and collect scored PDF link candidates."""
        try:
            await page.goto(url, timeout=25_000, wait_until="domcontentloaded")
        except Exception as nav_exc:
            logger.debug(f"_harvest_page nav failed {url}: {nav_exc}")
            return
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except PlaywrightTimeout:
            pass  # proceed with whatever loaded

        anchors = await page.query_selector_all("a[href]")
        for anchor in anchors:
            try:
                href = await anchor.get_attribute("href") or ""
                text = (await anchor.inner_text() or "").strip()
            except Exception:
                continue

            # Only consider PDF links
            href_lower = href.lower()
            if not (href_lower.endswith(".pdf") or ".pdf?" in href_lower or ".pdf#" in href_lower):
                continue

            # Skip partial-year (semester/quarterly) reports
            if _is_partial_year_url(href):
                continue

            # Build absolute URL
            abs_url = _make_absolute(href, base_origin)

            # Extract year — prefer filename (last path segment) over directory path,
            # since upload directories like /2025/03/...2024.pdf would otherwise
            # return 2025 (upload year) instead of 2024 (fiscal year in filename).
            _fname = href.rsplit("/", 1)[-1]
            year = _extract_year_from_text(_fname) or _extract_year_from_text(text) or _extract_year_from_text(href)
            if year is None:
                continue

            score = _score_pdf_link(href, text, year)
            candidates.setdefault(year, []).append((score, abs_url))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # Initial harvest
            await _harvest_page(listing_url)

            # Follow financial nav links when the starting page is a homepage
            # (few or no PDFs directly on root). T1 nav links (estados financieros,
            # balance general) are followed before generic financial links so the
            # backfiller mirrors the same priority as the scraper's corporate crawl.
            if len(candidates) < 3:
                try:
                    nav_anchors = await page.query_selector_all("a[href]")
                    t1_nav: list[str] = []
                    other_nav: list[str] = []
                    seen_nav: set[str] = set()
                    for anchor in nav_anchors:
                        try:
                            href = (await anchor.get_attribute("href") or "").strip()
                            text = (await anchor.inner_text() or "").strip().lower()
                        except Exception:
                            continue
                        if not href:
                            continue
                        href_lower = href.lower()
                        # Skip PDF links — we want navigation pages, not direct PDFs
                        if href_lower.endswith(".pdf") or ".pdf?" in href_lower:
                            continue
                        abs_url = _make_absolute(href, base_origin)
                        if not abs_url or abs_url in seen_nav:
                            continue
                        if not _is_on_domain(abs_url, target_domain_str):
                            continue
                        if abs_url == listing_url:
                            continue
                        seen_nav.add(abs_url)
                        is_t1 = any(
                            kw in text or kw.replace(" ", "-") in href_lower
                            for kw in NAV_T1_KEYWORDS
                        )
                        is_financial = any(
                            kw in text or kw.replace(" ", "-") in href_lower
                            for kw in NAV_FINANCIAL_KEYWORDS
                        )
                        if is_t1:
                            t1_nav.append(abs_url)
                        elif is_financial:
                            other_nav.append(abs_url)
                    # Visit T1 nav links first (up to 3 total nav pages)
                    nav_followed = 0
                    for nav_url in (t1_nav[:3] + other_nav[:2]):
                        if nav_followed >= 3:
                            break
                        if len(candidates) >= 5:
                            break
                        await _harvest_page(nav_url)
                        nav_followed += 1
                except Exception as nav_exc:
                    logger.debug(f"_async_collect_listing_pdfs nav-following failed: {nav_exc}")

            # Follow pagination if still too few results found
            if len(candidates) < 3:
                PAGINATION_PATTERNS = ["page=", "pagina=", "p=", "/page/", "/pagina/"]
                PAGINATION_TEXT = ["anterior", "siguiente", "older", "newer"]
                pages_followed = 0

                anchors = await page.query_selector_all("a[href]")
                for anchor in anchors:
                    if pages_followed >= 3:
                        break
                    try:
                        href = await anchor.get_attribute("href") or ""
                        text = (await anchor.inner_text() or "").strip().lower()
                    except Exception:
                        continue

                    is_pagination = (
                        any(pat in href for pat in PAGINATION_PATTERNS)
                        or any(t in text for t in PAGINATION_TEXT)
                    )
                    if not is_pagination:
                        continue

                    abs_href = _make_absolute(href, base_origin)
                    if abs_href == listing_url:
                        continue

                    await _harvest_page(abs_href)
                    pages_followed += 1
        finally:
            await browser.close()

    # Best-scoring URL per year
    return {
        year: max(urls, key=lambda x: x[0])[1]
        for year, urls in candidates.items()
        if urls
    }


def _thread_collect_listing_pdfs(listing_url: str, domain: str) -> dict[int, str]:
    """Thread worker: set up ProactorEventLoop on Windows and run the async crawler."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_async_collect_listing_pdfs(listing_url, domain))
    finally:
        loop.close()


def collect_listing_pdfs(listing_url: str, domain: str) -> dict[int, str]:
    """Crawl a portal listing page to discover annual PDFs.

    Returns a dict mapping fiscal year (int) to PDF URL (str).
    Wraps Playwright in ThreadPoolExecutor to avoid asyncio conflicts on Windows.
    Timeout: 180 seconds.

    Example:
        pdfs = collect_listing_pdfs(
            "https://example.gov.co/empresa/estados-financieros",
            "example.gov.co",
        )
        # {2022: "https://...", 2021: "https://...", 2020: "https://..."}
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_thread_collect_listing_pdfs, listing_url, domain)
        try:
            return future.result(timeout=180)
        except Exception as exc:
            logger.warning(f"collect_listing_pdfs failed for {listing_url}: {exc}")
            return {}


# ---------------------------------------------------------------------------
# BackfillResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class BackfillResult:
    """Result of a single-year backfill attempt."""

    year: int
    status: str  # "ok" | "low_conf" | "not_found" | "skipped" | "error"
    pdf_path: Optional[Path] = None
    extraction_result: Optional[object] = None  # ExtractionResult from latam_extractor
    confidence: Optional[str] = None            # "Alta" | "Media" | "Baja"
    error_msg: Optional[str] = None


# ---------------------------------------------------------------------------
# LatamBackfiller — multi-year coordination class
# ---------------------------------------------------------------------------

class LatamBackfiller:
    """Coordinates multi-year PDF backfill for a single LATAM company.

    Responsibilities:
    - Determine which fiscal years are missing from financials.parquet
    - Download + extract one year at a time via run_year()
    - Delegate parquet writes to write_year() (caller controls when to persist)

    Args:
        slug:         Company slug (matches storage directory and parquet ticker column).
        country:      Two-letter ISO country code ("CO", "BR", "MX", …).
        storage_path: Path to data/latam/{country}/{slug}/ directory.
        domain:       Company or portal domain for relevance scoring.
    """

    def __init__(
        self,
        slug: str,
        country: str,
        storage_path: Path,
        domain: str,
    ) -> None:
        self.slug = slug
        self.country = country
        self.storage_path = storage_path
        self.domain = domain
        self.parquet_path = storage_path / "financials.parquet"
        self.raw_dir = storage_path / "raw"

    def get_target_years(self) -> list[int]:
        """Return the last BACKFILL_YEARS completed fiscal years, most recent first.

        Example (2026): [2025, 2024, 2023, 2022, 2021]
        """
        current = datetime.now().year
        return [current - i for i in range(1, BACKFILL_YEARS + 1)]

    def get_missing_years(self) -> list[int]:
        """Return target years not yet present in financials.parquet."""
        existing = _years_already_in_parquet(self.parquet_path)
        return [y for y in self.get_target_years() if y not in existing]

    def run_year(
        self,
        year: int,
        pdf_url: str,
        currency_code: str,
        force_reextract: bool = False,
    ) -> BackfillResult:
        """Download and extract one fiscal year. Does NOT write to parquet.

        Returns a BackfillResult with extraction_result populated on success.
        The caller (app.py) decides whether to persist the data:
        - status="ok"       → auto-write (Alta/Media confidence)
        - status="low_conf" → prompt analyst before writing (Baja confidence)
        - status="skipped"  → year already in parquet; nothing to do
        - status="not_found"→ PDF download failed
        - status="error"    → unexpected exception

        Args:
            year:            Target fiscal year (e.g. 2023).
            pdf_url:         Direct URL to the annual report PDF.
            currency_code:   ISO currency code for the country ("COP", "BRL", …).
            force_reextract: When True, skip the already-in-parquet guard.
        """
        # Skip guard — avoid redundant work
        if not force_reextract:
            existing = _years_already_in_parquet(self.parquet_path)
            if year in existing:
                logger.info(f"LatamBackfiller.run_year: year={year} already in parquet — skipping")
                return BackfillResult(year=year, status="skipped")

        # Download the PDF
        try:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            scrape_result = _download_pdf(
                url=pdf_url,
                out_dir=self.raw_dir,
                strategy="backfill",
                attempts=[],
            )
            if not scrape_result.ok or not scrape_result.pdf_path:
                return BackfillResult(
                    year=year,
                    status="not_found",
                    error_msg=scrape_result.error,
                )
            pdf_path = scrape_result.pdf_path
        except Exception as exc:
            logger.error(f"LatamBackfiller.run_year download failed year={year}: {exc}")
            return BackfillResult(year=year, status="error", error_msg=str(exc))

        # Extract financial data from the PDF
        try:
            results = _extract(
                str(pdf_path),
                currency_code=currency_code,
                fiscal_year=year,
                country=self.country,
            )
            if not results:
                return BackfillResult(
                    year=year,
                    status="error",
                    pdf_path=pdf_path,
                    error_msg="extract() returned empty list",
                )
            # extract() returns list[ExtractionResult]; prefer the one matching year
            target = next(
                (r for r in results if r.fiscal_year == year),
                results[0],
            )
            status = "low_conf" if target.confidence == "Baja" else "ok"
            return BackfillResult(
                year=year,
                status=status,
                pdf_path=pdf_path,
                extraction_result=target,
                confidence=target.confidence,
            )
        except Exception as exc:
            logger.error(f"LatamBackfiller.run_year extract failed year={year}: {exc}")
            return BackfillResult(
                year=year,
                status="error",
                pdf_path=pdf_path,
                error_msg=str(exc),
            )

    def write_year(self, result: BackfillResult) -> bool:
        """Write a BackfillResult to parquet via latam_processor.process().

        Returns True on success. Should only be called after the analyst has
        confirmed low-confidence results (status="low_conf").

        Note: data_dir is derived as storage_path.parent.parent.parent because
        storage_path is data/latam/{country}/{slug}/ and latam_processor
        expects DATA_DIR = data/ (it appends "latam/{country}/{slug}" itself).
        """
        if not result.extraction_result:
            logger.warning(f"LatamBackfiller.write_year: no extraction_result for year={result.year}")
            return False
        try:
            _process(
                company_slug=self.slug,
                extraction_result=result.extraction_result,
                country=self.country,
                data_dir=str(self.storage_path.parent.parent.parent),
            )
            logger.info(f"LatamBackfiller.write_year: wrote year={result.year} to parquet")
            return True
        except Exception as exc:
            logger.error(f"LatamBackfiller.write_year failed year={result.year}: {exc}")
            return False
