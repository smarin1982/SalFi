"""
CMF (Chile) portal adapter.
Bank sector: URL pattern cmfchile.cl/bancos/estados_anuales/{year}/ is MEDIUM confidence.
Non-bank IFRS portal: JS-rendered, returns None (Playwright fallback required).
"""
from typing import Optional

import requests
from loguru import logger

CMF_BANK_BASE = "https://www.cmfchile.cl/bancos/estados_anuales"
VALIDATION_TIMEOUT = 10


def find_pdf(rut: str, year: int) -> Optional[str]:
    """
    Attempt to construct direct PDF URL for a CMF-regulated entity by RUT.
    Bank sector only — tries URL pattern from research.
    Returns URL if validated (HEAD request 200), otherwise None.
    Never raises.

    Parameters
    ----------
    rut : str
        Chilean RUT identifier (e.g. "97006000-6" for Banco de Chile).
    year : int
        Fiscal year of the annual report (e.g. 2023).

    Returns
    -------
    str or None
        Validated PDF URL if HEAD returns 200; None if not found or any error.

    Notes
    -----
    The {code} in the CMF bank URL is likely an internal CMF identifier, not
    the RUT directly. We use the cleaned RUT as a proxy; this requires live
    validation to confirm. Non-bank entities (IFRS portal) always return None
    because their portal is JS-rendered and cannot be URL-constructed.
    """
    # Normalize RUT: strip non-alphanumeric chars for URL use
    rut_clean = rut.replace("-", "").replace(".", "").lower()
    # CMF bank pattern: {year}12 = December filing (most common year-end)
    # The {code} is likely an internal CMF code, not directly the RUT.
    # Attempt with RUT as proxy — requires live validation.
    candidate_urls = [
        f"{CMF_BANK_BASE}/{year}/Bancos-{year}/{year}12-{rut_clean}.pdf",
        f"{CMF_BANK_BASE}/{year}/Bancos-{year}/{year}09-{rut_clean}.pdf",
    ]
    for url in candidate_urls:
        try:
            resp = requests.head(url, timeout=VALIDATION_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                logger.info(f"CMF: found PDF for RUT={rut} year={year}: {url}")
                return url
        except requests.RequestException as e:
            logger.debug(f"CMF HEAD check failed for {url}: {e}")
    logger.warning(
        f"CMF adapter: no validated URL for RUT={rut} year={year}. "
        "Non-bank entities require Playwright navigation of cmfchile.cl IFRS portal."
    )
    return None
