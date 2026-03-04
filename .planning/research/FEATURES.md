# Feature Research: LATAM Financial Analysis Pipeline (v2.0)

**Domain:** Multi-source financial data pipeline — LATAM corporate financial reports (web + PDF) with currency normalization, KPI analysis, red flags, and executive reporting
**Researched:** 2026-03-03
**Confidence:** MEDIUM — table stakes and complexity well-grounded; ARS/currency fallback is LOW confidence pending API validation; regulatory portal structure is LOW confidence (portals differ by country)

> **Milestone context:** This is a subsequent milestone. The US pipeline (SEC EDGAR, 20 KPIs, Streamlit dashboard, Task Scheduler) is fully built. All features below are net-new for v2.0 and must integrate with the existing dashboard and KPI engine.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features that a professional analyst expects when using a LATAM financial analysis tool. Missing any of these breaks trust or makes the pipeline non-functional.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Web scraping to locate financial PDFs on corporate / regulatory portals | Core data acquisition — without it there is no LATAM pipeline | HIGH | Playwright handles JS-heavy portals; must handle login-free public portals; Supersalud, SMV, SFC, CMF, CNV, CNBV have different site structures |
| PDF text extraction (digital PDFs) | Most formal LATAM financial reports are digital PDFs (IFRS-compliant, audited) | MEDIUM | pdfplumber v0.11.8+ handles table detection including dashed lines; edge_min_length_prefilter solves subtle border issues |
| OCR fallback for scanned/image PDFs | Significant fraction of LATAM corporate PDFs are scanned or image-embedded | HIGH | pdfplumber alone fails on images; pymupdf + pytesseract required; accuracy 95-99% with good scans, degrades with poor quality |
| Balance sheet, P&L, and cash flow extraction | Three core statements are minimum for any KPI calculation | HIGH | Tables vary by layout: vertical vs horizontal, IFRS labels vs local labels, Spanish vs Portuguese column headers |
| Currency normalization to USD | KPI comparison across COP/PEN/CLP/ARS/MXN requires a common denomination | MEDIUM | frankfurter covers MXN only; COP, PEN, CLP, ARS require fallback API (exchangerate.host or equivalent); ARS has severe inflation/devaluation complexity |
| Company identification by name + country | LATAM companies are not ticker-identified; NIT (CO), RUC (PE), RUT (CL), CUIT (AR), RFC (MX) are the canonical IDs | MEDIUM | Registry maps company name + country → regulatory ID → portal search URL |
| KPI calculation reusing the existing 20-KPI engine | Analysts expect the same metrics they see for S&P 500 companies | MEDIUM | The existing processor.py engine must accept normalized USD figures from LATAM pipeline; adapter pattern required |
| LATAM section visible in the existing Streamlit dashboard | Single unified experience — two tabs or sections, not two apps | MEDIUM | app.py must gain a routing structure; LATAM section displays company name, country, source PDF, KPI cards |
| Red flags with severity classification | Any due diligence or credit analysis tool flags anomalies; severity (Alta/Media/Baja) is expected in LATAM professional context | MEDIUM | Thresholds based on healthcare sector benchmarks; current ratio < 1.0 is Alta, 1.0–1.5 is Media; interest coverage < 1.5 is Alta |
| Source attribution per extracted figure | Analysts need to verify numbers against the source PDF; trust breaks without this | LOW | Display: filename, page number, extraction method (digital/OCR), period, currency original + converted |
| IFRS vs local GAAP label awareness | Colombia, Chile, Peru, Mexico are IFRS-mandatory for regulated entities; Argentina allows local GAAP for SMEs | MEDIUM | Label the accounting standard on each company card; do not silently mix standards in comparisons |

### Differentiators (Competitive Advantage)

Features that elevate this tool above a manual "download PDF and enter numbers in Excel" workflow — which is what LATAM analysts currently do.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Regulatory portal web search via duckduckgo-search | Automatically finds the right regulatory source (Supersalud, SMV, SFC, CMF, CNV, CNBV) for a given company | MEDIUM | User inputs company name + country; system queries regulatory portal and returns direct PDF links; reduces discovery from hours to seconds |
| URL input as alternative to search | Expert users know the exact corporate or regulatory URL; accepting URL input makes the tool immediately usable without portal search | LOW | st.text_input() → Playwright navigates directly; bypasses duckduckgo-search step |
| Period average FX conversion (not spot) | Using year-end spot rate distorts historical comparisons; period average is the correct method for income statement items | MEDIUM | Requires querying daily rates for the full fiscal year and computing mean; separate logic for balance sheet (year-end) vs P&L (period average) |
| Executive PDF report with download button | Analysts produce deliverables; a formatted PDF export converts the tool from "analysis aid" to "deliverable generator" | HIGH | weasyprint converts HTML/CSS to PDF; Streamlit st.download_button() serves it; Plotly charts must be rendered as static images (weasyprint does not execute JS) |
| Severity-coded red flags with LATAM context | Generic thresholds (US healthcare benchmarks) misfire on LATAM companies; severity labels in Spanish (Alta/Media/Baja) match professional context | MEDIUM | Thresholds calibrated per sector and country where possible; flag: operating margin < 3% (Media), < 0% (Alta); current ratio < 1.0 (Alta) |
| Multi-year trend display for LATAM companies | Most LATAM tools show only the latest year; multi-year trend reveals deterioration or recovery | MEDIUM | Parquet store (same format as US pipeline) enables time-series display; requires consistent re-extraction across years |
| Extraction confidence score per statement | Shows analyst how reliable the extracted figures are (digital PDF = high, clean OCR = medium, degraded scan = low) | MEDIUM | Drives trust: low-confidence extractions shown with visual warning; analyst knows to manually verify |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Automatic login to gated regulatory portals | Some regulatory portals require registration (e.g., CMF Chile login) | Credential storage risk; session management complexity; legal gray area for automation | Flag gated portals to user; provide direct URL instructions; manual download fallback |
| Real-time or quarterly LATAM extraction | US pipeline has quarterly scheduling; natural to replicate for LATAM | LATAM companies publish annually (not quarterly on SEC schedule); scraping quarterly adds noise from interim/unaudited reports | Keep LATAM on annual cycle; note publication lags (LATAM companies often file 3-6 months after fiscal year end) |
| ARS inflation adjustment | Argentine peso inflation ~32% monthly in 2025; nominal figures seem meaningless | Inflation adjustment requires a deflator series (IPC) and introduces methodology disputes; project scope explicitly excludes inflation adjustments | Show nominal USD figures; note the devaluation context in a dashboard warning banner for ARS companies |
| Auto-translation of PDF content | PDFs in Spanish/Portuguese; tempting to translate labels for uniformity | Translation adds hallucination risk for financial terminology; "Resultados del Ejercicio" ≠ "Net Income" in all accounting frameworks | Map known Spanish/Portuguese financial labels to standard English keys via lookup dictionary; do not LLM-translate |
| Generic PDF scraping beyond financial statements | Some portals expose audit reports, ESG reports, governance filings | Out-of-scope content bloats storage and confuses extraction; audit report tables look like financial statement tables | Filter by filename pattern (estados financieros, balance, informe financiero) and file size; skip non-financial documents |
| Cross-company LATAM comparison screener | US pipeline has a multi-company comparison view; natural to replicate | LATAM companies are not a homogeneous universe; mixing Colombian healthcare EPS with Chilean AFP is misleading | Provide single-company deep analysis; allow explicit side-by-side when user selects same-country same-sector companies |
| Stock price / market cap for LATAM companies | Most target companies are not publicly listed; no ticker available | Data simply does not exist for private/mixed companies; valuation multiples (P/E, EV/EBITDA) are not computable | Display only computable KPIs from financial statements; clearly label that valuation multiples are unavailable for non-listed entities |

---

## Feature Dependencies

```
[EXISTING] 20-KPI Engine (processor.py)
    └──adapter──> [NEW] LATAM KPI Adapter
                      └──requires──> [NEW] Normalized USD Financial Data (Parquet)
                                         └──requires──> [NEW] Currency Normalizer (FX API)
                                         └──requires──> [NEW] PDF Extractor (pdfplumber + pytesseract + pymupdf)
                                                             └──requires──> [NEW] Web Scraper (Playwright)
                                                             └──requires──> [NEW] Company Registry LATAM

[NEW] Company Registry LATAM
    └──feeds──> [NEW] Regulatory Web Search (duckduckgo-search)
                    └──feeds──> [NEW] Web Scraper (Playwright) → PDF download

[NEW] LATAM KPI Adapter
    └──feeds──> [NEW] Red Flags Engine
    └──feeds──> [EXISTING] Dashboard (app.py) via [NEW] LATAM Section

[NEW] Red Flags Engine
    └──feeds──> [NEW] Executive Report Generator (weasyprint)
    └──feeds──> [NEW] LATAM Dashboard Section

[NEW] Executive Report Generator
    └──requires──> [NEW] Red Flags Engine
    └──requires──> [NEW] LATAM KPI Adapter (computed KPIs)
    └──requires──> [NEW] Normalized USD Financial Data (rendered charts as static images)
```

### Dependency Notes

- **PDF Extractor requires Web Scraper:** You cannot extract from a PDF you have not found and downloaded. Scraper must run first and deposit PDFs to a local staging area.
- **Currency Normalizer requires fiscal year detection:** The normalizer must know the fiscal period (calendar year vs non-December year end) before it can query the correct date range for period average rates. Fiscal period comes from PDF extraction.
- **LATAM KPI Adapter requires the 20-KPI Engine to remain untouched:** The adapter translates LATAM field names (Activo Corriente → current_assets) into the schema the existing processor.py expects. The engine itself is not modified — preserving the US pipeline.
- **Red Flags Engine requires KPIs:** It consumes computed KPI values, not raw financials. It cannot run before the LATAM KPI Adapter.
- **Executive Report requires static chart images:** weasyprint does not execute JavaScript. Plotly charts must be exported as PNG via kaleido or plotly.io.write_image() before being embedded in the HTML report template.
- **Dashboard LATAM Section requires all upstream:** It is the final consumer. It displays company metadata, extracted financials, KPIs, red flags, and the report download button.

---

## MVP Definition

### Launch With (v2.0 core)

Minimum scope to validate the LATAM pipeline end-to-end with a single company.

- [ ] Playwright scraper navigates a known URL (corporate or regulatory portal) and downloads the annual financial report PDF — validates the acquisition layer
- [ ] pdfplumber extracts balance sheet and P&L tables from a digital PDF — validates the extraction layer for the happy path
- [ ] pytesseract OCR fallback activates when pdfplumber returns empty tables — validates scanned PDF handling
- [ ] LATAM field-name mapper translates Spanish financial labels to standard schema fields — validates normalization
- [ ] Currency normalizer converts one LATAM currency to USD using period average rate — validates FX layer
- [ ] LATAM KPI Adapter feeds existing 20-KPI engine and produces KPI output for one company — validates pipeline integration
- [ ] Red flags engine evaluates KPIs against healthcare thresholds and outputs severity-coded alerts — validates alert logic
- [ ] LATAM section appears in Streamlit dashboard showing one company's KPIs and red flags — validates UI integration
- [ ] Company registry supports at least CO + PE + CL entries with NIT / RUC / RUT mapping — validates identifier layer

### Add After Validation (v2.x)

Features to add once the single-company end-to-end pipeline is confirmed working.

- [ ] Regulatory web search (duckduckgo-search) — add once manual URL input is working; search is an enhancement, not a prerequisite
- [ ] Executive PDF report download — add after KPI and red flag display is stable; weasyprint + static chart images is a self-contained feature
- [ ] Multi-year storage and trend display — add after single-year extraction is reliable; requires consistent label mapping across years
- [ ] Extraction confidence score — add after both extraction paths (digital + OCR) are working and producing measurable quality signals
- [ ] AR (Argentina) + MX (Mexico) company support — add after CO + PE + CL baseline works; ARS devaluation warning banner required before enabling

### Future Consideration (v3+)

- [ ] Firecrawl / Tavily API integration — defer; project explicitly scopes these to v3.0 (paid APIs, not needed for MVP)
- [ ] Cross-country LATAM screener — defer until enough companies are registered to make comparison meaningful
- [ ] Automated quarterly re-extraction — defer; LATAM companies publish annually; premature automation before annual cycle is validated adds complexity
- [ ] Login to gated regulatory portals — defer; credential management is a separate security concern; manual download fallback is acceptable for now

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Playwright web scraper (URL input) | HIGH | MEDIUM | P1 |
| pdfplumber digital PDF extraction | HIGH | MEDIUM | P1 |
| pytesseract OCR fallback | HIGH | HIGH | P1 |
| Spanish label → standard schema mapper | HIGH | MEDIUM | P1 |
| Currency normalizer (MXN via frankfurter; COP/PEN/CLP via exchangerate.host; ARS with warning) | HIGH | MEDIUM | P1 |
| Company registry LATAM (name + country + regulatory ID) | HIGH | LOW | P1 |
| LATAM KPI Adapter (feeds existing 20-KPI engine) | HIGH | MEDIUM | P1 |
| Red flags engine (severity Alta/Media/Baja) | HIGH | MEDIUM | P1 |
| LATAM section in Streamlit dashboard | HIGH | MEDIUM | P1 |
| Regulatory web search (duckduckgo-search) | MEDIUM | MEDIUM | P2 |
| Executive PDF report (weasyprint + download button) | MEDIUM | HIGH | P2 |
| Multi-year trend display for LATAM companies | MEDIUM | MEDIUM | P2 |
| Extraction confidence score | MEDIUM | MEDIUM | P2 |
| ARS devaluation warning banner | LOW | LOW | P2 |
| IFRS vs local GAAP label on company card | LOW | LOW | P2 |

**Priority key:**
- P1: Must have for v2.0 pipeline to work end-to-end
- P2: Should have; adds significant value, add when P1 pipeline is stable
- P3: Nice to have; future consideration

---

## LATAM-Specific Nuances

These are not standard features in financial pipeline research — they are unique constraints that affect every feature in this milestone.

### PDF Quality Variance

LATAM corporate financial reports range from:
- **High quality:** IFRS-audited, digital PDF, structured tables, clear column headers — pdfplumber extracts cleanly
- **Medium quality:** Digital PDF but non-standard layout (multi-column, merged cells, footnotes embedded in table rows) — pdfplumber requires tuning; edge_min_length_prefilter helps
- **Low quality:** Scanned document or image-embedded PDF — pytesseract required; accuracy degrades with scan quality; manual verification warranted; extraction confidence score should be LOW

Regulatory portal PDFs (Supersalud, SMV, SFC, CMF, CNV, CNBV) tend to be higher quality than directly published corporate website PDFs. Prioritize regulatory sources over corporate website PDFs where available.

### Multi-Currency Complexity

| Currency | Frankfurter Support | Fallback | Special Notes |
|----------|--------------------|---------|-|
| MXN | YES (ECB data) | — | Reliable; use frankfurter directly |
| CLP | NO | exchangerate.host | ECB does not track CLP; requires alternative API |
| COP | NO | exchangerate.host | ECB does not track COP; requires alternative API |
| PEN | NO | exchangerate.host | ECB does not track PEN; requires alternative API |
| ARS | NO | exchangerate.host | HIGH RISK: Argentina had 54%+ devaluation Dec 2023; ongoing crawling peg; period average is valid but produces very different results year-over-year; display warning to user |

**Confidence: LOW** for ARS conversion reliability — the ARS-USD rate data from free APIs may not reflect the official/unofficial dual-rate system that existed in 2023-2024. Validate against Banco Central de la República Argentina data before using ARS KPIs for credit decisions.

Annual average calculation: Neither frankfurter nor exchangerate.host provides a pre-computed annual average. Must query daily rates for the fiscal year period and compute mean in Python. For a 365-day year this is ~365 API calls or a timeseries request (exchangerate.host supports up to 365-day ranges per request, one call per year).

### Accounting Standard Variance

| Country | Standard for Listed/Regulated Entities | SMEs / Private |
|---------|----------------------------------------|----------------|
| Colombia | IFRS (mandatory since 2015 for regulated entities; Supersalud requires) | IFRS for SMEs or local GAAP |
| Peru | IFRS (mandatory for SMV-registered entities) | IFRS for SMEs with local modifications |
| Chile | IFRS (mandatory since 2009; CMF requires) | IFRS for SMEs |
| Mexico | IFRS (CNBV-regulated entities; NIF for others) | Mexican Financial Reporting Standards (NIF) — similar to IFRS but distinct |
| Argentina | IFRS (publicly traded companies); RT (Resoluciones Técnicas) for others | Local GAAP via FACPCE RT |

**Implication:** Healthcare companies with regulatory obligation (primary target sector) are almost always required to use IFRS or IFRS for SMEs. Balance sheet and P&L line item names will be IFRS-standard in Spanish. The Spanish label mapper should cover IFRS Spanish terminology first; local GAAP labels are secondary.

### Regulatory Portal Characteristics

| Regulator | Country | Coverage | Portal Type | Access |
|-----------|---------|----------|-------------|--------|
| Supersalud | Colombia | Health insurers (EPS), hospitals | docs.supersalud.gov.co | Public PDFs, no login |
| SFC | Colombia | Financial sector (banks, insurers) | superfinanciera.gov.co | Public, structured portal |
| SMV | Peru | Securities market participants | smv.gob.pe/SIMV | Public, structured portal with company search |
| CMF | Chile | Financial market (banks, insurers, issuers) | cmfchile.cl | Requires registration for some documents |
| CNV | Argentina | Securities issuers | cnv.gob.ar | Public, but portal structure changes frequently |
| CNBV | Mexico | Banks, brokerage firms | cnbv.gob.mx | Public statistics; individual company filings may require navigation |

**Confidence: LOW** for portal-specific scraping patterns — site structures change; Playwright scripts will need to be validated against live portals and may require maintenance. Recommend building a portal adapter layer where each regulator has its own scraping strategy.

### Red Flags Thresholds (Healthcare Sector Reference)

Based on HFMA benchmarks and LATAM healthcare sector research:

| KPI | Alta (Critical) | Media (Warning) | Baja (Watch) |
|-----|----------------|-----------------|--------------|
| Current ratio | < 1.0 | 1.0 – 1.5 | 1.5 – 2.0 |
| Debt/Equity | > 2.0 | 1.0 – 2.0 | 0.8 – 1.0 |
| Interest coverage | < 1.5 | 1.5 – 2.5 | 2.5 – 3.5 |
| Operating margin | < 0% | 0% – 3% | 3% – 5% |
| Net margin | < -5% | -5% – 0% | 0% – 2% |
| Revenue growth YoY | < -10% | -10% – 0% | 0% – 3% |

**Confidence: MEDIUM** — thresholds calibrated for US healthcare; LATAM healthcare companies operate with different leverage norms (higher debt ratios common in infrastructure-heavy health systems). Consider making thresholds configurable in a YAML file so they can be tuned without code changes.

---

## Dependencies on Existing Features

| Existing Feature | How v2.0 Depends On It |
|-----------------|------------------------|
| 20-KPI calculation engine (processor.py) | LATAM KPI Adapter feeds normalized financial data into this engine; engine is not modified |
| Parquet storage format (data/clean/{TICKER}/) | LATAM uses same format at data/latam/{NOMBRE_PAIS}/; same read/write patterns |
| Streamlit dashboard (app.py) | LATAM section is added as a new tab/section; existing US section is not modified |
| FinancialAgent orchestrator (agent.py) | LATAM pipeline uses same orchestrator interface with a different adapter; staleness detection reused |
| loguru logging | All LATAM pipeline components use loguru for consistency |
| Windows Task Scheduler quarterly automation | LATAM extraction can be added to the same scheduler job (annual cycle); or separate job |

---

## Sources

- pdfplumber 0.11.8 table-AI update: [BrightCoding](https://www.blog.brightcoding.dev/2025/11/26/finance-bros-are-obsessed-with-this-0-11-8-update-pdfplumbers-new-table-ai-trick-explained/)
- PDF extraction comparison (2025): [Medium — 7 Python PDF extractors tested](https://onlyoneaman.medium.com/i-tested-7-python-pdf-extractors-so-you-dont-have-to-2025-edition-c88013922257)
- Financial PDF extraction challenges: [Seattle Data Guy](https://www.theseattledataguy.com/challenges-you-will-face-when-parsing-pdfs-with-python-how-to-parse-pdfs-with-python/)
- Playwright file downloads: [Marketing Scoop](https://www.marketingscoop.com/tech/web-scraping/playwright-how-to-download-file-with-playwright/)
- Playwright scraping guide 2025: [Oxylabs](https://oxylabs.io/blog/playwright-web-scraping)
- Frankfurter API (ECB-sourced, MXN supported): [frankfurter.dev](https://frankfurter.dev/)
- Frankfurter currency gap — COP/PEN/CLP/ARS not supported: [GitHub issue #144](https://github.com/lineofflight/frankfurter/issues/144)
- exchangerate.host timeseries API: [exchangerate.host documentation](https://exchangerate.host/documentation)
- LATAM IFRS adoption — Colombia 2015, Chile 2009, Peru adopted: [MDPI IFRS LATAM study](https://www.mdpi.com/1911-8074/18/10/567)
- Mexico CNBV IFRS S1/S2 mandatory 2026: [GA Institute](https://ga-institute.com/Sustainability-Update/new-sustainability-reporting-requirements-in-mexico/)
- ARS devaluation history and 2025 crawling peg: [EBC Financial Group](https://www.ebc.com/forex/usd-to-ars-outlook-how-argentina-s-fx-reform-changes-trading)
- Argentina inflation 2025 (32.4% monthly peak): [TradingEconomics](https://tradingeconomics.com/argentina/inflation-cpi)
- LATAM regulatory IDs (NIT, RUC, RUT, CUIT, RFC): [Microsoft Dynamics 365 LATAM tax ID documentation](https://learn.microsoft.com/en-us/dynamics365/finance/localizations/iberoamerica/ltm-core-tax-id-type)
- Healthcare KPI thresholds: [HFMA](https://www.hfma.org/revenue-cycle/financial-kpis-redefined-in-healthcare/), [Definitive HC liquidity analysis](https://www.definitivehc.com/resources/healthcare-insights/hospital-liquidity)
- Supersalud portal: [supersalud.gov.co](https://www.supersalud.gov.co/)
- SMV Peru portal: [smv.gob.pe/SIMV](https://www.smv.gob.pe/SIMV/)
- WeasyPrint Streamlit integration: [Medium — PDF in 3 steps](https://medium.com/@karanshingde/download-your-streamlit-data-dashboard-as-a-pdf-report-in-3-steps-97e09ed65558)
- WeasyPrint JS limitation (confirmed, does not execute JS): [DEV Community](https://dev.to/thawkin3/docraptor-vs-weasyprint-a-pdf-export-showdown-34f)

---

*Feature research for: LATAM Financial Analysis Pipeline (v2.0)*
*Researched: 2026-03-03*
