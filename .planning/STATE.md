# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-03)

**Core value:** Un analista debe poder analizar la salud financiera de cualquier empresa — S&P 500 o LATAM — en segundos, con KPIs calculados automáticamente, red flags detectadas y un reporte ejecutivo listo para presentar.
**Current focus:** Milestone v2.0 — Phase 9: Validation Orchestrator (next)

## Current Position

Phase: 9 of 10 (Orchestration & Red Flags) — IN PROGRESS
Plan: 1 of 3 in current phase — Plan 01 complete
Status: Phase 09 Plan 01 complete — web_search.py (SCRAP-03) and red_flags.py + config/red_flags.yaml (FLAG-01, FLAG-02) shipped
Last activity: 2026-03-06 — Phase 9 Plan 01: web_search wrapper + YAML-configurable red flags engine

Progress: [######░░░░] 60% (6/10 phases complete — v1.0 shipped; Phase 8 complete; Phase 9 in progress)

## Performance Metrics

**v1.0 Velocity (reference):**
- Total plans completed: 12
- Average duration: 4 min
- Total execution time: ~0.28 hours

**v2.0:**
- Plans completed: 4
- Status: In progress

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 06-foundation | 01 | 25min | 2 | 4 |
| 07-latam-scraper | 01 | 30min | 2 | 4 |
| 07-latam-scraper | 02 | 45min | 3 | 9 |
| 08-pdf-extraction-kpi-mapping | 01 | 6min | 2 | 2 |
| 08-pdf-extraction-kpi-mapping | 02 | 30min | 2 | 1 |
| 08-pdf-extraction-kpi-mapping | 03 | 4min | 1 | 1 |
| 09-orchestration-red-flags | 01 | 4min | 2 | 4 |

## Accumulated Context

### Decisions (v1.0 — preserved)

- [Setup]: Parquet for local storage — faster reads, avoids re-scraping, survives schema migrations
- [Setup]: edgartools for EDGAR extraction — XBRL-native, returns DataFrames, SEC rate limiting built in
- [Phase 02]: save_parquet unlinks before rename on Windows (NTFS atomic rename requirement)
- [Phase 03-02]: FinancialAgent.run() calls processor.process() even on skipped_scrape
- [Phase 05-02]: Task AI2026_QuarterlyETL registered — Status: Ready, Next: 4/1/2026 6:00 AM

### Decisions (v2.0 — accumulating)

- [v2.0 Roadmap]: Playwright always called via ThreadPoolExecutor — never from Streamlit main thread (asyncio conflict on Windows 11)
- [v2.0 Roadmap]: FX tiered fallback required — Frankfurter covers BRL/MXN only; secondary API for ARS/CLP/COP/PEN; implement before writing any Parquet
- [v2.0 Roadmap]: LATAM imports in app.py must be lazy (inside functions, try/except ImportError) — import failure must not break S&P 500 section
- [v2.0 Roadmap]: LATAM widget keys prefixed latam_ to avoid DuplicateWidgetID collisions
- [v2.0 Roadmap]: WeasyPrint GTK3 is a spike in Phase 10 session 1 — decision finalizes before any template work; fallback is reportlab or fpdf2
- [06-01 FX]: Frankfurter annual average (true daily ECB mean) used for BRL/MXN; open.er-api.com spot rate for ARS/CLP/COP/PEN — approximated_fx=true required in meta.json
- [06-01 FX]: is_low_confidence_currency() flags only ARS — CLP/COP/PEN stable enough to not warn
- [06-01 FX]: Disk cache (fx_rates.json) is NOT thread-safe by design — single-threaded processor context; filelock deferred
- [07-01 Scraper]: sync_playwright in ThreadPoolExecutor thread worker — safe on Windows 11; simpler than async pattern with identical isolation guarantee
- [07-01 Scraper]: HTML interstitial detection via %PDF magic bytes (4-byte check) — Content-Type not reliable for LATAM servers; post-download validation is the safety net
- [07-01 Scraper]: All LATAM PDF acquisition returns ScraperResult — callers check .ok; never raises for "not found" conditions
- [07-02 Adapters]: SMV adapter always returns None — SIMV uses session-dependent ?data=HEX URLs unresolvable from RUC; Playwright is the only path
- [07-02 Adapters]: CMF adapter HEAD-validates URL before returning — avoids returning 404 URLs to Phase 9 caller
- [07-02 Adapters]: PORTAL_STATUS dict tracks live validation state per portal — updated post-checkpoint human verification
- [07-02 Adapters]: PORTAL_STATUS live results — supersalud_co=partial (ddgs finds planning docs, not EEFF), cmf_cl=broken (bank URL pattern 404s, code is internal CMF ID not RUT), smv_pe=stub by design
- [08-01 Concept Map]: map_to_canonical() iterates synonyms longest-first; label_in_synonym direction only when len(label)>=len(synonym) — prevents short-synonym false positives
- [08-01 Extractor]: _score_confidence() uses COUNTRY_CRITICAL_FIELDS.get(country, DEFAULT_CRITICAL_FIELDS) — CO/PE/CL regulator-specific critical field sets
- [08-01 Extractor]: extract() never writes files; ExtractionResult is in-memory only until latam_processor.py writes Parquet after human validation
- [08-02 Processor]: latam_processor imports calculate_kpis and save_parquet from processor.py unchanged — processor.py hash must remain identical to guarantee KPI calculation parity between US and LATAM pipelines
- [08-02 Processor]: All 22 monetary fields converted to USD before Parquet write — not just revenue; partial conversion would make KPI ratios meaningless
- [08-02 Processor]: Prior-year append uses drop_duplicates(keep='last') — latest ExtractionResult wins on re-run; idempotent with multi-year accumulation
- [08-02 Processor]: ticker column contains company_slug (not a stock exchange ticker) — LATAM companies identified by slug throughout the pipeline
- [08-03 Badge]: PDF download button inside _latam_confidence_badge() — st.download_button keyed latam_pdf_download_{slug}_{country} appears when confidence==Baja; discovers PDF via raw_dir.glob('*.pdf') sorted()
- [08-03 Badge]: Confidence badge second call site uses session-state guard so badge shows on section re-entry without requiring a new upload
- [09-01 WebSearch]: ddgs 9.11.2 uses DDGSException not DuckDuckGoSearchException — exception class renamed; tenacity retry updated to (RatelimitException, DDGSException)
- [09-01 RedFlags]: load_config() returns {} when YAML missing — evaluate_flags() returns [] for graceful degradation without FileNotFoundError
- [09-01 RedFlags]: evaluate_flags() accepts both kpis_df and financials_df — FLAG-S01 uses operating_cash_flow from financials_df; FLAG-S02 uses net_profit_margin from kpis_df

### Pending Todos

None.

### Blockers/Concerns

- [v2.0 Phase 8]: pytesseract requires Tesseract 5 binary + spa language pack on Windows — CONFIRMED ABSENT: TESSERACT_AVAILABLE=False; OCR path degrades gracefully; install Tesseract 5 to enable OCR
- [v2.0 Phase 10]: WeasyPrint requires GTK3 via MSYS2 on Windows — treat Phase 10 session 1 as validation spike; decide library before building templates
- [v2.0 Phase 7]: Regulatory portal URL structures are LOW confidence — RESOLVED: Supersalud=partial, CMF=broken, SMV=stub by design (validated 2026-03-06)
- [v2.0 Phase 6]: ARS secondary FX API accuracy vs BCRA official rates is unvalidated — flag in currency.py comments

## Session Continuity

Last session: 2026-03-06
Stopped at: Completed 09-01-PLAN.md — web_search.py + red_flags.py + config/red_flags.yaml shipped; ready for Plan 09-02 (LatamAgent)
Resume file: None
