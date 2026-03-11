---
phase: 12-learned-synonyms
plan: "06"
subsystem: latam-scraper
tags: [scraper, playwright, pdf-discovery, per-provider-learning, relevance-scoring]
dependency_graph:
  requires: [12-01]
  provides: [smart-scraper-with-profiles]
  affects: [latam_scraper.py, LatamAgent.run()]
tech_stack:
  added: []
  patterns:
    - relevance-scoring-before-download
    - corporate-site-crawl-before-external-search
    - append-only-learned-profiles-json
key_files:
  created:
    - data/latam/scraper_profiles.json
  modified:
    - latam_scraper.py
decisions:
  - "[12-06 Scraper]: _validate_pdf_relevance scores PDF URLs 0.0-1.0; domain match is +0.5 (dominant signal); threshold 0.5 blocks wrong-domain results like INEGI for a Colombian IPS query"
  - "[12-06 Scraper]: Corporate site crawl runs before DDGS — same-origin PDFs get highest trust; up to 5 nav links followed + 9 common doc paths tried"
  - "[12-06 Scraper]: scraper_profiles.json uses append-only merge strategy — pdf_url_pattern and nav_path never overwritten when new value is empty; failed_ddgs_queries is a deduplicated accumulation list"
  - "[12-06 Scraper]: search_and_download() strategy order: profile pattern (fastest) → corporate crawl → ddgs (with relevance gate) → playwright fallback"
metrics:
  duration: "28min"
  completed_date: "2026-03-11"
  tasks_completed: 3
  files_modified: 2
---

# Phase 12 Plan 06: Smart Web Scraper with Per-Provider Learning Summary

**One-liner:** Relevance-scored PDF acquisition with corporate-site crawl first, DDGS validation gate, and per-slug learned profiles persisted in JSON.

## What Was Built

### SCRAPE-01 — PDF Relevance Scoring (`_validate_pdf_relevance`)

Scores candidate PDF URLs 0.0–1.0 before downloading:
- `+0.5` domain match (pdf URL host == company domain)
- `+0.2` financial keywords in URL path (`estados-financieros`, `informe`, `reporte`, etc.)
- `+0.1` fiscal year in URL
- `+0.1` PDF file size > 100KB via HEAD request (scanned financials are large)
- `+0.1` filetype is PDF

`search()` now skips any DDGS result with score < 0.5. This prevents downloading unrelated government reports (e.g. INEGI for a Colombian IPS query). Tested: INEGI URL scores 0.20, matching corporate domain + keywords scores 1.00.

### SCRAPE-02 — Corporate Site Crawl (`_crawl_corporate_site`)

Playwright-based crawl of the company's own website — executed via `ThreadPoolExecutor` (same Windows/asyncio isolation pattern as the rest of the module). Strategy:

1. Visit domain root → scan for nav links containing financial keywords
2. Follow up to 5 financial nav links, scan each for PDF links
3. Try 9 common document paths: `/informes/`, `/transparencia/`, `/documentos/`, `/reportes/`, `/estados-financieros/`, `/sala-de-prensa/`, `/publicaciones/`, `/rendicion-de-cuentas/`, `/informacion-financiera/`

Only returns PDFs that belong to the target domain (`_is_on_domain()` check). This is strategy position 1 in `search_and_download()` — runs before DDGS.

### SCRAPE-03 — Learned Scraper Profiles (`data/latam/scraper_profiles.json`)

`_save_scraper_profile(slug, profile_update)` — append-only update:
- Merges new values into existing profile
- Preserves `pdf_url_pattern` and `nav_path` if new value is empty
- Accumulates `failed_ddgs_queries` as a deduplicated list
- Writes `last_success` as ISO date on every success

`_try_profile_pattern()` — year substitution replay:
- Replaces `*` or 4-digit year in saved pattern with current fiscal year
- Validates relevance score > 0.3 before attempting download

`search_and_download()` updated strategy order:
```
0. Profile pattern (fastest — direct URL with year substitution)
1. Corporate crawl (Playwright, same-origin trust)
2. DDGS search (with relevance gate >= 0.5)
3. Playwright generic fallback
```

On success, each strategy saves its URL pattern for next run. On DDGS failure, failed queries are recorded to skip on rerun.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- [x] `latam_scraper.py` imports cleanly — confirmed via `python -c "import latam_scraper"`
- [x] `_validate_pdf_relevance` unit tests pass: correct-domain score=1.00, INEGI score=0.20
- [x] `_save_scraper_profile` unit tests pass: append-only, pattern preservation, query accumulation
- [x] `data/latam/scraper_profiles.json` created at `642e8a5`
- [x] All new functions exported in module namespace

## Self-Check: PASSED
