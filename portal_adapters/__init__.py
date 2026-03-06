"""
LATAM Regulatory Portal Adapters.

Each adapter exposes find_pdf(regulatory_id: str, year: int) -> Optional[str].
Returns a direct PDF URL if found, or None if not found.
NEVER raises — all errors are caught and logged; None is returned to trigger
the Playwright fallback in latam_scraper.scrape_with_playwright().

Live validation status (updated during Phase 7 implementation):
"""
from typing import Optional, Dict

# Updated during Task 2 live validation spike
# Status values: "working" | "partial" | "broken" | "not_validated"
PORTAL_STATUS: Dict[str, str] = {
    # Live-validated 2026-03-06
    "supersalud_co": "partial",   # ddgs returns PDFs but query precision low (planning docs, not EEFF)
    "smv_pe": "stub",             # by design: session-dependent URLs, Playwright fallback required
    "cmf_cl": "broken",           # bank URL pattern HEAD check returns 404 for tested RUT 97006000-6
    "sfc_co": "stub",
    "cnv_ar": "stub",
    "cnbv_mx": "stub",
}


def get_adapter(country: str, authority: str):
    """Return the adapter module for a given country/authority combo."""
    from portal_adapters import supersalud, smv, cmf, sfc, cnv, cnbv
    _MAP = {
        ("CO", "Supersalud"): supersalud,
        ("PE", "SMV"): smv,
        ("CL", "CMF"): cmf,
        ("CO", "SFC"): sfc,
        ("AR", "CNV"): cnv,
        ("MX", "CNBV"): cnbv,
    }
    return _MAP.get((country.upper(), authority))
