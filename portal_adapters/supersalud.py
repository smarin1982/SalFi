"""
Supersalud (Colombia) portal adapter.
Strategy: ddgs site:docs.supersalud.gov.co filetype:pdf search.
URL pattern confidence: LOW — requires live validation.
If ddgs search fails: return None (Playwright fallback handles navigation).
"""
from typing import Optional

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from loguru import logger

SUPERSALUD_DOCS_BASE = "docs.supersalud.gov.co"


def find_pdf(nit: str, year: int) -> Optional[str]:
    """
    Search for Supersalud-hosted financial report PDF for a company by NIT.
    Returns direct PDF URL or None.
    Never raises.

    Strategy: DuckDuckGo search restricted to docs.supersalud.gov.co.
    Two queries are attempted in order; returns the first PDF href found.

    Parameters
    ----------
    nit : str
        Colombian NIT identifier (e.g. "800058016").
    year : int
        Fiscal year of the annual report (e.g. 2023).

    Returns
    -------
    str or None
        Direct PDF URL if found; None if not found or on any error.
    """
    queries = [
        f'site:{SUPERSALUD_DOCS_BASE} filetype:pdf "{nit}" {year}',
        f'site:{SUPERSALUD_DOCS_BASE} filetype:pdf "estados financieros" {year}',
    ]
    for query in queries:
        try:
            results = DDGS().text(query, max_results=5, backend="auto")
            for r in results:
                href = r.get("href", "")
                if href.lower().endswith(".pdf"):
                    logger.info(
                        f"Supersalud: found PDF via ddgs for NIT={nit} year={year}: {href}"
                    )
                    return href
        except DDGSException as e:
            logger.debug(f"Supersalud ddgs failed for NIT={nit}: {e}")
    logger.warning(
        f"Supersalud: no PDF found for NIT={nit} year={year}. "
        "Use Playwright fallback (scrape_with_playwright)."
    )
    return None
