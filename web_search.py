"""SCRAP-03: ddgs web search wrapper with tenacity retry and graceful degradation.

Returns [] on any failure — never raises, never blocks pipeline.
"""

from __future__ import annotations

from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

try:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException, RatelimitException

    _DDGS_AVAILABLE = True
except ImportError:
    _DDGS_AVAILABLE = False
    RatelimitException = Exception  # type: ignore[assignment, misc]
    DDGSException = Exception  # type: ignore[assignment, misc]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=30),
    retry=retry_if_exception_type((RatelimitException, DDGSException)),
    reraise=False,
)
def _search_with_retry(query: str, max_results: int) -> list[dict]:
    """Inner search — retried up to 3 times with exponential backoff."""
    with DDGS() as ddgs:
        return ddgs.text(query, max_results=max_results)


def search_sector_context(
    company_name: str, country: str, sector: str = "salud"
) -> list[dict]:
    """Search for sector context and comparable companies.

    SCRAP-03: Returns list of dicts with 'title', 'href', 'body'.
    Returns [] on failure — NEVER raises, never blocks pipeline.

    Args:
        company_name: e.g., "Grupo Keralty"
        country: ISO 2-letter code, e.g., "CO"
        sector: sector name in Spanish, e.g., "salud"

    Returns:
        list[dict] with keys 'title', 'href', 'body'. Empty list on any failure.
    """
    if not _DDGS_AVAILABLE:
        logger.warning("ddgs not installed — web search skipped")
        return []

    query = f"{company_name} sector {sector} {country} comparables financieros"
    try:
        results = _search_with_retry(query, max_results=5)
        logger.info(
            f"Web search returned {len(results or [])} results for '{query}'"
        )
        return results or []
    except Exception as exc:
        logger.warning(f"Web search failed (non-blocking): {exc!r}")
        return []


def search_comparable_companies(
    sector: str, country: str, max_results: int = 3
) -> list[dict]:
    """Search for comparable healthcare companies in same country.

    Used by RPT-03 (executive report with 2-3 comparables) — Phase 11.
    Returns [] on failure — NEVER raises, never blocks pipeline.

    Args:
        sector: sector name in Spanish, e.g., "salud"
        country: ISO 2-letter code, e.g., "CO"
        max_results: maximum number of search results to return

    Returns:
        list[dict] with keys 'title', 'href', 'body'. Empty list on any failure.
    """
    if not _DDGS_AVAILABLE:
        return []

    query = f"empresas sector {sector} {country} estados financieros comparables"
    try:
        results = _search_with_retry(query, max_results=max_results)
        logger.info(
            f"Comparable search returned {len(results or [])} results for '{query}'"
        )
        return results or []
    except Exception as exc:
        logger.warning(f"Comparable search failed (non-blocking): {exc!r}")
        return []
