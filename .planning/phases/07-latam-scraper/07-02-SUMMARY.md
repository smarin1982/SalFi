---
phase: 07-latam-scraper
plan: "02"
subsystem: portal-adapters
tags: [portal-adapters, ddgs, requests, streamlit, latam, file-upload, dashboard]

# Dependency graph
requires:
  - latam_scraper.py (handle_upload, scrape_with_playwright — called from adapters and app.py)
  - company_registry.py (make_slug, make_storage_path — used in render_latam_upload_section)
  - ddgs (supersalud adapter ddgs search)
  - requests (cmf adapter HEAD validation)
provides:
  - "portal_adapters/__init__.py: PORTAL_STATUS dict + get_adapter() factory"
  - "portal_adapters/supersalud.py: find_pdf(nit, year) — ddgs site:docs.supersalud.gov.co search (CO)"
  - "portal_adapters/smv.py: find_pdf(ruc, year) — always None (SMV uses session-dependent URLs) (PE)"
  - "portal_adapters/cmf.py: find_pdf(rut, year) — bank sector HEAD-validated URL pattern attempt (CL)"
  - "portal_adapters/sfc.py: find_pdf stub (CO)"
  - "portal_adapters/cnv.py: find_pdf stub (AR)"
  - "portal_adapters/cnbv.py: find_pdf stub (MX)"
  - "tests/test_portal_adapters.py: 6 unit tests covering all adapters — mocked network"
  - "app.py: render_latam_upload_section() — st.file_uploader with latam_ widget keys (SCRAP-04)"
affects:
  - phase 09 (LatamAgent calls portal adapters when regulatory_id provided)
  - phase 07-03 (post-checkpoint: PORTAL_STATUS updated with live validation results)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Portal adapter pattern: find_pdf(id, year) -> Optional[str] — never raises, returns URL or None"
    - "PORTAL_STATUS dict: 'working' | 'partial' | 'broken' | 'not_validated' — updated after live spike"
    - "CMF validation: requests.head() with 10s timeout to confirm URL exists before returning"
    - "Lazy imports in app.py functions: try/except ImportError isolates LATAM from S&P 500"
    - "latam_ widget key prefix: prevents DuplicateWidgetID collisions across dashboard sections"

key-files:
  created:
    - portal_adapters/__init__.py
    - portal_adapters/supersalud.py
    - portal_adapters/smv.py
    - portal_adapters/cmf.py
    - portal_adapters/sfc.py
    - portal_adapters/cnv.py
    - portal_adapters/cnbv.py
    - tests/test_portal_adapters.py
  modified:
    - app.py

key-decisions:
  - "supersalud adapter uses ddgs site:docs.supersalud.gov.co — may work since docs subdomain appears indexed; live validation required (PORTAL_STATUS='not_validated' until checkpoint)"
  - "smv adapter always returns None — SMV SIMV uses obfuscated ?data=HEX session parameters unresolvable from RUC alone; Playwright is the only path"
  - "cmf adapter attempts HEAD validation before returning — prevents returning 404 URLs; if HEAD fails, None is returned cleanly"
  - "SFC/CNV/CNBV are documented stubs — URL pattern research pending for Phase 9"
  - "Phase 6 smoke test fixed: scrape_url_title() removed in 07-01, updated to scrape_with_playwright()"

# Metrics
duration: ~10min
completed: 2026-03-06
---

# Phase 7 Plan 02: Portal Adapter Layer + Dashboard Upload Handler Summary

**portal_adapters/ package with Supersalud/SMV/CMF best-effort adapters and 3 documented stubs, plus app.py LATAM drag-and-drop upload section satisfying SCRAP-04**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-03-06T08:34:32Z
- **Completed:** 2026-03-06T08:44:xx Z (Tasks 1+2; Task 3 = checkpoint:human-verify pending)
- **Tasks:** 2 auto-tasks complete (Task 3 checkpoint awaiting human verification)
- **Files modified:** 9 (7 created in portal_adapters/, 1 test file created, 1 app.py modified)

## Accomplishments

- `portal_adapters/` package created with 6 adapter files and `__init__.py`
- `PORTAL_STATUS` dict documents live-validation state for all 6 portals (currently `"not_validated"` for primary adapters; `"stub"` for SFC/CNV/CNBV)
- `get_adapter(country, authority)` factory function routes to correct adapter module
- Supersalud adapter: ddgs site-restricted search for `docs.supersalud.gov.co` — returns first PDF href found or None
- SMV adapter: always returns None (per RESEARCH.md Pitfall 4 — session-dependent URLs)
- CMF adapter: bank sector HEAD-validated URL pattern; returns URL only if HEAD returns 200
- SFC, CNV, CNBV: documented stubs with clear "not yet researched" warnings
- 6/6 tests in `tests/test_portal_adapters.py` pass; 42/42 full suite pass
- `render_latam_upload_section()` added to `app.py` with lazy imports, `latam_` widget keys, file saver
- Phase 6 smoke test bug fixed: `scrape_url_title()` (removed in 07-01) replaced with `scrape_with_playwright()`

## Task Commits

1. **Task 1: Portal adapter package** — `76226c0` (feat)
2. **Task 2: LATAM upload section in app.py** — `5667260` (feat)

## Files Created/Modified

- `portal_adapters/__init__.py` — Package init: PORTAL_STATUS dict + get_adapter() factory; 35 lines
- `portal_adapters/supersalud.py` — Supersalud CO adapter: ddgs search; 57 lines
- `portal_adapters/smv.py` — SMV PE adapter: always None stub; 36 lines
- `portal_adapters/cmf.py` — CMF CL adapter: bank sector HEAD validation; 62 lines
- `portal_adapters/sfc.py` — SFC CO stub; 35 lines
- `portal_adapters/cnv.py` — CNV AR stub; 35 lines
- `portal_adapters/cnbv.py` — CNBV MX stub; 36 lines
- `tests/test_portal_adapters.py` — 6 unit tests with mocked network; 80 lines
- `app.py` — render_latam_upload_section() + Phase 6 smoke test fix; +76 lines

## Decisions Made

- **Supersalud uses ddgs site-search:** Research suggested `docs.supersalud.gov.co` may be indexed. Live validation at the checkpoint will confirm. Status stays `"not_validated"` until checkpoint approval.
- **SMV always returns None:** The SIMV portal encodes state in obfuscated `?data=HEX` query params that require a browser session to resolve. There is no deterministic URL construction possible from RUC alone. Playwright is the only viable path.
- **CMF validates before returning:** Rather than returning an unverified URL that may 404, the CMF adapter issues a HEAD request. If the URL doesn't return 200, it falls through to None. This avoids silent failures in Phase 9.
- **SFC/CNV/CNBV as stubs:** These three portals were not included in the Phase 7 research depth. Rather than guessing, they are documented stubs with clear warnings directing to Playwright fallback.
- **Phase 6 smoke test auto-fixed:** `scrape_url_title()` was removed in Phase 07-01 as part of the latam_scraper.py rewrite. The existing call in app.py would silently fail at runtime. Updated to `scrape_with_playwright()` which tests the same thread isolation property with the current public API.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Phase 6 LATAM smoke test used removed function scrape_url_title()**
- **Found during:** Task 2 — reading app.py before modifying
- **Issue:** The LATAM developer tools expander imported `scrape_url_title` which was removed during Phase 07-01 as part of the latam_scraper.py rewrite. This would cause a runtime ImportError whenever the smoke test button was clicked.
- **Fix:** Updated the import to use `scrape_with_playwright("https://example.com", 2024, Path(tmp))` which tests the same thread isolation property with the current production API.
- **Files modified:** `app.py`
- **Commit:** `5667260`

## Checkpoint: Task 3 — Awaiting Human Verification

Task 3 is a `checkpoint:human-verify` gate. The human verifier must:
1. Run `python -m pytest tests/ -v` — expect 42 pass
2. Run a live ddgs smoke test from `latam_scraper.search()`
3. Launch `streamlit run app.py` and test the upload section
4. Run live portal adapter tests and update `PORTAL_STATUS` in `portal_adapters/__init__.py`

PORTAL_STATUS will be updated post-checkpoint based on live validation results.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `portal_adapters/__init__.py` exists | FOUND |
| `portal_adapters/supersalud.py` exists | FOUND |
| `portal_adapters/smv.py` exists | FOUND |
| `portal_adapters/cmf.py` exists | FOUND |
| `portal_adapters/sfc.py` exists | FOUND |
| `portal_adapters/cnv.py` exists | FOUND |
| `portal_adapters/cnbv.py` exists | FOUND |
| `tests/test_portal_adapters.py` exists | FOUND |
| PORTAL_STATUS dict has 6 keys | CONFIRMED |
| get_adapter() function exists | CONFIRMED |
| `find_pdf()` in each adapter — never raises | CONFIRMED |
| All 6 portal adapter tests pass | CONFIRMED (6/6) |
| Full suite 42/42 pass | CONFIRMED |
| app.py render_latam_upload_section() exists | CONFIRMED |
| app.py widget keys all latam_ prefixed | CONFIRMED (4 keys) |
| app.py no duplicate widget keys | CONFIRMED (None) |
| app.py syntax valid | CONFIRMED (ast.parse OK) |
| S&P 500 section unchanged (git diff additions only) | CONFIRMED |
| Commit `76226c0` (Task 1 portal adapters) | FOUND |
| Commit `5667260` (Task 2 app.py upload section) | FOUND |

---
*Phase: 07-latam-scraper*
*Completed: 2026-03-06 (Tasks 1+2; Task 3 checkpoint pending)*
