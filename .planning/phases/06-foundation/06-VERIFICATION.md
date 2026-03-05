---
phase: 06-foundation
verified: 2026-03-05T00:00:00Z
status: human_needed
score: 5/5 must-haves verified
human_verification:
  - test: "Run: streamlit run app.py, expand 'LATAM — Developer Tools (Phase 6 Smoke Test)', click 'Test Playwright Thread Isolation'"
    expected: "Green success message reading 'Thread isolation OK — page title: Example Domain' appears within ~15 seconds; no error banner; no hang"
    why_human: "Playwright thread isolation from Streamlit main-thread context cannot be verified without a live Streamlit session — pytest smoke test passes but Streamlit's Tornado asyncio policy interaction is runtime-only"
  - test: "Run: python -m pytest tests/ -v and confirm total count"
    expected: "27 tests pass (11 test_currency + 10 test_company_registry + 2 test_playwright_thread + 4 test_kpi_registry), 0 failures, 0 errors"
    why_human: "test_playwright_thread.py makes live HTTP requests to example.com via Playwright; cannot run without network + installed chromium binary in CI context"
---

# Phase 6: Foundation Verification Report

**Phase Goal:** Implement the four infrastructure pillars that all LATAM phases depend on: FX normalizer (currency.py), company registry with slug generation (company_registry.py), Playwright thread isolation (latam_scraper.py), and storage layout validation.
**Verified:** 2026-03-05T00:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `currency.to_usd(amount, "ARS", fiscal_year)` returns a float for all six currencies via tiered fallback | VERIFIED | `currency.py` L137-153: to_usd() calls get_annual_avg_rate() with lru_cache + fallback; test_currency.py covers all 6 currencies; fx_rates.json seeded with BRL/MXN/ARS/CLP/COP/PEN 2023 rates |
| 2 | Company name + country produces deterministic Windows-safe slug | VERIFIED | `company_registry.py` L153: `slugify(company_name, allow_unicode=False, separator="-")`; test_slug_with_accents asserts "clinica-las-americas"; test_slug_windows_path confirms no OSError on NTFS |
| 3 | `data/latam/{country}/{slug}/` created correctly; Parquet schema matches US pipeline | VERIFIED | `make_storage_path()` L179-181: `path.mkdir(parents=True, exist_ok=True)`; `EXPECTED_FINANCIALS_COLS` (24 cols) and `EXPECTED_KPIS_COLS` (22 cols) defined; test_parquet_schema_parity validates AAPL reference schema |
| 4 | Playwright from ThreadPoolExecutor does not raise NotImplementedError or hang on Windows 11 | HUMAN NEEDED | `latam_scraper.py` implements correct async_playwright + ProactorEventLoop pattern; test_playwright_thread.py exists and SUMMARY reports passing; Streamlit button integration requires live runtime verification |
| 5 | ARS companies surface low-confidence warning flag | VERIFIED | `currency.py` L156-167: `is_low_confidence_currency()` returns True for "ARS" only; `CompanyRecord` has `low_confidence_fx` field; `write_meta_json()` serializes it to meta.json; test_ars_low_confidence and test_ars_low_confidence_in_meta cover both layers |

**Score:** 4/5 truths verified programmatically; 1 requires human runtime test

### Required Artifacts

| Artifact | Expected | Lines | Status | Details |
|----------|----------|-------|--------|---------|
| `currency.py` | FX normalizer: to_usd, is_low_confidence_currency, get_annual_avg_rate; min 70 lines | 168 | VERIFIED | All 3 exports present; tiered fallback implemented; lru_cache + disk cache wired |
| `tests/test_currency.py` | 11-test suite covering 6 currencies, fallback, flag, cache; min 60 lines | 161 | VERIFIED | 11 test functions present; mock-based fallback test at L121; cache test at L97 |
| `data/cache/fx_rates.json` | Disk cache keyed by currency_year | 8 lines | VERIFIED | Contains all 6 entries: BRL_2023, MXN_2023, ARS_2023, CLP_2023, COP_2023, PEN_2023 with float values |
| `company_registry.py` | CompanyRecord, make_slug, make_storage_path, write_meta_json; min 80 lines | 223 | VERIFIED | All 4 exports present plus EXPECTED_FINANCIALS_COLS and EXPECTED_KPIS_COLS constants |
| `tests/test_company_registry.py` | 10-test suite covering slug, storage, Parquet parity; min 70 lines | 155 | VERIFIED | 10 test functions present; test_parquet_schema_parity validates AAPL reference schema |
| `latam_scraper.py` | ThreadPoolExecutor Playwright wrapper with scrape_url_title | 56 lines | VERIFIED | async_playwright + ProactorEventLoop pattern present; correct per-thread isolation; deviates from plan (sync → async) for valid Windows reason |
| `tests/test_playwright_thread.py` | 2 Playwright smoke tests; min 25 lines | 34 | VERIFIED | test_thread_isolation and test_thread_isolation_returns_on_timeout present; imports from latam_scraper |
| `app.py` (LATAM section) | st.expander with key="latam_playwright_test"; lazy import of latam_scraper | Present | VERIFIED | Lines 536-547: correct expander label, correct button key, lazy import pattern |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `currency.py` | `api.frankfurter.app` | requests.get in `_frankfurter_annual_avg()` | WIRED | L60: `url = f"https://api.frankfurter.app/{year}-01-01..{year}-12-31"` — confirmed present |
| `currency.py` | `open.er-api.com` | requests.get in `_secondary_api_rate()` | WIRED | L26: `SECONDARY_API_BASE = "https://open.er-api.com/v6/latest/{base}"` used at L79 — confirmed present |
| `currency.py` | `data/cache/fx_rates.json` | `_load_disk_cache()` / `_save_disk_cache()` | WIRED | L27: `CACHE_FILE = Path("data/cache/fx_rates.json")`; L34 loads, L41 saves; both called in get_annual_avg_rate() |
| `company_registry.py` | python-slugify | `slugify(..., allow_unicode=False)` | WIRED | L26: `from slugify import slugify`; L153: call with allow_unicode=False confirmed |
| `company_registry.py` | `data/latam/{country}/{slug}/` | `make_storage_path()` using `mkdir(parents=True, exist_ok=True)` | WIRED | L180: `path.mkdir(parents=True, exist_ok=True)` confirmed |
| `company_registry.py` | `data/latam/{country}/{slug}/meta.json` | `write_meta_json()` writing dataclass as JSON | WIRED | L220: `(path / "meta.json").write_text(...)` confirmed |
| `tests/test_playwright_thread.py` | `playwright.async_api.async_playwright` | ThreadPoolExecutor via `_thread_worker` → `_async_playwright_worker` | WIRED | latam_scraper.py L21: lazy import inside async function; L38: ProactorEventLoop created per thread |
| `app.py` | `latam_scraper.scrape_url_title` | st.button key='latam_playwright_test' | WIRED | app.py L540: `key="latam_playwright_test"`; L543: `from latam_scraper import scrape_url_title` (lazy) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| FX-01 | 06-01, 06-03 | Tiered FX conversion: frankfurter (BRL/MXN) → open.er-api.com (COP/PEN/CLP/ARS) | SATISFIED | currency.py FRANKFURTER_CURRENCIES={"BRL","MXN"}; fallback to _secondary_api_rate() for others; all 6 currencies in fx_rates.json |
| FX-02 | 06-01, 06-03 | ARS companies show low-confidence banner | SATISFIED | is_low_confidence_currency("ARS") returns True; CompanyRecord.low_confidence_fx field; write_meta_json serializes it; FX-02 marked [x] in REQUIREMENTS.md |
| COMP-01 | 06-02, 06-03 | Name + country → deterministic URL-safe slug | SATISFIED | make_slug() with allow_unicode=False; test_slug_with_accents confirms "clinica-las-americas"; NOTE: REQUIREMENTS.md checkbox is `[ ]` — documentation not updated to reflect completion |
| COMP-02 | 06-02, 06-03 | Regulatory ID (NIT/RUC/RUT) stored as secondary identifier | SATISFIED | CompanyRecord.regulatory_id field at L103; write_meta_json includes "regulatory_id" key; test_regulatory_id_stored and test_write_meta_json verify storage; NOTE: REQUIREMENTS.md checkbox is `[ ]` |
| COMP-03 | 06-02, 06-03 | Data persisted at data/latam/{country}/{slug}/ with matching Parquet schema | SATISFIED | make_storage_path() creates correct path; EXPECTED_FINANCIALS_COLS (24 cols) defined; test_parquet_schema_parity validates parity against AAPL; NOTE: REQUIREMENTS.md checkbox is `[ ]` |

**Orphaned requirements check:** No requirements in REQUIREMENTS.md are mapped to Phase 6 beyond the five declared in plans.

**Documentation discrepancy noted:** REQUIREMENTS.md checkboxes for COMP-01, COMP-02, COMP-03 remain `[ ]` (unchecked) while FX-01 and FX-02 are correctly `[x]`. The traceability table says "Phase 6 | Pending" for COMP requirements. The code fully implements all three. REQUIREMENTS.md should be updated to `[x]` and traceability table to "Complete".

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `currency.py` | 38 | `return {}` | Info | Legitimate: returns empty dict for absent cache file — not a stub |
| `latam_scraper.py` | — | Uses `async_playwright` instead of `sync_playwright` as specified in plan | Info | Intentional deviation documented in SUMMARY: sync_playwright fails on Windows due to Tornado policy; async_playwright with ProactorEventLoop is correct fix |

No blocker or warning-level anti-patterns found in any artifact.

### Human Verification Required

#### 1. Playwright Thread Isolation — Streamlit Context

**Test:** Run `streamlit run app.py`, navigate to the app in a browser, expand the "LATAM — Developer Tools (Phase 6 Smoke Test)" section, and click "Test Playwright Thread Isolation".
**Expected:** A green st.success banner appears within ~15 seconds reading "Thread isolation OK — page title: Example Domain". No st.error banner. App does not hang or become unresponsive.
**Why human:** Playwright thread isolation behavior differs between a plain pytest context and a live Streamlit session that has an active Tornado event loop. The pytest smoke tests pass, but the SUMMARY's claim of Streamlit approval ("Human Verification Result: APPROVED") cannot be confirmed from code alone — this is a runtime interaction.

#### 2. Full pytest Suite Pass Count

**Test:** Run `python -m pytest tests/ -v` in the project root.
**Expected:** 27 tests pass (11 test_currency.py + 10 test_company_registry.py + 2 test_playwright_thread.py + 4 test_kpi_registry.py), exit code 0.
**Why human:** test_playwright_thread.py makes live HTTP requests through a real Chromium browser. This requires network access and the chromium binary installed via `playwright install chromium`. Cannot be verified statically.

### Summary

All five infrastructure pillars exist, are substantive, and are fully wired:

- **currency.py** (168 lines): Tiered Frankfurter/open.er-api.com FX normalizer with lru_cache and disk persistence. All three public functions (`to_usd`, `is_low_confidence_currency`, `get_annual_avg_rate`) implemented correctly. The `data/cache/fx_rates.json` is seeded with 2023 rates for all six LATAM currencies. Key links to both external APIs and the cache file are verified.

- **company_registry.py** (223 lines): CompanyRecord dataclass with all 9 fields, `make_slug()` using python-slugify with `allow_unicode=False`, `make_storage_path()` with `mkdir(parents=True)`, `write_meta_json()` writing full meta.json schema. Schema constants (`EXPECTED_FINANCIALS_COLS` 24 cols, `EXPECTED_KPIS_COLS` 22 cols) defined for parity validation.

- **latam_scraper.py** (56 lines): Deviates from plan's `sync_playwright` spec in favour of `async_playwright + ProactorEventLoop` — a documented and necessary fix for Windows. ThreadPoolExecutor pattern is correctly implemented with per-thread event loop creation.

- **app.py LATAM section**: Correct expander label, correct `key="latam_playwright_test"`, lazy import of `scrape_url_title`.

- **Requirements FX-01, FX-02**: Fully satisfied and correctly marked `[x]` in REQUIREMENTS.md. **Requirements COMP-01, COMP-02, COMP-03**: Fully implemented in code but REQUIREMENTS.md checkboxes remain `[ ]` — a documentation gap only, not an implementation gap.

One item cannot be confirmed statically: the Streamlit button's runtime behaviour with an active Tornado event loop. This needs one manual browser check.

---
_Verified: 2026-03-05T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
