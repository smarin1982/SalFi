# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-03)

**Core value:** Un analista debe poder analizar la salud financiera de cualquier empresa — S&P 500 o LATAM — en segundos, con KPIs calculados automáticamente, red flags detectadas y un reporte ejecutivo listo para presentar.
**Current focus:** Milestone v2.0 — Phase 7: LATAM Scraper (in progress)

## Current Position

Phase: 7 of 10 (LATAM Scraper)
Plan: 2 of 3 in current phase
Status: Plan 02 Tasks 1+2 complete — awaiting checkpoint:human-verify (Task 3)
Last activity: 2026-03-06 — Phase 7 Plan 02: portal_adapters package + LATAM upload section (42 tests green)

Progress: [#####░░░░░] 50% (5/10 phases complete — v1.0 shipped; v2.0 in progress)

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

### Pending Todos

None.

### Blockers/Concerns

- [v2.0 Phase 8]: pytesseract requires Tesseract 5 binary + spa language pack on Windows — validate before Phase 8
- [v2.0 Phase 10]: WeasyPrint requires GTK3 via MSYS2 on Windows — treat Phase 10 session 1 as validation spike; decide library before building templates
- [v2.0 Phase 7]: Regulatory portal URL structures are LOW confidence — validate Supersalud, SMV, CMF live during Phase 7 before committing portal scraper logic
- [v2.0 Phase 6]: ARS secondary FX API accuracy vs BCRA official rates is unvalidated — flag in currency.py comments

## Session Continuity

Last session: 2026-03-06
Stopped at: 07-02-PLAN.md checkpoint:human-verify — Tasks 1+2 complete (portal_adapters + app.py upload section), Task 3 awaiting verification
Resume file: None
