# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-03)

**Core value:** Un analista debe poder analizar la salud financiera de cualquier empresa — S&P 500 o LATAM — en segundos, con KPIs calculados automáticamente, red flags detectadas y un reporte ejecutivo listo para presentar.
**Current focus:** Milestone v2.0 — Phase 11: Dashboard & Report (next)

## Current Position

Phase: 12 of 12 (Learned Synonyms) — IN PROGRESS
Plan: 4 of 6 in current phase — 12-04 complete
Status: Phase 12 in progress — multi-year comparative extraction shipped (12-04 complete)
Last activity: 2026-03-11 — Phase 12 Plan 04: Multi-Year Extraction from Comparative PDFs

Progress: [##########] 100% (10/10 phases complete — v1.0 shipped; v2.0 Phases 6-10 complete)

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
| 09-orchestration-red-flags | 02 | 8min | 1 | 1 |
| 10-human-validation-lite | 01 | 2min | 2 | 2 |
| 10-human-validation-lite | 02 | 45min | 2 | 3 |
| 12-learned-synonyms | 01 | 4min | 2 | 3 |
| 12-learned-synonyms | 02 | 4min | 1 | 1 |
| 12-learned-synonyms | 03 | 2min | 1 | 1 |
| 12-learned-synonyms | 04 | 26min | 3 | 3 |

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
- [09-02 LatamAgent]: DATA_DIR set to data/ (not data/latam/) — make_storage_path() appends "latam/{country}/{slug}" itself; using data/latam/ as base would produce double-latam path data/latam/latam/country/slug
- [09-02 LatamAgent]: _same_quarter() copied verbatim from agent.py lines 122-136 — quarter-boundary logic must be identical between US and LATAM pipelines
- [09-02 LatamAgent]: ars_warning=True hardcoded for country=="AR" in _build_meta() — FX-02 requirement; ARS volatility warning always required regardless of confidence level
- [09-02 LatamAgent]: _process_existing() re-evaluates flags on skip-scrape path — YAML threshold changes take effect even when data is current-quarter
- [10-01 Validation]: Baja guard in _handle_confirm uses value comparison (not disabled=True) to block silent confirmation — avoids Streamlit bug #8075 with disabled submit buttons
- [10-01 Validation]: _handle_confirm clears session state ONLY after successful Parquet+meta.json write — analyst can retry on exception without losing extraction result
- [10-01 Validation]: _handle_discard sets latam_show_rerun=True (not st.info directly) so app.py re-run block owns the discard message UX
- [10-01 Validation]: active_latam_company captured before clearing pending session keys — navigation state survives the deletion on same rerun
- [10-02 Validation]: _DISPLAY_TO_CANONICAL maps ingresos/utilidad_neta/total_activos/deuda_total to revenue/net_income/total_assets/long_term_debt — session state uses Spanish aliases, latam_processor uses English canonical names; bridge is explicit mapping in _handle_confirm
- [10-02 Validation]: _META_KEYS set filters extracted_at, pdf_path, currency_code, fiscal_year, extraction_method, confidence, and all confidence_{f}/source_page_{f} keys from session dict before building ExtractionResult.fields
- [10-02 Validation]: fiscal_year, currency_code, confidence, extraction_method must be present in session state dict for confirm path — latam_extractor / LatamAgent responsibility to populate

- [12-01 Learned Synonyms]: _append_candidate uses read-modify-write JSONL (safe in single-threaded extraction context) — base LATAM_CONCEPT_MAP always wins on conflict with learned synonyms
- [12-01 Learned Synonyms]: _LEARNED_SYNONYMS fallback in map_to_canonical uses label.strip().lower() — no accent normalization in learned path (labels pre-normalized in JSON by human reviewer)

- [12-02 Synonym Reviewer]: Module-level latam_concept_map import avoids dotenv side-effects inside suggest_mapping — latam_concept_map triggers python-dotenv at import, which re-populates ANTHROPIC_API_KEY; moved to module level so dotenv runs before caller code modifies environment
- [12-02 Synonym Reviewer]: suggest_mapping uses module-level _CANONICAL_CHOICES (not local import) — prevents key re-injection from dotenv inside the function body; all error paths return SuggestionResult(canonical=None) instead of raising

- [12-03 Review Panel]: _render_synonym_panel() defined before _render_latam_tab() — ensures call site resolves at definition time; approved/rejected state stored in learned_synonyms.json (not session_state) to survive app restarts

- [12-04 Multi-Year]: _infer_fiscal_years scans first 500 chars of OCR text for year-pair via \b(20[12]\d)\b — two distinct years = (primary, comparative); one year = (year, year-1); none = (now-1, now-2)
- [12-04 Multi-Year]: extract() return type changed to list[ExtractionResult]; digital PDF path wraps single result in list for uniform caller interface
- [12-04 Multi-Year]: process() accepts Union[ExtractionResult, list[ExtractionResult]] — isinstance check normalises old single-result callers without breaking them; LatamAgent keeps extraction_result[0] alias for _build_meta

### Pending Todos

None.

### Blockers/Concerns

- [v2.0 Phase 8]: pytesseract requires Tesseract 5 binary + spa language pack on Windows — CONFIRMED ABSENT: TESSERACT_AVAILABLE=False; OCR path degrades gracefully; install Tesseract 5 to enable OCR
- [v2.0 Phase 10]: WeasyPrint requires GTK3 via MSYS2 on Windows — treat Phase 10 session 1 as validation spike; decide library before building templates
- [v2.0 Phase 7]: Regulatory portal URL structures are LOW confidence — RESOLVED: Supersalud=partial, CMF=broken, SMV=stub by design (validated 2026-03-06)
- [v2.0 Phase 6]: ARS secondary FX API accuracy vs BCRA official rates is unvalidated — flag in currency.py comments

## Session Continuity

Last session: 2026-03-11
Stopped at: Completed 12-04-PLAN.md — Multi-Year Extraction from Comparative PDFs
Resume file: None
