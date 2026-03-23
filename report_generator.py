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
    """Extract intro, conclusions, glosas and cartera sections from a T2 management report PDF.

    Strategy:
    1. Classify each page: TOC (dot_ratio > 0.12) vs content
    2. Search for 4 labelled sections using keyword lists:
       - Intro/Presentacion  → fallback: first 2 content pages
       - Conclusiones/Cierre → fallback: last 2 content pages
       - Glosas/Objeciones   → extracted only when found (no fallback)
       - Cartera/CxC         → extracted only when found (no fallback)
    3. Label blocks and cap total at 3600 chars:
       Intro 1200 | Conclusiones 800 | Glosas 800 | Cartera 800

    Never raises — returns "" on any failure.
    """
    _INTRO_KEYS  = ("introduccion", "introducción", "presentacion", "presentación", "carta al lector")
    _CONCL_KEYS  = ("conclusion", "conclusiones", "conclusión", "cierre", "perspectivas",
                    "balance general", "reflexiones", "resumen ejecutivo")
    _GLOSA_KEYS  = ("glosa", "glosas", "objetada", "objeciones", "cuentas objetadas",
                    "recobro", "glosado", "glosadas")
    _CARTERA_KEYS = ("cartera", "cuentas por cobrar", "composicion de cartera",
                     "cartera por eps", "rotacion de cartera", "aging", "antiguedad de cartera",
                     "deudores")

    try:
        import pdfplumber

        pages_text: list[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                pages_text.append(page.extract_text() or "")

        n = len(pages_text)
        if not n:
            return ""

        def _is_toc(text: str) -> bool:
            return len(text) > 0 and text.count(".") / len(text) > 0.12

        def _header_matches(text: str, keys: tuple) -> bool:
            for line in text.lower().split("\n")[:8]:
                stripped = line.strip().lstrip("0123456789. ")
                if any(stripped.startswith(k) for k in keys):
                    return True
            return False

        def _body_mentions(text: str, keys: tuple) -> bool:
            """Check if any key appears anywhere in the page body."""
            low = text.lower()
            return any(k in low for k in keys)

        content_pages = [(i, t) for i, t in enumerate(pages_text) if t.strip() and not _is_toc(t)]

        def _find_section(keys, fallback_idxs=None, check_body=False):
            """Return page indices for the first matching section."""
            for i, text in content_pages:
                matched = _header_matches(text, keys) or (check_body and _body_mentions(text, keys))
                if matched:
                    next_content = next((j for j, _ in content_pages if j > i), i)
                    return [i, next_content] if next_content != i else [i]
            return fallback_idxs or []

        intro_idxs = _find_section(_INTRO_KEYS, fallback_idxs=[idx for idx, _ in content_pages[:2]])
        concl_idxs = _find_section(_CONCL_KEYS, fallback_idxs=[idx for idx, _ in content_pages[-2:]])
        glosa_idxs = _find_section(_GLOSA_KEYS, check_body=True)
        cartera_idxs = _find_section(_CARTERA_KEYS, check_body=True)

        def _join(idxs, char_limit):
            text = "\n\n".join(pages_text[i] for i in idxs if i < n).strip()
            return text[:char_limit]

        parts = []
        if intro_idxs:
            parts.append(f"[INTRODUCCION]\n{_join(intro_idxs, 1200)}")
        if concl_idxs and concl_idxs != intro_idxs:
            parts.append(f"[CONCLUSIONES/CIERRE]\n{_join(concl_idxs, 800)}")
        if glosa_idxs:
            parts.append(f"[GLOSAS/OBJECIONES]\n{_join(glosa_idxs, 800)}")
        if cartera_idxs and cartera_idxs not in (intro_idxs, concl_idxs):
            parts.append(f"[CARTERA/CUENTAS POR COBRAR]\n{_join(cartera_idxs, 800)}")

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
# compute_factoring_context
# ---------------------------------------------------------------------------

def compute_factoring_context(kpis_df, financials_df) -> dict:
    """Pre-compute factoring-eligibility metrics for Section 3 prompt injection.

    Computes DSO zone, CCC trend, WC gap projection (Option B), leverage zones,
    factoring-eligible AR estimate, and a pre-computed rating suggestion.
    Never raises — returns {} on any failure.
    """
    try:
        import math
        import pandas as pd

        if kpis_df.empty or financials_df.empty:
            return {}

        kpis = kpis_df.sort_values("fiscal_year")
        fin = financials_df.sort_values("fiscal_year")
        lk = kpis.iloc[-1]
        lf = fin.iloc[-1]

        def _v(row, key):
            val = row.get(key)
            return None if (val is None or (isinstance(val, float) and math.isnan(val))) else float(val)

        # DSO zone
        dso = _v(lk, "dso")
        if dso is not None:
            dso_zone = (
                "Excelente — por debajo del rango LATAM (menor de 90 dias)" if dso < 90
                else "Bueno — limite inferior del rango LATAM (90-120 dias)" if dso <= 120
                else "Rango Estandar LATAM — zona objetivo SalFi (120-210 dias)" if dso <= 210
                else "Cartera en Riesgo Critico — fuera del rango LATAM (mayor de 210 dias)"
            )
        else:
            dso_zone = "N/D"

        # CCC trend (last 2 years)
        ccc_latest = _v(lk, "cash_conversion_cycle")
        ccc_trend = "N/D"
        if "cash_conversion_cycle" in kpis.columns:
            ccc_vals = kpis["cash_conversion_cycle"].dropna()
            if len(ccc_vals) >= 2:
                delta = float(ccc_vals.iloc[-1]) - float(ccc_vals.iloc[-2])
                ccc_trend = "estable" if abs(delta) < 5 else ("creciente" if delta > 0 else "decreciente")

        # Revenue and receivables (latest year, in local currency)
        revenue = _v(lf, "revenue") or 0.0
        receivables = _v(lf, "receivables") or 0.0

        # Average revenue growth from historical series
        avg_growth = 0.10
        if "revenue_growth_yoy" in kpis.columns:
            g_vals = kpis["revenue_growth_yoy"].dropna()
            if len(g_vals) > 0:
                avg_growth = max(-0.10, min(float(g_vals.mean()), 0.40))

        # WC gap projection (Option B):
        # If DSO holds and revenue grows at avg_growth, incremental WC need = delta in receivables
        projected_revenue = None
        wc_gap = None
        if dso is not None and revenue > 0:
            projected_revenue = revenue * (1 + avg_growth)
            wc_gap = (dso / 365) * projected_revenue - receivables

        # Factoring eligible estimate (~70% of AR as >60d aging proxy)
        factoring_eligible = receivables * 0.70 if receivables > 0 else None

        # D/EBITDA zone
        debt_ebitda = _v(lk, "debt_to_ebitda")
        if debt_ebitda is not None:
            debt_ebitda_zone = (
                "Saludable (menor de 3.5x)" if debt_ebitda < 3.5
                else "Vigilancia (3.5-5x)" if debt_ebitda < 5
                else "Estres Financiero / Posible Zombie (mayor de 5x)"
            )
        else:
            debt_ebitda_zone = "N/D"

        # Net debt
        net_debt = (
            (_v(lf, "long_term_debt") or 0)
            + (_v(lf, "short_term_debt") or 0)
            - (_v(lf, "cash") or 0)
        )

        debt_equity = _v(lk, "debt_to_equity")
        current_ratio = _v(lk, "current_ratio")
        ebitda_margin = _v(lk, "ebitda_margin")

        # Pre-computed factoring rating suggestion
        factoring_rating = None
        if dso is not None and debt_ebitda is not None and ebitda_margin is not None:
            if dso > 150 and debt_ebitda < 3.5 and ebitda_margin > 0.08:
                factoring_rating = "CANDIDATO PRIORITARIO"
            elif dso > 150 and (debt_ebitda > 5 or ebitda_margin < 0.05):
                factoring_rating = "CANDIDATO CON RESTRICCIONES"
            elif debt_ebitda > 5 and ebitda_margin <= 0:
                factoring_rating = "NO RECOMENDADO"
        if factoring_rating is None and dso is not None and debt_ebitda is not None:
            if 120 <= dso <= 150 or (3.5 <= debt_ebitda < 5):
                factoring_rating = "CANDIDATO MODERADO"

        def _mmm(v):
            return round(v / 1e9, 1) if v is not None else None

        return {
            "dso_days": round(dso, 1) if dso is not None else None,
            "dso_zone": dso_zone,
            "ccc_days": round(ccc_latest, 1) if ccc_latest is not None else None,
            "ccc_trend": ccc_trend,
            "current_ratio": round(current_ratio, 2) if current_ratio is not None else None,
            "revenue_mmm": _mmm(revenue),
            "receivables_mmm": _mmm(receivables),
            "avg_growth_pct": round(avg_growth * 100, 1),
            "projected_revenue_mmm": _mmm(projected_revenue),
            "wc_gap_mmm": _mmm(wc_gap),
            "factoring_eligible_mmm": _mmm(factoring_eligible),
            "debt_ebitda": round(debt_ebitda, 2) if debt_ebitda is not None else None,
            "debt_ebitda_zone": debt_ebitda_zone,
            "debt_equity": round(debt_equity, 2) if debt_equity is not None else None,
            "net_debt_mmm": _mmm(net_debt),
            "ebitda_margin_pct": round(ebitda_margin * 100, 1) if ebitda_margin is not None else None,
            "factoring_rating": factoring_rating,
        }
    except Exception as exc:
        logger.warning("compute_factoring_context failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# generate_executive_report
# ---------------------------------------------------------------------------

def generate_executive_report(
    kpis: dict,
    red_flags: list,
    comparables: list,
    company: dict,
    management_narrative: str = "",
    factoring_context: dict = None,
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

        # Factoring context block for Section 3
        fc = factoring_context or {}
        fc_block = ""
        if fc:
            def _fmt(v, unit="", dec=1):
                return f"{v:.{dec}f}{unit}" if v is not None else "N/D"

            fc_block = (
                f"\nCONTEXTO PRECOMPUTADO PARA SECCION 3 (usa estos valores, no los recalcules):\n"
                f"DSO actual: {_fmt(fc.get('dso_days'), ' dias', 0)} — {fc.get('dso_zone', 'N/D')}\n"
                f"Ciclo de Conversion de Caja: {_fmt(fc.get('ccc_days'), ' dias', 0)} (tendencia: {fc.get('ccc_trend', 'N/D')})\n"
                f"Razon corriente: {_fmt(fc.get('current_ratio'), '', 2)}\n"
                f"Deuda/EBITDA: {_fmt(fc.get('debt_ebitda'), 'x', 2)} — {fc.get('debt_ebitda_zone', 'N/D')}\n"
                f"Deuda/Patrimonio: {_fmt(fc.get('debt_equity'), 'x', 2)}\n"
                f"Deuda neta: {_fmt(fc.get('net_debt_mmm'), ' mil millones COP')}\n"
                f"Ingresos actuales: {_fmt(fc.get('revenue_mmm'), ' mil millones COP')}\n"
                f"Cartera (cuentas por cobrar): {_fmt(fc.get('receivables_mmm'), ' mil millones COP')}\n"
                f"Crecimiento promedio historico de ingresos: {_fmt(fc.get('avg_growth_pct'), '%')}\n"
                f"Ingresos proyectados proximo ejercicio: {_fmt(fc.get('projected_revenue_mmm'), ' mil millones COP')}\n"
                f"Brecha proyectada de capital de trabajo: {_fmt(fc.get('wc_gap_mmm'), ' mil millones COP')}\n"
                f"Cartera elegible estimada para factoring (~70% AR): {_fmt(fc.get('factoring_eligible_mmm'), ' mil millones COP')}\n"
                f"EBITDA margin actual: {_fmt(fc.get('ebitda_margin_pct'), '%')}\n"
            )
            if fc.get("factoring_rating"):
                fc_block += f"Calificacion sugerida por algoritmo: {fc['factoring_rating']}\n"
            fc_block += "(Nota: Aging >120d y Glosa Rate no disponibles — menciona esta limitacion en el reporte)\n"

        # Section 1 instruction depends on whether T2 is available
        sec1_instruction = (
            "Fuente PRIMARIA: el INFORME DE GESTION (T2) incluido arriba. "
            "2 parrafos en tono corporativo impecable. "
            "Parrafo 1: narrativa sobre el desempeno operativo del periodo — que hizo la empresa, "
            "como evoluciono su actividad clinica y comercial, logros y desafios declarados. "
            "Parrafo 2: conclusion ejecutiva sobre la posicion del negocio y perspectiva estrategica. "
            "PROHIBIDO: no interpretes ratios ni KPIs individuales — eso es exclusivo de Section 2. "
            "Puedes mencionar como maximo 1 cifra de contexto (ej. crecimiento de ingresos) "
            "pero sin analisis de indicadores."
            if management_narrative else
            "2 parrafos en tono corporativo impecable. "
            "Parrafo 1: perfil del prestador, su posicion en el mercado y desempeno general del periodo. "
            "Parrafo 2: conclusion ejecutiva sobre la salud financiera del negocio y los principales "
            "retos estrategicos que enfrenta. "
            "PROHIBIDO: no interpretes ratios ni KPIs individuales — eso es exclusivo de Section 2. "
            "Menciona como maximo 1 cifra de contexto sin analisis de indicadores."
        )

        user_prompt = (
            f"Genera un reporte ejecutivo de análisis financiero para:\n"
            f"Empresa: {company['name']}\n"
            f"País: {company['country']} | Año fiscal: {company['fiscal_year']} | {fx_note}\n"
            f"{t2_block}\n"
            f"DATOS FINANCIEROS:\n"
            f"KPIs año principal ({currency}): {json.dumps(kpis_clean, ensure_ascii=False, separators=(',', ':'))}\n"
            f"Red Flags detectadas: {json.dumps(red_flags, ensure_ascii=False, separators=(',', ':'))}\n"
            f"Contexto sectorial (búsqueda web): {comparables}\n"
            f"{scenario_block}\n"
            f"{fc_block}\n"
            f"ESTRUCTURA REQUERIDA — exactamente 3 secciones en español corporativo impecable. "
            f"Las 3 secciones son OBLIGATORIAS; no omitas ninguna bajo ningun concepto.\n\n"
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
            f"## 3. Insights — Liquidez, Apalancamiento y Oportunidad de Factoring\n"
            f"ESTA SECCION ES OBLIGATORIA Y DEBE GENERARSE COMPLETA. "
            f"Narrativa continua sin bullets, sin numeracion, sin subtitulos internos. "
            f"Prosa corporativa densa, voz activa, gramatica impecable, nivel CEO/CFO/inversor. "
            f"Usa los datos del CONTEXTO PRECOMPUTADO inyectados arriba. "
            f"La narrativa debe cubrir organicamente los siguientes tres momentos:\n"
            f"PRIMERO — Diagnostico de liquidez estructural: analiza DSO, Ciclo de Conversion "
            f"de Caja y razon corriente. Determina si el prestador esta financiando a las "
            f"EPS/aseguradoras a expensas de su propia operacion y si la liquidez atrapada en "
            f"cartera es el principal driver de riesgo operativo.\n"
            f"SEGUNDO — Diagnostico de apalancamiento: analiza Deuda/EBITDA, Deuda/Patrimonio "
            f"y deuda neta. Evalua si la estructura de deuda actual deja margen para absorber "
            f"el costo de un instrumento de factoring adicional, o si el prestador esta en zona "
            f"de vigilancia (D/EBITDA 3.5-5x) o estres financiero (D/EBITDA mayor de 5x).\n"
            f"TERCERO — Proyeccion de necesidad de liquidez y calificacion de factoring: "
            f"usa la brecha proyectada de capital de trabajo y la cartera elegible estimada "
            f"para cuantificar la oportunidad. Evalua la viabilidad de un esquema de factoring "
            f"de cartera EPS considerando el margen EBITDA disponible para absorber el costo "
            f"del instrumento y el vinculo con buenos desenlaces clinicos como condicion de "
            f"elegibilidad. Si Aging mayor de 120 dias y Glosa Rate no estan disponibles, "
            f"menciona esta limitacion explicitamente. "
            f"Concluye con la calificacion explicita en mayusculas: "
            f"CANDIDATO PRIORITARIO (DSO mayor de 150d, D/EBITDA menor de 3.5x, EBITDA mayor de 8%), "
            f"CANDIDATO MODERADO (DSO 120-150d o D/EBITDA 3.5-5x con margen positivo), "
            f"CANDIDATO CON RESTRICCIONES (DSO mayor de 150d pero D/EBITDA mayor de 5x o margen menor de 5%), "
            f"o NO RECOMENDADO (D/EBITDA mayor de 5x con margen negativo), "
            f"seguida de 1-2 lineas de justificacion. "
            f"Cierra con postura integrada: Favorable / Neutral / Precaucion con la condicion "
            f"especifica que podria modificarla.\n"
            f"No repitas cifras ya presentes en la seccion 2 salvo las criticas para el argumento.\n\n"
            f"REGLAS GENERALES:\n"
            f"- No inventes valores; si un dato falta, omitelo o indica 'N/D'\n"
            f"- Solo guion simple (-), nunca doble guion ni em-dash\n"
            f"- Espanol corporativo impecable, gramatica perfecta, sin anglicismos innecesarios\n"
            f"- Exactamente 3 secciones; ninguna puede omitirse"
        )

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=(
                "Eres un analista financiero senior especializado en banca de inversion, "
                "due diligence y estructuracion de instrumentos de credito para el sector salud "
                "de Colombia y Latinoamerica. Tus reportes son leidos por CEOs, CFOs, "
                "inversionistas y juntas directivas de IPS privadas; el lenguaje debe ser "
                "impecablemente corporativo: gramatica perfecta, prosa densa y precisa, sin "
                "coloquialismos, sin anglicismos innecesarios, sin redundancias. Cada afirmacion "
                "debe estar sustentada en datos o en contexto sectorial verificable. "
                "Sigues la metodologia del Financial Analysis Skill con enfasis en liquidez "
                "estructural y apalancamiento para evaluar la elegibilidad de instrumentos de "
                "factoring de cartera EPS.\n\n"
                "BENCHMARKS SECTOR SALUD LATAM — IPS privadas (Referencia Gemini):\n"
                "- CAGR ingresos (5 anos): 8-12% | Crecimiento YoY: 10-15%\n"
                "- Margen bruto: 35-48% (alto costo de insumos medicos y dispositivos)\n"
                "- Margen operativo (EBIT): 10-18% (sensible a eficiencia administrativa)\n"
                "- Margen neto: 4-8% (impactado por costo financiero de la deuda)\n"
                "- ROE: 12-18% | ROA: 6-10%\n"
                "- Razon corriente: 1.1-1.4x (inflada por cartera de dificil recaudo)\n"
                "- Razon rapida: 0.8-1.1x (excluye inventarios; revela dependencia del FCO)\n"
                "- Capital de trabajo / Ingresos: 15-25%\n"
                "- Deuda/Patrimonio: 0.8-1.5x (prestadores al limite de capacidad crediticia)\n"
                "- Deuda/Activos: 45-65%\n"
                "- Cobertura de intereses (EBIT/Int): 2.5-4.0x (<2.0x = riesgo de default)\n"
                "- DSO: 120-210 dias (rango estandar LATAM; estandar global <60 dias; "
                  "pain point SalFi — toda IPS en este rango es candidata a factoring)\n"
                "- CCC positivo y creciente = prestador financiando EPS a expensas de su "
                  "propio capital de trabajo — senal critica de necesidad de factoring\n\n"
                "NOTA CRITICA — LIMITACION DE DATOS LATAM:\n"
                "Los PDFs de IPS LATAM no desglosan costos con suficiente granularidad para "
                "calcular margen bruto contable real (35-48%). El campo 'gross_profit_margin' "
                "extraido equivale funcionalmente al EBITDA operativo. En la tabla de Section 2, "
                "etiquetarlo como 'Margen Bruto / EBITDA (est.)' y compararlo contra el benchmark "
                "de margen operativo (10-18%), NO contra el de margen bruto (35-48%). "
                "Indicar esta limitacion con una nota breve en la tabla.\n\n"
                "CRITERIOS DE CALIFICACION FACTORING SALFI:\n"
                "- CANDIDATO PRIORITARIO: DSO >150d, Deuda/EBITDA <3.5x, EBITDA margin >8%\n"
                "- CANDIDATO MODERADO: DSO 120-150d con margen positivo, "
                  "o D/EBITDA 3.5-5x pero con margen EBITDA saludable\n"
                "- CANDIDATO CON RESTRICCIONES: DSO >150d pero D/EBITDA >5x, "
                  "o EBITDA margin <5%\n"
                "- NO RECOMENDADO: D/EBITDA >5x con margen EBITDA negativo o nulo\n\n"
                "Eres critico y objetivo: identificas fortalezas genuinas pero señalas con igual "
                "rigor las brechas y riesgos estructurales. "
                "Nunca inventas datos; cuando un dato falta, lo omites o lo señalas con 'N/D'."
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
