# Phase 8: PDF Extraction & KPI Mapping - Context

**Gathered:** 2026-03-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Given a downloaded PDF (digital or scanned), the extractor returns structured financial data
with page-level source tracking — mapped through the LATAM health sector CONCEPT_MAP to the
20-KPI schema — and latam_processor.py produces valid Parquet by reusing calculate_kpis()
without modifying processor.py. Covers: latam_extractor.py, latam_concept_map.py,
latam_processor.py. UI/dashboard surfacing of confidence alerts is within scope for this
phase (badge/indicator in Streamlit). Full dashboard build is a separate phase.

</domain>

<decisions>
## Implementation Decisions

### Extraction failure handling
- Always return a partial ExtractionResult — never raise on low coverage; the caller decides
  what to do with Baja confidence results
- Data trust is paramount: load what was found and surface it for user validation rather than
  silently discarding
- Confidence alerts (Baja result or missing critical fields) must appear in the Streamlit
  dashboard as a visible badge/indicator on the company card ("⚠ Revisar datos")

### Multi-year PDF data
- LATAM PDFs often contain comparative statements (current year + prior year)
- Capture both years: one row per year in financials.parquet with a `year` column
- This is consistent with the existing US Parquet schema — no structural divergence

### Unknown label behavior
- When an extracted Spanish label has no match in CONCEPT_MAP, log: raw label text +
  page number + company name
- This structured log enables iterative enrichment of CONCEPT_MAP after real PDFs are
  processed
- Do not silently skip; do not attempt fuzzy matching at this stage

### Confidence scoring criteria (Alta / Media / Baja)
- Critical fields that determine confidence level must be derived from the minimum financial
  statements required by each country's regulatory body:
    - CO: Supersalud (Superintendencia Nacional de Salud)
    - PE: SMV (Superintendencia del Mercado de Valores)
    - CL: CMF (Comisión para el Mercado Financiero)
- If a regulator requires revenue + total assets + equity as mandatory disclosures, those
  become the critical fields for Alta confidence for that country
- Alta = all regulator-required critical fields present
- Media = most critical fields present but some optional fields missing
- Baja = one or more regulator-required critical fields absent

### Claude's Discretion
- Exact OCR preprocessing pipeline (image dpi, contrast enhancement)
- pdfplumber table extraction parameters (column tolerance, edge detection)
- Log file format and rotation for unmapped labels
- Exact Streamlit badge styling and placement

</decisions>

<specifics>
## Specific Ideas

- "La confianza en la información es primordial" — data quality over speed; better to surface
  uncertain data for manual review than to silently produce incorrect KPIs
- Use official regulatory frameworks (Supersalud, SMV, CMF) as the authoritative source for
  what fields matter in each country — not an arbitrary internal list
- Unknown labels should be collected as a corpus for future CONCEPT_MAP expansion (the log
  is a seed dataset, not just an error list)

</specifics>

<deferred>
## Deferred Ideas

- Fuzzy matching for CONCEPT_MAP synonyms (difflib/rapidfuzz) — consider in a future
  maintenance phase once real label corpus is collected
- Full Streamlit validation UI (review queue, approve/reject per field) — Phase 9+ dashboard
- Scheduled re-extraction when PDFs are updated — out of scope for this phase

</deferred>

---

*Phase: 08-pdf-extraction-kpi-mapping*
*Context gathered: 2026-03-06*
