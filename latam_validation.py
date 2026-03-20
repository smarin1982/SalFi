"""
LATAM Human Validation Gate — Phase 10
Renders a Streamlit form panel to intercept extraction results before Parquet write.
Analyst can review and correct 4 key financial values; only confirmed data is written to disk.

Module-level imports: stdlib + streamlit only.
latam_processor is imported lazily inside _handle_confirm() to keep S&P 500 section safe.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

import streamlit as st

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

# Flat list of the 4 validated fields (used in multiple functions)
_FIELDS = ["ingresos", "utilidad_neta", "total_activos", "deuda_total"]

# Mapping from Spanish display names → latam_processor canonical English field names
_DISPLAY_TO_CANONICAL = {
    "ingresos": "revenue",
    "utilidad_neta": "net_income",
    "total_activos": "total_assets",
    "deuda_total": "long_term_debt",
}

# Keys in the session state dict that are metadata, not financial values
_META_KEYS = (
    {"extracted_at", "pdf_path", "currency_code", "fiscal_year",
     "extraction_method", "confidence"}
    | {f"confidence_{f}" for f in _FIELDS}
    | {f"source_page_{f}" for f in _FIELDS}
)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _render_confidence_badge(confidence: str | None) -> None:
    """
    Display a colored badge for Alta / Media / Baja confidence levels.
    Tries st.badge first (Streamlit >= 1.54.0); falls back to markdown badge syntax.
    Never uses unsafe_allow_html.
    """
    label = confidence if confidence in _COLOR_MAP else None
    try:
        # st.badge available since Streamlit 1.54.0
        if label:
            st.badge(label=label, color=_COLOR_MAP[label])
        else:
            st.badge(label="Desconocida", color="gray")
    except AttributeError:
        # Fallback: Streamlit markdown badge syntax (:green-badge[...])
        md = _BADGE_MARKDOWN.get(confidence or "", ":gray-badge[Desconocida]")
        st.markdown(md)


def _advance_backfill_queue(slug: str) -> None:
    """Pop the first year from the backfill queue for slug (called after confirm/discard)."""
    queue = st.session_state.get("latam_backfill_queue", {}).get(slug, [])
    if queue:
        st.session_state["latam_backfill_queue"][slug] = queue[1:]


def _handle_discard() -> None:
    """
    Clear all pending LATAM extraction state from session.
    Sets latam_show_rerun so app.py can render the re-run button.
    Does NOT show any st.info here — re-run block in app.py handles that.
    Calls st.rerun() to refresh the UI.
    """
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
    ingresos: float,
    utilidad_neta: float,
    total_activos: float,
    deuda_total: float,
) -> None:
    """
    Validate Baja-confidence fields, then write Parquet + meta.json atomically.

    Baja guard: if any Baja-confidence field still has its original extracted value
    (meaning the analyst did not edit it), abort with st.error and return immediately.
    This enforces the locked UX requirement without using disabled=True (Streamlit bug #8075).

    Session state is cleared ONLY after both Parquet and meta.json are written
    successfully — preserving the retry-safe invariant on exception.
    """
    corrected_map = {
        "ingresos": ingresos,
        "utilidad_neta": utilidad_neta,
        "total_activos": total_activos,
        "deuda_total": deuda_total,
    }

    # ── Baja-confidence guard (must run BEFORE any disk write) ────────────────
    baja_unedited = []
    for field in _FIELDS:
        if extraction_result.get(f"confidence_{field}") == "Baja":
            original = float(extraction_result.get(field) or 0.0)
            if corrected_map[field] == original:
                baja_unedited.append(field)

    if baja_unedited:
        st.error("Debe corregir los campos con confianza Baja antes de confirmar.")
        return

    # ── Build corrected and original value dicts ──────────────────────────────
    corrected_values = {
        "ingresos": ingresos,
        "utilidad_neta": utilidad_neta,
        "total_activos": total_activos,
        "deuda_total": deuda_total,
    }
    original_values = {
        field: float(extraction_result.get(field) or 0.0) for field in _FIELDS
    }

    # ── Capture navigation state BEFORE clearing session ─────────────────────
    slug = company.get("slug", "")
    country = company.get("country", "")

    # ── Atomic disk write (try/except — do NOT clear state on exception) ──────
    try:
        try:
            import latam_processor  # lazy import — S&P 500 section unaffected
            from latam_extractor import ExtractionResult  # noqa: PLC0415
        except ImportError as imp_err:
            st.error(f"Error de importacion LATAM: {imp_err}. Instale las dependencias LATAM.")
            return

        # Build canonical fields dict for ExtractionResult:
        # 1. Pass through any numeric canonical fields already in session state
        # 2. Apply the 4 corrected values mapped to English canonical names
        fields: dict = {
            k: v for k, v in extraction_result.items()
            if k not in _META_KEYS and isinstance(v, (int, float))
        }
        for display_name, canonical in _DISPLAY_TO_CANONICAL.items():
            fields[canonical] = corrected_values[display_name]

        er = ExtractionResult(
            fields=fields,
            source_map={},
            confidence=extraction_result.get("confidence", "Baja"),
            currency_code=extraction_result.get("currency_code", "USD"),
            fiscal_year=int(extraction_result.get("fiscal_year") or 0),
            extraction_method=extraction_result.get("extraction_method", "unknown"),
        )
        latam_processor.process(slug, er, country)
        write_meta_json(slug, country, extraction_result, corrected_values, original_values)
        st.cache_data.clear()

        # Reload parquet caches directly into session state so charts refresh on rerun.
        # _auto_load_existing_latam() skips already-loaded slugs, so we must update here.
        from pathlib import Path as _Path
        import pandas as _pd
        _sp = _Path("data") / "latam" / country / slug
        if (_sp / "financials.parquet").exists():
            st.session_state.setdefault("latam_financials", {})[slug] = _pd.read_parquet(_sp / "financials.parquet")
        if (_sp / "kpis.parquet").exists():
            st.session_state.setdefault("latam_kpis", {})[slug] = _pd.read_parquet(_sp / "kpis.parquet")

        # Navigation state — app.py reads this on next rerun to show success message
        st.session_state["active_latam_company"] = {"slug": slug, "country": country}

        # Advance backfill queue — year was held pending validation, now confirmed
        _advance_backfill_queue(slug)

        # Clear pending keys ONLY after successful write
        # Do NOT call _handle_discard() here — that sets latam_show_rerun, wrong after confirm
        for key in ("latam_pending_extraction", "latam_pending_company"):
            if key in st.session_state:
                del st.session_state[key]

        st.success("Datos guardados correctamente.")
        st.rerun()

    except Exception as exc:  # noqa: BLE001
        # CRITICAL: Do NOT clear session state here — let analyst retry
        st.error(f"Error al guardar: {exc}")


# ── Public API ─────────────────────────────────────────────────────────────────

def write_meta_json(
    company_slug: str,
    country: str,
    extraction_result: dict,
    corrected_values: dict,
    original_values: dict,
) -> None:
    """
    Write data/latam/{country}/{company_slug}/meta.json with extraction provenance
    and human-validation audit trail.

    human_validated is True if any field value was changed by the analyst.
    human_validated_fields records original, corrected, and validated_at for changed fields only.
    confirmed_at is the UTC timestamp of the confirmation action.
    """
    storage_path = Path("data") / "latam" / country / company_slug
    storage_path.mkdir(parents=True, exist_ok=True)

    # Build audit trail — only changed fields are recorded
    human_validated_fields: dict = {
        field: {
            "original": original_values.get(field),
            "corrected": corrected_values.get(field),
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }
        for field in _FIELDS
        if corrected_values.get(field) != original_values.get(field)
    }

    # Preserve currency_original from existing meta.json if present
    _existing_meta: dict = {}
    try:
        if meta_path.exists():
            _existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    meta = {
        "company_slug": company_slug,
        "country": country,
        "currency_original": (
            extraction_result.get("currency_code")
            or _existing_meta.get("currency_original")
        ),
        "extraction_timestamp": extraction_result.get("extracted_at"),
        "pdf_path": extraction_result.get("pdf_path"),
        "confidence_scores": {
            "ingresos": extraction_result.get("confidence_ingresos"),
            "utilidad_neta": extraction_result.get("confidence_utilidad_neta"),
            "total_activos": extraction_result.get("confidence_total_activos"),
            "deuda_total": extraction_result.get("confidence_deuda_total"),
        },
        "source_pages": {
            "ingresos": extraction_result.get("source_page_ingresos"),
            "utilidad_neta": extraction_result.get("source_page_utilidad_neta"),
            "total_activos": extraction_result.get("source_page_total_activos"),
            "deuda_total": extraction_result.get("source_page_deuda_total"),
        },
        "human_validated": bool(human_validated_fields),
        "human_validated_fields": human_validated_fields,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }

    meta_path = storage_path / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _extraction_result_to_dict(er) -> dict:
    """Convert an ExtractionResult dataclass to the flat dict expected by this panel.

    Maps canonical English field names to Spanish display names used by the form,
    and extracts per-field confidence and source-page metadata.
    """
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
    Render the LATAM extraction validation form panel.

    Uses st.form so field edits do not trigger reruns mid-editing — all edits are
    batched until a submit button is pressed (Streamlit form batching behavior).

    Layout: subheader + caption, then two columns with 2 fields each (left: ingresos,
    total_activos; right: utilidad_neta, deuda_total). Each field has a confidence badge,
    source caption, and a st.warning for Baja fields.

    Two submit buttons: "Confirmar y guardar" (primary) and "Descartar" (secondary).
    Neither uses disabled=True — enforcement handled in _handle_confirm() instead
    (Streamlit bug #8075 with disabled submit buttons).

    After the form block closes, confirmed/discarded booleans drive the handler calls.
    """
    # Accept ExtractionResult dataclass or legacy dict
    if not isinstance(extraction_result, dict):
        extraction_result = _extraction_result_to_dict(extraction_result)

    currency = extraction_result.get("currency_code") or "COP"

    fiscal_year = extraction_result.get("fiscal_year")
    year_label = f" — {int(fiscal_year)}" if fiscal_year else ""
    with st.form(key="latam_validation_form"):
        st.subheader(f"Validación de Extracción{year_label}")
        st.caption(
            "Revise los valores detectados. Corrija cualquier valor incorrecto antes de confirmar. "
            "Si cierra el navegador antes de confirmar, no se escribira ningun dato."
        )

        col_left, col_right = st.columns(2)

        # ── Left column: Ingresos + Total Activos ─────────────────────────────
        with col_left:
            ingresos = st.number_input(
                label=f"Ingresos ({currency})",
                value=float(extraction_result.get("ingresos") or 0.0),
                step=1_000_000.0,
                format="%.0f",
                min_value=0.0,
                key="latam_val_ingresos",
                help=(
                    f"Fuente: pag. {extraction_result.get('source_page_ingresos', '?')} | "
                    f"Confianza: {extraction_result.get('confidence_ingresos', 'N/A')}"
                ),
            )
            _render_confidence_badge(extraction_result.get("confidence_ingresos"))
            st.caption(f"Fuente: pagina {extraction_result.get('source_page_ingresos', '?')}")
            if extraction_result.get("confidence_ingresos") == "Baja":
                st.warning("Confianza Baja: verifique y corrija este valor antes de confirmar.")

            total_activos = st.number_input(
                label=f"Total Activos ({currency})",
                value=float(extraction_result.get("total_activos") or 0.0),
                step=1_000_000.0,
                format="%.0f",
                min_value=0.0,
                key="latam_val_total_activos",
                help=(
                    f"Fuente: pag. {extraction_result.get('source_page_total_activos', '?')} | "
                    f"Confianza: {extraction_result.get('confidence_total_activos', 'N/A')}"
                ),
            )
            _render_confidence_badge(extraction_result.get("confidence_total_activos"))
            st.caption(f"Fuente: pagina {extraction_result.get('source_page_total_activos', '?')}")
            if extraction_result.get("confidence_total_activos") == "Baja":
                st.warning("Confianza Baja: verifique y corrija este valor antes de confirmar.")

        # ── Right column: Utilidad Neta + Deuda Total ─────────────────────────
        with col_right:
            utilidad_neta = st.number_input(
                label=f"Utilidad Neta ({currency})",
                value=float(extraction_result.get("utilidad_neta") or 0.0),
                step=1_000_000.0,
                format="%.0f",
                min_value=0.0,
                key="latam_val_utilidad_neta",
                help=(
                    f"Fuente: pag. {extraction_result.get('source_page_utilidad_neta', '?')} | "
                    f"Confianza: {extraction_result.get('confidence_utilidad_neta', 'N/A')}"
                ),
            )
            _render_confidence_badge(extraction_result.get("confidence_utilidad_neta"))
            st.caption(f"Fuente: pagina {extraction_result.get('source_page_utilidad_neta', '?')}")
            if extraction_result.get("confidence_utilidad_neta") == "Baja":
                st.warning("Confianza Baja: verifique y corrija este valor antes de confirmar.")

            deuda_total = st.number_input(
                label=f"Deuda Total ({currency})",
                value=float(extraction_result.get("deuda_total") or 0.0),
                step=1_000_000.0,
                format="%.0f",
                min_value=0.0,
                key="latam_val_deuda_total",
                help=(
                    f"Fuente: pag. {extraction_result.get('source_page_deuda_total', '?')} | "
                    f"Confianza: {extraction_result.get('confidence_deuda_total', 'N/A')}"
                ),
            )
            _render_confidence_badge(extraction_result.get("confidence_deuda_total"))
            st.caption(f"Fuente: pagina {extraction_result.get('source_page_deuda_total', '?')}")
            if extraction_result.get("confidence_deuda_total") == "Baja":
                st.warning("Confianza Baja: verifique y corrija este valor antes de confirmar.")

        # ── Submit buttons (side by side, no disabled=True per bug #8075) ─────
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

    # ── After form closes: dispatch to handler ────────────────────────────────
    if confirmed:
        _handle_confirm(
            extraction_result,
            company,
            ingresos,
            utilidad_neta,
            total_activos,
            deuda_total,
        )
    elif discarded:
        _handle_discard()
