"""
latam_scraper.py — LATAM PDF discovery and download (Phase 7+).

Three-strategy PDF acquisition module:
  1. search()               — Primary: ddgs semantic search for direct PDF URL
  2. scrape_with_playwright() — Fallback: Playwright browser when no direct URL
  3. handle_upload()        — Manual: st.file_uploader drag-and-drop path

All three strategies converge on the same ScraperResult return type and write
downloaded PDFs to data/latam/{country}/{slug}/raw/{filename}.pdf.

CRITICAL: Playwright is always called via ThreadPoolExecutor — never from the
Streamlit main thread (asyncio/Tornado conflict on Windows 11). This module
uses sync_playwright inside the thread worker; the thread has its own fresh
sync context independent of any event loop on the calling thread.
"""
from __future__ import annotations
import concurrent.futures
import hashlib
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException
from loguru import logger
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright


# ---------------------------------------------------------------------------
# ScraperResult — structured return type for all acquisition strategies
# ---------------------------------------------------------------------------

@dataclass
class ScraperResult:
    ok: bool
    pdf_path: Optional[Path] = None
    strategy: str = ""          # "ddgs", "playwright", "portal", "upload"
    source_url: Optional[str] = None
    error: Optional[str] = None
    attempts: list[str] = field(default_factory=list)  # log of strategies tried

    @property
    def failed(self) -> bool:
        return not self.ok


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEARCH_KEYWORDS_ES = '"Estado de Situación Financiera"'
SEARCH_KEYWORDS_ALT = '"informe anual" "estados financieros"'

PDF_LINK_SELECTORS = [
    'a[href$=".pdf"]',
    'a[href*="informe"][href$=".pdf"]',
    'a[href*="reporte"][href$=".pdf"]',
    'a[href*="annual"][href$=".pdf"]',
    'a[href*="estados-financieros"]',
    'a[href*="memoria-anual"]',
]

IR_PAGE_FRAGMENTS = [
    "relaciones-con-inversionistas",
    "informes-anuales",
    "sala-de-inversionistas",
    "informacion-financiera",
    "inversionistas",
    "investor-relations",
    "annual-report",
]


# ---------------------------------------------------------------------------
# Strategy 1: DDGS semantic search — PRIMARY PATH
# ---------------------------------------------------------------------------

def search(domain: str, year: int, out_dir: Path) -> ScraperResult:
    """
    Primary strategy: semantic ddgs search for annual report PDF.

    Tries 3 query variants in order. Returns ScraperResult with ok=True and
    pdf_path set if PDF found and downloaded. Returns ok=False with error
    message if nothing found. Never raises.

    Args:
        domain:  Corporate website domain (e.g. "empresa.com")
        year:    Fiscal year (e.g. 2023)
        out_dir: Base output directory (PDF written to out_dir/raw/)
    """
    attempts: list[str] = []
    queries = [
        f'site:{domain} filetype:pdf {SEARCH_KEYWORDS_ES} {year}',
        f'site:{domain} filetype:pdf {SEARCH_KEYWORDS_ALT} {year}',
        f'site:{domain} filetype:pdf "informe anual" {year}',
    ]

    for i, query in enumerate(queries):
        attempts.append(f"ddgs:{query[:60]}")
        pdf_url = _ddgs_first_pdf_url(query)
        if pdf_url:
            logger.info(f"search: found PDF URL via ddgs on query {i+1}/{len(queries)}")
            return _download_pdf(pdf_url, out_dir=out_dir, strategy="ddgs", attempts=attempts)
        # Sleep between queries (not before first, not after last)
        if i < len(queries) - 1:
            time.sleep(random.uniform(2.0, 4.0))

    logger.warning(f"search: no PDF URL found for domain={domain} year={year}")
    return ScraperResult(
        ok=False,
        strategy="ddgs",
        error=f"No PDF URL found for domain={domain} year={year} after {len(queries)} queries",
        attempts=attempts,
    )


def _ddgs_first_pdf_url(query: str, max_results: int = 5) -> Optional[str]:
    """
    Return first href ending in .pdf from DDGS search, or None.

    Retries 3 times on RatelimitException with exponential backoff.
    Returns None immediately on TimeoutException or DDGSException.
    """
    for attempt in range(3):
        try:
            results = DDGS().text(query, max_results=max_results, backend="auto")
            for r in results:
                href = r.get("href", "")
                # Check both endswith .pdf and .pdf? (download scripts)
                if href.lower().endswith(".pdf") or ".pdf?" in href.lower():
                    return href
            return None  # Results found but none are direct PDF links
        except RatelimitException:
            wait = (2 ** attempt) * random.uniform(3.0, 6.0)
            logger.debug(f"_ddgs_first_pdf_url: rate limited, waiting {wait:.1f}s (attempt {attempt+1}/3)")
            time.sleep(wait)
        except (TimeoutException, DDGSException) as e:
            logger.debug(f"_ddgs_first_pdf_url: ddgs exception: {e}")
            return None
    return None


# ---------------------------------------------------------------------------
# Strategy 2: Playwright browser — FALLBACK PATH
# ---------------------------------------------------------------------------

def scrape_with_playwright(
    base_url: str,
    year: int,
    out_dir: Path,
    attempts: list,
) -> ScraperResult:
    """
    Fallback strategy: launch browser, find PDF link via heuristics, download.

    CRITICAL: Always uses ThreadPoolExecutor — never calls _playwright_find_pdf
    directly. This prevents asyncio/Tornado conflicts on Windows 11 when called
    from Streamlit buttons.

    Args:
        base_url: Corporate website base URL (e.g. "https://empresa.com")
        year:     Fiscal year (e.g. 2023)
        out_dir:  Base output directory (PDF written to out_dir/raw/)
        attempts: Accumulated attempts list from prior strategies
    """
    attempts = list(attempts)  # Don't mutate caller's list
    attempts.append(f"playwright:{base_url[:60]}")
    logger.info(f"scrape_with_playwright: trying {base_url} for year {year}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_playwright_find_pdf, base_url, year)
        try:
            pdf_url = future.result(timeout=120)
        except concurrent.futures.TimeoutError:
            return ScraperResult(
                ok=False,
                strategy="playwright",
                error="Browser timeout after 120s",
                attempts=attempts,
            )

    if pdf_url:
        logger.info(f"scrape_with_playwright: found PDF URL {pdf_url[:80]}")
        return _download_pdf(pdf_url, out_dir=out_dir, strategy="playwright", attempts=attempts)

    return ScraperResult(
        ok=False,
        strategy="playwright",
        error=f"No PDF link found on {base_url}",
        attempts=attempts,
    )


def _playwright_find_pdf(base_url: str, year: int) -> Optional[str]:
    """
    Thread worker: runs in its own ThreadPoolExecutor thread.

    Creates its own sync_playwright() instance — not shared. Navigates to
    base_url, tries to find a PDF link for the given year using heuristics.
    Returns PDF URL (absolute) or None.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(base_url, timeout=30_000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeout:
                pass  # Continue even if networkidle times out

            # Parse base URL for relative href resolution
            parsed = urlparse(base_url)
            base_origin = f"{parsed.scheme}://{parsed.netloc}"

            # Try direct PDF links on current page
            pdf_url = _find_pdf_link_on_page(page, year)
            if pdf_url:
                if pdf_url.startswith("/"):
                    pdf_url = base_origin + pdf_url
                return pdf_url

            # Try navigating to IR sub-pages via fragment links
            for fragment in IR_PAGE_FRAGMENTS:
                try:
                    ir_locator = page.locator(f'a[href*="{fragment}"]')
                    if ir_locator.count() > 0:
                        ir_locator.first.click(timeout=5_000)
                        try:
                            page.wait_for_load_state("networkidle", timeout=10_000)
                        except PlaywrightTimeout:
                            pass
                        pdf_url = _find_pdf_link_on_page(page, year)
                        if pdf_url:
                            if pdf_url.startswith("/"):
                                pdf_url = base_origin + pdf_url
                            return pdf_url
                except PlaywrightTimeout:
                    continue
                except Exception:
                    continue
        finally:
            browser.close()
    return None


def _find_pdf_link_on_page(page, year: int) -> Optional[str]:
    """
    Scan current page for PDF anchors. Prefer links containing the year.

    Returns href string or None.
    """
    for selector in PDF_LINK_SELECTORS:
        try:
            links = page.locator(selector).all()
        except Exception:
            continue

        # First pass: prefer year-matched links
        for link in links:
            try:
                href = link.get_attribute("href") or ""
                text = ""
                try:
                    text = link.inner_text() or ""
                except Exception:
                    pass
                if str(year) in href or str(year) in text:
                    return href
            except Exception:
                continue

        # Second pass: fallback to first link in selector
        if links:
            try:
                href = links[0].get_attribute("href") or ""
                if href:
                    return href
            except Exception:
                continue

    return None


# ---------------------------------------------------------------------------
# Shared: PDF download helper — used by all strategies
# ---------------------------------------------------------------------------

def _download_pdf(
    url: str,
    out_dir: Path,
    strategy: str,
    attempts: list,
    timeout: int = 30,
) -> ScraperResult:
    """
    Download PDF from URL to out_dir/raw/{filename}.pdf with streaming.

    Validates Content-Type header, streams download to avoid memory exhaustion,
    validates %PDF magic bytes after download. Returns ScraperResult.

    Note: Some LATAM servers return application/octet-stream for PDFs. Falls
    back to URL extension check when Content-Type is ambiguous.
    """
    try:
        head = requests.head(url, timeout=timeout, allow_redirects=True)
        content_type = head.headers.get("Content-Type", "")

        # Accept PDF content-type OR any octet-stream (LATAM servers) OR PDF URL
        url_looks_like_pdf = url.lower().endswith(".pdf") or ".pdf?" in url.lower()
        ct_lower = content_type.lower()
        ct_clearly_not_pdf = "text/html" in ct_lower and not url_looks_like_pdf

        if ct_clearly_not_pdf:
            return ScraperResult(
                ok=False,
                strategy=strategy,
                error=f"URL does not appear to be a PDF (Content-Type: {content_type})",
                attempts=attempts,
            )

        filename = _normalize_filename(url)
        raw_dir = out_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = raw_dir / filename

        # Deduplication: skip download if file already exists
        if pdf_path.exists():
            logger.info(f"_download_pdf: already exists, skipping download: {pdf_path}")
            return ScraperResult(
                ok=True,
                pdf_path=pdf_path,
                strategy=strategy,
                source_url=url,
                attempts=attempts,
            )

        resp = requests.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()

        with pdf_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # Validate magic bytes — reject HTML interstitials (CAPTCHAs, login pages)
        if not _validate_pdf_magic(pdf_path):
            pdf_path.unlink()
            return ScraperResult(
                ok=False,
                strategy=strategy,
                error="Downloaded file is not a valid PDF (HTML interstitial suspected)",
                attempts=attempts,
            )

        logger.info(f"_download_pdf: downloaded {pdf_path.name} ({pdf_path.stat().st_size} bytes)")
        return ScraperResult(
            ok=True,
            pdf_path=pdf_path,
            strategy=strategy,
            source_url=url,
            attempts=attempts,
        )

    except requests.RequestException as e:
        return ScraperResult(
            ok=False,
            strategy=strategy,
            error=f"Download failed: {e}",
            attempts=attempts,
        )


def _validate_pdf_magic(path: Path) -> bool:
    """Return True if file begins with PDF magic bytes (%PDF)."""
    with path.open("rb") as f:
        return f.read(4) == b"%PDF"


def _normalize_filename(url: str) -> str:
    """
    Extract filename from URL; fall back to SHA-256 prefix if not deterministic.

    Rules:
    - Sanitize to Windows-safe characters only
    - Ensure .pdf extension
    - Prefix with 8-char URL hash if name is too short or starts with 'download'
    """
    name = url.rstrip("/").split("/")[-1]
    # Strip query string component if present
    name = name.split("?")[0]
    name = re.sub(r"[^\w.\-]", "_", name)  # Windows-safe chars only
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    # If name is generic (e.g., "download.php.pdf"), prefix with URL hash
    if len(name) < 8 or name.lower().startswith("download"):
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
        name = f"{url_hash}_{name}"
    return name


# ---------------------------------------------------------------------------
# Strategy 3: Manual upload — st.file_uploader drag-and-drop path
# ---------------------------------------------------------------------------

def handle_upload(uploaded_file, out_dir: Path) -> ScraperResult:
    """
    Save an UploadedFile from st.file_uploader to out_dir/raw/.

    Returns ScraperResult for downstream pipeline compatibility.
    SCRAP-04: extraction pipeline is identical regardless of PDF origin.

    Args:
        uploaded_file: Streamlit UploadedFile (has .getvalue() and .name)
        out_dir:       Base output directory (PDF written to out_dir/raw/)
    """
    try:
        raw_dir = out_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = raw_dir / _normalize_filename_from_upload(uploaded_file.name)
        pdf_path.write_bytes(uploaded_file.getvalue())
        logger.info(f"handle_upload: saved {pdf_path.name} ({pdf_path.stat().st_size} bytes)")
        return ScraperResult(
            ok=True,
            pdf_path=pdf_path,
            strategy="upload",
            source_url=None,
            attempts=["upload:drag-and-drop"],
        )
    except Exception as e:
        return ScraperResult(
            ok=False,
            strategy="upload",
            error=f"Upload save failed: {e}",
            attempts=["upload:drag-and-drop"],
        )


def _normalize_filename_from_upload(name: str) -> str:
    """Sanitize upload filename to Windows-safe characters. Ensures .pdf extension."""
    name = re.sub(r"[^\w.\-]", "_", name)  # Windows-safe
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name
