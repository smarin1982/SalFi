"""
latam_scraper.py — LATAM PDF discovery and download (Phase 7+).

Four-strategy PDF acquisition module (Phase 12-06 smart scraper additions):
  0. _crawl_corporate_site()   — Highest trust: crawl actual corporate website
  1. search()                  — Primary: ddgs semantic search for direct PDF URL
  2. scrape_with_playwright()  — Fallback: Playwright browser when no direct URL
  3. handle_upload()           — Manual: st.file_uploader drag-and-drop path

Phase 12-06 additions:
- _validate_pdf_relevance()   — Score PDF URL relevance before downloading
- _crawl_corporate_site()     — Playwright crawl of corporate site (highest trust)
- _load_scraper_profile()     — Load per-provider learned profile from JSON
- _save_scraper_profile()     — Persist learned patterns for reuse (append-only)
- search_and_download() now: try profile pattern → crawl corporate site → ddgs → playwright

All strategies converge on the same ScraperResult return type and write
downloaded PDFs to data/latam/{country}/{slug}/raw/{filename}.pdf.

CRITICAL: Playwright is always called via ThreadPoolExecutor — never from the
Streamlit main thread (asyncio/Tornado conflict on Windows 11). Thread workers
use async_playwright + asyncio.ProactorEventLoop (sync_playwright raises
NotImplementedError when called from a ThreadPoolExecutor on Windows).
"""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException
from loguru import logger
import asyncio
from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright


# ---------------------------------------------------------------------------
# ScraperResult — structured return type for all acquisition strategies
# ---------------------------------------------------------------------------

@dataclass
class ScraperResult:
    ok: bool
    pdf_path: Optional[Path] = None
    strategy: str = ""          # "ddgs", "playwright", "portal", "upload", "profile", "corporate_crawl"
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

# Common corporate document section paths to try during crawl
COMMON_DOC_PATHS = [
    "/informes/",
    "/transparencia/",
    "/documentos/",
    "/reportes/",
    "/estados-financieros/",
    "/sala-de-prensa/",
    "/publicaciones/",
    "/rendicion-de-cuentas/",
    "/informacion-financiera/",
    "/relaciones-con-inversionistas/",
]

# Nav link text fragments indicating financial document sections
NAV_FINANCIAL_KEYWORDS = [
    "financiero",
    "informe",
    "estados",
    "reporte anual",
    "transparencia",
    "rendicion de cuentas",
    "rendición de cuentas",
    "documentos",
    "publicaciones",
    "sala de prensa",
    "memoria",
]

# Relevance keywords found in PDF URL path
PDF_PATH_RELEVANCE_KEYWORDS = [
    "estados-financieros",
    "estados_financieros",
    "informe",
    "reporte",
    "financiero",
    "memoria",
    "annual",
    "report",
    "transparencia",
    "rendicion",
]

# Default location for scraper profiles
_PROFILES_PATH = Path("data/latam/scraper_profiles.json")


# ---------------------------------------------------------------------------
# SCRAPE-01: PDF Relevance Scoring
# ---------------------------------------------------------------------------

def _validate_pdf_relevance(
    pdf_url: str,
    company_domain: str,
    company_name: str,
    year: Optional[int] = None,
) -> float:
    """
    Score a PDF URL for relevance to a company's annual financial report.

    Returns a score from 0.0 to 1.0:
      +0.5  domain match (pdf_url domain == company_domain)
      +0.2  financial keywords in URL path
      +0.1  current or prior year in URL
      +0.1  PDF file size > 100KB (scanned financials are large) — checked via HEAD
      +0.1  filetype is PDF (URL ends in .pdf or has .pdf?)

    Only download if score >= 0.5. Below that threshold the PDF is likely
    from the wrong source (e.g. a government report from an external site).
    """
    if not pdf_url:
        return 0.0

    score = 0.0
    url_lower = pdf_url.lower()

    # +0.1 — filetype check
    if url_lower.endswith(".pdf") or ".pdf?" in url_lower:
        score += 0.1

    # +0.2 — financial keywords in URL path
    url_path = urlparse(pdf_url).path.lower()
    has_financial_kw = any(kw in url_path for kw in PDF_PATH_RELEVANCE_KEYWORDS)
    if has_financial_kw:
        score += 0.2

    # +0.1 — year in URL
    has_year = bool(year and (str(year) in pdf_url or str(year - 1) in pdf_url))
    if has_year:
        score += 0.1

    # +0.5 / +0.2 — domain match
    #   Full +0.5 only when corroborated by financial keyword or year in URL.
    #   +0.2 for domain-only match (prevents generic same-domain PDFs like lab
    #   instruction manuals from clearing the 0.5 download threshold alone).
    try:
        pdf_host = urlparse(pdf_url).netloc.lower().lstrip("www.")
        target_domain = company_domain.lower().lstrip("www.")
        # Strip scheme if caller passed full URL as domain
        if "://" in target_domain:
            target_domain = urlparse(target_domain).netloc.lower().lstrip("www.")
        if pdf_host and target_domain and (
            pdf_host == target_domain
            or pdf_host.endswith("." + target_domain)
            or target_domain.endswith("." + pdf_host)
        ):
            score += 0.5 if (has_financial_kw or has_year) else 0.2
    except Exception:
        pass

    # +0.1 — PDF file size > 100KB (HEAD request, best-effort)
    try:
        head = requests.head(pdf_url, timeout=10, allow_redirects=True)
        content_length = int(head.headers.get("Content-Length", 0))
        if content_length > 100_000:
            score += 0.1
    except Exception:
        pass  # Can't check size — don't penalise

    logger.debug(
        f"_validate_pdf_relevance: {pdf_url[:80]} → score={score:.2f} "
        f"(domain={company_domain})"
    )
    return min(score, 1.0)


# ---------------------------------------------------------------------------
# SCRAPE-02: Corporate Site Crawl (highest trust strategy)
# ---------------------------------------------------------------------------

def _crawl_corporate_site(domain: str, slug: str, year: int) -> Optional[str]:
    """
    Crawl the company's own website to find the financial report PDF.

    Strategy order:
    1. Visit domain root → look for nav links to financial/document sections
    2. Follow those links → look for direct PDF links or embedded PDF viewers
    3. Try common paths (/informes/, /transparencia/, etc.)
    4. Return first PDF URL found on the corporate domain (highest trust)

    Always executed via ThreadPoolExecutor to avoid asyncio/Tornado conflicts.
    Returns absolute PDF URL or None.
    """
    logger.info(f"_crawl_corporate_site: crawling {domain} for {slug} year={year}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_playwright_crawl_corporate, domain, year)
        try:
            return future.result(timeout=120)
        except concurrent.futures.TimeoutError:
            logger.warning(f"_crawl_corporate_site: timeout after 120s for {domain}")
            return None
        except Exception as e:
            logger.warning(f"_crawl_corporate_site: unexpected error for {domain}: {e}")
            return None


def _playwright_crawl_corporate(domain: str, year: int) -> Optional[str]:
    """
    Thread worker: crawl corporate website for financial PDF.

    Uses async_playwright + ProactorEventLoop — required on Windows when called
    from a ThreadPoolExecutor (sync_playwright raises NotImplementedError there).
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_async_crawl_corporate(domain, year))
    finally:
        loop.close()


async def _async_crawl_corporate(domain: str, year: int) -> Optional[str]:
    """Async implementation of corporate website crawl for financial PDF."""
    # Normalise domain to a full URL
    base_url = domain if domain.startswith("http") else f"https://{domain}"
    parsed = urlparse(base_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    target_domain = parsed.netloc.lower().lstrip("www.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            # --- Step 1: Visit root and look for financial nav links ---
            try:
                await page.goto(base_url, timeout=30_000, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except PlaywrightTimeout:
                    pass
            except Exception as e:
                logger.debug(f"_async_crawl_corporate: goto {base_url} failed: {e}")
                return None

            # Check for PDFs directly on root page
            pdf_url = await _async_find_pdf_link_on_page(page, year)
            if pdf_url:
                pdf_url = _make_absolute(pdf_url, base_origin)
                if _is_on_domain(pdf_url, target_domain):
                    return pdf_url

            # --- Step 2: Follow financial section nav links ---
            financial_links = await _async_find_financial_nav_links(page, base_origin)
            for link_url in financial_links[:5]:
                try:
                    await page.goto(link_url, timeout=20_000, wait_until="domcontentloaded")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10_000)
                    except PlaywrightTimeout:
                        pass
                    pdf_url = await _async_find_pdf_link_on_page(page, year)
                    if pdf_url:
                        pdf_url = _make_absolute(pdf_url, base_origin)
                        if _is_on_domain(pdf_url, target_domain):
                            return pdf_url
                except Exception as e:
                    logger.debug(f"_async_crawl_corporate: nav link {link_url} failed: {e}")
                    continue

            # --- Step 3: Try common document paths ---
            for path in COMMON_DOC_PATHS:
                candidate_url = base_origin + path
                try:
                    resp = await page.goto(candidate_url, timeout=15_000, wait_until="domcontentloaded")
                    if resp and resp.status >= 400:
                        continue
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10_000)
                    except PlaywrightTimeout:
                        pass
                    pdf_url = await _async_find_pdf_link_on_page(page, year)
                    if pdf_url:
                        pdf_url = _make_absolute(pdf_url, base_origin)
                        if _is_on_domain(pdf_url, target_domain):
                            return pdf_url
                except Exception as e:
                    logger.debug(f"_async_crawl_corporate: path {path} failed: {e}")
                    continue

        finally:
            await browser.close()

    return None


def _find_financial_nav_links(page, base_origin: str) -> list[str]:
    """
    Scan current page for navigation links pointing to financial document sections.

    Returns list of absolute URLs (deduplicated, same-origin only).
    """
    found: list[str] = []
    seen: set[str] = set()

    try:
        all_links = page.locator("a[href]").all()
    except Exception:
        return found

    for link in all_links:
        try:
            href = link.get_attribute("href") or ""
            text = ""
            try:
                text = (link.inner_text() or "").lower()
            except Exception:
                pass

            href_lower = href.lower()

            # Check if text or href fragment matches financial keywords
            is_financial = any(kw in text for kw in NAV_FINANCIAL_KEYWORDS) or \
                           any(kw.replace(" ", "-") in href_lower or
                               kw.replace(" ", "_") in href_lower
                               for kw in NAV_FINANCIAL_KEYWORDS)

            if not is_financial:
                continue

            # Skip PDF links in this step (those are handled separately)
            if href_lower.endswith(".pdf") or ".pdf?" in href_lower:
                continue

            abs_url = _make_absolute(href, base_origin)
            if abs_url and abs_url not in seen:
                seen.add(abs_url)
                found.append(abs_url)
        except Exception:
            continue

    return found


async def _async_find_financial_nav_links(page, base_origin: str) -> list[str]:
    """Async version of _find_financial_nav_links for use with async_playwright."""
    found: list[str] = []
    seen: set[str] = set()
    try:
        all_links = await page.locator("a[href]").all()
    except Exception:
        return found
    for link in all_links:
        try:
            href = await link.get_attribute("href") or ""
            text = ""
            try:
                text = (await link.inner_text() or "").lower()
            except Exception:
                pass
            href_lower = href.lower()
            is_financial = any(kw in text for kw in NAV_FINANCIAL_KEYWORDS) or \
                           any(kw.replace(" ", "-") in href_lower or
                               kw.replace(" ", "_") in href_lower
                               for kw in NAV_FINANCIAL_KEYWORDS)
            if not is_financial:
                continue
            if href_lower.endswith(".pdf") or ".pdf?" in href_lower:
                continue
            abs_url = _make_absolute(href, base_origin)
            if abs_url and abs_url not in seen:
                seen.add(abs_url)
                found.append(abs_url)
        except Exception:
            continue
    return found


async def _async_find_pdf_link_on_page(page, year: int) -> Optional[str]:
    """Async version of _find_pdf_link_on_page for use with async_playwright."""
    for selector in PDF_LINK_SELECTORS:
        try:
            links = await page.locator(selector).all()
        except Exception:
            continue
        for link in links:
            try:
                href = await link.get_attribute("href") or ""
                text = ""
                try:
                    text = await link.inner_text() or ""
                except Exception:
                    pass
                if str(year) in href or str(year) in text:
                    return href
            except Exception:
                continue
        if links:
            try:
                href = await links[0].get_attribute("href") or ""
                if href:
                    return href
            except Exception:
                continue
    return None


def _make_absolute(href: str, base_origin: str) -> str:
    """Convert relative href to absolute URL using base_origin."""
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return base_origin + href
    return urljoin(base_origin + "/", href)


def _is_on_domain(url: str, target_domain: str) -> bool:
    """Return True if url belongs to target_domain (or a subdomain)."""
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
        return host == target_domain or host.endswith("." + target_domain)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# SCRAPE-03: Learned Scraper Profiles
# ---------------------------------------------------------------------------

def _load_scraper_profiles(profiles_path: Path = _PROFILES_PATH) -> dict[str, Any]:
    """Load all scraper profiles from JSON file. Returns empty dict if not found."""
    if not profiles_path.exists():
        return {}
    try:
        return json.loads(profiles_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"_load_scraper_profiles: failed to read {profiles_path}: {e}")
        return {}


def _save_scraper_profile(
    slug: str,
    profile_update: dict[str, Any],
    profiles_path: Path = _PROFILES_PATH,
) -> None:
    """
    Append-only update of a single slug's scraper profile.

    Loads existing profiles, merges profile_update into the slug entry
    (never deletes existing keys), then writes back. Creates the file
    if it doesn't exist. Thread-safe enough for single-threaded scraper use.

    Successful patterns (pdf_url_pattern, nav_path) are preserved even when
    a new run updates last_success — we never overwrite them.
    """
    profiles = _load_scraper_profiles(profiles_path)
    existing = profiles.get(slug, {})

    # Merge: new values win for scalar fields, but don't clear patterns that worked
    merged = {**existing, **profile_update}

    # Preserve successful URL patterns from previous runs (never overwrite)
    for preserve_key in ("pdf_url_pattern", "nav_path"):
        if preserve_key in existing and existing[preserve_key]:
            # Only overwrite if new value is non-empty
            new_val = profile_update.get(preserve_key)
            if not new_val:
                merged[preserve_key] = existing[preserve_key]

    # Accumulate failed DDGS queries (append-only list)
    existing_failed = existing.get("failed_ddgs_queries", [])
    new_failed = profile_update.get("failed_ddgs_queries", [])
    merged["failed_ddgs_queries"] = list(dict.fromkeys(existing_failed + new_failed))

    profiles[slug] = merged

    try:
        profiles_path.parent.mkdir(parents=True, exist_ok=True)
        profiles_path.write_text(
            json.dumps(profiles, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug(f"_save_scraper_profile: updated profile for {slug}")
    except Exception as e:
        logger.warning(f"_save_scraper_profile: failed to write {profiles_path}: {e}")


def _try_profile_pattern(
    slug: str,
    profile: dict[str, Any],
    year: int,
    out_dir: Path,
) -> Optional[ScraperResult]:
    """
    Try the saved pdf_url_pattern from a learned profile with year substitution.

    Returns ScraperResult on success (ok=True) or None if pattern not available
    or download fails (caller should fall through to next strategy).
    """
    pattern = profile.get("pdf_url_pattern", "")
    if not pattern:
        return None

    # Year substitution: replace wildcard or prior year with current year
    current_year_url = re.sub(r"\*|\b20\d{2}\b", str(year), pattern)
    logger.info(f"_try_profile_pattern: trying saved pattern for {slug}: {current_year_url[:80]}")

    score = _validate_pdf_relevance(
        current_year_url,
        profile.get("domain", ""),
        slug,
        year,
    )
    if score < 0.3:
        logger.debug(f"_try_profile_pattern: low relevance score {score:.2f} for {current_year_url[:60]}")
        return None

    result = _download_pdf(current_year_url, out_dir=out_dir, strategy="profile", attempts=[f"profile:{current_year_url[:60]}"])
    if result.ok:
        return result
    return None


# ---------------------------------------------------------------------------
# Strategy 1: DDGS semantic search — PRIMARY PATH (after corporate crawl)
# ---------------------------------------------------------------------------

def search(domain: str, year: int, out_dir: Path) -> ScraperResult:
    """
    Primary external search strategy: semantic ddgs search for annual report PDF.

    Tries 3 query variants in order. Validates each result URL for relevance
    (score >= 0.5) before downloading. Returns ScraperResult with ok=True and
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
            # Validate relevance before downloading
            score = _validate_pdf_relevance(pdf_url, domain, domain, year)
            if score < 0.5:
                logger.warning(
                    f"search: skipping low-relevance result (score={score:.2f}) "
                    f"from query {i+1}: {pdf_url[:80]}"
                )
                if i < len(queries) - 1:
                    time.sleep(random.uniform(2.0, 4.0))
                continue

            logger.info(f"search: found PDF URL via ddgs on query {i+1}/{len(queries)} (score={score:.2f})")
            return _download_pdf(pdf_url, out_dir=out_dir, strategy="ddgs", attempts=attempts)

        # Sleep between queries (not before first, not after last)
        if i < len(queries) - 1:
            time.sleep(random.uniform(2.0, 4.0))

    logger.warning(f"search: no relevant PDF URL found for domain={domain} year={year}")
    return ScraperResult(
        ok=False,
        strategy="ddgs",
        error=f"No relevant PDF URL found for domain={domain} year={year} after {len(queries)} queries",
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


# ---------------------------------------------------------------------------
# Convenience wrapper — called by LatamAgent.run()
# ---------------------------------------------------------------------------

def search_and_download(
    domain: str,
    slug: str,
    storage_path: Path,
    profiles_path: Path = _PROFILES_PATH,
) -> Optional[Path]:
    """Search for and download the annual report PDF for a LATAM company.

    Phase 12-06 enhanced strategy order:
      0. Profile pattern   — Try saved URL pattern (fastest, highest trust)
      1. Corporate crawl   — Playwright crawl of company's own website
      2. DDGS search       — External search with relevance validation
      3. Playwright        — Generic Playwright browser fallback

    On success, saves/updates a scraper profile for the slug.
    Returns pdf_path on success, None if all strategies fail.

    Args:
        domain:        Corporate website URL (e.g. "https://keralty.com")
        slug:          Company slug — used for profile lookup and logging
        storage_path:  Base storage directory (e.g. data/latam/CO/grupo-keralty/)
        profiles_path: Path to scraper_profiles.json (injectable for tests)
    """
    from datetime import datetime as _dt
    year = _dt.now().year - 1  # Target the most recent completed fiscal year

    logger.info(f"search_and_download: starting for {slug} ({domain}) year={year}")

    # Load existing profile for this slug
    profiles = _load_scraper_profiles(profiles_path)
    profile = profiles.get(slug, {})

    # Strategy 0: Try saved profile pattern (fastest)
    if profile:
        logger.info(f"search_and_download: found existing profile for {slug}, trying saved pattern")
        result = _try_profile_pattern(slug, profile, year, storage_path)
        if result and result.ok:
            logger.info(f"search_and_download: found via profile pattern — {result.pdf_path}")
            _save_scraper_profile(slug, {
                "domain": domain,
                "last_success": str(date.today()),
                "strategy": "profile",
            }, profiles_path)
            return result.pdf_path

    # Strategy 1: Crawl the corporate website directly (highest trust)
    logger.info(f"search_and_download: crawling corporate site {domain} for {slug}")
    pdf_url = _crawl_corporate_site(domain, slug, year)
    if pdf_url:
        crawl_score = _validate_pdf_relevance(pdf_url, domain, slug, year)
        if crawl_score < 0.5:
            logger.warning(
                f"search_and_download: corporate crawl found low-relevance PDF "
                f"(score={crawl_score:.2f}) — skipping {pdf_url[:80]}"
            )
            pdf_url = None
    if pdf_url:
        result = _download_pdf(pdf_url, out_dir=storage_path, strategy="corporate_crawl", attempts=[f"corporate_crawl:{domain[:60]}"])
        if result.ok:
            logger.info(f"search_and_download: found via corporate crawl — {result.pdf_path}")
            # Learn: save the URL pattern for future runs
            url_pattern = re.sub(str(year), "*", pdf_url)
            _save_scraper_profile(slug, {
                "domain": domain,
                "last_success": str(date.today()),
                "strategy": "corporate_crawl",
                "pdf_url_pattern": url_pattern,
            }, profiles_path)
            return result.pdf_path

    # Strategy 2: DDGS semantic search (with relevance validation)
    logger.info(f"search_and_download: corporate crawl failed, trying DDGS for {domain}")
    result = search(domain=domain, year=year, out_dir=storage_path)
    if result.ok:
        logger.info(f"search_and_download: found via ddgs — {result.pdf_path}")
        # Learn: save the successful URL pattern
        if result.source_url:
            url_pattern = re.sub(str(year), "*", result.source_url)
            _save_scraper_profile(slug, {
                "domain": domain,
                "last_success": str(date.today()),
                "strategy": "ddgs",
                "pdf_url_pattern": url_pattern,
            }, profiles_path)
        return result.pdf_path
    else:
        # Record failed DDGS queries so we can skip them next time
        failed_queries = [a for a in result.attempts if a.startswith("ddgs:")]
        if failed_queries:
            _save_scraper_profile(slug, {
                "domain": domain,
                "failed_ddgs_queries": failed_queries,
            }, profiles_path)

    # Strategy 3: Playwright browser fallback
    logger.info(f"search_and_download: ddgs failed, trying Playwright for {domain}")
    result = scrape_with_playwright(
        base_url=domain,
        year=year,
        out_dir=storage_path,
        attempts=result.attempts or [],
    )
    if result.ok:
        logger.info(f"search_and_download: found via Playwright — {result.pdf_path}")
        if result.source_url:
            url_pattern = re.sub(str(year), "*", result.source_url)
            _save_scraper_profile(slug, {
                "domain": domain,
                "last_success": str(date.today()),
                "strategy": "playwright",
                "pdf_url_pattern": url_pattern,
            }, profiles_path)
        return result.pdf_path

    logger.warning(
        f"search_and_download: all strategies failed for {slug} ({domain}). "
        f"Attempts: {result.attempts}"
    )
    return None
