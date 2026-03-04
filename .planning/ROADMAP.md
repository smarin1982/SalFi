# Roadmap: Financial Analysis Dashboard

## Milestones

- [x] **v1.0 SP500 Pipeline** - Phases 1-5 (shipped 2026-02-28)
- [ ] **v2.0 LATAM Financial Analysis Pipeline** - Phases 6-10 (in progress)

## Phases

<details>
<summary>v1.0 SP500 Pipeline (Phases 1-5) — SHIPPED 2026-02-28</summary>

**Overview:**
Local Python ETL pipeline and Streamlit dashboard that extracts audited 10-K financial data from SEC EDGAR for the Top 20 S&P 500 companies, calculates 20 KPIs per company per year, and surfaces everything in an interactive multi-company comparison dashboard. Build order: scraper produces raw JSON, processor turns it into clean Parquet, orchestrator batches the pipeline, dashboard reads from Parquet, scheduling keeps data current.

### Phase 1: Data Extraction
**Goal**: The scraper can fetch, rate-limit, and persist raw 10-K financial data from SEC EDGAR for any S&P 500 ticker
**Depends on**: Nothing (first phase)
**Requirements**: XTRCT-01, XTRCT-02, XTRCT-03, XTRCT-04
**Success Criteria** (what must be TRUE):
  1. Running the scraper for any valid S&P 500 ticker produces a `data/raw/{TICKER}/facts.json` file containing 10 years of 10-K financial facts
  2. The scraper resolves any ticker to its SEC CIK using the downloaded `tickers.json` without a network call per resolution
  3. The scraper never exceeds 10 requests/second to SEC EDGAR across any burst of activity
  4. If a `facts.json` file already exists, the scraper uses the local copy instead of re-fetching
**Plans**: 2 plans

Plans:
- [x] 01-01-PLAN.md — Bootstrap project dependencies (.env, requirements.txt, data/ directories)
- [x] 01-02-PLAN.md — Implement scraper.py with ticker→CIK resolution, rate limiting, and raw facts.json persistence

### Phase 2: Transformation & KPIs
**Goal**: The processor transforms raw EDGAR facts into clean, analysis-ready Parquet files with all 20 KPIs calculated for every company/year combination
**Depends on**: Phase 1
**Requirements**: XFORM-01, XFORM-02, XFORM-03, XFORM-04
**Success Criteria** (what must be TRUE):
  1. Running the processor on any Top 20 ticker produces `data/clean/{TICKER}/financials.parquet` and `data/clean/{TICKER}/kpis.parquet` with no silent NaN for revenue
  2. All 20 KPIs are present as columns in `kpis.parquet`
  3. Companies with genuinely missing data have NaN rather than wrong values; no division-by-zero exceptions occur; outliers are preserved as-is
  4. Running the processor twice on the same raw data produces identical output (idempotent)
**Plans**: 2 plans

Plans:
- [x] 02-01-PLAN.md — XBRL normalizer: CONCEPT_MAP (22 fields) + extract_concept() + normalize_xbrl()
- [x] 02-02-PLAN.md — Cleaning + 20 KPI engine + atomic Parquet writer + process() entry point + end-to-end verification

### Phase 3: Orchestration & Batch
**Goal**: The FinancialAgent coordinates the full ETL pipeline per ticker with staleness detection, and can batch-process all 20 base companies in one command
**Depends on**: Phase 2
**Requirements**: ORCHS-01, ORCHS-02, ORCHS-03
**Success Criteria** (what must be TRUE):
  1. Calling `FinancialAgent(ticker).run()` on a ticker with no existing data produces complete `data/raw/` and `data/clean/` artifacts end-to-end without manual steps
  2. Calling `FinancialAgent(ticker).run()` on a ticker whose data is current for this quarter skips all SEC network requests and completes immediately
  3. Running the batch initializer produces clean Parquet files for all 20 base companies
  4. Adding a new KPI to `KPI_REGISTRY` does not require changes to the scraper, agent, or dashboard code
**Plans**: 3 plans

Plans:
- [x] 03-01-PLAN.md — KPI_REGISTRY refactor in processor.py (TDD: registry iteration + per-KPI error isolation)
- [x] 03-02-PLAN.md — FinancialAgent class with run() + needs_update() staleness detection + metadata.parquet
- [x] 03-03-PLAN.md — run_batch() function + CLI entry point + full 20-ticker batch verification

### Phase 4: Dashboard
**Goal**: The Streamlit dashboard lets an analyst visually compare any combination of S&P 500 companies across all 20 KPIs over up to 10 years, and add new companies on demand
**Depends on**: Phase 3
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04
**Success Criteria** (what must be TRUE):
  1. An analyst can select any subset of the loaded companies and any of the 20 KPIs, and see a multi-line time-series chart that updates without page reload
  2. An analyst can adjust a year-range slider to restrict the chart to any window within the available 10-year history
  3. An analyst can type any valid S&P 500 ticker into the input field and see that company's data added to all charts within the same session, without restarting the app
  4. Switching between KPIs or adjusting filters does not re-query Parquet files on disk (Streamlit cache is active)
**Plans**: 3 plans

Plans:
- [x] 04-01-PLAN.md — App foundation: requirements.txt, app.py skeleton (page_config, @st.cache_data loaders, KPI_META registry, format_kpi)
- [x] 04-02-PLAN.md — Full UI: sidebar controls + main canvas with Executive Cards (Plotly trend) + Comparativo overlay + dynamic layout
- [x] 04-03-PLAN.md — Human verification checkpoint: automated smoke checks + browser validation of all DASH requirements

### Phase 5: Scheduling
**Goal**: The ETL pipeline runs automatically at the start of each quarter, keeping all loaded company data current without manual intervention
**Depends on**: Phase 4
**Requirements**: SCHED-01
**Success Criteria** (what must be TRUE):
  1. The scheduler triggers a full ETL run for all loaded companies at the start of each calendar quarter without a human running a command
  2. After the scheduled run completes, the dashboard reflects updated data on the next page load
  3. If a scheduled run is triggered when data is already current for the quarter, the run completes quickly by skipping re-scraping
**Plans**: 2 plans

Plans:
- [x] 05-01-PLAN.md — Create scheduler.bat, quarterly_etl_task.xml, and register_task.bat infrastructure files
- [x] 05-02-PLAN.md — Register task via schtasks CLI, trigger test run, human verify log output and Task Scheduler GUI

</details>

---

## v2.0 LATAM Financial Analysis Pipeline

**Milestone Goal:** Extend the system with a complete LATAM pipeline — web scraping + PDF extraction, USD normalization, KPI calculation, red flags, and a downloadable executive report — integrated into the existing Streamlit dashboard as an additive LATAM section. The US S&P 500 pipeline is never modified.

- [ ] **Phase 6: Foundation** - currency.py + company registry + storage schema + Playwright ThreadPoolExecutor proof-of-concept
- [ ] **Phase 7: LATAM Scraper** - Semantic search (ddgs site:) as primary + Playwright fallback + drag & drop PDF upload
- [ ] **Phase 8: PDF Extraction & KPI Mapping** - Three-level extraction (pdfplumber → PyMuPDF → pytesseract) + evidence trail + LATAM health sector CONCEPT_MAP
- [ ] **Phase 9: Orchestration & Red Flags** - LatamAgent orchestrator, web search (ddgs), red flags engine with YAML thresholds
- [ ] **Phase 10: Human Validation Lite** - Analyst confirmation screen for extracted key values before writing to Parquet
- [ ] **Phase 11: Dashboard & Report** - Additive LATAM section in app.py, multi-currency toggle, evidence viewer, executive report (Claude API), PDF download

## Phase Details

### Phase 6: Foundation
**Goal**: The infrastructure layer is in place so every subsequent LATAM module can be built, tested, and run in isolation — FX normalizer validated for all six currencies, company registry with slug convention locked in, Playwright thread-isolation pattern smoke-tested, and storage schema defined
**Depends on**: Phase 5 (v1.0 complete)
**Requirements**: FX-01, FX-02, COMP-01, COMP-02, COMP-03
**Success Criteria** (what must be TRUE):
  1. `currency.to_usd(amount, "ARS", fiscal_year)` returns a float (not None) by falling back to the secondary FX API when Frankfurter returns HTTP 422 — verified for all six currencies: BRL, MXN, ARS, CLP, COP, PEN
  2. A company identified by name + country produces a deterministic URL-safe slug (e.g., "Clínica Las Américas" + "CO" → `clinica-las-americas`) that can be used as a filesystem path on Windows without OSError
  3. `data/latam/{country}/{slug}/` directories are created correctly and the Parquet schema (column names and dtypes) matches the US `data/clean/{TICKER}/` schema exactly
  4. Calling the Playwright scraper function from a Streamlit button click (inside ThreadPoolExecutor) does not raise NotImplementedError or hang — thread isolation is confirmed working on Windows 11
  5. Argentine peso (ARS) companies surface a baja-confianza warning flag in the returned metadata
**Plans**: 3 plans

Plans:
- [ ] 06-01-PLAN.md — currency.py TDD: tiered FX normalizer (Frankfurter BRL/MXN, open.er-api.com ARS/CLP/COP/PEN) with lru_cache + disk cache; 11 tests
- [ ] 06-02-PLAN.md — company_registry.py TDD: CompanyRecord dataclass, make_slug() (python-slugify), make_storage_path(), Parquet schema parity validation; 10 tests
- [ ] 06-03-PLAN.md — Playwright thread isolation: latam_scraper.py ThreadPoolExecutor wrapper, smoke test, Streamlit latam_ button; human verification gate

### Phase 7: LATAM Scraper
**Goal**: Given a company name or regulatory ID, the scraper discovers and downloads the annual financial report PDF using semantic ddgs site-search as primary strategy and Playwright as fallback — plus a drag & drop upload path for when automated scraping is blocked
**Depends on**: Phase 6
**Requirements**: SCRAP-01, SCRAP-02, SCRAP-04
**Success Criteria** (what must be TRUE):
  1. Given a corporate domain, `latam_scraper.search(domain, year)` constructs a `site:empresa.com filetype:pdf "Estado de Situación Financiera" {year}` query, retrieves the direct PDF URL, and downloads it to `data/latam/{country}/{slug}/raw/` — without launching a browser
  2. When semantic search returns no direct PDF URL, Playwright launches as fallback, navigates the corporate site, finds the PDF link using heuristics, and downloads the file
  3. Passing a company's regulatory ID to the portal adapter for Supersalud (CO), SMV (PE), or CMF (CL) locates and downloads the most recent annual financial report PDF
  4. The dashboard accepts a manually uploaded PDF (drag & drop via `st.file_uploader`) and routes it through the same extraction pipeline as an automatically scraped PDF — no code divergence
  5. If no PDF is found via any path, the scraper returns a structured error (not an exception) with a clear message indicating what was attempted
**Plans**: TBD

Plans:
- [ ] 07-01-PLAN.md — latam_scraper.py: ddgs semantic search primary → Playwright fallback, PDF download to raw/, ThreadPoolExecutor wrapper; smoke test against one live corporate URL
- [ ] 07-02-PLAN.md — Regulatory portal adapters (Supersalud, SMV, CMF, SFC, CNV, CNBV) + drag & drop PDF upload handler in dashboard (st.file_uploader routing to same pipeline)

### Phase 8: PDF Extraction & KPI Mapping
**Goal**: Given a downloaded PDF (digital or scanned), the extractor returns structured financial data with page-level source tracking — mapped through the LATAM health sector CONCEPT_MAP to the 20-KPI schema — and latam_processor.py produces valid Parquet by reusing calculate_kpis() without modifying processor.py
**Depends on**: Phase 7
**Requirements**: PDF-01, PDF-02, PDF-03, PDF-04, KPI-01, KPI-03
**Success Criteria** (what must be TRUE):
  1. Running `latam_extractor.extract(pdf_path)` on a born-digital PDF returns a dict with balance sheet, P&L, and cash flow fields populated — verified against a real PDF from at least one of Supersalud (CO), SMV (PE), or CMF (CL)
  2. Running `latam_extractor.extract(pdf_path)` on a scanned-image PDF automatically activates the pytesseract OCR path and returns structured data without user intervention
  3. Every extraction result includes a confidence score (Alta / Media / Baja) and a source map — each extracted field records the page number and section heading where it was found in the PDF
  4. `latam_concept_map.py` maps at least 5 known Spanish healthcare revenue synonyms ("Ingresos por prestación de servicios", "Ventas de servicios de salud", "Ingresos operacionales", etc.) to the correct KPI schema field — validated against real extracted labels from at least one CO/PE/CL report
  5. Running `latam_processor.process(company)` produces `financials.parquet` and `kpis.parquet` with column names and dtypes identical to US output
**Plans**: TBD

Plans:
- [ ] 08-01-PLAN.md — latam_extractor.py: PyMuPDF triage → pdfplumber multi-column table extraction → pytesseract OCR fallback; page+section source tracking per field; confidence score; Tesseract startup validation
- [ ] 08-02-PLAN.md — latam_concept_map.py (health sector synonym dictionary) + latam_processor.py: field-to-schema mapping via CONCEPT_MAP, currency.to_usd() per field per year, calculate_kpis() reuse, atomic Parquet write

### Phase 9: Orchestration & Red Flags
**Goal**: LatamAgent orchestrates the full LATAM pipeline end-to-end (scrape → extract → normalize → process) mirroring the FinancialAgent interface, and the red flags engine automatically evaluates every processed company's KPIs against YAML-configurable healthcare thresholds
**Depends on**: Phase 8
**Requirements**: SCRAP-03, KPI-02, FLAG-01, FLAG-02
**Success Criteria** (what must be TRUE):
  1. Calling `LatamAgent(name, country, url).run()` on a company with no existing data runs the full pipeline end-to-end and produces valid `financials.parquet`, `kpis.parquet`, and `meta.json` without manual steps
  2. Calling `LatamAgent(name, country, url).run()` on a company whose data is current skips re-scraping and re-extraction — `needs_update()` mirrors the FinancialAgent staleness detection behavior
  3. After a successful pipeline run, the red flags engine evaluates all 20 KPIs and returns at least the mandatory flags (Deuda/EBITDA > 4x, FCO negativo con utilidad positiva, perdidas consecutivas >= 2 anos) with Alta/Media/Baja severity
  4. Changing a threshold in `config/red_flags.yaml` is reflected in the next pipeline run without modifying any Python file
  5. When `ddgs` web search returns no results (rate-limited or no matches), the pipeline completes successfully — web search is optional and degradable, not a blocking dependency
**Plans**: TBD

Plans:
- [ ] 09-01-PLAN.md — LatamAgent.py: orchestrate scrape→extract→process→save, needs_update() staleness detection, meta.json with company metadata and extraction quality; ddgs web_search.py wrapper with exponential backoff
- [ ] 09-02-PLAN.md — Red flags engine: FLAG evaluation against 20 KPIs, Alta/Media/Baja severity, YAML threshold file per sector (config/red_flags.yaml), ARS devaluation warning flag; validate against one real company's KPI output

### Phase 10: Human Validation Lite
**Goal**: Before any LATAM extraction is written to Parquet, the analyst sees the key financial values detected by the extractor and explicitly confirms or corrects them — creating a human checkpoint that compensates for the inherent uncertainty of LATAM PDF extraction vs. the structured SEC data of the US pipeline
**Depends on**: Phase 9
**Requirements**: VAL-01
**Success Criteria** (what must be TRUE):
  1. After `latam_extractor.extract()` completes, the dashboard displays a validation panel showing the four key detected values: Ingresos, Utilidad Neta, Total Activos, Deuda Total — each with its source page number and confidence score
  2. The analyst can edit any value directly in the validation panel before confirming — corrected values are flagged as "human-validated" in the metadata
  3. Clicking "Confirmar y guardar" writes the (possibly corrected) data to Parquet and proceeds to KPI calculation — the pipeline does not write to disk before this confirmation
  4. If the analyst closes the dashboard before confirming, no partial data is written — the extraction result is held in session state only
**Plans**: TBD

Plans:
- [ ] 10-01-PLAN.md — Validation panel UI: st.form with editable fields for 4 key values, source page display, confidence badge, "Confirmar y guardar" / "Descartar" buttons; session state management; human-validated flag in meta.json

### Phase 11: Dashboard & Report
**Goal**: The Streamlit dashboard has a dedicated LATAM section where an analyst can add a company by URL or PDF upload, view KPI cards with evidence links and a multi-currency toggle, see severity-coded red flags, and download a Claude-generated executive report as PDF — all without affecting the existing S&P 500 section
**Depends on**: Phase 10
**Requirements**: FX-03, RPT-01, RPT-02, RPT-03, DASHL-01, DASHL-02, DASHL-03, DASHL-04
**Success Criteria** (what must be TRUE):
  1. An analyst can enter a corporate URL (or drag & drop a PDF) in the LATAM section, click Run, pass the validation panel, and see KPI cards, trend charts, and severity-coded red flags rendered in the dashboard
  2. A currency toggle (Moneda Original / USD) switches all KPI values in the LATAM section; ARS companies show the exchange rate type (promedio anual) and a low-confidence warning
  3. Each KPI card in the LATAM section displays a "fuente: pág. X" indicator linking the displayed value back to the PDF page where it was extracted
  4. The executive report renders in the dashboard with four sections — Resumen de Gestión, KPIs destacados, Red Flags activas, Contexto Sectorial — with narrative text generated by Claude API (claude-opus-4-6) using the actual KPI and red flag data; includes 2-3 comparable companies from web search
  5. Clicking the Download PDF button produces a downloadable PDF of the executive report
  6. The S&P 500 section loads and operates correctly with all LATAM packages installed — no widget key collisions, no import errors, no regression (verified by explicit backward-compatibility test)
**Plans**: TBD

Plans:
- [ ] 11-01-PLAN.md — WeasyPrint spike (GTK3 via MSYS2 smoke test) or fallback to reportlab/fpdf2; Claude API report generator (claude-opus-4-6): narrative sections from KPI + red flags + ddgs comparables; HTML report template with static chart PNGs via kaleido
- [ ] 11-02-PLAN.md — app.py LATAM section: URL input + st.file_uploader drag & drop (key prefix latam_), LatamAgent.run() in st.spinner(), KPI cards + evidence page links + multi-currency toggle + red flag severity display; all LATAM imports lazy with try/except ImportError
- [ ] 11-03-PLAN.md — Backward-compatibility verification: S&P 500 smoke test with LATAM packages, widget key audit, LATAM import failure simulation, full pitfall checklist from PITFALLS.md

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Data Extraction | v1.0 | 2/2 | Complete | 2026-02-25 |
| 2. Transformation & KPIs | v1.0 | 2/2 | Complete | 2026-02-25 |
| 3. Orchestration & Batch | v1.0 | 3/3 | Complete | 2026-02-26 |
| 4. Dashboard | v1.0 | 3/3 | Complete | 2026-02-26 |
| 5. Scheduling | v1.0 | 2/2 | Complete | 2026-02-28 |
| 6. Foundation | v2.0 | 0/2 | Not started | - |
| 7. LATAM Scraper | v2.0 | 0/2 | Not started | - |
| 8. PDF Extraction & KPI Mapping | v2.0 | 0/2 | Not started | - |
| 9. Orchestration & Red Flags | v2.0 | 0/2 | Not started | - |
| 10. Dashboard & Report | v2.0 | 0/3 | Not started | - |
