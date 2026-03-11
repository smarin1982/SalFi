"""
latam_concept_map.py

Spanish healthcare accounting synonym dictionary for the LATAM pipeline.
Maps Spanish-language accounting labels (CO/PE/CL regulatory filings) to the
canonical 22-column schema of financials.parquet.

Exports:
    LATAM_CONCEPT_MAP          - dict[str, list[str]] — 22-field synonym dictionary
    COUNTRY_CRITICAL_FIELDS    - dict[str, set[str]] — country-specific critical fields
    DEFAULT_CRITICAL_FIELDS    - set[str] — fallback when country unknown
    map_to_canonical           - function(label: str) -> Optional[str]
    parse_latam_number         - function(text: str) -> Optional[float]
    validate_tesseract         - function() -> bool
    TESSERACT_AVAILABLE        - bool — set at import time via validate_tesseract()
"""

import re
from pathlib import Path
from typing import Optional

from loguru import logger

_LEARNED_SYNONYMS_FILE = Path("data/latam/learned_synonyms.json")

# ---------------------------------------------------------------------------
# LATAM_CONCEPT_MAP
# Source: IFRS Spanish terminology + CO/PE/CL regulatory filing samples.
# Revenue must have >= 10 synonyms including the 5 confirmed KPI-03 terms.
# ---------------------------------------------------------------------------

LATAM_CONCEPT_MAP: dict[str, list[str]] = {
    # KPI-03: >= 5 confirmed Spanish healthcare revenue synonyms required.
    "revenue": [
        "ingresos por prestacion de servicios de salud",    # CO/PE clinics (normalised: no accent)
        "ingresos por prestación de servicios de salud",    # CO/PE clinics (with accent)
        "ingresos por prestación de servicios",             # CO generic
        "ingresos por prestacion de servicios",             # CO generic (no accent)
        "ventas de servicios de salud",                     # PE hospitals
        "ingresos operacionales",                           # CO/CL generic
        "ingresos de actividades ordinarias",               # IFRS 15 standard term
        "ingresos netos",                                   # net revenue variant
        "ingresos por servicios",                           # abbreviated form
        "ingresos totales",                                 # total revenues
        "ventas netas",                                     # net sales (some MX companies)
        "total de ingresos",                                # total income
        "ingresos",                                         # bare label
    ],
    "gross_profit": [
        "utilidad bruta",
        "ganancia bruta",
        "margen bruto",
        "resultado bruto",
    ],
    "cogs": [
        "costo de ventas",
        "costo de servicios",
        "costo de prestacion de servicios",
        "costo de prestación de servicios",
        "costo de servicios de salud",
        "costos y gastos de operacion",
        "costos y gastos de operación",
    ],
    "operating_income": [
        "utilidad operacional",
        "utilidad de operacion",
        "utilidad de operación",
        "ganancia operacional",
        "resultado de operacion",
        "resultado de operación",
        "resultado operativo",
        "ebit",
    ],
    "net_income": [
        "utilidad neta",
        "ganancia neta",
        "resultado neto",
        "utilidad del ejercicio",
        "ganancia del ejercicio",
        "utilidad del periodo",
        "utilidad del período",
        "resultado del periodo",
        "resultado del período",
        "resultado del ejercicio",
        "perdida neta",
        "pérdida neta",
    ],
    "interest_expense": [
        "gastos financieros",
        "gastos por intereses",
        "intereses a cargo",
        "costo de financiamiento",
        "costos financieros",
    ],
    "depreciation_amortization": [
        "depreciacion y amortizacion",
        "depreciación y amortización",
        "depreciacion",
        "depreciación",
        "amortizacion",
        "amortización",
        "depreciacion de activos fijos",
        "depreciación de activos fijos",
        "deterioro de activos",
    ],
    "total_assets": [
        "total activos",
        "total de activos",
        "activo total",
        "suma del activo",
        "total activo",
    ],
    "total_liabilities": [
        "total pasivos",
        "total de pasivos",
        "pasivo total",
        "suma del pasivo",
        "total pasivo",
    ],
    "total_equity": [
        "patrimonio total",
        "total patrimonio",
        "patrimonio neto",
        "capital y reservas",
        "total patrimonio neto",
        "patrimonio de los accionistas",
    ],
    "current_assets": [
        "activos corrientes",
        "activo corriente",
        "activos de corto plazo",
        "total activos corrientes",
    ],
    "current_liabilities": [
        "pasivos corrientes",
        "pasivo corriente",
        "pasivos de corto plazo",
        "total pasivos corrientes",
    ],
    "cash": [
        "efectivo y equivalentes en efectivo",
        "efectivo y equivalentes de efectivo",
        "efectivo y equivalentes al efectivo",
        "caja y bancos",
        "disponible",
        "efectivo",
    ],
    "short_term_investments": [
        "inversiones a corto plazo",
        "inversiones corrientes",
        "inversiones temporales",
        "valores negociables",
    ],
    "receivables": [
        "cuentas comerciales - por cobrar y otras cuentas por cobrar corrientes",
        "cuentas comerciales - por cobrar y otras cuentas por cobrar",
        "cuentas comerciales - por cobrar",
        "cuentas por cobrar comerciales y otras cuentas por cobrar",
        "cuentas por cobrar",
        "deudores comerciales",
        "cartera de clientes",
        "cuentas por cobrar netas",
        "deudores",
    ],
    "inventory": [
        "inventarios",
        "existencias",
        "mercancias",
        "mercancías",
        "suministros medicos",
        "suministros médicos",
        "medicamentos e insumos",
    ],
    "long_term_debt": [
        "obligaciones financieras a largo plazo",
        "deuda a largo plazo",
        "pasivos financieros no corrientes",
        "prestamos a largo plazo",
        "préstamos a largo plazo",
        "deuda financiera no corriente",
    ],
    "short_term_debt": [
        "obligaciones financieras a corto plazo",
        "obligaciones financieras corrientes",
        "deuda a corto plazo",
        "pasivos financieros corrientes",
        "prestamos a corto plazo",
        "préstamos a corto plazo",
        "porcion corriente de la deuda",
        "porción corriente de la deuda",
        "obligaciones financieras",
    ],
    "accounts_payable": [
        "cuentas por pagar",
        "proveedores",
        "acreedores comerciales",
        "cuentas por pagar proveedores",
    ],
    "shares_outstanding": [
        "acciones en circulacion",
        "acciones en circulación",
        "numero de acciones",
        "número de acciones",
        "acciones comunes en circulacion",
        "acciones comunes en circulación",
        "acciones suscritas y pagadas",
    ],
    "operating_cash_flow": [
        "flujo de efectivo de operaciones",
        "flujos netos de efectivo de actividades de operacion",
        "flujos netos de efectivo de actividades de operación",
        "actividades de operacion",
        "actividades de operación",
        "efectivo neto de actividades operativas",
        "flujos de efectivo por actividades operativas",
    ],
    "capex": [
        "adquisicion de activos fijos",
        "adquisición de activos fijos",
        "compra de propiedad planta y equipo",
        "inversiones en activos fijos",
        "gastos de capital",
        "adquisiciones de propiedad planta y equipo",
        "compras de propiedad planta y equipo",
    ],
}

# ---------------------------------------------------------------------------
# COUNTRY_CRITICAL_FIELDS
# Country-specific minimum-disclosure requirements from each country's regulator.
# ---------------------------------------------------------------------------

COUNTRY_CRITICAL_FIELDS: dict[str, set[str]] = {
    # CO: Supersalud requires revenue, total_assets, total_liabilities, total_equity, operating_cash_flow
    "CO": {"revenue", "total_assets", "total_liabilities", "total_equity", "operating_cash_flow"},
    # PE: SMV (IFRS full) requires revenue, net_income, total_assets, total_liabilities, operating_cash_flow
    "PE": {"revenue", "net_income", "total_assets", "total_liabilities", "operating_cash_flow"},
    # CL: CMF requires revenue, net_income, total_assets, total_equity, operating_cash_flow
    "CL": {"revenue", "net_income", "total_assets", "total_equity", "operating_cash_flow"},
}

# Fallback used when country is unknown or not in COUNTRY_CRITICAL_FIELDS
DEFAULT_CRITICAL_FIELDS: set[str] = {
    "revenue",
    "net_income",
    "total_assets",
    "total_liabilities",
    "operating_cash_flow",
}


# ---------------------------------------------------------------------------
# Learned synonyms loader
# ---------------------------------------------------------------------------

def _load_learned_synonyms() -> dict[str, str]:
    """Load approved synonyms from learned_synonyms.json.

    Returns dict mapping lowercase label -> canonical_field.
    Returns {} if file missing or malformed — never raises.

    File format (list of objects):
    [{"label": "ganancia antes de impuesto", "canonical": "operating_income", ...}]
    """
    import json

    result: dict[str, str] = {}
    if not _LEARNED_SYNONYMS_FILE.exists():
        return result
    try:
        with open(_LEARNED_SYNONYMS_FILE, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
        for entry in entries:
            label = entry.get("label", "").strip().lower()
            canonical = entry.get("canonical", "").strip()
            if label and canonical:
                result[label] = canonical
    except Exception:  # noqa: BLE001
        pass  # corrupt file — silently return empty dict
    return result


# Loaded once at import time. Re-import the module (or call reload) to pick up changes.
_LEARNED_SYNONYMS: dict[str, str] = _load_learned_synonyms()


# ---------------------------------------------------------------------------
# map_to_canonical
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, strip whitespace, remove accent marks for accent-insensitive matching."""
    text = text.lower().strip()
    # Basic accent normalization (replace common accented chars with ASCII equivalents)
    accent_map = str.maketrans(
        "áéíóúüñàèìòùâêîôûãõ",
        "aeiouunaeiouaeiouao",
    )
    return text.translate(accent_map)


def map_to_canonical(label: str) -> Optional[str]:
    """
    Look up a Spanish accounting label in LATAM_CONCEPT_MAP.

    Case-insensitive and accent-insensitive. Parenthetical content (e.g. "(nota 12)",
    "(en miles)") is stripped before matching.

    Synonyms are matched longest-first to prevent short synonyms (e.g. "efectivo")
    from incorrectly matching labels that contain them as substrings
    (e.g. "flujo de efectivo de operaciones").

    Returns canonical field name (str) on match, or None if not recognised.
    """
    if not label or not label.strip():
        return None

    # Step 1: lowercase + strip
    normalized = label.lower().strip()
    # Step 2: remove parenthetical content
    normalized = re.sub(r"\(.*?\)", "", normalized).strip()
    # Step 3: accent-normalise for matching
    normalized_plain = _normalize(normalized)

    # Build a flat list of (canonical, synonym_plain) sorted by synonym length descending.
    # Longer synonyms are more specific — check them first to avoid short-synonym false
    # positives (e.g. "efectivo" matching "flujo de efectivo de operaciones").
    candidates: list[tuple[str, str]] = []
    for canonical, synonyms in LATAM_CONCEPT_MAP.items():
        for synonym in synonyms:
            candidates.append((canonical, _normalize(synonym)))
    candidates.sort(key=lambda x: len(x[1]), reverse=True)

    for canonical, synonym_plain in candidates:
        # Direction 1: synonym appears within the normalised label
        #   e.g. "total activos" matches "total activos (nota 3)"
        synonym_in_label = synonym_plain in normalized_plain
        # Direction 2: label appears within the synonym
        #   Only valid when the label is AT LEAST as long as the synonym.
        #   Prevents a short input like "total activos" from being swallowed by a
        #   longer synonym "total activos corrientes" (which would be a false positive).
        label_in_synonym = (
            len(normalized_plain) >= len(synonym_plain)
            and normalized_plain in synonym_plain
        )
        if synonym_in_label or label_in_synonym:
            return canonical

    # Fallback: check human-approved learned synonyms (base map always wins)
    label_lower = label.strip().lower()
    if label_lower in _LEARNED_SYNONYMS:
        return _LEARNED_SYNONYMS[label_lower]

    return None


# ---------------------------------------------------------------------------
# parse_latam_number
# ---------------------------------------------------------------------------

def parse_latam_number(text: str) -> Optional[float]:
    """
    Parse a number formatted in LATAM conventions where:
      - period (.) is the thousands separator
      - comma (,) is the decimal separator

    Examples:
      "1.234.567,89"  -> 1234567.89
      "(500.000)"     -> -500000.0  (parentheses = negative)
      "1,234"         -> 1.234      (only comma = decimal separator)
      "1.234"         -> 1234.0     (only period with 3-digit tail = thousands)
      "1.23"          -> 1.23       (only period with 2-digit tail = decimal)

    Returns None on parse failure.
    """
    if text is None:
        return None

    # Step 1: strip whitespace and non-breaking spaces
    cleaned = str(text).strip().replace("\xa0", "").replace(" ", "")

    if not cleaned:
        return None

    # Step 2: detect negative via parenthesis notation
    negative = cleaned.startswith("(") and cleaned.endswith(")")

    # Step 3: strip parentheses
    cleaned = cleaned.strip("()")

    if not cleaned:
        return None

    # Step 4-6: determine format
    has_comma = "," in cleaned
    has_period = "." in cleaned

    if has_comma and has_period:
        # Format: 1.234.567,89 — remove periods (thousands), replace comma with dot (decimal)
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif has_comma and not has_period:
        # Only comma: comma is decimal separator (e.g. "1234567,89")
        cleaned = cleaned.replace(",", ".")
    elif has_period and not has_comma:
        # Only period: check if last segment has exactly 3 digits → thousands separator
        parts = cleaned.split(".")
        if len(parts[-1]) == 3:
            # All period separators are thousands separators → remove all periods
            cleaned = cleaned.replace(".", "")
        # else: period is decimal separator → leave as-is

    # Step 7: parse
    try:
        value = float(cleaned)
    except ValueError:
        return None

    # Step 8: apply sign
    return -value if negative else value


# ---------------------------------------------------------------------------
# validate_tesseract
# ---------------------------------------------------------------------------

def validate_tesseract() -> bool:
    """
    Validate that the Tesseract binary is available and the Spanish language pack is installed.

    Runs at module initialisation time. Never raises — any exception is caught and logged.

    Returns True only when Tesseract binary is reachable AND 'spa' language pack is present.
    Returns False and logs a warning/error otherwise.
    """
    try:
        import os
        import pytesseract
        from dotenv import load_dotenv

        load_dotenv()
        _cmd = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        pytesseract.pytesseract.tesseract_cmd = _cmd

        pytesseract.get_tesseract_version()

        langs = pytesseract.get_languages()
        if "spa" not in langs:
            logger.warning(
                "Tesseract found but 'spa' language pack missing — OCR will be disabled. "
                "Install spa.traineddata in the tessdata directory."
            )
            return False

        return True

    except Exception as exc:
        logger.error(
            f"Tesseract binary not found or not usable — OCR path disabled. "
            f"Install Tesseract 5 and set TESSERACT_CMD env var if needed. Error: {exc}"
        )
        return False


# ---------------------------------------------------------------------------
# Module-level initialisation — run Tesseract validation at import time so
# latam_extractor.py can check TESSERACT_AVAILABLE before attempting OCR.
# ---------------------------------------------------------------------------

TESSERACT_AVAILABLE: bool = validate_tesseract()
