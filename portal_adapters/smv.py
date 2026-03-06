"""
SMV (Peru) SIMV portal adapter.
URL pattern confidence: LOW — obfuscated ?data=HEX session parameters.
Direct URL construction from RUC is not reliable without JS execution.
This adapter returns None; Playwright fallback navigates smv.gob.pe directly.
"""
from typing import Optional

from loguru import logger


def find_pdf(ruc: str, year: int) -> Optional[str]:
    """
    Attempt to find SMV annual report PDF for a company by RUC.
    Currently returns None — SMV SIMV requires browser session for URL resolution.
    Playwright fallback (scrape_with_playwright) is the primary path for SMV companies.

    Parameters
    ----------
    ruc : str
        Peruvian RUC identifier (e.g. "20100003539").
    year : int
        Fiscal year of the annual report (e.g. 2023).

    Returns
    -------
    None
        Always returns None. Never raises.
    """
    logger.warning(
        f"SMV adapter: RUC={ruc} year={year}. "
        "Direct URL construction not supported — SMV uses session-dependent URLs. "
        "Use scrape_with_playwright('https://www.smv.gob.pe/SIMV/', year) as fallback."
    )
    return None
