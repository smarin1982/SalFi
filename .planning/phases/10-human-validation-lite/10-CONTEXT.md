# Phase 10: Human Validation Lite - Context

**Gathered:** 2026-03-07
**Status:** Ready for planning

<domain>
## Phase Boundary

A Streamlit validation gate that intercepts LATAM extraction results before any Parquet write. The analyst reviews the four key financial values (Ingresos, Utilidad Neta, Total Activos, Deuda Total), corrects if needed, and explicitly confirms. No new extraction capabilities, no KPI display — only the confirmation checkpoint.

</domain>

<decisions>
## Implementation Decisions

### Panel placement & flow
- The validation panel renders inline at the bottom of the existing app page, below the S&P 500 section
- No page takeover or modal — analyst sees it scroll into view after extraction completes
- Panel persists until the analyst confirms or discards

### Confidence UX — low-confidence fields
- Baja-confidence fields must show an explicit warning (e.g., colored warning box or st.warning under the field) and require the analyst to actively edit the value before the "Confirmar y guardar" button becomes enabled
- Alta and Media fields: badge only, no extra friction
- The intent is to force attention on uncertain values — silent confirmation of Baja extractions is not acceptable

### After "Confirmar y guardar"
- Panel disappears and the app navigates to the company's KPI view (i.e., the dashboard loads the confirmed LATAM company as the active selection)
- Brief success message shown during transition

### After "Descartar"
- A "Re-run extraction" button is shown after discarding — analyst can trigger a new extraction without navigating away
- Discard does not write any data; the re-run button re-invokes the extraction flow

### Claude's Discretion
- Exact styling of the Baja-field warning (st.warning vs colored border vs inline text)
- Exact navigation mechanism to company KPI view (st.query_params, session state key, or rerun with active_company set)
- Wording of all Spanish-language UI strings

</decisions>

<specifics>
## Specific Ideas

- Baja confidence = the analyst MUST touch the field before confirming. The "Confirmar y guardar" button should be disabled (or show an error on click) if any Baja field still holds the raw extracted value unchanged.
- After confirm, navigate to the LATAM company KPI view — the analyst just validated the data, they'll want to see the resulting KPIs immediately.
- After discard, keep the LATAM section visible with a "Re-run extraction" button — don't abandon the analyst.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 10-human-validation-lite*
*Context gathered: 2026-03-07*
