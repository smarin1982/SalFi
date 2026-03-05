# Phase 10: Human Validation Lite - Research

**Researched:** 2026-03-04
**Domain:** Streamlit form-based confirmation UX, session state lifecycle management, meta.json schema extension
**Confidence:** HIGH

---

## Summary

Phase 10 inserts a human checkpoint between PDF extraction (Phase 8) and Parquet write (KPI calculation). The analyst sees 4 key extracted values — Ingresos, Utilidad Neta, Total Activos, Deuda Total — with their source page and confidence score, edits any incorrect values, and explicitly confirms before any disk write occurs. If the analyst closes the dashboard without confirming, the extraction result evaporates with the session.

The implementation is a **single `st.form` panel** with four `st.number_input` fields, two `st.form_submit_button` elements (Confirmar / Descartar), and a confidence badge per field. All intermediate state lives in `st.session_state` under `latam_` prefixed keys. The "no disk write before confirmation" invariant is enforced by deferring the `latam_processor.process()` and atomic Parquet write until the "Confirmar y guardar" submit path executes.

This is the smallest possible human-in-the-loop gate: no dialog components, no page navigation, no multi-step wizard. One form, one rerun on submit, one write to disk.

**Primary recommendation:** Use `st.form` (not bare `st.number_input` widgets) so field edits do not trigger reruns mid-editing. Two `st.form_submit_button` elements in the same form distinguish the confirm vs. discard paths by checking each button's boolean return value after the `with st.form` block closes.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VAL-01 | Before writing to Parquet, present analyst with 4 detected key values (Ingresos, Utilidad Neta, Total Activos, Deuda) with source page + confidence score; allow editing; "Confirmar y guardar" triggers Parquet write; closing dashboard before confirming leaves no partial data | st.form batches edits until submit; session_state holds extraction result; latam_ key prefix avoids DuplicateWidgetID; meta.json human_validated flag records corrections; delete session_state keys on discard |

</phase_requirements>

---

## Standard Stack

### Core (no new dependencies — all already in environment)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `streamlit` | `>=1.35` (already installed) | st.form, st.number_input, st.badge, st.session_state | Dashboard framework for the entire project |
| `json` (stdlib) | — | Read/write meta.json alongside Parquet | No dependency; already used in agent.py pattern |
| `pathlib` (stdlib) | — | Path construction for latam storage | Already used throughout the project |

### Supporting (no new dependencies)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `st.badge` | Streamlit v1.54.0+ | Native colored confidence badge | Use for Alta/Media/Baja pill display without unsafe_allow_html |
| `st.markdown` with inline color badge syntax | Streamlit current | Alternative if st.badge version not confirmed | `:green-badge[Alta]` `:orange-badge[Media]` `:red-badge[Baja]` |

**Installation:** No new packages required. All needed functionality is in the existing Streamlit installation.

---

## Architecture Patterns

### Recommended Flow

```
latam_extractor.extract(pdf_path)
    → returns extraction_result dict (held in memory)

app.py LATAM section detects extraction_result in session_state
    → renders validation panel (st.form)

Analyst edits values → clicks "Confirmar y guardar"
    → form submits → session_state updated with corrected values
    → latam_processor.process(corrected_extraction_result)
    → atomic Parquet write
    → meta.json updated with human_validated flags
    → session_state keys cleared

OR analyst clicks "Descartar"
    → session_state keys cleared → no disk write
```

### Recommended Project Structure (Phase 10 additions)

```
app.py                                  # add: render_latam_validation_panel()
latam_agent.py                          # (from Phase 9) LatamAgent.run() calls
                                        # extract but does NOT write until confirmed
data/latam/{country}/{slug}/
    financials.parquet                  # written only after "Confirmar"
    kpis.parquet                        # written only after "Confirmar"
    meta.json                           # written alongside Parquet; includes
                                        # human_validated flags and corrections
```

### Pattern 1: st.form with Two Submit Buttons (Confirm / Discard)

**What:** A single `st.form` renders all 4 editable fields plus two `st.form_submit_button` elements. Each button returns a boolean; the code block after the `with st.form:` block checks which was pressed.

**When to use:** Whenever you need to batch multiple widget edits into a single rerun AND provide two distinct submit actions in the same form.

**Why st.form is critical here:** Without `st.form`, each `st.number_input` interaction triggers an immediate rerun, which may re-display stale extraction data or trigger partial processing. Inside a form, all edits are batched — the backend sees the values only when a submit button is pressed.

**Example:**
```python
# Source: https://docs.streamlit.io/develop/api-reference/execution-flow/st.form
# Source: https://www.restack.io/docs/streamlit-knowledge-streamlit-form-multiple-submit-buttons

def render_latam_validation_panel(extraction_result: dict) -> None:
    """
    Display validation panel for LATAM extraction result.
    extraction_result keys: ingresos, utilidad_neta, total_activos, deuda_total,
                            source_page_{field}, confidence_{field}
    """
    st.subheader("Validacion de Extraccion")
    st.caption(
        "Revise los valores detectados. Corrija cualquier valor incorrecto "
        "antes de confirmar."
    )

    with st.form(key="latam_validation_form"):
        col1, col2 = st.columns(2)

        with col1:
            ingresos = st.number_input(
                label="Ingresos (USD)",
                value=float(extraction_result.get("ingresos") or 0.0),
                step=1_000_000.0,
                format="%.0f",
                key="latam_val_ingresos",
                help=(
                    f"Fuente: pag. {extraction_result.get('source_page_ingresos', '?')} | "
                    f"Confianza: {extraction_result.get('confidence_ingresos', 'N/A')}"
                ),
            )
            _render_confidence_badge(extraction_result.get("confidence_ingresos"))
            st.caption(f"Fuente: pagina {extraction_result.get('source_page_ingresos', '?')}")

            total_activos = st.number_input(
                label="Total Activos (USD)",
                value=float(extraction_result.get("total_activos") or 0.0),
                step=1_000_000.0,
                format="%.0f",
                key="latam_val_total_activos",
                help=(
                    f"Fuente: pag. {extraction_result.get('source_page_total_activos', '?')} | "
                    f"Confianza: {extraction_result.get('confidence_total_activos', 'N/A')}"
                ),
            )
            _render_confidence_badge(extraction_result.get("confidence_total_activos"))
            st.caption(f"Fuente: pagina {extraction_result.get('source_page_total_activos', '?')}")

        with col2:
            utilidad_neta = st.number_input(
                label="Utilidad Neta (USD)",
                value=float(extraction_result.get("utilidad_neta") or 0.0),
                step=1_000_000.0,
                format="%.0f",
                key="latam_val_utilidad_neta",
            )
            _render_confidence_badge(extraction_result.get("confidence_utilidad_neta"))
            st.caption(f"Fuente: pagina {extraction_result.get('source_page_utilidad_neta', '?')}")

            deuda_total = st.number_input(
                label="Deuda Total (USD)",
                value=float(extraction_result.get("deuda_total") or 0.0),
                step=1_000_000.0,
                format="%.0f",
                key="latam_val_deuda_total",
            )
            _render_confidence_badge(extraction_result.get("confidence_deuda_total"))
            st.caption(f"Fuente: pagina {extraction_result.get('source_page_deuda_total', '?')}")

        # Two submit buttons in same form — each returns a bool
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

    # --- After form closes: handle submission ---
    if confirmed:
        _handle_confirm(extraction_result, ingresos, utilidad_neta,
                        total_activos, deuda_total)
    elif discarded:
        _handle_discard()
```

### Pattern 2: Session State as the Holding Area (No Disk Write Until Confirmed)

**What:** The extraction result dict is stored in `st.session_state["latam_pending_extraction"]`. The Parquet write only happens inside `_handle_confirm()`. The Parquet write never runs unless the analyst explicitly presses "Confirmar y guardar" in the current session.

**When to use:** Any time data must be conditionally persisted based on explicit user approval.

**Example:**
```python
# Source: https://docs.streamlit.io/develop/concepts/architecture/session-state

# After extraction completes (in the LATAM pipeline trigger):
st.session_state["latam_pending_extraction"] = extraction_result
st.session_state["latam_pending_company"] = company_record  # CompanyRecord dataclass

# In app.py main loop:
if "latam_pending_extraction" in st.session_state:
    render_latam_validation_panel(st.session_state["latam_pending_extraction"])
```

### Pattern 3: human_validated Flag in meta.json

**What:** `meta.json` is a sidecar JSON file alongside the Parquet files in `data/latam/{country}/{slug}/`. It records extraction provenance, quality metadata, and human validation decisions.

**Why JSON (not Parquet):** meta.json is a single-row document with mixed types (strings, dicts, timestamps, booleans). JSON sidecar is the established pattern in this project's Phase 9 design (`meta.json with company metadata and extraction quality`). Parquet is for tabular time-series data.

**Schema extension for VAL-01:**
```python
import json
from pathlib import Path
from datetime import datetime, timezone

def write_meta_json(
    company_slug: str,
    country: str,
    extraction_result: dict,
    corrected_values: dict,
    original_values: dict,
) -> None:
    """
    Write meta.json sidecar with human validation provenance.
    corrected_values: dict of field -> final value (after analyst edit)
    original_values:  dict of field -> extracted value (before edit)
    """
    storage_path = Path(f"data/latam/{country}/{company_slug}")
    storage_path.mkdir(parents=True, exist_ok=True)

    # Determine which fields were corrected by the analyst
    human_validated_fields = {
        field: {
            "original": original_values.get(field),
            "corrected": corrected_values.get(field),
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }
        for field in ["ingresos", "utilidad_neta", "total_activos", "deuda_total"]
        if corrected_values.get(field) != original_values.get(field)
    }

    meta = {
        # Extraction provenance
        "company_slug": company_slug,
        "country": country,
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
        # Human validation
        "human_validated": bool(human_validated_fields),  # True if any field was corrected
        "human_validated_fields": human_validated_fields,  # empty dict if no corrections
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }

    meta_path = storage_path / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
```

### Pattern 4: Discard Path — Clearing Session State

**What:** When the analyst clicks "Descartar", all `latam_pending_*` keys are deleted from session state. No Parquet, no meta.json, no disk write.

**Example:**
```python
# Source: https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state

def _handle_discard() -> None:
    """Remove pending extraction from session state. No disk write."""
    for key in ["latam_pending_extraction", "latam_pending_company"]:
        if key in st.session_state:
            del st.session_state[key]
    st.info("Extraccion descartada. No se escribio ningun dato.")
    st.rerun()
```

### Pattern 5: Confidence Badge Display

**What:** Use `st.badge` (available since Streamlit v1.54.0) for colored Alta/Media/Baja indicators. Avoid `unsafe_allow_html=True` to keep the code clean and safe.

**Color mapping:**
```python
# Source: https://docs.streamlit.io/develop/api-reference/text/st.badge

def _render_confidence_badge(confidence: str | None) -> None:
    """Render a colored badge for confidence level."""
    COLOR_MAP = {
        "Alta": "green",
        "Media": "orange",
        "Baja": "red",
    }
    if confidence in COLOR_MAP:
        st.badge(label=confidence, color=COLOR_MAP[confidence])
    else:
        st.badge(label="Desconocida", color="gray")
```

**Alternative (if st.badge not available in installed version):**
```python
# Uses Streamlit's Markdown badge directive — no unsafe_allow_html needed
BADGE_MARKDOWN = {
    "Alta": ":green-badge[Alta]",
    "Media": ":orange-badge[Media]",
    "Baja": ":red-badge[Baja]",
}
st.markdown(BADGE_MARKDOWN.get(confidence, ":gray-badge[Desconocida]"))
```

### Anti-Patterns to Avoid

- **Using bare `st.number_input` outside a form:** Each edit triggers a rerun. The validation panel re-renders mid-edit with potentially re-fetched extraction data, confusing the analyst.
- **Writing to Parquet before confirmation:** Violates the success criterion. Never call `latam_processor.process()` or Parquet write until `confirmed == True` is detected.
- **Storing large DataFrames in session state:** Only the extraction result dict (a small Python dict with ~20 keys) goes in session state — not DataFrames. DataFrames are constructed during the confirmation handler.
- **Using `st.dialog` for the validation panel:** Adds complexity without benefit. The form renders inline in the LATAM section — no modal needed for this use case.
- **Widget keys without `latam_` prefix:** Will cause `DuplicateWidgetID` error when combined with any other widget that uses a generic key name.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Colored confidence indicators | Custom HTML spans with `unsafe_allow_html` | `st.badge(color=...)` | Native component, no XSS risk, consistent theme |
| Batch-until-submit behavior | Manual `st.session_state` flags to suppress reruns | `st.form` | Built-in batching; one rerun on submit |
| "No disk write before confirmation" | Custom transaction manager | `st.session_state` + conditional write | Session state dies with the session naturally; use `if confirmed:` before writing |
| Two-action form (confirm/discard) | Two separate forms | Two `st.form_submit_button` in one form | Streamlit supports multiple submit buttons in one form; each returns bool |

**Key insight:** The entire Phase 10 validation mechanism requires zero new Python packages. Streamlit's built-in `st.form`, `st.number_input`, `st.badge`, and `st.session_state` cover all requirements. The complexity is architectural (when to write, what to clear) not technical.

---

## Common Pitfalls

### Pitfall 1: Widget Key Collision (DuplicateWidgetID)

**What goes wrong:** Adding `st.number_input("Ingresos", key="ingresos")` in the LATAM section clashes with any widget elsewhere that uses the same key — crashing the entire app including the S&P 500 section.

**Why it happens:** Streamlit identifies every widget by its `key` parameter. Same key in two places = `DuplicateWidgetID` exception on load.

**How to avoid:** Prefix ALL Phase 10 validation widget keys with `latam_val_`:
```python
st.number_input(..., key="latam_val_ingresos")
st.number_input(..., key="latam_val_utilidad_neta")
st.number_input(..., key="latam_val_total_activos")
st.number_input(..., key="latam_val_deuda_total")
st.form(key="latam_validation_form")
```

**Warning signs:** `DuplicateWidgetID` error appearing when the LATAM section is added; error message refers to a generic key name like `"ingresos"` or `"value"`.

---

### Pitfall 2: Partial Write on Exception During Confirmation

**What goes wrong:** `_handle_confirm()` begins writing `financials.parquet`, then crashes mid-write. The session state keys are already cleared (discard path), but a corrupt partial Parquet file now exists on disk.

**Why it happens:** Exception between `financials.parquet` write and `kpis.parquet` write leaves one file written and one missing.

**How to avoid:** Use the existing project's atomic write pattern (from `agent.py`): write to `.parquet.tmp`, then rename. If the rename fails, the `.tmp` file can be deleted on next startup. Never clear session state keys until BOTH Parquet writes succeed:
```python
def _handle_confirm(extraction_result, ingresos, utilidad_neta,
                    total_activos, deuda_total):
    try:
        corrected = {
            "ingresos": ingresos,
            "utilidad_neta": utilidad_neta,
            "total_activos": total_activos,
            "deuda_total": deuda_total,
        }
        # atomic write pattern (both files before clearing state)
        latam_processor.process_with_validation(
            st.session_state["latam_pending_company"],
            corrected,
            extraction_result,
        )
        write_meta_json(...)
        # Only clear session state after successful write
        _handle_discard()  # reuses the clear-state function
        st.success("Datos guardados correctamente.")
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Error al guardar: {e}")
        # Do NOT clear session state — let analyst retry
```

**Warning signs:** Parquet file exists but KPIs file is missing; loading LATAM data shows partial results.

---

### Pitfall 3: st.number_input Precision Loss for Billion-Scale Values

**What goes wrong:** A company reports Ingresos of 12,345,678,901 (twelve billion). `st.number_input` renders this but the JavaScript client (React) loses precision beyond ±(2^53 - 1) ≈ 9 quadrillion for integers. For float, precision loss begins at ~15 significant digits.

**Why it happens:** The widget serializes values as JSON between Python backend and JavaScript frontend. JavaScript's `number` type is a 64-bit IEEE 754 float — same limitation as Python `float`. Integers beyond `(1<<53) - 1` cannot be exactly represented.

**How to avoid:** Store and display LATAM financials as `float` (not `int`). LATAM company revenues in the hundreds of millions to tens of billions USD range well within `float` safe range (~±9×10^15). Use `format="%.0f"` to display without decimal noise:
```python
st.number_input(
    label="Ingresos (USD)",
    value=float(extraction_result.get("ingresos") or 0.0),
    step=1_000_000.0,   # 1 million step for comfortable editing
    format="%.0f",       # display as integer (no decimal point)
    min_value=0.0,
    key="latam_val_ingresos",
)
```
For values in local currency (before USD conversion), they may be much larger (e.g., ARS trillions). Always normalize to USD before populating the validation form.

**Warning signs:** Large values display as scientific notation; editor shows `1.2345678901e10` instead of `12,345,678,901`; value returned by widget differs from value entered.

---

### Pitfall 4: Session State Not Cleared on Browser Refresh (Expected Behavior)

**What goes wrong:** Analyst closes the browser tab (or refreshes) mid-validation. On returning, the session state is gone — so is the extraction result. The analyst must re-run extraction.

**Why it happens:** This is correct and desired behavior (success criterion 4: "closing dashboard before confirming leaves no partial data"). `st.session_state` is session-scoped and does not survive browser close.

**How to avoid:** This is not a bug — it's the mechanism. Document it in the UI with a caption: "Este panel desaparecera si cierra o recarga el navegador antes de confirmar."

**Warning signs if behavior is WRONG:** If data DOES persist after browser close, the code has accidentally written to disk before confirmation — trace all write paths.

---

### Pitfall 5: Two st.form_submit_button Elements — Disabled Button Bug

**What goes wrong:** If one `st.form_submit_button` is set `disabled=True`, the other button may not trigger submission (known Streamlit bug reported Feb 2024, GitHub issue #8075).

**Why it happens:** Streamlit form submission interacts unexpectedly with the disabled state of submit buttons, preventing the enabled button from firing.

**How to avoid:** Do NOT use `disabled=True` on either submit button in the validation form. Both "Confirmar y guardar" and "Descartar" should always be active. Guarding against double-submission is handled by checking `"latam_pending_extraction" in st.session_state` before rendering the form at all.

**Warning signs:** Clicking "Confirmar" does nothing; `if confirmed:` block never executes; no error message.

---

### Pitfall 6: LATAM Imports Breaking S&P 500 Section

**What goes wrong:** Adding `import latam_processor` or `import latam_agent` at the top of `app.py` causes the S&P 500 section to fail if those modules have import-time errors (missing dependencies, syntax errors during Phase 10 development).

**Why it happens:** Top-level imports execute at module load time. Any error in LATAM modules propagates to the entire app.

**How to avoid:** Keep all LATAM imports inside the `render_latam_validation_panel()` function (lazy import pattern, established in v2.0 roadmap decisions):
```python
def _handle_confirm(...):
    try:
        import latam_processor  # lazy import — S&P 500 section unaffected
        latam_processor.process_with_validation(...)
    except ImportError as e:
        st.error(f"Error de importacion LATAM: {e}")
```

**Warning signs:** S&P 500 section fails to render after adding any LATAM code; import error references a LATAM-only module.

---

## Code Examples

Verified patterns from Streamlit official documentation:

### st.number_input for Large Financial Values
```python
# Source: https://docs.streamlit.io/develop/api-reference/widgets/st.number_input
# Use float type, format="%.0f" to display without decimal noise
# step=1_000_000.0 gives a comfortable edit increment for USD-normalized financials

revenue = st.number_input(
    label="Ingresos (USD)",
    value=float(extracted_ingresos),
    step=1_000_000.0,
    format="%.0f",
    min_value=0.0,
    key="latam_val_ingresos",
)
# revenue is a float — safe for billion-scale values in LATAM context
```

### st.form with Two Submit Buttons
```python
# Source: https://docs.streamlit.io/develop/api-reference/execution-flow/st.form
# Source: https://www.restack.io/docs/streamlit-knowledge-streamlit-form-multiple-submit-buttons
# Both buttons return bool; check each after the with block

with st.form("latam_validation_form"):
    val1 = st.number_input("Campo 1", value=0.0, step=1_000_000.0, format="%.0f",
                            key="latam_val_campo1")
    col_a, col_b = st.columns(2)
    with col_a:
        confirmed = st.form_submit_button("Confirmar y guardar", type="primary",
                                          use_container_width=True)
    with col_b:
        discarded = st.form_submit_button("Descartar", type="secondary",
                                          use_container_width=True)

# Exactly one of these will be True on submission; neither is True before submit
if confirmed:
    # write to disk
    pass
elif discarded:
    # clear session state
    pass
```

### Session State Initialization and Cleanup
```python
# Source: https://docs.streamlit.io/develop/concepts/architecture/session-state

# Store extraction result after pipeline completes (no disk write yet)
st.session_state["latam_pending_extraction"] = extraction_result
st.session_state["latam_pending_company"] = company_record

# Clear state after confirm or discard (no disk write on discard)
for key in list(st.session_state.keys()):
    if key.startswith("latam_pending_"):
        del st.session_state[key]
```

### st.badge for Confidence Indicators
```python
# Source: https://docs.streamlit.io/develop/api-reference/text/st.badge
# Available since Streamlit v1.54.0
# Colors: "red", "orange", "yellow", "blue", "green", "violet", "gray", "primary"

CONFIDENCE_COLORS = {"Alta": "green", "Media": "orange", "Baja": "red"}
confidence = extraction_result.get("confidence_ingresos", "Desconocida")
st.badge(
    label=confidence,
    color=CONFIDENCE_COLORS.get(confidence, "gray"),
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `unsafe_allow_html=True` for colored text | `st.badge(color=...)` native component | Streamlit v1.54.0 (2025) | No HTML injection risk; consistent theming |
| `st.number_input` with `format="%d"` for integers | `format="%.0f"` on float type | Always | Float handles billion-scale correctly; `%d` may overflow on some platforms |
| `st.experimental_rerun()` | `st.rerun()` | Streamlit v1.27.0 | `experimental_rerun` removed; use `st.rerun()` |
| Separate confirm/cancel buttons outside form | Two `st.form_submit_button` in one form | Streamlit 1.x | Batches widget edits; one rerun; cleaner UX |

**Deprecated/outdated:**
- `st.experimental_rerun()`: Removed; use `st.rerun()`.
- `st.beta_expander()`: Removed; use `st.expander()`.
- `st.write_stream()` does not apply to this phase.

---

## Open Questions

1. **st.badge version availability**
   - What we know: `st.badge` was added in Streamlit v1.54.0 per documentation
   - What's unclear: The exact Streamlit version currently installed in the project environment
   - Recommendation: At plan time, run `import streamlit; print(streamlit.__version__)`. If below 1.54.0, use the Markdown badge directive fallback (`:green-badge[Alta]`). Both approaches are coded in the examples above.

2. **meta.json schema alignment with Phase 9**
   - What we know: Phase 9 ROADMAP describes `meta.json with company metadata and extraction quality` but no schema has been written yet (Phase 9 not started)
   - What's unclear: Whether Phase 9 will define the full meta.json schema, or whether Phase 10 should own it
   - Recommendation: Phase 10 plan should define meta.json schema explicitly and note that Phase 9 must produce an extraction_result dict compatible with the schema. The Phase 10 planner should include a `meta.json` schema definition as a deliverable.

3. **Extraction result dict structure from Phase 8/9**
   - What we know: Phase 8 produces confidence scores and source page per field; Phase 9 wraps this in LatamAgent
   - What's unclear: The exact key names in the extraction_result dict (e.g., `confidence_ingresos` vs `confidence["ingresos"]`)
   - Recommendation: Phase 10 plan should define the expected extraction_result dict interface and note that the latam_extractor must conform to it. Use a flat key structure (`confidence_ingresos`, `source_page_ingresos`) for simplicity with st.form.

---

## Sources

### Primary (HIGH confidence)
- [Streamlit st.form official docs](https://docs.streamlit.io/develop/api-reference/execution-flow/st.form) — form batching behavior, submit button restrictions, clear_on_submit
- [Streamlit st.form_submit_button official docs](https://docs.streamlit.io/develop/api-reference/execution-flow/st.form_submit_button) — type parameter, multiple buttons, callback
- [Streamlit st.number_input official docs](https://docs.streamlit.io/develop/api-reference/widgets/st.number_input) — format, value, min/max, large integer limits
- [Streamlit st.badge official docs](https://docs.streamlit.io/develop/api-reference/text/st.badge) — color options, label, version v1.54.0
- [Streamlit Session State official docs](https://docs.streamlit.io/develop/concepts/architecture/session-state) — initialization, access, deletion
- [Streamlit Forms concepts](https://docs.streamlit.io/develop/concepts/architecture/forms) — widget rerun behavior inside forms

### Secondary (MEDIUM confidence)
- [Streamlit multiple form_submit_button pattern](https://www.restack.io/docs/streamlit-knowledge-streamlit-form-multiple-submit-buttons) — confirmed: multiple submit buttons supported, each returns bool
- [Streamlit disabled submit button bug](https://github.com/streamlit/streamlit/issues/8075) — known issue: disabled submit button prevents other button from firing (Feb 2024); verified against multiple community reports

### Tertiary (LOW confidence)
- Community forum pattern for `del st.session_state[key]` cleanup — consistent across multiple Streamlit forum answers; not an official docs page

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all tools are existing Streamlit components, verified against official docs
- Architecture: HIGH — st.form batching, session_state lifecycle, and multi-submit-button pattern all verified against official docs
- Pitfalls: HIGH — widget key collision and lazy import patterns are established project decisions; disabled button bug verified against GitHub issue tracker

**Research date:** 2026-03-04
**Valid until:** 2026-09-04 (Streamlit is stable; st.badge available since v1.54.0 — unlikely to change)
