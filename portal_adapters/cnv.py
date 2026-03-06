"""
CNV (Argentina) portal adapter — stub.
URL patterns not yet researched. Returns None.

CNV (Comision Nacional de Valores) regulates publicly listed companies in Argentina.
URL pattern research is pending. Playwright fallback navigates cnv.gov.ar directly.
"""
from typing import Optional

from loguru import logger


def find_pdf(regulatory_id: str, year: int) -> Optional[str]:
    """
    Attempt to find CNV annual report PDF. Stub — not yet implemented.
    Returns None. Never raises.

    Parameters
    ----------
    regulatory_id : str
        Argentine CNV entity identifier (CUIT or internal ID).
    year : int
        Fiscal year of the annual report.

    Returns
    -------
    None
        Always returns None. Playwright fallback is the primary path.
    """
    logger.warning(
        f"CNV adapter: stub — URL patterns not yet researched for "
        f"regulatory_id={regulatory_id} year={year}. Returns None."
    )
    return None
