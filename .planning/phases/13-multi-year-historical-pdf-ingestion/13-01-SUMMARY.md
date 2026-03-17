---
phase: 13-multi-year-historical-pdf-ingestion
plan: "01"
subsystem: backfill-orchestration
tags: [latam, backfill, multi-year, playwright, parquet]
dependency_graph:
  requires:
    - latam_scraper._is_partial_year_url
    - latam_scraper._score_pdf_link
    - latam_scraper._detect_doc_tier
    - latam_scraper._download_pdf
    - latam_scraper._make_absolute
    - latam_scraper._is_on_domain
    - latam_extractor.extract
    - latam_processor.process
  provides:
    - latam_backfiller.collect_listing_pdfs
    - latam_backfiller._years_already_in_parquet
    - latam_backfiller.LatamBackfiller
    - latam_backfiller.BackfillResult
  affects: []
tech_stack:
  added: []
  patterns:
    - ThreadPoolExecutor + asyncio.ProactorEventLoop for Playwright on Windows
    - Pure coordinator pattern — no modifications to existing modules
key_files:
  created:
    - latam_backfiller.py
    - tests/test_latam_backfiller.py
  modified: []
decisions:
  - "[13-01 Backfiller]: _download_pdf() called with strategy='backfill' and attempts=[] — actual signature requires these positional args (not slug as plan pseudocode suggested)"
  - "[13-01 Backfiller]: ScraperResult.pdf_path used (not .path) — matching the actual dataclass field name in latam_scraper.py"
  - "[13-01 Backfiller]: _make_absolute and _is_on_domain imported from latam_scraper (both confirmed present) rather than re-implemented locally"
metrics:
  duration: "2min"
  completed: "2026-03-17"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
---

# Phase 13 Plan 01: Backfill Orchestration Module Summary

Multi-year PDF backfill coordinator using async_playwright listing-page crawler, parquet skip guard, and per-year download/extract/return pattern without touching existing modules.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create latam_backfiller.py | 2d5de0d | latam_backfiller.py |
| 2 | Create tests/test_latam_backfiller.py | bd87d5f | tests/test_latam_backfiller.py |

## What Was Built

**latam_backfiller.py** (282 lines) provides three components:

1. `collect_listing_pdfs(listing_url, domain) -> dict[int, str]` — synchronous wrapper that runs `_async_collect_listing_pdfs` in a `ThreadPoolExecutor(max_workers=1)` with 180s timeout. The async crawler navigates a portal listing page, collects all PDF anchor hrefs, filters partial-year URLs via `_is_partial_year_url`, extracts year from URL or link text, scores each candidate via `_score_pdf_link`, and follows up to 3 pagination pages when fewer than 3 candidates are found. Returns best-scoring URL per year.

2. `_years_already_in_parquet(parquet_path) -> set[int]` — reads only the `fiscal_year` column from financials.parquet, returns empty set on missing file or error.

3. `LatamBackfiller` class:
   - `get_target_years()` — last 5 completed fiscal years, most recent first
   - `get_missing_years()` — target years not yet in parquet
   - `run_year(year, pdf_url, currency_code, force_reextract)` — downloads PDF via `_download_pdf`, extracts via `latam_extractor.extract()`, returns `BackfillResult` (does NOT write parquet)
   - `write_year(result)` — delegates to `latam_processor.process()` with `data_dir=str(storage_path.parent.parent)`

4. `BackfillResult` dataclass — status values: "ok", "low_conf", "not_found", "skipped", "error"

**tests/test_latam_backfiller.py** (203 lines) — 19 tests, all passing:
- 7 tests for `_extract_year_from_text` (bounds, ambiguous filenames, future years)
- 3 tests for `_years_already_in_parquet` (missing file, populated, empty)
- 5 tests for `get_target_years`/`get_missing_years`
- 2 tests for `BackfillResult` values
- 2 integration-level tests for `run_year` skip guard and `force_reextract` bypass

## Verification Results

- `python -m pytest tests/test_latam_backfiller.py -v` — 19/19 passed
- `python -c "import latam_backfiller"` — imports without error
- `sync_playwright` — zero actual code uses (3 grep hits are all in comments/docstrings)
- `ProactorEventLoop` — present in `_thread_collect_listing_pdfs`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Incorrect _download_pdf() call signature**
- **Found during:** Task 1 implementation
- **Issue:** Plan pseudocode shows `_download_pdf(pdf_url, self.raw_dir, self.slug)` but actual function signature is `_download_pdf(url, out_dir, strategy, attempts, timeout=30)`. Using slug as strategy would silently pass but produce confusing log entries; missing `attempts` list would raise TypeError.
- **Fix:** Called with `strategy="backfill"` and `attempts=[]` matching the actual signature.
- **Files modified:** latam_backfiller.py
- **Commit:** 2d5de0d

**2. [Rule 1 - Bug] Wrong ScraperResult field name**
- **Found during:** Task 1 implementation
- **Issue:** Plan pseudocode uses `scrape_result.path` but `ScraperResult` dataclass defines `pdf_path` (not `path`). Accessing `.path` would return `None` always (AttributeError in strict mode).
- **Fix:** Used `scrape_result.pdf_path` matching the actual dataclass field.
- **Files modified:** latam_backfiller.py
- **Commit:** 2d5de0d

**3. [Rule 2 - Enhancement] _make_absolute and _is_on_domain imported rather than duplicated**
- **Found during:** Task 1 implementation
- **Issue:** Plan says "if absent, implement them locally" — both functions confirmed present in latam_scraper.py (lines 755 and 766).
- **Fix:** Imported directly. No local duplicate needed.
- **Files modified:** latam_backfiller.py
- **Commit:** 2d5de0d

## Self-Check: PASSED

| Item | Status |
|------|--------|
| latam_backfiller.py | FOUND |
| tests/test_latam_backfiller.py | FOUND |
| commit 2d5de0d | FOUND |
| commit bd87d5f | FOUND |
