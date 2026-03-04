# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-03)

**Core value:** Un analista debe poder analizar la salud financiera de cualquier empresa — S&P 500 o LATAM — en segundos, con KPIs calculados automáticamente, red flags detectadas y un reporte ejecutivo listo para presentar.
**Current focus:** Milestone v2.0 — Phase 6: Foundation (ready to plan)

## Current Position

Phase: 6 of 10 (Foundation)
Plan: 0 of 2 in current phase
Status: Ready to plan
Last activity: 2026-03-04 — v2.0 roadmap created (Phases 6-10), ready to begin Phase 6

Progress: [#####░░░░░] 50% (5/10 phases complete — v1.0 shipped)

## Performance Metrics

**v1.0 Velocity (reference):**
- Total plans completed: 12
- Average duration: 4 min
- Total execution time: ~0.28 hours

**v2.0:**
- Plans completed: 0
- Status: Not started

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

### Pending Todos

None.

### Blockers/Concerns

- [v2.0 Phase 6]: Playwright requires `playwright install chromium` after pip install — must run before Phase 6 smoke test
- [v2.0 Phase 8]: pytesseract requires Tesseract 5 binary + spa language pack on Windows — validate before Phase 8
- [v2.0 Phase 10]: WeasyPrint requires GTK3 via MSYS2 on Windows — treat Phase 10 session 1 as validation spike; decide library before building templates
- [v2.0 Phase 7]: Regulatory portal URL structures are LOW confidence — validate Supersalud, SMV, CMF live during Phase 7 before committing portal scraper logic
- [v2.0 Phase 6]: ARS secondary FX API accuracy vs BCRA official rates is unvalidated — flag in currency.py comments

## Session Continuity

Last session: 2026-03-04
Stopped at: v2.0 roadmap written — ROADMAP.md and STATE.md updated, ready to plan Phase 6
Resume file: None
