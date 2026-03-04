# Project Research Summary

**Project:** LATAM Financial Analysis Pipeline (v2.0)
**Domain:** Additive ETL pipeline — LATAM corporate PDF extraction, currency normalization, KPI analysis, red flags, and executive reporting layered onto an existing Python/Streamlit financial dashboard
**Researched:** 2026-03-03
**Confidence:** MEDIUM-HIGH (stack and architecture HIGH; currency coverage and regulatory portal patterns LOW)

## Executive Summary

The v2.0 LATAM pipeline is an additive extension to an already-validated US S&P 500 financial analysis dashboard. The core design principle across all four research areas is strict isolation: every new LATAM module runs alongside its US counterpart without touching existing code. The existing `processor.py`, `scraper.py`, `agent.py`, and the S&P 500 section of `app.py` are never modified — only the dashboard gains a new LATAM section. This pattern reduces integration risk to a known surface area (`app.py` modifications and `requirements.txt`) and ensures that if the LATAM pipeline breaks, the US pipeline keeps working.

The recommended technical approach uses Playwright for headless JavaScript scraping, a tiered PDF extraction stack (pdfplumber for tables, PyMuPDF for text triage and page-to-image, pytesseract for OCR fallback), and a two-tier FX normalizer (Frankfurter for BRL/MXN, a secondary free API for ARS/CLP/COP/PEN). The build order is strictly bottom-up: `currency.py` first (no dependencies, testable immediately with static inputs), then `web_search.py`, then the scraper, then the extractor, then the processor, then the `LatamAgent` orchestrator, and finally the dashboard section. Each layer is testable independently before the next is built.

The primary risks cluster around three Windows-specific system integrations: Playwright's event-loop conflict with Streamlit's Tornado server (must be thread-isolated via `ThreadPoolExecutor`), WeasyPrint's GTK3 dependency via MSYS2 (non-trivial Windows install with a viable fallback to `reportlab` or `fpdf2`), and pytesseract's Tesseract binary dependency (must be explicitly path-configured, not PATH-reliant). A critical data-integrity risk is the Frankfurter API's currency coverage gap: it only covers BRL and MXN of the six target LATAM currencies. ARS, CLP, COP, and PEN are absent — using Frankfurter alone silently produces `None` for all normalized financials for four of six countries, with no runtime error raised. The tiered FX fallback must be implemented before any LATAM Parquet data is written.

## Key Findings

### Recommended Stack

The v1.0 stack (edgartools, Streamlit, Plotly, Pandas, PyArrow, loguru, Windows Task Scheduler) is unchanged. Six new packages are added for v2.0, with two system-level binary dependencies.

**Core technologies (new):**
- `playwright>=1.48`: Headless Chromium scraping — the only free Python library handling JS-rendered corporate IR pages; requires `playwright install chromium` as a separate post-pip binary download step
- `PyMuPDF>=1.24` (imported as `fitz`): Fast PDF triage and page-to-image rendering at 300 DPI for OCR pre-processing; used as first pass before pdfplumber to classify scanned vs. digital PDFs
- `pdfplumber>=0.11`: Bounding-box table extraction from born-digital PDFs; complement to PyMuPDF for structured table detection, not a replacement
- `pytesseract>=0.3.13`: OCR fallback via Tesseract 5 binary; requires separate UB Mannheim Windows installer with Spanish (`spa`) and Portuguese (`por`) language packs installed explicitly
- `ddgs>=9.0`: Free DuckDuckGo web search for regulatory source discovery; renamed successor to `duckduckgo-search` — the old package name now shows RuntimeWarning and will eventually break
- `weasyprint>=68.0`: HTML-to-PDF executive report generation; requires MSYS2 and GTK3/Pango on Windows; `reportlab` or `fpdf2` are valid pure-Python fallbacks if GTK install proves unworkable

**Currency API (no new package):**
- Frankfurter API (`api.frankfurter.dev/v1/`) via existing `requests`: Free, ECB-backed, no key required; covers BRL and MXN only — CLP, COP, PEN, ARS require a secondary free API (open.er-api.com or exchangerate.host); annual average must be computed from the daily timeseries endpoint, not a built-in average endpoint

See `.planning/research/STACK.md` for full version table, installation commands, and Windows-specific gotchas including the Playwright event-loop conflict, PyMuPDF import name quirk, and WeasyPrint MSYS2 setup.

### Expected Features

The research separates v2.0 features into a tight P1 core (end-to-end pipeline for a single company) and a P2 enhancement layer to add once the core is stable.

**Must have — v2.0 P1 core (table stakes):**
- Web scraper accepting a direct corporate or regulatory URL and downloading the annual financial report PDF
- PDF text and table extraction with both digital and OCR paths — both required from day one; 30-50% of LATAM health sector PDFs are scanned image documents
- Spanish/Portuguese financial label mapper translating IFRS labels (Activo Corriente, Ingresos, etc.) to the existing `processor.py` KPI schema field names; IFRS terminology first, local GAAP labels secondary
- Currency normalizer with tiered FX fallback (Frankfurter for BRL/MXN, secondary API for ARS/CLP/COP/PEN); period-average rates for income statement items
- Company registry mapping name + country to regulatory ID (NIT/RUC/RUT/CUIT/RFC) and regulatory authority
- LATAM KPI adapter feeding the existing 20-KPI engine via `processor.calculate_kpis()` without modifying `processor.py`
- Red flags engine with Alta/Media/Baja severity classification using healthcare sector KPI thresholds
- LATAM section in the existing Streamlit dashboard displaying company cards, KPIs, and severity-coded red flags

**Should have — v2.x additions (differentiators):**
- Regulatory web search via `ddgs` to discover the correct portal URL for a given company + country (enhances the scraper; direct URL input works without it)
- Executive PDF report download via WeasyPrint + `st.download_button` (Plotly charts must be exported as static PNGs via kaleido before embedding — WeasyPrint does not execute JavaScript)
- Multi-year trend display (Parquet storage pattern already enables this once extraction is stable)
- Extraction confidence score (HIGH/MEDIUM/LOW) surfaced in the UI per extracted financial statement
- ARS devaluation warning banner for Argentine companies

**Defer to v3+:**
- Automated login to gated regulatory portals (credential storage risk, legal ambiguity)
- Cross-country LATAM screener (meaningful only with enough registered companies for comparison)
- Firecrawl/Tavily API integration (paid, explicitly out of scope per PROJECT.md)
- Automated quarterly LATAM re-extraction (LATAM companies publish annually; premature before annual cycle is validated)

See `.planning/research/FEATURES.md` for full prioritization matrix, feature dependency graph, multi-currency complexity table, accounting standard variance by country, and regulatory portal characteristics per regulator.

### Architecture Approach

The architecture uses a parallel-modules pattern: every new LATAM module mirrors its US counterpart in name and responsibility but never modifies the original. `LatamAgent.py` exposes the same `run()` / `needs_update()` interface as `FinancialAgent`, so `app.py` calls both pipelines with identical patterns. LATAM data lands in `data/latam/{country}/{slug}/` — a separate directory tree — with `financials.parquet` and `kpis.parquet` that are schema-identical to US output (all monetary values in USD, missing fields as `NaN` not `0`). The same dashboard loaders, chart builders, and KPI comparisons work on both datasets without branching.

**Major components (all new):**
1. `currency.py` — stateless FX normalizer; Frankfurter primary + secondary API fallback; `lru_cache` + disk cache at `data/cache/fx_rates.json` to avoid repeated API calls per fiscal year
2. `web_search.py` — `ddgs` wrapper for regulatory source discovery; treats search results as optional/degradable; retry with exponential backoff on `RatelimitException`
3. `latam_scraper.py` — Playwright scraper isolated in `ThreadPoolExecutor`; navigates corporate/regulatory URLs, finds PDF links, downloads to `data/latam/{country}/{slug}/raw/`
4. `latam_extractor.py` — three-mode extraction pipeline: PyMuPDF text triage (fast, classifies scanned vs. digital) → pdfplumber table extraction (born-digital PDFs) → pytesseract OCR (scanned PDFs at 300 DPI); returns `{fiscal_year: {field: (value, currency_code)}}`
5. `latam_processor.py` — maps extracted fields to KPI schema; calls `currency.to_usd()` per field per year; calls `processor.calculate_kpis()` directly (no duplicated KPI logic); writes atomic Parquet
6. `LatamAgent.py` — orchestrator mirroring `FinancialAgent` interface; coordinates scrape → extract → process → save; writes `meta.json` with company metadata and extraction quality
7. `app.py` (modified, additive only) — adds LATAM section with `latam_`-namespaced widget keys; all LATAM imports are lazy (inside functions, not at module top level); `st.cache_data.clear()` after ETL completes

**Key patterns:**
- Schema compatibility contract: LATAM Parquet output must match US column names and dtypes exactly; FX metadata stored in `meta.json`, not in Parquet columns
- Lazy imports in `app.py`: GTK or Playwright import failure must not break the S&P 500 section
- Slug-based storage paths: `unicodedata.normalize("NFKD")` + ASCII encode + lowercase before any company name is used as a directory segment (Windows NTFS Unicode encoding issues with Spanish/Portuguese characters)
- Thread isolation for Playwright: always via `concurrent.futures.ThreadPoolExecutor`; never from the Streamlit main thread

See `.planning/research/ARCHITECTURE.md` for full component responsibility table, annotated build order, data flow diagrams for both pipelines, storage schema definitions, and four documented anti-patterns with explanations.

### Critical Pitfalls

1. **Playwright sync API crashes inside Streamlit's asyncio loop** — on Windows 11 this is a double failure: Playwright's synchronous API detects the running event loop and refuses to execute, compounded by Streamlit's Tornado server using `SelectorEventLoop` while Playwright requires `ProactorEventLoop` for subprocess communication. Manifests as `NotImplementedError` or a silent hang. Prevention: always call the Playwright scraper via `ThreadPoolExecutor`; validate this thread-isolation pattern in Phase 1 with a smoke test from a Streamlit button click before writing any scraping logic.

2. **Frankfurter API silently returns nothing for ARS, CLP, COP, PEN** — these four currencies are absent from ECB tracking; calls return HTTP 422 or `{"message": "not found"}` which, if not explicitly handled, causes the normalizer to return `None` for all financial figures for four of six target countries with no runtime exception. Prevention: implement the tiered FX fallback before writing any normalized Parquet data; unit-test all six LATAM currency codes against the normalizer before Phase 3 is considered done.

3. **Scanned PDFs return empty strings without OCR fallback** — 30-50% of LATAM health sector PDFs are image-embedded; `pdfplumber.extract_text()` returns `""` without error for these documents. Prevention: implement the OCR fallback from day one using a character-count heuristic (fewer than 50 chars triggers OCR path); never defer OCR as a "future enhancement" — it must be part of the initial extractor design.

4. **WeasyPrint fails at `write_pdf()` time with GTK DLL errors** — `import weasyprint` succeeds even when GTK3 DLLs are missing; the crash only surfaces at the first actual `write_pdf()` call. Prevention: run `weasyprint.HTML(string="<p>test</p>").write_pdf()` end-to-end on the actual Windows machine before building any report templates. If MSYS2/GTK3 install fails, commit to `reportlab` or `fpdf2` (both pure-Python, no system dependencies) in the same session.

5. **Top-level LATAM imports in `app.py` break the S&P 500 section** — if any LATAM package fails to load (missing GTK for WeasyPrint, missing Playwright browser binaries), the entire `app.py` module fails to import and the S&P 500 section becomes unavailable. Prevention: all LATAM-specific `import` statements must be lazy (inside the function that uses them) with `try/except ImportError` showing a setup-instructions panel rather than crashing.

See `.planning/research/PITFALLS.md` for all 12 documented pitfalls with code-level prevention patterns, warning signs, recovery cost estimates, and a pitfall-to-phase assignment table.

## Implications for Roadmap

Based on the hard dependency chain from ARCHITECTURE.md and the pitfall-to-phase mapping in PITFALLS.md, six phases are recommended. The ordering follows the build dependency graph: foundational infrastructure first (modules with no dependencies), data acquisition second, data transformation third, analysis fourth, reporting fifth, and dashboard integration last. This ordering ensures each phase has real output to test against, and that the highest-risk Windows integrations are validated before significant template or UI work is built on top of them.

### Phase 1: Foundation — Environment, Scraper Infrastructure, and FX Layer

**Rationale:** Three pitfalls (Playwright asyncio conflict, browser binaries missing, Spanish slug path errors) must be resolved before any other LATAM code is written. The FX normalizer and web search wrapper have zero dependencies on other LATAM modules and can be built and fully unit-tested here in isolation. The storage directory structure and slug convention must be locked in before any Parquet files are written — retrofitting path conventions after data is saved requires a migration.
**Delivers:** Working Playwright scraper thread-isolated in `ThreadPoolExecutor` (smoke-tested from a Streamlit button), `currency.py` with tiered FX fallback validated for all six LATAM currencies (unit tests for MXN, BRL, ARS, CLP, COP, PEN), `web_search.py` with rate-limit retry and cache, `make_slug()` function tested against Spanish/Portuguese names with accents and special characters, `data/latam/` directory structure defined.
**Addresses:** Web scraper (URL input), company registry foundation, currency normalizer (all P1 features)
**Avoids:** Playwright + asyncio crash (Pitfall 1), missing browser binaries (Pitfall 2), slug/path OSError on Spanish characters (Pitfall 9), silent FX currency coverage gaps (Pitfall 5)
**Research flag:** Playwright thread-isolation pattern is well-documented — standard implementation. The secondary FX API (open.er-api.com) should be empirically validated for rate limits and ARS data accuracy against BCRA official rates during implementation.

### Phase 2: PDF Extraction Pipeline

**Rationale:** The extractor depends on real downloaded PDFs from Phase 1; it cannot be meaningfully built or tested against synthetic inputs. This is the highest-complexity phase: three extraction modes must work correctly, the OCR fallback must be present from day one (not deferred), and the country-adapter pattern must be established before a single extraction function is committed — retrofitting a universal parser to handle per-country structural differences costs more than building the adapter pattern correctly from the start.
**Delivers:** `latam_extractor.py` with three-mode pipeline (PyMuPDF triage → pdfplumber tables → pytesseract OCR at 300 DPI); startup validation that Tesseract binary exists and `spa` language pack is installed; extraction confidence score per statement; per-country adapter stubs for CO, PE, CL; tested against at least one real PDF from each of those three countries.
**Uses:** PyMuPDF (`fitz`), pdfplumber, pytesseract, langdetect, Pillow
**Avoids:** Scanned PDFs returning empty (Pitfall 6), pytesseract `TesseractNotFoundError` (Pitfall 3), wrong-tool pdfplumber vs. PyMuPDF confusion (Pitfall 8), IFRS vs. local GAAP structural failures (Pitfall 12)
**Research flag:** Needs per-country calibration on real PDFs from Supersalud (CO), SMV (PE), CMF (CL). Regulatory portal URL structure is LOW confidence — validate live portal accessibility before committing portal-specific scraper logic. Budget extra time for country calibration; this phase has the highest probability of schedule variance.

### Phase 3: Data Transformation and KPI Integration

**Rationale:** `latam_processor.py` depends on extractor output (Phase 2) and the FX layer (Phase 1); it cannot be built or meaningfully tested before both are complete. This is where the schema compatibility contract is enforced. The `LatamAgent` orchestrator ties all upstream modules together and produces the first complete end-to-end pipeline run for one real company.
**Delivers:** `latam_processor.py` mapping extracted fields to the 24-column financial schema with USD normalization per field per year; `LatamAgent.py` orchestrating scrape → extract → process → save and mirroring `FinancialAgent` interface; `meta.json` with company metadata and extraction quality; end-to-end pipeline producing valid `financials.parquet` and `kpis.parquet` for one real LATAM healthcare company, with KPI output verified for plausibility.
**Implements:** Schema compatibility contract (identical column schema as US output), LatamAgent mirrors FinancialAgent pattern, currency normalization as pure function with caching
**Avoids:** Modifying `processor.py` (Architecture Anti-Pattern 1), using different Parquet schema for LATAM (Anti-Pattern 2), storing LATAM data under `data/clean/` (Anti-Pattern 3), silent FX failures for COP/PEN/CLP/ARS (Pitfall 5 — final verification)
**Research flag:** `ddgs` rate-limit behavior (Pitfall 7) should be integration-tested here; confirm that pipeline succeeds when DDGS returns no results. The web search step must be optional and degradable, never a blocking dependency.

### Phase 4: Red Flags Engine

**Rationale:** The red flags engine consumes computed KPI values and cannot run before Phase 3 produces them. Separating it into its own phase ensures threshold configuration (YAML, not hardcoded) is designed as a first-class concern rather than an afterthought. The LATAM healthcare calibration is a distinct domain concern from data transformation.
**Delivers:** Red flags engine evaluating the 20 KPIs against Alta/Media/Baja thresholds; configurable YAML threshold file per sector; severity-coded output consumed by both the dashboard section and the executive report; validated against at least one real company's KPI output; ARS devaluation warning flag surfaced when currency is ARS.
**Addresses:** Red flags with severity classification (P1), IFRS vs. local GAAP label on company card (P2)
**Research flag:** Healthcare threshold calibration is MEDIUM confidence per FEATURES.md — current thresholds are derived from US HFMA benchmarks. Flag this explicitly in the YAML file comments as an approximation that requires LATAM-specific calibration. Standard implementation otherwise.

### Phase 5: Executive PDF Report

**Rationale:** The PDF report is a self-contained P2 deliverable feature that depends on stable KPIs and red flags from Phases 3-4. It is isolated here because the WeasyPrint GTK dependency requires a hard go/no-go decision before any template work begins. Plotly charts must be exported as static PNGs before embedding, since WeasyPrint does not execute JavaScript.
**Delivers:** WeasyPrint validated end-to-end with `write_pdf()` on the actual Windows machine (or explicit documented decision to use `reportlab`/`fpdf2` instead); HTML report template with company overview, KPI table, red flags section, and embedded Plotly chart PNGs (via kaleido or `plotly.io.write_image`); `st.download_button` wired to PDF bytes in the dashboard.
**Uses:** WeasyPrint (or reportlab/fpdf2 fallback), Plotly + kaleido for static chart export
**Avoids:** WeasyPrint GTK DLL failure discovered mid-template-build (Pitfall 4) — validate `write_pdf()` smoke test as the first action of this phase, not `import weasyprint`
**Research flag:** WeasyPrint Windows GTK3 is MEDIUM confidence. Treat Phase 5 session 1 as a validation spike: install, test `write_pdf()`, decide. If MSYS2/GTK fails, switch to `reportlab` or `fpdf2` (1-2 hours for switch, simpler CSS support is acceptable for a text+table financial report). Do not build templates until the library decision is final.

### Phase 6: Dashboard Integration

**Rationale:** The LATAM section in `app.py` is last because it requires Parquet data from the full pipeline and a stable `LatamAgent` interface. All integration pitfalls (widget key collisions, backwards-compatibility import breaks) are guarded at this phase. This phase is additive only — the S&P 500 section is never modified.
**Delivers:** `app.py` with LATAM section (URL input widget, `LatamAgent.run()` call wrapped in `st.spinner()` with stage progress, company card display, red flag display with severity colors, PDF download button); all new widget keys prefixed `latam_`; all LATAM imports lazy with `try/except ImportError` showing setup instructions; `st.cache_data` cleared after ETL completes; S&P 500 section confirmed working with LATAM packages uninstalled.
**Addresses:** LATAM section in Streamlit dashboard (P1), URL input alternative to search (P2 differentiator), ARS devaluation warning banner (P2)
**Avoids:** Widget `DuplicateWidgetID` from key collisions (Pitfall 10), backward-compatibility import breaks (Pitfall 11), 30-120 second blocking ETL call freezing the browser tab (Architecture Anti-Pattern 4)
**Research flag:** Standard Streamlit patterns apply — no deep research needed. The `latam_` key namespace convention must be enforced in code review. After completing this phase, verify the full pitfall checklist in PITFALLS.md section "Looks Done But Isn't."

### Phase Ordering Rationale

- Phases 1-3 follow the hard dependency graph from ARCHITECTURE.md: no phase can be meaningfully tested without the preceding phase producing real output. Attempting Phase 3 without Phase 2 means building a processor with no real extracted data to validate against.
- Phase 4 (red flags) is decoupled from Phase 5 (PDF report) even though the report consumes red flag output. This separation enables the dashboard (Phase 6) to display red flags before the PDF report feature is complete, delivering user value incrementally.
- Phase 5 is positioned before Phase 6 because the PDF download button in the dashboard section depends on the WeasyPrint (or fallback) integration; the dashboard phase must not be left incomplete pending a library decision.
- Phase 6 (dashboard integration) is last because it is the only phase that modifies existing code (`app.py`). Deferring it minimizes the window during which the existing S&P 500 section is at any risk.

### Research Flags

Phases needing deeper investigation during planning or early implementation:
- **Phase 2 (PDF Extractor):** Per-country PDF format calibration is LOW confidence. Real PDFs from Supersalud (CO), SMV (PE), CMF (CL), and CNV (AR) should be downloaded and manually inspected before the country-adapter design is finalized. Budget additional time — this is the phase most likely to require schedule adjustment.
- **Phase 3 (Currency normalizer — ARS):** Argentine peso exchange rate reliability from free APIs is LOW confidence. The ARS-USD rate data may reflect the official crawling peg or the parallel market depending on the API; validate against Banco Central de la República Argentina official data for at least one historical year before using ARS-normalized KPIs for any credit decision context.
- **Phase 5 (PDF Report):** WeasyPrint Windows GTK3 install is MEDIUM confidence. Treat session 1 as a spike; decide WeasyPrint vs. reportlab before any template work.

Phases with standard, well-documented patterns (no deep research needed):
- **Phase 1:** Playwright thread isolation is confirmed in official docs and multiple community sources. Currency API endpoints are live and verified. Standard implementation.
- **Phase 4:** Red flags threshold configuration is a deterministic YAML-driven design. Standard implementation — only LATAM-specific calibration is a gap, and it is documented as an approximation.
- **Phase 6:** Streamlit patterns are well-established. The lazy import and `latam_` namespace convention are documented with code examples in PITFALLS.md.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions verified via live PyPI (Mar 2026). Windows-specific install steps confirmed against official docs and community issue trackers. Single exception: WeasyPrint GTK3 install is MEDIUM — confirmed approach (MSYS2) but known Windows friction with a documented fallback path. |
| Features | MEDIUM | Table stakes and P1 features are well-grounded. Frankfurter currency coverage gap confirmed via GitHub Issue #144. Regulatory portal scraping patterns are LOW confidence — portal structures change frequently and must be validated live. ARS exchange rate reliability is LOW confidence. |
| Architecture | HIGH | Based on direct analysis of the existing codebase (`agent.py`, `processor.py`, `scraper.py`, `app.py`) plus PROJECT.md milestone specification. All component boundaries, the schema compatibility contract, and the LatamAgent interface design are grounded in actual existing code, not inference. |
| Pitfalls | HIGH | All 7 critical pitfalls traced to official documentation or confirmed GitHub issue threads with reproducible behaviors and community-verified fixes. Windows-specific issues (Playwright event loop, WeasyPrint DLL, Tesseract PATH) are particularly well-evidenced. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **ARS/COP/PEN/CLP FX API accuracy:** The secondary FX API (open.er-api.com or exchangerate.host) is identified but not benchmarked against official central bank data. Validate one historical year of ARS-USD rates against BCRA official publications before any ARS-normalized figures are used for credit analysis. This is an explicit LOW confidence item.

- **Regulatory portal scraping patterns:** The portal adapter design is the right architectural decision, but the specific scraping logic for Supersalud, SMV, CMF, CNV, and CNBV cannot be finalized until live portals are inspected in Phase 2. These portals change URL structure without notice. Plan for per-portal calibration time — treat portal scraping as inherently maintenance-prone.

- **OCR accuracy on real LATAM health sector PDFs:** The `eng+spa` language model and 300 DPI rendering are reasonable starting points. Actual accuracy on Supersalud or SMV scanned filings is unknown until tested. The extraction confidence score (built in Phase 2) is the mechanism for surfacing this to the user so low-accuracy extractions are flagged for manual verification rather than silently accepted.

- **WeasyPrint vs. reportlab/fpdf2 decision:** Remains open until Phase 5. The recommendation is to treat Phase 5 session 1 as a validation spike. If WeasyPrint GTK3 install fails, switch to `reportlab` or `fpdf2` (both pure-Python, adequate CSS/layout support for a text-and-table financial report, 1-2 hour switch cost).

- **Healthcare KPI thresholds — LATAM calibration:** The red flags thresholds in Phase 4 are derived from US HFMA benchmarks. LATAM healthcare companies (especially Colombian EPS, Peruvian IPRESS) operate with different leverage norms and margin structures. The YAML threshold file design in Phase 4 is the right architectural choice precisely because it allows thresholds to be tuned without code changes as LATAM-specific benchmarks become available.

## Sources

### Primary (HIGH confidence)
- `agent.py`, `processor.py`, `scraper.py`, `app.py` (direct codebase analysis) — existing architecture, interface contracts, Parquet schema
- PROJECT.md milestone specification — authoritative feature scope, constraints, and out-of-scope items
- [playwright PyPI](https://pypi.org/project/playwright/) — version 1.58.0, Jan 2026; `playwright install chromium` step confirmed
- [Playwright Python docs](https://playwright.dev/python/docs/intro) — Windows 11+ confirmed, thread isolation approach
- [PyMuPDF PyPI](https://pypi.org/project/PyMuPDF/) — version 1.27.1, Feb 2026; import as `fitz` confirmed
- [pdfplumber PyPI](https://pypi.org/project/pdfplumber/) — version 0.11.9, Jan 2026
- [ddgs PyPI](https://pypi.org/project/ddgs/) — version 9.11.1, Mar 2026; confirmed successor to `duckduckgo-search`
- [weasyprint PyPI](https://pypi.org/project/weasyprint/) — version 68.1, Feb 2026
- [WeasyPrint Windows docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) — MSYS2 as recommended GTK3 source confirmed
- [Frankfurter API](https://frankfurter.dev/) — ECB-backed; BRL and MXN confirmed supported; ARS/CLP/COP/PEN absence confirmed via [GitHub Issue #144](https://github.com/lineofflight/frankfurter/issues/144)
- [Playwright + Streamlit asyncio conflict](https://github.com/streamlit/streamlit/issues/7825) and [playwright-python Issue #462](https://github.com/microsoft/playwright-python/issues/462) — confirmed behavior and ThreadPoolExecutor fix
- [WeasyPrint GTK DLL errors](https://github.com/Kozea/WeasyPrint/issues/971); [WeasyPrint MSYS2 recommendation](https://github.com/Kozea/WeasyPrint/issues/2105)
- [pytesseract TesseractNotFoundError](https://github.com/madmaze/pytesseract/issues/348) — confirmed fix via explicit `tesseract_cmd`

### Secondary (MEDIUM confidence)
- [Frankfurter API timeseries endpoint](https://frankfurter.dev/) — annual average must be computed from daily series; no built-in average endpoint; weekends/holidays return business days only
- [pdfplumber 0.11.8 table update](https://www.blog.brightcoding.dev/2025/11/26/finance-bros-are-obsessed-with-this-0-11-8-update-pdfplumbers-new-table-ai-trick-explained/) — `edge_min_length_prefilter` behavior on financial tables confirmed
- [LATAM IFRS adoption timeline](https://www.mdpi.com/1911-8074/18/10/567) — country-by-country IFRS mandates
- [LATAM regulatory tax IDs](https://learn.microsoft.com/en-us/dynamics365/finance/localizations/iberoamerica/ltm-core-tax-id-type) — NIT/RUC/RUT/CUIT/RFC structure
- [Healthcare KPI thresholds](https://www.hfma.org/revenue-cycle/financial-kpis-redefined-in-healthcare/) — US-derived HFMA benchmarks; LATAM calibration is an explicit open gap
- [duckduckgo-search rate limit behavior](https://github.com/open-webui/open-webui/discussions/6624) — `RatelimitException` at 10-20 requests in some conditions; threshold undocumented
- [ARS devaluation and crawling peg 2025](https://www.ebc.com/forex/usd-to-ars-outlook-how-argentina-s-fx-reform-changes-trading)

### Tertiary (LOW confidence — requires live validation during implementation)
- Regulatory portal scraping structure (Supersalud, SMV, CMF, CNV, CNBV) — site structures change; must be validated live in Phase 2 before finalizing scraper design
- ARS-USD rate accuracy from secondary FX APIs vs. BCRA official rates — not cross-validated against authoritative source
- OCR accuracy on actual LATAM health sector scanned PDFs — estimated 95-99% on good scans; untested against real document corpus

---
*Research completed: 2026-03-03*
*Ready for roadmap: yes*
