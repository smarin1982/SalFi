---
phase: 11-dashboard-report
plan: 01
status: complete
completed: 2026-03-10
---

## What Was Done

Created `report_generator.py` — standalone report engine decoupled from app.py.

## Artifacts

- **report_generator.py** (190 lines): four public functions, all heavy imports lazy
  - `fetch_comparables()` — calls `web_search.search_sector_context()`, returns up to 3 snippets, never raises
  - `generate_executive_report()` — single Claude API call (`claude-opus-4-6`, max_tokens=4096), Spanish prompt with 4 required sections, API key guard returns descriptive error string
  - `build_pdf_bytes()` — fpdf2 FPDF, Latin-1 safe (em dash replaced with ASCII hyphen), returns `b'%PDF'` bytes
  - `export_chart_png()` — Kaleido `fig.to_image()`, returns PNG bytes or None on failure

- **requirements.txt** — added `anthropic>=0.40`, `fpdf2>=2.8.7`, `kaleido>=1.0.0`

## Test Results

All automated tests passed:
- `fetch_comparables OK: 3 results`
- `generate_executive_report no-key guard OK`
- `build_pdf_bytes OK: 1238 bytes`
- `export_chart_png OK: 53515 bytes PNG` (Playwright Chromium detected by Kaleido)

## Decisions

- em dash `—` (U+2014) replaced with ASCII `-` in PDF header — Helvetica core font is Latin-1 only; em dash is outside Latin-1 range and causes `FPDFUnicodeEncodingException`
- Kaleido 1.2.0 detected Playwright Chromium automatically — no `kaleido.get_chrome_sync()` needed
- `fetch_comparables` builds snippet as `f"{title}: {body}"` from `search_sector_context` result dicts
