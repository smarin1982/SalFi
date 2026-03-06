"""
SFC (Colombia) portal adapter — stub.
URL patterns not yet researched. Returns None.

SFC (Superintendencia Financiera de Colombia) regulates financial companies
(banks, insurance, etc.) in Colombia. URL pattern research is pending.
Playwright fallback navigates sfc.gov.co directly.
"""
from typing import Optional

from loguru import logger


def find_pdf(regulatory_id: str, year: int) -> Optional[str]:
    """
    Attempt to find SFC annual report PDF. Stub — not yet implemented.
    Returns None. Never raises.

    Parameters
    ----------
    regulatory_id : str
        Colombian NIT or entity identifier.
    year : int
        Fiscal year of the annual report.

    Returns
    -------
    None
        Always returns None. Playwright fallback is the primary path.
    """
    logger.warning(
        f"SFC adapter: stub — URL patterns not yet researched for "
        f"regulatory_id={regulatory_id} year={year}. Returns None."
    )
    return None
