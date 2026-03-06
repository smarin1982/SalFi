"""
CNBV (Mexico) portal adapter — stub.
URL patterns not yet researched. Returns None.

CNBV (Comision Nacional Bancaria y de Valores) regulates financial institutions
in Mexico. URL pattern research is pending. Playwright fallback navigates
cnbv.gob.mx directly.
"""
from typing import Optional

from loguru import logger


def find_pdf(regulatory_id: str, year: int) -> Optional[str]:
    """
    Attempt to find CNBV annual report PDF. Stub — not yet implemented.
    Returns None. Never raises.

    Parameters
    ----------
    regulatory_id : str
        Mexican regulatory ID (RFC or internal CNBV code).
    year : int
        Fiscal year of the annual report.

    Returns
    -------
    None
        Always returns None. Playwright fallback is the primary path.
    """
    logger.warning(
        f"CNBV adapter: stub — URL patterns not yet researched for "
        f"regulatory_id={regulatory_id} year={year}. Returns None."
    )
    return None
