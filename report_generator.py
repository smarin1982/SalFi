"""
report_generator.py — Phase 11 standalone report engine.

Public API:
    fetch_comparables(company_name, country, sector) -> list[str]
    generate_executive_report(kpis, red_flags, comparables, company) -> str
    build_pdf_bytes(report_text, company_name, country, fiscal_year) -> bytes
    export_chart_png(fig) -> bytes | None

All heavy imports (anthropic, fpdf2, kaleido, plotly) are lazy — inside functions.
Module-level imports: stdlib only.
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# fetch_comparables
# ---------------------------------------------------------------------------

def fetch_comparables(company_name: str, country: str, sector: str = "salud") -> list[str]:
    """Return up to 3 comparable company snippets via web search.

    Never raises — returns [] on any failure.
    """
    try:
        from web_search import search_sector_context

        query = f"empresas comparables {sector} {country} {company_name} financiero"
        results = search_sector_context(company_name=company_name, country=country, sector=sector)
        snippets = []
        for r in results[:3]:
            title = r.get("title", "")
            body = r.get("body", "")
            snippet = f"{title}: {body}".strip(": ").strip()
            if snippet:
                snippets.append(snippet)
        return snippets
    except Exception as exc:
        logger.warning("fetch_comparables failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# generate_executive_report
# ---------------------------------------------------------------------------

def generate_executive_report(
    kpis: dict,
    red_flags: list,
    comparables: list,
    company: dict,
) -> str:
    """Generate a Spanish executive report via Claude.

    Args:
        kpis: dict of KPI name -> value (USD-normalised)
        red_flags: list of red flag dicts from red_flags.py
        comparables: list of strings from fetch_comparables()
        company: dict with keys name, country, currency_original, fiscal_year

    Returns:
        Markdown report string in Spanish, or an error string (never raises).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return (
            "[Error: ANTHROPIC_API_KEY no configurada. "
            "Agrega ANTHROPIC_API_KEY=sk-ant-... al archivo .env]"
        )

    try:
        from anthropic import Anthropic

        client = Anthropic(timeout=120.0)

        user_prompt = (
            f"Genera un reporte ejecutivo para {company['name']} "
            f"({company['country']}, Año fiscal {company['fiscal_year']}) "
            f"con estas cuatro secciones exactas:\n\n"
            f"## 1. Resumen de Gestión\n"
            f"## 2. KPIs Destacados\n"
            f"## 3. Red Flags Activas\n"
            f"## 4. Contexto Sectorial y Comparables\n\n"
            f"Datos disponibles:\n"
            f"KPIs (valores en USD normalizados): {json.dumps({k: v for k, v in kpis.items() if v is not None}, ensure_ascii=False, separators=(',', ':'))}\n"
            f"Red Flags detectadas: {json.dumps(red_flags, ensure_ascii=False, separators=(',', ':'))}\n"
            f"Empresas comparables (búsqueda web): {comparables}\n"
            f"Moneda original: {company.get('currency_original', 'N/D')}\n\n"
            f"Instrucciones por sección:\n"
            f"- Sección 1: 2-3 párrafos de evaluación general de la gestión financiera\n"
            f"- Sección 2: tabla markdown de los 5 KPIs más relevantes con valor + interpretación; "
            f"muestra valores tanto en moneda original como en USD (ej: \"COP 4.2B (~USD 1.05M)\")\n"
            f"- Sección 3: lista numerada; para cada red flag indica severidad (Alta/Media/Baja) "
            f"y una oración de contexto\n"
            f"- Sección 4: menciona 2-3 empresas comparables del sector con benchmarks sectoriales "
            f"disponibles; si no hay comparables, indica "
            f"\"No se encontraron comparables disponibles.\""
        )

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=(
                "Eres un analista financiero senior especializado en empresas de salud de "
                "Latinoamérica. Genera reportes ejecutivos concisos, factuales y en español "
                "profesional. No inventes datos; si un dato falta, indícalo explícitamente."
            ),
            messages=[{"role": "user", "content": user_prompt}],
        )
        return msg.content[0].text

    except Exception as exc:
        logger.error("generate_executive_report failed: %s", exc)
        return f"[Error al generar reporte: {exc}]"


# ---------------------------------------------------------------------------
# build_pdf_bytes
# ---------------------------------------------------------------------------

def build_pdf_bytes(
    report_text: str,
    company_name: str,
    country: str,
    fiscal_year: int,
) -> bytes:
    """Render report_text to a PDF and return raw bytes.

    Uses fpdf2 (pure Python). Spanish characters (á é í ó ú ñ) are Latin-1
    compatible — Helvetica handles them without TTF font installation.

    Raises RuntimeError (with install hint) if fpdf2 is not installed.
    """
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError(
            "fpdf2 is not installed. Run: pip install 'fpdf2>=2.8.7'"
        ) from exc

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Reporte Ejecutivo - {company_name}", ln=True)

    # Sub-header: country + fiscal year
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, f"{country} \u00b7 A\u00f1o fiscal {fiscal_year}", ln=True)

    # Sub-header: generation date
    pdf.set_text_color(128, 128, 128)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"Generado: {datetime.now().strftime('%Y-%m-%d')}", ln=True)
    pdf.set_text_color(0, 0, 0)

    pdf.ln(8)

    # Body — fpdf2 multi_cell renders plain text; markdown symbols appear as literals
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, report_text)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# export_chart_png
# ---------------------------------------------------------------------------

# Kaleido chrome discovery: confirmed working (Playwright Chromium detected)

def export_chart_png(fig) -> "bytes | None":
    """Render a Plotly figure to PNG bytes via Kaleido.

    Returns PNG bytes on success, None on any failure (Chrome not found, etc.).
    Never raises.
    """
    try:
        import kaleido  # noqa: F401
        result = fig.to_image(format="png", width=800, height=300, scale=2)
        return result
    except Exception as exc:
        logger.warning("export_chart_png failed (Kaleido unavailable): %s", exc)
        return None
