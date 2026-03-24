"""
LATAM Human Validation Gate — Phase 10
Renders a Streamlit form panel to intercept extraction results before Parquet write.
Analyst reviews and corrects financial values in miles de millones (local currency);
only confirmed data is written to disk.

Module-level imports: stdlib + streamlit only.
latam_processor is imported lazily inside _handle_confirm() to keep S&P 500 section safe.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

import streamlit as st

# Scale factor: form shows values in miles de millones (10^9) for readability
_MMM = 1_000_000_000

# ── Confidence badge color map ─────────────────────────────────────────────────
_COLOR_MAP = {
    "Alta": "green",
    "Media": "orange",
    "Baja": "red",
}
_BADGE_MARKDOWN = {
    "Alta": ":green-badge[Alta]",
    "Media": ":orange-badge[Media]",
    "Baja": ":red-badge[Baja]",
}

# All validated fields (Spanish display names) — full set for complete KPI coverage
_FIELDS = [
    # Estado de Resultados
    "ingresos", "utilidad_bruta", "cogs", "ingreso_operacional", "utilidad_neta",
    "depreciacion_amortizacion",
    # Balance General
    "total_activos", "pasivos_totales", "patrimonio",
    "activos_corrientes", "pasivos_corrientes", "deuda_total",
    # Capital de Trabajo
    "efectivo", "cartera", "inventarios", "cuentas_por_pagar",
]

# Human-readable labels for the form
_FIELD_LABELS = {
    "ingresos":                  "Ingresos",
    "utilidad_bruta":            "Utilidad Bruta",
    "cogs":                      "Costo de Ventas/Servicios",
    "ingreso_operacional":       "Utilidad Operacional (EBIT)",
    "utilidad_neta":             "Utilidad Neta",
    "depreciacion_amortizacion": "Depreciación y Amortización",
    "total_activos":             "Total Activos",
    "pasivos_totales":           "Total Pasivos",
    "patrimonio":                "Patrimonio",
    "activos_corrientes":        "Activos Corrientes",
    "pasivos_corrientes":        "Pasivos Corrientes",
    "deuda_total":               "Deuda LP",
    "efectivo":                  "Efectivo y Equivalentes",
    "cartera":                   "Cartera / Cuentas por Cobrar",
    "inventarios":               "Inventarios",
    "cuentas_por_pagar":         "Cuentas por Pagar",
}

# Mapping from Spanish display names → latam_processor canonical English field names
_DISPLAY_TO_CANONICAL = {
    "ingresos":                  "revenue",
    "utilidad_bruta":            "gross_profit",
    "cogs":                      "cogs",
    "ingreso_operacional":       "operating_income",
    "utilidad_neta":             "net_income",
    "depreciacion_amortizacion": "depreciation_amortization",
    "total_activos":             "total_assets",
    "pasivos_totales":           "total_liabilities",
    "patrimonio":                "total_equity",
    "activos_corrientes":        "current_assets",
    "pasivos_corrientes":        "current_liabilities",
    "deuda_total":               "long_term_debt",
    "efectivo":                  "cash",
    "cartera":                   "receivables",
    "inventarios":               "inventory",
    "cuentas_por_pagar":         "accounts_payable",
}

# Keys in the session state dict that are metadata, not financial values
_META_KEYS = (
    {"extracted_at", "pdf_path", "currency_code", "fiscal_year",
     "extraction_method", "confidence"}
    | {f"confidence_{f}" for f in _FIELDS}
    | {f"source_page_{f}" for f in _FIELDS}
)

# Form layout: 3 sections × 2 columns for organised data entry
_SECTION_FIELDS = {
    "Estado de Resultados": {
        "left":  ["ingresos", "ingreso_operacional", "utilidad_neta"],
        "right": ["utilidad_bruta", "cogs", "depreciacion_amortizacion"],
    },
    "Balance General": {
        "left":  ["total_activos", "pasivos_totales", "patrimonio"],
        "right": ["activos_corrientes", "pasivos_corrientes", "deuda_total"],
    },
    "Capital de Trabajo": {
        "left":  ["efectivo", "cartera"],
        "right": ["inventarios", "cuentas_por_pagar"],
    },
}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _render_confidence_badge(confidence: str | None) -> None:
    label = confidence if confidence in _COLOR_MAP else None
    try:
        if label:
            st.badge(label=label, color=_COLOR_MAP[label])
        else:
            st.badge(label="Desconocida", color="gray")
    except AttributeError:
        md = _BADGE_MARKDOWN.get(confidence or "", ":gray-badge[Desconocida]")
        st.markdown(md)


def _advance_backfill_queue(slug: str) -> None:
    """Pop the first year from the backfill queue for slug (called after confirm/discard)."""
    queue = st.session_state.get("latam_backfill_queue", {}).get(slug, [])
    if queue:
        st.session_state["latam_backfill_queue"][slug] = queue[1:]


def _handle_discard() -> None:
    _company = st.session_state.get("latam_pending_company", {})
    _slug = _company.get("slug", "") if isinstance(_company, dict) else str(_company)
    if _slug:
        _advance_backfill_queue(_slug)
    for key in ("latam_pending_extraction", "latam_pending_company"):
        if key in st.session_state:
            del st.session_state[key]
    st.session_state["latam_show_rerun"] = True
    st.rerun()


def _handle_confirm(
    extraction_result: dict,
    company: dict,
    corrected_values: dict,  # {display_name: float in miles de millones}
) -> None:
    """
    Validate and write confirmed values (all fields) to Parquet + meta.json.

    Baja guard: only blocks fields where the original extraction found a NON-ZERO
    value that the analyst hasn't edited. Fields extracted as 0 (empty OCR) can be
    confirmed at any value — including 0 for genuinely zero fields (e.g. zero debt).
    """
    # ── Baja-confidence guard ─────────────────────────────────────────────────
    baja_unedited = []
    for field in _FIELDS:
        if extraction_result.get(f"confidence_{field}") == "Baja":
            original_raw = float(extraction_result.get(field) or 0.0)
            original_mmm = original_raw / _MMM
            # Only block if original was non-zero AND user left it unchanged
            if original_mmm != 0.0 and abs(corrected_values[field] - original_mmm) < 0.0005:
                baja_unedited.append(field)

    if baja_unedited:
        labels = [_FIELD_LABELS.get(f, f) for f in baja_unedited]
        st.error(f"Corrija los valores con confianza Baja antes de confirmar: {', '.join(labels)}")
        return

    # ── Original values in mmm for audit trail ────────────────────────────────
    original_mmm = {f: float(extraction_result.get(f) or 0.0) / _MMM for f in _FIELDS}

    # ── Capture navigation state BEFORE clearing session ─────────────────────
    slug = company.get("slug", "")
    country = company.get("country", "")

    # ── Atomic disk write ─────────────────────────────────────────────────────
    try:
        try:
            import latam_processor
            from latam_extractor import ExtractionResult
        except ImportError as imp_err:
            st.error(f"Error de importacion LATAM: {imp_err}")
            return

        # Build canonical fields: pass through any existing numeric fields from
        # extraction, then apply all corrected values (scaled back from mmm → full units)
        fields: dict = {
            k: v for k, v in extraction_result.items()
            if k not in _META_KEYS and isinstance(v, (int, float))
        }
        for display_name, canonical in _DISPLAY_TO_CANONICAL.items():
            fields[canonical] = corrected_values[display_name] * _MMM

        er = ExtractionResult(
            fields=fields,
            source_map={},
            confidence=extraction_result.get("confidence", "Baja"),
            currency_code=extraction_result.get("currency_code", "COP"),
            fiscal_year=int(extraction_result.get("fiscal_year") or 0),
            extraction_method=extraction_result.get("extraction_method", "unknown"),
        )
        proc_result = latam_processor.process(slug, er, country)
        write_meta_json(slug, country, extraction_result, corrected_values, original_mmm, proc_result)
        st.cache_data.clear()

        # Reload parquet caches into session state so charts refresh immediately.
        # _auto_load_existing_latam() skips already-loaded slugs, so we reload here.
        from pathlib import Path as _Path
        import pandas as _pd
        _sp = _Path("data") / "latam" / country / slug
        if (_sp / "financials.parquet").exists():
            st.session_state.setdefault("latam_financials", {})[slug] = _pd.read_parquet(_sp / "financials.parquet")
        if (_sp / "kpis.parquet").exists():
            st.session_state.setdefault("latam_kpis", {})[slug] = _pd.read_parquet(_sp / "kpis.parquet")

        st.session_state["active_latam_company"] = {"slug": slug, "country": country}
        _advance_backfill_queue(slug)
        for key in ("latam_pending_extraction", "latam_pending_company"):
            if key in st.session_state:
                del st.session_state[key]

        st.success("Datos guardados correctamente.")
        st.rerun()

    except Exception as exc:
        st.error(f"Error al guardar: {exc}")


# ── Public API ─────────────────────────────────────────────────────────────────

def write_meta_json(
    company_slug: str,
    country: str,
    extraction_result: dict,
    corrected_mmm: dict,   # {display_name: float in mmm}
    original_mmm: dict,    # {display_name: float in mmm}
    processor_result: dict | None = None,
) -> None:
    """Write meta.json with extraction provenance and human-validation audit trail.

    Merges with existing meta.json so that fields written by LatamAgent (name, url,
    currency_original, fx_rate_usd, etc.) are preserved. Overwrites only the fields
    that the validation session knows: confidence, fiscal_year(s), human_validated.
    """
    storage_path = Path("data") / "latam" / country / company_slug
    storage_path.mkdir(parents=True, exist_ok=True)
    meta_path = storage_path / "meta.json"

    # Load existing meta as base — preserves name, url, fx_rate_usd, etc.
    _existing_meta: dict = {}
    try:
        if meta_path.exists():
            _existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    human_validated_fields: dict = {
        field: {
            "original_mmm": original_mmm.get(field),
            "corrected_mmm": corrected_mmm.get(field),
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }
        for field in _FIELDS
        if abs((corrected_mmm.get(field) or 0.0) - (original_mmm.get(field) or 0.0)) > 0.0005
    }

    _pr = processor_result or {}
    # Start from existing meta so nothing is lost; then update validation fields
    meta = dict(_existing_meta)
    meta.update({
        "company_slug": company_slug,
        "country": country,
        "currency_original": (
            extraction_result.get("currency_code")
            or _existing_meta.get("currency_original")
        ),
        "fiscal_year": _pr.get("fiscal_year") or _existing_meta.get("fiscal_year"),
        "fiscal_years": _pr.get("fiscal_years") or _existing_meta.get("fiscal_years", []),
        "confidence": _pr.get("confidence") or extraction_result.get("confidence") or _existing_meta.get("confidence"),
        "extraction_method": extraction_result.get("extraction_method") or _existing_meta.get("extraction_method"),
        "extraction_timestamp": extraction_result.get("extracted_at") or _existing_meta.get("extraction_timestamp"),
        "pdf_path": extraction_result.get("pdf_path") or _existing_meta.get("pdf_path"),
        "confidence_scores": {f: extraction_result.get(f"confidence_{f}") for f in _FIELDS},
        "source_pages": {f: extraction_result.get(f"source_page_{f}") for f in _FIELDS},
        "human_validated": bool(human_validated_fields),
        "human_validated_fields": human_validated_fields,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    })

    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _extraction_result_to_dict(er) -> dict:
    """Convert an ExtractionResult dataclass to the flat dict expected by this panel."""
    canonical_to_display = {v: k for k, v in _DISPLAY_TO_CANONICAL.items()}
    fields = getattr(er, "fields", {})
    source_map = getattr(er, "source_map", {})
    confidence = getattr(er, "confidence", None)
    d: dict = {
        "fiscal_year": getattr(er, "fiscal_year", None),
        "currency_code": getattr(er, "currency_code", None),
        "extraction_method": getattr(er, "extraction_method", None),
        "confidence": confidence,
    }
    for canonical, display in canonical_to_display.items():
        d[display] = fields.get(canonical)
        d[f"confidence_{display}"] = confidence
        src = source_map.get(canonical)
        d[f"source_page_{display}"] = getattr(src, "page_number", None) if src else None
    return d


def render_latam_validation_panel(extraction_result, company: dict) -> None:
    """
    Render the LATAM extraction validation form.

    Values are shown and entered in miles de millones (÷10^9) for readability.
    Pre-populates from existing parquet data for fields that were not extracted
    (so re-processing a year doesn't lose previously confirmed values).
    """
    if not isinstance(extraction_result, dict):
        extraction_result = _extraction_result_to_dict(extraction_result)

    currency = extraction_result.get("currency_code") or "COP"
    fiscal_year = extraction_result.get("fiscal_year")
    year_label = f" — {int(fiscal_year)}" if fiscal_year else ""

    # Pre-populate from existing parquet for fields not extracted (value = 0/None)
    _existing_raw: dict = {}
    try:
        import pandas as _pd
        _par_path = (
            Path("data") / "latam"
            / company.get("country", "")
            / company.get("slug", "")
            / "financials.parquet"
        )
        if _par_path.exists() and fiscal_year:
            _df = _pd.read_parquet(_par_path, engine="pyarrow")
            _row = _df[_df["fiscal_year"] == int(fiscal_year)]
            if not _row.empty:
                for _display, _canonical in _DISPLAY_TO_CANONICAL.items():
                    if _canonical in _row.columns:
                        _v = _row[_canonical].iloc[0]
                        if not _pd.isna(_v):
                            _existing_raw[_display] = float(_v)
    except Exception:
        pass

    def _default_mmm(field: str) -> float:
        """Default value in miles de millones: extracted value first, parquet fallback."""
        raw = float(extraction_result.get(field) or 0.0)
        if raw == 0.0 and field in _existing_raw:
            raw = _existing_raw[field]
        return round(raw / _MMM, 3)

    with st.form(key="latam_validation_form"):
        st.subheader(f"Validación de Extracción{year_label}")
        st.caption(
            f"Ingrese los valores en **miles de millones de {currency}** "
            f"(ej: 101.305 = 101.305 miles de millones). "
            "Solo se guarda al confirmar."
        )

        corrected_values: dict = {}

        for section_name, cols_def in _SECTION_FIELDS.items():
            st.markdown(f"**{section_name}**")
            col_left, col_right = st.columns(2)
            for field, col in (
                [(f, col_left)  for f in cols_def["left"]] +
                [(f, col_right) for f in cols_def["right"]]
            ):
                with col:
                    val = _default_mmm(field)
                    entered = st.number_input(
                        label=f"{_FIELD_LABELS[field]} (miles de mill., {currency})",
                        value=val,
                        step=0.001,
                        format="%.3f",
                        min_value=None,
                        key=f"latam_val_{field}",
                        help=(
                            f"Fuente: pag. {extraction_result.get(f'source_page_{field}', '?')} | "
                            f"Confianza: {extraction_result.get(f'confidence_{field}', 'N/A')}"
                        ),
                    )
                    corrected_values[field] = entered
                    _render_confidence_badge(extraction_result.get(f"confidence_{field}"))
                    extracted_raw = float(extraction_result.get(field) or 0.0)
                    if extraction_result.get(f"confidence_{field}") == "Baja":
                        if extracted_raw == 0.0:
                            st.warning("Sin extracción automática — ingrese el valor.")
                        else:
                            st.warning("Confianza Baja — verifique y corrija si es necesario.")
            st.divider()

        col_confirm, col_discard = st.columns([1, 1])
        with col_confirm:
            confirmed = st.form_submit_button(
                "Confirmar y guardar",
                type="primary",
                use_container_width=True,
            )
        with col_discard:
            discarded = st.form_submit_button(
                "Descartar",
                type="secondary",
                use_container_width=True,
            )

    if confirmed:
        _handle_confirm(extraction_result, company, corrected_values)
    elif discarded:
        _handle_discard()
