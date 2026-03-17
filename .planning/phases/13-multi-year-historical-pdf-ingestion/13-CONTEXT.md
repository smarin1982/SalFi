# Phase 13: Multi-year Historical PDF Ingestion - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Crawl a LATAM company's financial report listing page, discover all available annual PDFs (e.g. 2019–2024), download each, extract financial data, and accumulate into `financials.parquet`. This phase adds historical depth to an existing company — it does not change how the most recent year is fetched (Phase 7) or how data is displayed beyond showing multi-year trends in charts.

</domain>

<decisions>
## Implementation Decisions

### Trigger & UX
- Backfill starts **automatically when a new LATAM company is registered** — no separate button needed for first-time ingestion
- On subsequent dashboard loads, the system **silently checks for new years** and downloads/extracts any gaps found
- During backfill, show a **per-year progress list**: one row per year with status (e.g. "2021 ✓ OK", "2022 ⏳ descargando...", "2020 ✗ no encontrado")
- **KPI cards** (recuadros principales) display the most recent year's value with the year labeled (e.g. "Revenue 2024: $X")
- **Charts** show historical trend for the **last 5 years** — not just the most recent

### Re-extraction Policy
- **Skip years already in parquet** — if a year exists, do not re-download or re-extract
- **Force re-extract button** available per year in the evidence/validation panel (useful when confidence badge is low)
- Each backfill year goes through the **Phase 10 individual validation screen** — not a batch screen
- When extraction confidence is **low**, the system triggers the validation screen to let the analyst manually verify/correct key values before writing to parquet

### Partial Failure Handling
- If a year's PDF is not found, **continue with remaining years** — the parquet ends up with available years and a gap
- If extraction yields low confidence, **offer the validation screen** rather than silently writing or discarding
- At the end of a backfill run, show a **summary table per year**: "2019 ✓", "2020 ⚠️ baja confianza (validado)", "2021 ✗ PDF no encontrado", etc.

### Discovery Scope
- Window: **last 5 years** (fiscal years ending 5 years before current year)
- Discovery method: **crawl the portal's listing page** for the company (e.g. supersalud.gov.co report index, BVC filings page) and parse all PDF links — do not run one DDGS search per year
- Tier priority: **T1 only** (estados financieros). Fall back to T2 only as absolute last resort if T1 is unavailable for a given year
- Discovery uses the `scraper_profile` stored for the company (the portal URL already known from Phase 7 ingestion)

### Claude's Discretion
- Exact crawl depth for the listing page (how many pagination levels)
- How to handle PDFs with ambiguous year in the URL when year cannot be detected from filename
- Storage of per-year download metadata (PDF path, download date, tier, confidence score)

</decisions>

<specifics>
## Specific Ideas

- The company's portal listing page (already crawled in Phase 7 to find the latest PDF) is the starting point — don't re-search, just go deeper on that same page
- MiRed IPS is the reference company: supersalud.gov.co has a listing with 2019–2024 reports; Phase 13 should handle this pattern
- Charts should feel like the US S&P 500 trend charts in app.py — consistent style

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 13-multi-year-historical-pdf-ingestion*
*Context gathered: 2026-03-17*
