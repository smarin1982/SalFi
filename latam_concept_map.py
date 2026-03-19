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
        "ventas de servicios",                              # abbreviated form
        "ventas",                                           # bare label (pdfplumber truncation)
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
        "ebitda",  # EBITDA used as operating_income proxy (closest schema column)
        # Pre-tax income (closest proxy in current schema)
        "ganancia antes de impuestos",
        "ganancia antes de impuesto",
        "utilidad antes de impuestos",
        "utilidad antes de impuesto",
        "resultado antes de impuestos",
        "resultado antes de impuesto",
        "utilidad antes de impuesto sobre la renta",
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
        # IFRS / Colombian IPS variants
        "ganancia o perdida del año",
        "ganancia o pérdida del año",
        "ganancia o perdida del ejercicio",
        "ganancia o pérdida del ejercicio",
        "ganancia del año",
        "perdida del año",
        "pérdida del año",
        "resultado del año",
    ],
    "operating_expenses": [
        "gastos de administracion",
        "gastos de administración",
        "gastos administrativos",
        "gastos de ventas",
        "gastos de ventas y administracion",
        "gastos de ventas y administración",
        "gastos operacionales",
        "gastos operacionales de administracion",
        "gastos operacionales de administración",
        "gastos de operacion",
        "gastos de operación",
        "total gastos operacionales",
        "costos y gastos operacionales",
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
        "activos totales",               # PUC CO: noun-adj order
        "suma del activo",
        "total activo",
        # IFRS balance-sheet check line: equity + liabilities = total assets
        "patrimonio y pasivos totales",  # CO IFRS balance sheet total line
        "pasivos y patrimonio totales",  # variant column order
        "total pasivos y patrimonio",    # another variant
        "total patrimonio y pasivos",    # another variant
    ],
    "total_liabilities": [
        "total pasivos",
        "total de pasivos",
        "pasivo total",
        "pasivos totales",       # PUC CO: noun-adj order
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
        "cobrar corrientes",
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
    # ---------------------------------------------------------------------------
    # Derived indicators — extracted from indicator tables (e.g. CO management
    # report page 41). These fields are NOT in FINANCIALS_COLUMNS so they are
    # stored in ExtractionResult.fields but not written to financials.parquet.
    # They are included here so the extractor logs them and the synonym reviewer
    # can capture them for future schema additions.
    # ---------------------------------------------------------------------------
    "current_ratio": [
        "razón corriente",
        "razon corriente",
        "liquidez corriente",
        "índice de liquidez",
        "indice de liquidez",
        "razón de liquidez",
        "razon de liquidez",
    ],
    "dso": [
        "periodo de cobro",
        "período de cobro",
        "periodo de cobro en dias",
        "período de cobro en días",
        "período de cobro (días)",
        "periodo de cobro (dias)",
        "días de cuentas por cobrar",
        "dias de cuentas por cobrar",
        # NOTE: "rotacion de cartera en dias" deliberately excluded — "Rotación de cartera"
        # (without "en días") is the turnover RATIO (e.g. 2.65x), not DSO in days (135 days).
        # That label would falsely prefix-match this synonym via Direction 3.
    ],
    "dpo": [
        "periodo de pago",
        "período de pago",
        "periodo de pago en dias",
        "período de pago en días",
        "días de cuentas por pagar",
        "dias de cuentas por pagar",
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

    # -----------------------------------------------------------------------
    # TWO-PASS matching to prevent Direction-3 (prefix) from shadowing an
    # exact Direction-1/2 match that belongs to a shorter synonym.
    #
    # Example: label "total activos"
    #   Pass 1 — Direction 1 on (total_assets, "total activos") → MATCH ✓
    #   If merged in one loop, Direction 3 on (current_assets, "total activos
    #   corrientes") fires first (longer synonym, higher sort position) → wrong.
    # -----------------------------------------------------------------------

    # Pass 1: Direction 1 (synonym-in-label) and Direction 2 (label-in-synonym)
    for canonical, synonym_plain in candidates:
        # Direction 1: synonym appears as a whole-word sequence within the label.
        #   e.g. "ingresos" matches "ingresos operacionales" but NOT "reingresos"
        synonym_in_label = bool(
            re.search(r"(?<![a-z])" + re.escape(synonym_plain) + r"(?![a-z])", normalized_plain)
        )
        # Direction 2: label appears within the synonym, only when label >= synonym length.
        label_in_synonym = (
            len(normalized_plain) >= len(synonym_plain)
            and normalized_plain in synonym_plain
        )
        if synonym_in_label or label_in_synonym:
            return canonical

    # Pass 2: Direction 3 — prefix matching for pdfplumber-truncated labels.
    #   e.g. "Ganancia o" (10 chars) → prefix of "ganancia o perdida del año" → net_income
    #
    #   Guards:
    #   - len >= 8: ignore very short prefixes
    #   - ratio >= 0.30: label must be ≥30% of the synonym length — rules out a
    #     single word ("efectivo", 21%) being a prefix of a long unrelated synonym
    #     while still catching genuine truncations like "Ganancia o" (38%)
    for canonical, synonym_plain in candidates:
        label_is_prefix = (
            len(normalized_plain) >= 8
            and synonym_plain.startswith(normalized_plain)
            and len(normalized_plain) / len(synonym_plain) >= 0.30
        )
        if label_is_prefix:
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
        first_comma = cleaned.index(",")
        first_period = cleaned.index(".")
        if first_period < first_comma:
            # Colombian format: 1.234.567,89 — remove periods (thousands), comma → decimal
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # American / OCR-artifact format: 1,234,567.89 or 1,234,567.774
            # When the final period-segment has exactly 3 digits, it is also a thousands
            # group (not a decimal fraction) — common Tesseract OCR artifact at 300 DPI.
            last_segment = cleaned.rsplit(".", 1)[-1]
            if len(last_segment) == 3 and last_segment.isdigit():
                # e.g. 119,056,418.774 → all separators are thousands → 119056418774
                cleaned = cleaned.replace(",", "").replace(".", "")
            else:
                # Standard American decimal: remove commas (thousands), keep period
                cleaned = cleaned.replace(",", "")
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
