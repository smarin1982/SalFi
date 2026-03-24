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

# Common corporate document section paths to try during crawl.
# T1 paths (financial statements) are listed first — crawl visits them with priority.
COMMON_DOC_PATHS = [
    # T1 — financial statements sections (highest priority)
    # Directory-style paths
    "/estados-financieros/",
    "/informes-financieros/",
    "/informacion-financiera/",
    "/estados_financieros/",
    "/financiero/",
    "/auditoria/",
    "/auditorias/",
    "/balance/",
    # HTML page variants (e.g. crocsas.com/Estados-financieros.html)
    "/estados-financieros.html",
    "/estados-financieros.htm",
    "/Estados-financieros.html",
    "/informacion-financiera.html",
    "/informes-financieros.html",
    "/auditoria.html",
    # T2 — annual/management report sections (fallback)
    "/informes/",
    "/reportes/",
    "/transparencia/",
    "/rendicion-de-cuentas/",
    "/documentos/",
    "/publicaciones/",
    "/sala-de-prensa/",
    "/relaciones-con-inversionistas/",
    "/memoria/",
    # HTML page variants T2
    "/informes.html",
    "/reportes.html",
    "/documentos.html",
    "/transparencia.html",
]

# ---------------------------------------------------------------------------
# Three-tier keyword scoring for PDF filename / link text relevance.
#
# Tier 1 — FINANCIAL STATEMENTS (highest priority)
#   Pure balance sheet / income statement / cash flow documents.
#   These contain the exact structured data the extractor needs.
#
# Tier 2 — ANNUAL / MANAGEMENT REPORTS (medium priority)
#   Contain financial data but mixed with operational narrative.
#   Use as fallback when no Tier-1 PDF is found.
#
# Tier 3 — GENERIC FINANCIAL SIGNAL (low priority)
#   Any other document with financial language — last resort.
# ---------------------------------------------------------------------------

PDF_KEYWORDS_TIER1 = [
    # Spanish
    "estados financieros",
    "estado financiero",
    "estados-financieros",
    "estado-financiero",
    "estados_financieros",
    "estadosfinancieros",   # no-separator variant (e.g. nicepagecdn filenames)
    "balance general",
    "balance-general",
    "balance_general",
    "estado de situacion financiera",
    "estado de resultados",
    "estado de flujo",
    "estados contables",
    "cuentas anuales",
    # English
    "financial statements",
    "financial-statements",
    "balance sheet",
]

PDF_KEYWORDS_TIER2 = [
    # Spanish
    "informe anual",
    "informe-anual",
    "informe_anual",
    "reporte anual",
    "reporte-anual",
    "memoria anual",
    "memoria-anual",
    "informe de gestion",
    "informe-de-gestion",
    "informe_de_gestion",
    "informe de gestión",
    "reporte de gestion",
    "reporte-de-gestion",
    "rendicion de cuentas",
    "rendicion-de-cuentas",
    # English
    "annual report",
    "annual-report",
    "management report",
]

PDF_KEYWORDS_TIER3 = [
    "financiero", "financiera", "financieros",
    "informe", "reporte",
    "balance", "resultado", "utilidad",
    "transparencia", "sostenibilidad",
    "annual", "financial", "earnings",
]

# Nav link text fragments indicating financial document sections.
# NOTE: "estado de resultados" must appear BEFORE "estados" so that the more
# specific T1 term is checked first when iterating NAV_T1_KEYWORDS.
NAV_FINANCIAL_KEYWORDS = [
    # T1-specific nav terms (match financial statement sub-sections)
    "estado de resultados",
    "estados financieros",
    "estados de resultados",
    "balance general",
    "informacion financiera",
    "información financiera",
    "estados contables",
    # Generic financial section terms
    "financiero",
    "informe",
    "gestion",
    "gestión",
    "estados",
    "resultado",
    "reporte anual",
    "transparencia",
    "rendicion de cuentas",
    "rendición de cuentas",
    "documentos",
    "publicaciones",
    "sala de prensa",
    "memoria",
]

# Subset of NAV_FINANCIAL_KEYWORDS that specifically indicate T1 sub-sections.
# When navigating into a financial section, links matching these are followed
# before generic financial links to prioritise estados financieros over T2.
NAV_T1_KEYWORDS = [
    "estado de resultados",
    "estados financieros",
    "estados de resultados",
    "balance general",
    "informacion financiera",
    "información financiera",
    "estados contables",
    "flujo de caja",
    "flujo de efectivo",
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
    "rendicion",
    # NOTE: "transparencia" removed — matches Mexican gov transparency portals
    # (INEGI, INAI) and causes false positives for non-domain DDGS results.
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
    """Async implementation of corporate website crawl for financial PDF.

    Navigates up to 3 levels deep:
      Level 1: root page → find PDFs or financial section links
      Level 2: financial section → find PDFs or T1 sub-section links
               (e.g. "Estado de resultados", "Estados financieros")
      Level 3: T1 sub-section → find PDFs (estados financieros priority)

    T1 sub-sections (NAV_T1_KEYWORDS) are always visited before T2 sections
    so that estados financieros is preferred over informes de gestión.
    """
    base_url = domain if domain.startswith("http") else f"https://{domain}"
    parsed = urlparse(base_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    target_domain = parsed.netloc.lower().lstrip("www.")

    async def _visit_and_find_pdf(url: str) -> Optional[str]:
        """Navigate to url and return best PDF link found on the page."""
        try:
            await page.goto(url, timeout=20_000, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeout:
                pass
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(500)
            except Exception:
                pass
            pdf = await _async_find_pdf_link_on_page(page, year)
            if pdf:
                # PDFs may be on a CDN (nicepagecdn, S3, GDrive, etc.) —
                # domain guard only applies to navigation links.
                return _make_absolute(pdf, base_origin)
        except Exception as e:
            logger.debug(f"_async_crawl_corporate: visit {url} failed: {e}")
        return None

    async def _get_subsection_links(t1_first: bool = True) -> tuple[list[str], list[str]]:
        """Return (t1_links, other_financial_links) from current page."""
        t1: list[str] = []
        other: list[str] = []
        seen: set[str] = set()
        try:
            all_links = await page.locator("a[href]").all()
        except Exception:
            return t1, other
        for link in all_links:
            try:
                href = (await link.get_attribute("href") or "").strip()
                text = ""
                try:
                    text = (await link.inner_text() or "").lower().strip()
                except Exception:
                    pass
                href_lower = href.lower()
                if href_lower.endswith(".pdf") or ".pdf?" in href_lower:
                    continue
                abs_url = _make_absolute(href, base_origin)
                if not abs_url or abs_url in seen or not _is_on_domain(abs_url, target_domain):
                    continue
                seen.add(abs_url)
                is_t1 = any(kw in text for kw in NAV_T1_KEYWORDS) or \
                         any(kw.replace(" ", "-") in href_lower or
                             kw.replace(" ", "_") in href_lower
                             for kw in NAV_T1_KEYWORDS)
                is_financial = any(kw in text for kw in NAV_FINANCIAL_KEYWORDS) or \
                               any(kw.replace(" ", "-") in href_lower or
                                   kw.replace(" ", "_") in href_lower
                                   for kw in NAV_FINANCIAL_KEYWORDS)
                if is_t1:
                    t1.append(abs_url)
                elif is_financial:
                    other.append(abs_url)
            except Exception:
                continue
        return t1, other

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            # --- Level 1: root page ---
            try:
                await page.goto(base_url, timeout=30_000, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except PlaywrightTimeout:
                    pass
            except Exception as e:
                logger.debug(f"_async_crawl_corporate: goto {base_url} failed: {e}")
                return None

            # Scroll to bottom — ensures footer/lazy-loaded links are in DOM
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800)
            except Exception:
                pass

            pdf_url = await _async_find_pdf_link_on_page(page, year)
            if pdf_url:
                # PDFs may be hosted on a CDN (nicepagecdn, S3, GDrive, etc.) —
                # do NOT apply _is_on_domain here; domain guard only applies to
                # navigation links in _get_subsection_links.
                return _make_absolute(pdf_url, base_origin)

            t1_links_l1, other_links_l1 = await _get_subsection_links()
            section_links_l1 = t1_links_l1[:5] + other_links_l1[:4]

            # --- Level 2: financial section pages ---
            for section_url in section_links_l1:
                pdf_url = await _visit_and_find_pdf(section_url)
                if pdf_url:
                    # Check if it's T1 — if yes, return immediately
                    if _detect_doc_tier(pdf_url) == 1:
                        return pdf_url
                    # T2/T3 found — keep as candidate but look deeper for T1
                    t2_candidate = pdf_url

                # --- Level 3: T1 sub-sections within this financial section ---
                t1_links_l2, other_links_l2 = await _get_subsection_links()
                # Prioritise T1 sub-links (e.g. "Estado de resultados" within
                # "Información de Gestión")
                for sub_url in (t1_links_l2[:3] + other_links_l2[:2]):
                    pdf_url = await _visit_and_find_pdf(sub_url)
                    if pdf_url and _detect_doc_tier(pdf_url) == 1:
                        logger.info(
                            f"_async_crawl_corporate: found T1 at depth-3 "
                            f"via {sub_url}"
                        )
                        return pdf_url

            # --- Level 4: Try common document paths ---
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
                        return _make_absolute(pdf_url, base_origin)
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
    """
    Scan page for the best annual financial-report PDF link.

    Priority:
      1. T1 annual financial statements (estados financieros, balance general, etc.)
      2. T2 annual/management reports — only when no T1 found AND it's NOT a
         periodic/partial-year report (quarterly, semester, trimestral, etc.)

    Periodic reports (quarterly, semester) are rejected entirely — the pipeline
    only processes complete annual data.

    Returns the highest-scoring annual PDF href, or None.
    """
    t1_candidates: list[tuple[int, str]] = []
    t2_annual_candidates: list[tuple[int, str]] = []

    try:
        all_links = await page.locator("a[href]").all()
    except Exception:
        return None

    for link in all_links:
        try:
            href = (await link.get_attribute("href") or "").strip()
        except Exception:
            continue
        if not href:
            continue
        href_lower = href.lower()
        if not (href_lower.endswith(".pdf") or ".pdf?" in href_lower):
            continue

        text = ""
        try:
            text = (await link.inner_text() or "").lower()
        except Exception:
            pass

        # Reject periodic/partial-year reports outright
        if _is_partial_year_url(href) or _is_partial_year_url(text):
            continue

        score = _score_pdf_link(href, text, year)
        if score <= 0:
            continue

        tier = _detect_doc_tier(href)
        if tier == 1:
            t1_candidates.append((score, href))
        else:
            t2_annual_candidates.append((score, href))

    if t1_candidates:
        t1_candidates.sort(key=lambda x: x[0], reverse=True)
        return t1_candidates[0][1]
    if t2_annual_candidates:
        t2_annual_candidates.sort(key=lambda x: x[0], reverse=True)
        return t2_annual_candidates[0][1]
    return None


def _score_pdf_link(href: str, link_text: str, year: int) -> int:
    """
    Score a PDF href+link_text for financial-report relevance using three tiers.

    Tier scoring (filename match beats link text, which beats path):
      Tier 1 — "estados financieros", "balance general", etc.  → +10 filename / +8 text / +5 path
      Tier 2 — "informe anual", "informe de gestión", etc.     →  +5 filename / +4 text / +2 path
      Tier 3 — generic ("financiero", "balance", etc.)         →  +2 filename / +1 text

    Year bonus (+3) applied on top when tier > 0.

    Returns 0 when no financial signal found — caller skips this PDF.
    Highest-scoring candidate wins when multiple PDFs exist on a page.
    """
    try:
        path = urlparse(href).path.lower()
        filename = path.rsplit("/", 1)[-1]
    except Exception:
        path = href.lower()
        filename = href.lower()

    text_lower = link_text.lower()
    # Normalise: remove accents for matching (simple fold)
    import unicodedata
    def _fold(s: str) -> str:
        return unicodedata.normalize("NFD", s).encode("ascii", "errors").decode("ascii", "ignore") if False else s.replace("ó","o").replace("é","e").replace("á","a").replace("í","i").replace("ú","u").replace("ñ","n").replace("ü","u")

    filename_n = _fold(filename)
    text_n = _fold(text_lower)
    path_n = _fold(path)

    score = 0

    # --- Tier 1: financial statements ---
    for kw in PDF_KEYWORDS_TIER1:
        kw_n = _fold(kw)
        if kw_n in filename_n:
            score += 10
            break
    else:
        for kw in PDF_KEYWORDS_TIER1:
            kw_n = _fold(kw)
            if kw_n in text_n:
                score += 8
                break
        else:
            for kw in PDF_KEYWORDS_TIER1:
                kw_n = _fold(kw)
                if kw_n in path_n:
                    score += 5
                    break

    # --- Tier 2: annual/management reports (only if no Tier-1 match yet) ---
    if score == 0:
        for kw in PDF_KEYWORDS_TIER2:
            kw_n = _fold(kw)
            if kw_n in filename_n:
                score += 5
                break
        else:
            for kw in PDF_KEYWORDS_TIER2:
                kw_n = _fold(kw)
                if kw_n in text_n:
                    score += 4
                    break
            else:
                for kw in PDF_KEYWORDS_TIER2:
                    kw_n = _fold(kw)
                    if kw_n in path_n:
                        score += 2
                        break

    # --- Tier 3: generic signal (only if still zero) ---
    if score == 0:
        for kw in PDF_KEYWORDS_TIER3:
            if kw in filename_n:
                score += 2
                break
        if score == 0:
            for kw in PDF_KEYWORDS_TIER3:
                if kw in text_n:
                    score += 1
                    break

    # Year bonus — only when there's already a financial signal
    if score > 0 and year:
        if str(year) in href or str(year - 1) in href or str(year) in text_lower:
            score += 3

    return score


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


_PARTIAL_YEAR_PATTERNS = re.compile(
    r"semestre|semestral|trimestre|trimestral"
    r"|-1-|-2-|-3-|-4-"         # e.g. Infgestion-1-2025
    r"|primer|segundo|tercer|cuarto"
    r"|q1|q2|q3|q4"
    r"|ene[-_]jun|jul[-_]dic",   # Jan-Jun / Jul-Dec spans
    re.IGNORECASE,
)


def _is_partial_year_url(url: str) -> bool:
    """Return True if the URL suggests a partial-year (semester/quarterly) report."""
    return bool(_PARTIAL_YEAR_PATTERNS.search(url))


def _detect_doc_tier(url: str) -> int:
    """Return document tier inferred from the URL/filename.

    1 = estados financieros (financial statements — highest trust)
    2 = informe de gestión / informe anual (management / annual report)
    3 = generic or unrecognised

    Used to decide whether a cached scraper profile can be reused: only T1
    profiles are reused directly; T2/T3 profiles trigger a fresh search so
    that a T1 document is preferred.
    """
    def _fold(s: str) -> str:
        return (
            s.replace("ó", "o").replace("é", "e").replace("á", "a")
             .replace("í", "i").replace("ú", "u").replace("ñ", "n").replace("ü", "u")
        )

    url_n = _fold(url.lower())
    for kw in PDF_KEYWORDS_TIER1:
        if _fold(kw) in url_n:
            return 1
    for kw in PDF_KEYWORDS_TIER2:
        if _fold(kw) in url_n:
            return 2
    return 3


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

    # Accumulate historical_pdfs (append-only dict — never delete known URLs)
    existing_hist = existing.get("historical_pdfs", {})
    new_hist = profile_update.get("historical_pdfs", {})
    if existing_hist or new_hist:
        merged["historical_pdfs"] = {**existing_hist, **new_hist}

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
    # All queries target T1 (annual financial statements) explicitly.
    # No T2-only queries — annual management reports are accepted as last resort
    # by the caller (search_and_download), not here.
    queries = [
        f'site:{domain} filetype:pdf {SEARCH_KEYWORDS_ES} {year}',
        f'site:{domain} filetype:pdf "estados financieros" "balance" {year}',
        f'site:{domain} filetype:pdf {SEARCH_KEYWORDS_ALT} {year}',
        f'site:{domain} filetype:pdf "informe anual" "estados financieros" {year}',
    ]

    for i, query in enumerate(queries):
        attempts.append(f"ddgs:{query[:60]}")
        pdf_url = _ddgs_first_pdf_url(query)
        if pdf_url:
            # Reject partial/periodic reports entirely
            if _is_partial_year_url(pdf_url):
                logger.info(
                    f"search: skipping partial-year URL from query {i+1}: {pdf_url[:80]}"
                )
                if i < len(queries) - 1:
                    time.sleep(random.uniform(2.0, 4.0))
                continue

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
        except Exception as exc:
            logger.warning(f"scrape_with_playwright: worker raised {type(exc).__name__}: {exc}")
            return ScraperResult(
                ok=False,
                strategy="playwright",
                error=f"Worker exception: {exc}",
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

    Uses async_playwright + ProactorEventLoop — required on Windows when called
    from a ThreadPoolExecutor (sync_playwright raises NotImplementedError there).
    Returns PDF URL (absolute) or None.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_async_find_pdf(base_url, year))
    finally:
        loop.close()


async def _async_find_pdf(base_url: str, year: int) -> Optional[str]:
    """
    Async implementation: navigate to base_url, find best financial PDF link.

    Tries root page first, then IR_PAGE_FRAGMENTS sub-pages via click navigation.
    Returns the first matching PDF URL (absolute), or None.
    """
    parsed = urlparse(base_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(base_url, timeout=30_000, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeout:
                pass
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800)
            except Exception:
                pass

            # Try direct PDF links on root page
            pdf_url = await _async_find_pdf_link_on_page(page, year)
            if pdf_url:
                return _make_absolute(pdf_url, base_origin)

            # Try IR sub-pages via fragment links
            for fragment in IR_PAGE_FRAGMENTS:
                try:
                    ir_locator = page.locator(f'a[href*="{fragment}"]')
                    if await ir_locator.count() > 0:
                        await ir_locator.first.click(timeout=5_000)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=10_000)
                        except PlaywrightTimeout:
                            pass
                        pdf_url = await _async_find_pdf_link_on_page(page, year)
                        if pdf_url:
                            return _make_absolute(pdf_url, base_origin)
                except PlaywrightTimeout:
                    continue
                except Exception:
                    continue
        finally:
            await browser.close()
    return None


def _find_pdf_link_on_page(page, year: int) -> Optional[str]:
    """
    Scan current page for the best financial-report PDF link.

    Scores all PDF anchors by financial keywords in filename/text and year match.
    Returns the highest-scoring href, or None if no financial-signal PDF found.
    """
    candidates: list[tuple[int, str]] = []

    try:
        all_links = page.locator("a[href]").all()
    except Exception:
        return None

    for link in all_links:
        try:
            href = (link.get_attribute("href") or "").strip()
        except Exception:
            continue
        if not href:
            continue
        href_lower = href.lower()
        if not (href_lower.endswith(".pdf") or ".pdf?" in href_lower):
            continue

        text = ""
        try:
            text = (link.inner_text() or "").lower()
        except Exception:
            pass

        score = _score_pdf_link(href, text, year)
        if score > 0:
            candidates.append((score, href))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


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
    _now = _dt.now()
    # Before July most companies haven't published N-1 annual report yet — use N-2
    year = _now.year - 1 if _now.month >= 7 else _now.year - 2

    logger.info(f"search_and_download: starting for {slug} ({domain}) year={year}")

    # Load existing profile for this slug
    profiles = _load_scraper_profiles(profiles_path)
    profile = profiles.get(slug, {})

    # Strategy 0: Try saved profile pattern (fastest) — only reuse T1 profiles.
    # If the cached profile points to a T2 management report, skip it and search
    # fresh so that a T1 (estados financieros) document can be found instead.
    if profile:
        saved_tier = profile.get("doc_tier", 3)
        if saved_tier > 1:
            logger.info(
                f"search_and_download: existing profile for {slug} is doc_tier={saved_tier} "
                f"(management report / generic) — skipping saved pattern to search for T1 "
                f"estados financieros"
            )
        else:
            logger.info(f"search_and_download: found existing T1 profile for {slug}, trying saved pattern")
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
    # T1 (estados financieros) is returned immediately.
    # T2/T3 is stored as a fallback and we continue to DDGS/Playwright for T1.
    logger.info(f"search_and_download: crawling corporate site {domain} for {slug}")
    crawl_t2_fallback: Optional[ScraperResult] = None
    crawl_t2_url: Optional[str] = None
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
        crawl_tier = _detect_doc_tier(pdf_url)
        result = _download_pdf(pdf_url, out_dir=storage_path, strategy="corporate_crawl", attempts=[f"corporate_crawl:{domain[:60]}"])
        if result.ok:
            if crawl_tier == 1:
                # T1 found via crawl — use it immediately
                logger.info(f"search_and_download: found T1 via corporate crawl — {result.pdf_path}")
                url_pattern = re.sub(str(year), "*", pdf_url)
                _save_scraper_profile(slug, {
                    "domain": domain,
                    "last_success": str(date.today()),
                    "strategy": "corporate_crawl",
                    "pdf_url_pattern": url_pattern,
                    "doc_tier": 1,
                }, profiles_path)
                return result.pdf_path
            else:
                # T2/T3 from crawl — store as fallback, continue searching for T1
                logger.info(
                    f"search_and_download: corporate crawl found T{crawl_tier} document "
                    f"— storing as fallback, continuing to search for T1 estados financieros"
                )
                crawl_t2_fallback = result
                crawl_t2_url = pdf_url

    # Strategy 2: DDGS semantic search.
    # T1 results (estados financieros) are accepted immediately.
    # T2/T3 results are stored as fallback — we keep searching for T1.
    # If the T2 result looks like a partial-year report (first semester, quarterly),
    # we also search year-1 since a full annual report is more useful.
    logger.info(f"search_and_download: corporate crawl failed, trying DDGS for {domain}")

    t2_fallback: Optional[ScraperResult] = None
    failed_attempts: list[str] = []

    for search_year in (year, year - 1):
        if search_year < year - 1:
            break
        result = search(domain=domain, year=search_year, out_dir=storage_path)

        if result.ok:
            tier = _detect_doc_tier(result.source_url or "")
            if tier == 1:
                logger.info(f"search_and_download: found T1 via ddgs (year={search_year}) — {result.pdf_path}")
                if result.source_url:
                    url_pattern = re.sub(str(search_year), "*", result.source_url)
                    _save_scraper_profile(slug, {
                        "domain": domain,
                        "last_success": str(date.today()),
                        "strategy": "ddgs",
                        "pdf_url_pattern": url_pattern,
                        "doc_tier": 1,
                        "historical_pdfs": {str(search_year): result.source_url},
                    }, profiles_path)
                return result.pdf_path

            # T2/T3 found — only accept full annual reports, never partial/periodic
            is_partial = _is_partial_year_url(result.source_url or "")
            if is_partial:
                logger.info(
                    f"search_and_download: DDGS found partial-year T{tier} document "
                    f"(year={search_year}) — rejected, trying year-1 for full annual"
                )
                # Don't store as fallback — continue to year-1
            else:
                logger.info(
                    f"search_and_download: DDGS found annual T{tier} document "
                    f"(year={search_year}) — storing as fallback"
                )
                t2_fallback = result
                break  # Full-year T2 is acceptable — no need to try year-1
        else:
            failed_attempts.extend(a for a in result.attempts if a.startswith("ddgs:"))
            if search_year == year:
                logger.info(f"search_and_download: DDGS year={year} found nothing, trying year={year-1}")

    if failed_attempts:
        _save_scraper_profile(slug, {"domain": domain, "failed_ddgs_queries": failed_attempts}, profiles_path)

    # Strategy 3: Playwright browser fallback (try for T1)
    last_attempts = (t2_fallback.attempts if t2_fallback else []) or failed_attempts
    logger.info(f"search_and_download: trying Playwright for {domain}")
    result = scrape_with_playwright(
        base_url=domain,
        year=year,
        out_dir=storage_path,
        attempts=last_attempts,
    )
    if result.ok:
        tier = _detect_doc_tier(result.source_url or "")
        if tier == 1 or t2_fallback is None:
            logger.info(f"search_and_download: found via Playwright (T{tier}) — {result.pdf_path}")
            if result.source_url:
                url_pattern = re.sub(str(year), "*", result.source_url)
                _save_scraper_profile(slug, {
                    "domain": domain,
                    "last_success": str(date.today()),
                    "strategy": "playwright",
                    "pdf_url_pattern": url_pattern,
                    "doc_tier": tier,
                    "historical_pdfs": {str(year): result.source_url},
                }, profiles_path)
            return result.pdf_path
        # Playwright also returned T2 — compare with existing fallback
        is_partial = _is_partial_year_url(result.source_url or "")
        if not is_partial:
            t2_fallback = result

    # Last resort: use best T2 fallback found (DDGS > crawl preference)
    best_t2 = t2_fallback or crawl_t2_fallback
    best_t2_url = (t2_fallback.source_url if t2_fallback else crawl_t2_url) or ""
    if best_t2 and best_t2.ok:
        logger.info(
            f"search_and_download: no T1 found — using best T2 fallback "
            f"({best_t2_url or 'unknown url'})"
        )
        if best_t2_url:
            src = best_t2_url
            matched_year = year
            for y in (year, year - 1):
                if str(y) in src:
                    matched_year = y
                    break
            url_pattern = re.sub(str(matched_year), "*", src)
            _save_scraper_profile(slug, {
                "domain": domain,
                "last_success": str(date.today()),
                "strategy": "crawl_t2_fallback" if best_t2 is crawl_t2_fallback else "ddgs_t2_fallback",
                "pdf_url_pattern": url_pattern,
                "doc_tier": _detect_doc_tier(src),
            }, profiles_path)
        return best_t2.pdf_path

    logger.warning(
        f"search_and_download: all strategies failed for {slug} ({domain}). "
        f"Attempts: {last_attempts}"
    )
    return None
