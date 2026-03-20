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
import os
import re
from datetime import datetime

from loguru import logger


# ---------------------------------------------------------------------------
# _strip_markdown  (plain-text conversion for PDF rendering)
# ---------------------------------------------------------------------------

def _strip_markdown(text: str) -> str:
    """Convert markdown to plain text suitable for fpdf2 multi_cell rendering."""
    lines = []
    for line in text.split("\n"):
        # Section headers: ## Title → Title (uppercase for h1/h2, normal for h3)
        m = re.match(r"^(#{1,3})\s+(.+)", line)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            lines.append("")
            lines.append(title.upper() if level <= 2 else title)
            lines.append("-" * min(len(title), 60) if level <= 2 else "")
            continue
        # Table separator rows: |---|---|
        if re.match(r"^\s*\|[-|\s:]+\|\s*$", line):
            continue
        # Table data rows: | col1 | col2 | → col1   col2
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            lines.append("  ".join(c for c in cells if c))
            continue
        # Bold and italic
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"\*(.+?)\*", r"\1", line)
        line = re.sub(r"__(.+?)__", r"\1", line)
        # Inline code
        line = re.sub(r"`(.+?)`", r"\1", line)
        # Normalize bullet markers to a simple dash
        line = re.sub(r"^\s*[-*]\s+", "- ", line)
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# _extract_t2_narrative  (intro + conclusions from T2 PDF)
# ---------------------------------------------------------------------------

def _extract_t2_narrative(pdf_path: str) -> str:
    """Extract introduction and conclusions text from a T2 management report PDF.

    Strategy:
    1. Classify each page: TOC (dot_ratio > 0.15) vs content
    2. Intro: first content page whose first lines mention 'introduccion' / 'presentacion'
       + following content page. Fallback: first 2 content pages.
    3. Conclusions: first content page whose first lines mention 'conclusion' / 'cierre' /
       'perspectiva' / 'balance'. Fallback: last 2 content pages.
    4. Label blocks and truncate to 2400 chars total.

    Never raises — returns "" on any failure.
    """
    _INTRO_KEYS = ("introduccion", "introducción", "presentacion", "presentación", "carta al lector")
    _CONCL_KEYS = ("conclusion", "conclusiones", "conclusión", "cierre", "perspectivas",
                   "balance general", "reflexiones", "resumen ejecutivo")

    try:
        import pdfplumber

        pages_text: list[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                pages_text.append(page.extract_text() or "")

        n = len(pages_text)
        if not n:
            return ""

        # Classify pages — TOC pages have high dot density
        def _is_toc(text: str) -> bool:
            return len(text) > 0 and text.count(".") / len(text) > 0.12

        def _header_matches(text: str, keys: tuple) -> bool:
            for line in text.lower().split("\n")[:8]:
                stripped = line.strip().lstrip("0123456789. ")
                if any(stripped.startswith(k) for k in keys):
                    return True
            return False

        content_pages = [(i, t) for i, t in enumerate(pages_text) if t.strip() and not _is_toc(t)]

        # Find intro
        intro_idxs: list[int] = []
        for i, text in content_pages:
            if _header_matches(text, _INTRO_KEYS):
                next_content = next((j for j, _ in content_pages if j > i), i)
                intro_idxs = [i, next_content]
                break
        if not intro_idxs:
            intro_idxs = [idx for idx, _ in content_pages[:2]]

        # Find conclusions
        concl_idxs: list[int] = []
        for i, text in content_pages:
            if _header_matches(text, _CONCL_KEYS):
                next_content = next((j for j, _ in content_pages if j > i), i)
                concl_idxs = [i, next_content]
                break
        if not concl_idxs:
            # Fallback: last 2 content pages
            concl_idxs = [idx for idx, _ in content_pages[-2:]]

        intro_text = "\n\n".join(pages_text[i] for i in intro_idxs if i < n).strip()
        concl_text = "\n\n".join(pages_text[i] for i in concl_idxs if i < n).strip()

        parts = []
        if intro_text:
            parts.append(f"[INTRODUCCION]\n{intro_text[:1200]}")
        if concl_text and concl_idxs != intro_idxs:
            parts.append(f"[CONCLUSIONES/CIERRE]\n{concl_text[:1200]}")
        return "\n\n".join(parts)

    except Exception as exc:
        logger.warning("_extract_t2_narrative failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# fetch_management_narrative
# ---------------------------------------------------------------------------

def fetch_management_narrative(
    slug: str,
    country: str,
    fiscal_year: int,
    data_dir: str = "data",
) -> str:
    """Download T2 (informe de gestion) for fiscal_year and return intro + conclusions text.

    Lookup order:
    1. Disk cache: data/latam/{country}/{slug}/raw/t2_{year}_narrative.txt
    2. scraper_profiles.json → t2_pdfs[str(fiscal_year)] URL
    3. Download PDF, extract, write cache

    Returns narrative string (max ~2400 chars) or "" if unavailable. Never raises.
    """
    try:
        from pathlib import Path
        import requests

        raw_dir = Path(data_dir) / "latam" / country.lower() / slug / "raw"
        cache_txt = raw_dir / f"t2_{fiscal_year}_narrative.txt"

        if cache_txt.exists():
            logger.info("fetch_management_narrative: cache hit %s %d", slug, fiscal_year)
            return cache_txt.read_text(encoding="utf-8")

        profiles_path = Path(data_dir) / "latam" / "scraper_profiles.json"
        if not profiles_path.exists():
            return ""

        profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
        t2_url = profiles.get(slug, {}).get("t2_pdfs", {}).get(str(fiscal_year))
        if not t2_url:
            logger.info("fetch_management_narrative: no T2 URL for %s year %d", slug, fiscal_year)
            return ""

        t2_pdf_path = raw_dir / f"t2_{fiscal_year}.pdf"
        if not t2_pdf_path.exists():
            logger.info("fetch_management_narrative: downloading T2 %s", t2_url)
            raw_dir.mkdir(parents=True, exist_ok=True)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            resp = requests.get(t2_url, timeout=30, headers=headers)
            resp.raise_for_status()
            if resp.content[:4] != b"%PDF":
                logger.warning("fetch_management_narrative: response is not a PDF — skipping")
                return ""
            t2_pdf_path.write_bytes(resp.content)
            logger.info("fetch_management_narrative: saved %d bytes to %s", len(resp.content), t2_pdf_path)

        narrative = _extract_t2_narrative(str(t2_pdf_path))
        if narrative:
            cache_txt.write_text(narrative, encoding="utf-8")
            logger.info("fetch_management_narrative: extracted %d chars for %s %d", len(narrative), slug, fiscal_year)
        return narrative

    except Exception as exc:
        logger.warning("fetch_management_narrative failed: %s", exc)
        return ""


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
    management_narrative: str = "",
) -> str:
    """Generate a Spanish executive report via Claude following the financial-analysis skill.

    Args:
        kpis: dict of KPI name -> value (USD-normalised); may include multi-year history
              under key "history": {year: {kpi: value}}
        red_flags: list of red flag dicts from red_flags.py
        comparables: list of strings from fetch_comparables()
        company: dict with keys name, country, currency_original, fiscal_year
        management_narrative: extracted intro+conclusions from T2 informe de gestion (may be "")

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

        # Separate current KPIs from historical series
        history: dict = kpis.pop("history", {}) if isinstance(kpis, dict) else {}
        kpis_clean = {k: v for k, v in kpis.items() if v is not None}

        # Build scenario block from historical data (replaces DCF for private companies)
        scenario_block = ""
        if history and len(history) >= 2:
            years_sorted = sorted(history.keys())
            metric = "revenue_cagr_10y" if "revenue_cagr_10y" in kpis_clean else "ebitda_margin"
            vals = {y: history[y].get(metric) for y in years_sorted if history[y].get(metric) is not None}
            if vals:
                best_year = max(vals, key=vals.get)
                worst_year = min(vals, key=vals.get)
                avg_val = sum(vals.values()) / len(vals)
                scenario_block = (
                    f"\nSeries historicas disponibles ({', '.join(str(y) for y in years_sorted)}):\n"
                    f"{json.dumps({str(y): history[y] for y in years_sorted}, ensure_ascii=False, separators=(',', ':'))}\n"
                    f"Para la seccion de escenarios usa: "
                    f"Optimista={best_year} (mejor {metric}={vals[best_year]:.2f}), "
                    f"Base=promedio ({avg_val:.2f}), "
                    f"Pesimista={worst_year} (peor {metric}={vals[worst_year]:.2f})\n"
                )
        elif not history:
            scenario_block = "\nSolo hay datos del año fiscal más reciente — omite el análisis de tendencias históricas.\n"

        currency = company.get("currency_original", "USD")
        fx = company.get("fx_rate_usd")
        fx_note = (
            f"Tipo de cambio aplicado: 1 {currency} = {fx} USD" if fx else
            f"Valores en USD (moneda original: {currency})"
        )

        # T2 narrative block — injected only when available
        t2_block = ""
        if management_narrative:
            t2_block = (
                f"\nINFORME DE GESTION (T2) - Introduccion y Conclusiones:\n"
                f"{management_narrative}\n"
            )
            logger.info("generate_executive_report: T2 narrative included (%d chars)", len(management_narrative))
        else:
            logger.info("generate_executive_report: no T2 narrative — sections 1 and 3 will use KPI data only")

        # Section 1 instruction depends on whether T2 is available
        sec1_instruction = (
            "Fuente PRIMARIA: el INFORME DE GESTION (T2) incluido arriba. "
            "Redacta 2 párrafos basados en la introduccion y conclusiones del informe: "
            "qué hizo la empresa, cómo fue su gestión, logros y desafios declarados. "
            "Complementa solo con 1-2 KPIs clave para cuantificar afirmaciones."
            if management_narrative else
            "Maximo 2 párrafos breves: evaluación global de la salud financiera y "
            "posicion competitiva basada en los KPIs disponibles."
        )

        user_prompt = (
            f"Genera un reporte ejecutivo de análisis financiero para:\n"
            f"Empresa: {company['name']}\n"
            f"País: {company['country']} | Año fiscal: {company['fiscal_year']} | {fx_note}\n"
            f"{t2_block}\n"
            f"DATOS FINANCIEROS:\n"
            f"KPIs año principal (USD): {json.dumps(kpis_clean, ensure_ascii=False, separators=(',', ':'))}\n"
            f"Red Flags detectadas: {json.dumps(red_flags, ensure_ascii=False, separators=(',', ':'))}\n"
            f"Contexto sectorial (búsqueda web): {comparables}\n"
            f"{scenario_block}\n"
            f"ESTRUCTURA REQUERIDA — exactamente 3 secciones, español profesional. "
            f"LIMITE ESTRICTO: máximo 1.200 tokens de salida (2 páginas A4 máximo).\n\n"
            f"## 1. Resumen Ejecutivo\n"
            f"{sec1_instruction}\n\n"
            f"## 2. Análisis Financiero\n"
            f"Cuatro tablas independientes, una por categoría, con encabezado de sección visible:\n"
            f"Categorías obligatorias: Rentabilidad, Liquidez, Apalancamiento, Eficiencia.\n"
            f"Columnas de cada tabla: Indicador | Valor ({currency}) | Benchmark | Interpretación.\n"
            f"- 'Valor' muestra el número en moneda original ({currency}), sin columna USD adicional.\n"
            f"- 'Benchmark' es el valor de referencia sectorial del indicador.\n"
            f"- 'Interpretación' es una frase de 1-2 líneas que explica qué significa el valor "
            f"para la empresa (no solo si está por encima/debajo del benchmark).\n"
            f"- Incluye mínimo 1 indicador por categoría; omite filas con valor N/D solo si "
            f"la categoría tiene al menos otro indicador disponible.\n\n"
            f"## 3. Insights\n"
            f"Texto corrido de 4-6 oraciones — sin subsecciones, sin bullets, sin numeración. "
            f"Estilo corporativo: prosa fluida, voz activa, lenguaje de reporte ejecutivo. "
            f"No enumeres puntos ni uses conectores lineales como 'primero... segundo... tercero'. "
            f"El párrafo debe integrar orgánicamente: la valoración de riesgos que emergen de "
            f"los indicadores y alertas, el posicionamiento competitivo de la empresa frente al "
            f"sector y la coyuntura declarada en su informe de gestión, y una postura de inversión "
            f"o gestión (Favorable / Neutral / Precaución) sustentada en los elementos anteriores. "
            f"Si hay serie histórica, teje la tendencia en la narrativa sin destacarla como punto aparte. "
            f"No repitas cifras ya presentes en la sección 2.\n\n"
            f"REGLAS:\n"
            f"- No inventes valores; si un dato falta, omítelo o indica 'N/D'\n"
            f"- Solo guion simple (-), nunca doble guion ni em-dash\n"
            f"- Español profesional sin anglicismos innecesarios\n"
            f"- NO generes más de 3 secciones ni subsecciones dentro de la sección 3"
        )

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1600,
            system=(
                "Eres un analista financiero senior de una firma de banca de inversión, "
                "especializado en el sector salud de Latinoamérica. Produces reportes de due "
                "diligence y análisis de crédito con prosa corporativa de alto nivel: fluida, "
                "precisa y orientada a la toma de decisiones. Para empresas privadas sin precio "
                "de mercado, reemplazas el DCF tradicional con análisis de tendencias históricas "
                "y benchmarks sectoriales. Nunca inventas datos; cuando un dato falta, lo omites "
                "o lo señalas explícitamente."
            ),
            messages=[{"role": "user", "content": user_prompt}],
        )
        usage = msg.usage
        logger.info(
            "report_generator tokens | input: %d | output: %d | total: %d | cost_usd: ~$%.4f",
            usage.input_tokens,
            usage.output_tokens,
            usage.input_tokens + usage.output_tokens,
            (usage.input_tokens * 3 + usage.output_tokens * 15) / 1_000_000,
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

    # Body — strip markdown before rendering (multi_cell is plain text only)
    report_text = _strip_markdown(report_text)

    # Helvetica is Latin-1 only — replace common Unicode chars before rendering
    _LATIN1_MAP = {
        "\u2014": "--",   # em dash
        "\u2013": "-",    # en dash
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u2026": "...",  # ellipsis
        "\u2022": "*",    # bullet
        "\u2192": "->",   # right arrow
    }
    safe_text = report_text
    for _ch, _rep in _LATIN1_MAP.items():
        safe_text = safe_text.replace(_ch, _rep)
    safe_text = safe_text.encode("latin-1", errors="replace").decode("latin-1")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, safe_text)

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
