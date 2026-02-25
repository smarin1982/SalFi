---
phase: 01-data-extraction
verified: 2026-02-25T12:10:00Z
status: passed
score: 4/4 must-haves verified
re_verification: false
---

# Phase 1: Data Extraction — Verification Report

**Phase Goal:** The scraper can fetch, rate-limit, and persist raw 10-K financial data from SEC EDGAR for any S&P 500 ticker
**Verified:** 2026-02-25T12:10:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running `python scraper.py AAPL` produces `data/raw/AAPL/facts.json` with 10+ years of 10-K facts | VERIFIED | File exists (7,791,209 bytes); `validate_facts()` confirmed: 17 fiscal years, 2009-2025, 503 us-gaap concepts |
| 2 | Scraper resolves any ticker to CIK using local `tickers.json` without a network call per resolution | VERIFIED | `build_ticker_map()` checks `cache_path.exists()` before any `httpx.get()` call; `tickers.json` exists with 10,386 entries |
| 3 | Scraper never exceeds 10 req/s to SEC EDGAR | VERIFIED | `os.environ["EDGAR_RATE_LIMIT_PER_SEC"] = "8"` set in `_init_edgar()` at line index 13, before `set_identity()` at line index 15 |
| 4 | If `facts.json` already exists, scraper uses local copy instead of re-fetching | VERIFIED | `download_facts()` guards entry with `if out_path.exists() and not force_refresh: return out_path` at line 161-163 |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scraper.py` | Complete Phase 1 scraper — all 6 functions | VERIFIED | 271 lines; all 6 public functions callable: `scrape`, `build_ticker_map`, `resolve_cik`, `fetch_companyfacts`, `download_facts`, `validate_facts` |
| `requirements.txt` | Pinned Phase 1 Python dependencies | VERIFIED | 6 active packages; all installed: edgartools 5.17.1, httpx 0.28.1, tenacity 9.1.4, python-dotenv 1.1.0, loguru 0.7.3, tqdm 4.67.1 |
| `.env` | EDGAR_IDENTITY secret for SEC User-Agent | VERIFIED | Contains `EDGAR_IDENTITY="Seb Analyst 752615f5...@sec-key.io"`; loads correctly via `load_dotenv()` |
| `data/cache/tickers.json` | Local ticker→CIK map cache | VERIFIED | 866,020 bytes; 10,386 entries covering full S&P 500 universe |
| `data/raw/AAPL/facts.json` | Apple 10-K XBRL facts | VERIFIED | 7,791,209 bytes; 17 fiscal years (2009-2025); entityName: "Apple Inc." |
| `data/raw/BRK.B/facts.json` | Berkshire Hathaway 10-K XBRL facts | VERIFIED | 5,522,863 bytes; 16 fiscal years (2009-2024); entityName: "BERKSHIRE HATHAWAY INC" |
| `data/cache/.gitkeep` | Cache directory git marker | VERIFIED | Directory exists and is writable |
| `data/raw/.gitkeep` | Raw data directory git marker | VERIFIED | Directory exists and is writable |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `.env` | `scraper.py _init_edgar()` | `load_dotenv()` reading `EDGAR_IDENTITY` | VERIFIED | `load_dotenv(Path(__file__).parent / ".env")` at line 45; `EDGAR_IDENTITY` confirmed non-empty at runtime |
| `scraper.py _init_edgar()` | `EDGAR_RATE_LIMIT_PER_SEC=8` | `os.environ` set before `set_identity()` | VERIFIED | Env var set at function line index 13, `set_identity()` called at line index 15 — correct ordering |
| `build_ticker_map()` | `data/cache/tickers.json` | `cache_path.exists()` check before `httpx.get()` | VERIFIED | Cache check at line 73; file exists — no network call on subsequent runs |
| `download_facts()` | `data/raw/{TICKER}/facts.json` | `out_path.exists()` check before `fetch_companyfacts()` | VERIFIED | Guard at lines 161-163; returns immediately on cache hit |
| `resolve_cik()` | BRK-B normalization | dot-to-dash fallback in `ticker_map.get(alt)` | VERIFIED | SEC tickers.json uses "BRK-B"; fallback logic at line 100 handles `BRK.B` → `BRK-B` transparently |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| XTRCT-01 | 01-01, 01-02 | Downloads SEC Ticker→CIK JSON at init, enables immediate resolution of any ticker | SATISFIED | `build_ticker_map()` downloads once to `data/cache/tickers.json`; subsequent calls read from disk only |
| XTRCT-02 | 01-01, 01-02 | Rate limiter of max 10 req/s with correct User-Agent header per SEC policy | SATISFIED | `EDGAR_RATE_LIMIT_PER_SEC=8` (below 10 limit); `HEADERS["User-Agent"] = identity` for all direct httpx calls |
| XTRCT-03 | 01-02 | Extracts 10-K forms for last 10 years per CIK via EDGAR XBRL endpoints | SATISFIED | `fetch_companyfacts()` uses `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`; AAPL has 17 FY (2009-2025), BRK.B has 16 FY (2009-2024) — both exceed 10-year requirement |
| XTRCT-04 | 01-02 | Stores raw facts.json in `/data/raw/{TICKER}/` as checkpoint before any transformation | SATISFIED | `download_facts()` persists to `DATA_DIR / "raw" / ticker.upper() / "facts.json"`; checks existence before re-fetching; cache-hit confirmed by SUMMARY |

**Orphaned requirements check:** No requirements mapped to Phase 1 in REQUIREMENTS.md that are absent from plan frontmatter. All 4 XTRCT requirements accounted for.

---

### Notable Implementation Deviation

**set_rate_limit() removed in edgartools 5.x — auto-fixed**

The plan (01-02-PLAN.md) specified `from edgar import set_identity, set_rate_limit` and `set_rate_limit(8)` in `_init_edgar()`. edgartools 5.17.1 removed `set_rate_limit()`. The implementation correctly adapted by:
- Removing the `set_rate_limit` import (only `from edgar import set_identity` remains)
- Setting `os.environ["EDGAR_RATE_LIMIT_PER_SEC"] = "8"` before `set_identity()`

The 8 req/s limit is preserved — same safety margin, different mechanism. This is not a gap; the plan's key link pattern `"set_rate_limit\\(8\\)"` does not match the actual code, but the rate-limiting intent (XTRCT-02) is fully satisfied via the env var mechanism.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | No TODOs, FIXMEs, placeholders, empty returns, or stub implementations found | — | None |

---

### Human Verification Required

None. All success criteria are verifiable programmatically:
- File existence and byte sizes confirmed
- Fiscal year counts confirmed by parsing actual JSON structure
- Rate limit mechanism confirmed via source inspection
- Cache-first logic confirmed via code path analysis
- All 6 functions confirmed callable at runtime

The only behavior that could benefit from a live run test — the cache-hit log message "Using cached facts.json" — is confirmed by: (a) the code path at lines 161-163 of scraper.py, and (b) the SUMMARY documenting the second-run log output.

---

## Summary

Phase 1 goal fully achieved. All 4 observable truths are verified against the actual codebase, not just SUMMARY claims:

1. **facts.json with 10+ years**: AAPL has 17 FY (2009-2025), BRK.B has 16 FY (2009-2024) — both confirmed by parsing the actual JSON files, not relying on SUMMARY figures.

2. **Local tickers.json, no per-resolution network call**: The `build_ticker_map()` cache-check pattern (`if cache_path.exists()`) is implemented and the 866KB `tickers.json` file exists — the 10,386-entry cache is populated.

3. **Rate limit under 10 req/s**: `EDGAR_RATE_LIMIT_PER_SEC=8` is set via `os.environ` in `_init_edgar()`, correctly ordered before `set_identity()`. This is the edgartools 5.x mechanism replacing the removed `set_rate_limit()` function — the constraint is enforced.

4. **Cache-first for facts.json**: `download_facts()` has an explicit existence guard (`if out_path.exists() and not force_refresh: return out_path`) that prevents any SEC network call when the file is already present.

The BRK.B special-case normalization (dot-to-dash fallback) works correctly: SEC's `company_tickers.json` uses "BRK-B", and `resolve_cik()` transparently maps "BRK.B" to "BRK-B". Both AAPL and BRK.B facts files exist with substantial data.

---

_Verified: 2026-02-25T12:10:00Z_
_Verifier: Claude (gsd-verifier)_
