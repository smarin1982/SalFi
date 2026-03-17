# Phase 13: Multi-year Historical PDF Ingestion - Research

**Researched:** 2026-03-17
**Domain:** LATAM PDF crawl orchestration, multi-year parquet accumulation, Streamlit per-year progress UI
**Confidence:** HIGH (all findings from direct source-code inspection; no external libraries required)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Trigger & UX**
- Backfill starts **automatically when a new LATAM company is registered** — no separate button needed for first-time ingestion
- On subsequent dashboard loads, the system **silently checks for new years** and downloads/extracts any gaps found
- During backfill, show a **per-year progress list**: one row per year with status (e.g. "2021 ✓ OK", "2022 ⏳ descargando...", "2020 ✗ no encontrado")
- **KPI cards** (recuadros principales) display the most recent year's value with the year labeled (e.g. "Revenue 2024: $X")
- **Charts** show historical trend for the **last 5 years** — not just the most recent

**Re-extraction Policy**
- **Skip years already in parquet** — if a year exists, do not re-download or re-extract
- **Force re-extract button** available per year in the evidence/validation panel (useful when confidence badge is low)
- Each backfill year goes through the **Phase 10 individual validation screen** — not a batch screen
- When extraction confidence is **low**, the system triggers the validation screen to let the analyst manually verify/correct key values before writing to parquet

**Partial Failure Handling**
- If a year's PDF is not found, **continue with remaining years** — the parquet ends up with available years and a gap
- If extraction yields low confidence, **offer the validation screen** rather than silently writing or discarding
- At the end of a backfill run, show a **summary table per year**: "2019 ✓", "2020 ⚠️ baja confianza (validado)", "2021 ✗ PDF no encontrado", etc.

**Discovery Scope**
- Window: **last 5 years** (fiscal years ending 5 years before current year)
- Discovery method: **crawl the portal's listing page** for the company (e.g. supersalud.gov.co report index, BVC filings page) and parse all PDF links — do not run one DDGS search per year
- Tier priority: **T1 only** (estados financieros). Fall back to T2 only as absolute last resort if T1 is unavailable for a given year
- Discovery uses the `scraper_profile` stored for the company (the portal URL already known from Phase 7 ingestion)

### Claude's Discretion
- Exact crawl depth for the listing page (how many pagination levels)
- How to handle PDFs with ambiguous year in the URL when year cannot be detected from filename
- Storage of per-year download metadata (PDF path, download date, tier, confidence score)

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

---

## Summary

Phase 13 adds historical depth to the LATAM pipeline: when a company is registered (or on each dashboard load), the system crawls the listing page already known from the scraper_profile and discovers all annual PDFs for the last 5 years. Each year is individually downloaded, extracted, validated through the Phase 10 screen when confidence is low, and appended to `financials.parquet`. The dashboard shows per-year progress during backfill and historical trend charts once data is available.

All infrastructure already exists and is reused without modification. `latam_scraper._async_crawl_corporate` handles multi-year page crawling; `latam_extractor.extract()` already returns `list[ExtractionResult]`; `latam_processor.process()` already does `drop_duplicates(subset=["fiscal_year"], keep="last")` for idempotent multi-row appending. The only new code needed is:
1. A **listing crawler** that collects ALL PDF URLs from the portal listing page (not just the best one), groups them by year, and returns a dict `{year: pdf_url}`.
2. A **backfill orchestrator** (`LatamBackfiller`) that iterates over the 5-year window, skips years already in parquet, and coordinates per-year download → extract → validate → process.
3. A **Streamlit progress renderer** inside `_render_latam_tab()` that shows per-year status rows and the summary table at completion.

**Primary recommendation:** Add `latam_backfiller.py` as a new module. Reuse every existing function; do NOT copy or modify `latam_scraper.py`, `latam_extractor.py`, `latam_processor.py`, or `latam_validation.py`.

---

## Standard Stack

### Core (all already installed — no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `playwright` (async) | installed | Crawl listing pages, follow pagination | Already the pattern for `_async_crawl_corporate`; ThreadPoolExecutor pattern required on Windows |
| `pdfplumber` + `pytesseract` | installed | Extract per-year PDFs | Existing `latam_extractor.extract()` path |
| `pandas` / `pyarrow` | installed | Read/write Parquet; skip-year check | `latam_processor.process()` already handles append + dedup |
| `streamlit` | installed | Per-year progress display, summary table | Existing dashboard |
| `loguru` | installed | Structured logging | Project standard |
| `requests` | installed | PDF download | `_download_pdf()` already uses it |

### No New Installs Required
This phase adds Python code only. No new packages are needed.

---

## Architecture Patterns

### Recommended File Structure
```
latam_backfiller.py         # NEW — multi-year orchestration module
tests/test_latam_backfiller.py  # NEW — unit tests
```

All other files are called but not modified (except `app.py` and `LatamAgent.py` receive targeted additions).

### Pattern 1: Listing-Page Crawler — Collect All Annual PDF Links

**What:** A Playwright async function visits the portal listing page stored in `scraper_profile["domain"]` and collects ALL PDF anchors, grouped by detected year. Returns `dict[int, str]` mapping `{fiscal_year: best_pdf_url}`.

**When to use:** At the start of every backfill run, once per company.

**Key design decisions:**
- Run inside `ThreadPoolExecutor(max_workers=1)` + `asyncio.ProactorEventLoop()` (MANDATORY on Windows — same pattern as `_playwright_crawl_corporate`)
- Use `_score_pdf_link(href, text, year)` + `_detect_doc_tier(href)` already in `latam_scraper.py` — T1 wins, T2 only if no T1 for a given year
- Use `_is_partial_year_url(href)` to skip semester/quarterly links
- Year extraction from URL: `re.search(r'\b(20[12]\d)\b', href + link_text)` — same pattern LatamAgent already uses for filename inference
- If year is ambiguous (no year in URL or link text), assign `None` and skip those PDFs
- Crawl depth: 1–2 levels. Level 1 is the known listing page (portal nav path from profile). If Level 1 returns < 3 years, follow pagination links (`a[href*="page"]`, `a[href*="pagina"]`, `a[href*="?p="]`) up to 3 pages. This covers the discretion area around pagination.

**Implementation skeleton:**
```python
# Source: latam_scraper._async_crawl_corporate pattern
async def _async_collect_all_years(listing_url: str, domain: str) -> dict[int, str]:
    """Visit listing_url, collect all annual PDF links grouped by year."""
    results: dict[int, list[tuple[int, str]]] = {}  # {year: [(score, url), ...]}
    base_origin = ...
    target_domain = ...
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(listing_url, timeout=30_000, wait_until="domcontentloaded")
            # collect PDF links on this page + up to 3 pagination levels
            ...
            all_links = await page.locator("a[href]").all()
            for link in all_links:
                href = await link.get_attribute("href") or ""
                text = (await link.inner_text() or "").lower()
                if not (href.endswith(".pdf") or ".pdf?" in href.lower()):
                    continue
                if _is_partial_year_url(href) or _is_partial_year_url(text):
                    continue
                year = _extract_year_from_url(href + " " + text)
                if year is None:
                    continue
                score = _score_pdf_link(href, text, year)
                if score > 0:
                    results.setdefault(year, []).append((score, _make_absolute(href, base_origin)))
        finally:
            await browser.close()
    # Best PDF per year: T1 wins over T2 wins over T3
    return {yr: max(candidates, key=lambda x: x[0])[1]
            for yr, candidates in results.items()
            if candidates}
```

### Pattern 2: Skip-Year Guard — Check Existing Parquet

**What:** Before downloading a year's PDF, check if that fiscal year already exists in `financials.parquet`.

**How:** Read the parquet if it exists and check `existing_years = set(df["fiscal_year"].astype(int))`. If `year in existing_years`, skip unless `force_reextract=True`.

```python
def _years_already_in_parquet(parquet_path: Path) -> set[int]:
    if not parquet_path.exists():
        return set()
    df = pd.read_parquet(parquet_path, columns=["fiscal_year"])
    return set(df["fiscal_year"].dropna().astype(int))
```

**Confidence:** HIGH — existing `latam_processor.process()` already does `drop_duplicates(keep="last")`; checking before download is an optimization to avoid re-scraping.

### Pattern 3: Per-Year Progress in Streamlit

**What:** Show a live-updating status row for each year during backfill.

**Constraints from existing code:**
- Streamlit widget key prefix `latam_` required (v2.0 Roadmap decision)
- Placeholder pattern (`st.empty()`) for in-place updates — standard Streamlit approach
- Progress state tracked in a dict stored in `st.session_state["latam_backfill_status"][slug]`

**Status values per year:**
```python
# Values for display in the progress list
YEAR_STATUS_PENDING    = "pending"     # "⏳ pendiente"
YEAR_STATUS_RUNNING    = "running"     # "⏳ descargando..."
YEAR_STATUS_OK         = "ok"          # "✓ OK"
YEAR_STATUS_LOW_CONF   = "low_conf"    # "⚠️ baja confianza"
YEAR_STATUS_NOT_FOUND  = "not_found"   # "✗ PDF no encontrado"
YEAR_STATUS_SKIPPED    = "skipped"     # "— ya existe"
```

**Display pattern:**
```python
# In app.py, render a per-year status table after backfill completes
status_map = st.session_state.get("latam_backfill_status", {}).get(slug, {})
if status_map:
    for yr in sorted(status_map, reverse=True):
        st.markdown(f"**{yr}** — {_year_status_icon(status_map[yr])}")
```

### Pattern 4: Validation Intercept Per Year

**What:** When a year's extraction returns confidence "Baja", pause the backfill loop and invoke `latam_validation.render_latam_validation_panel()` for that specific year before proceeding.

**Existing mechanism:** `latam_pending_extraction` and `latam_pending_company` session state keys are already consumed by `_render_latam_tab()` (app.py lines 1013–1021). The backfill just needs to populate these keys the same way LatamAgent currently does (via `latam_validation.py` intercept point in `latam_extractor.extract()`).

**Critical insight:** The current validation flow already handles one year at a time. For multi-year backfill, each low-confidence year pauses at this intercept. The UI renders the validation panel, analyst confirms/corrects, then backfill continues to the next year on the following Streamlit rerun. This requires the backfill to persist its state across reruns — use `st.session_state["latam_backfill_queue"][slug]` to hold the remaining years to process.

### Pattern 5: Listing URL Derivation from Existing Profile

**What:** The `scraper_profiles.json` stores `domain` and optionally `nav_path` (list of nav link texts) and `pdf_url_pattern`. Phase 13 uses `domain` as the starting point for the listing-page crawl.

**For MiRed IPS (reference company):**
- `domain`: `"https://miredbarranquilla.com/"`
- `pdf_url_pattern`: `"https://miredbarranquilla.com/wp-content/uploads/*/03/ESTADOS-FINANCIEROS-A-CORTE-DE-DICIEMBRE-31-DEL-2024.pdf"`
- The listing page is the WordPress uploads directory listing or the same nav path used to find the 2024 PDF.

**Approach for listing discovery:**
1. Visit the domain root page
2. Follow the same nav logic as `_async_crawl_corporate` but collect ALL PDF links from the financial section instead of stopping at the first match
3. Extract years from filenames: `re.search(r'\b(20[12]\d)\b', href)` — the MiRed pattern `ESTADOS-FINANCIEROS-A-CORTE-DE-DICIEMBRE-31-DEL-2024.pdf` yields 2024 directly

### Pattern 6: LatamAgent Integration — Automatic Trigger on Registration

**What:** When `_run_latam_pipeline()` in `app.py` completes successfully for a new company, immediately queue a backfill for the last 5 years.

**How:** After the `agent.run()` call succeeds and results are stored in session state, check if this is a new company (was not in `latam_companies` before). If new, set `st.session_state["latam_backfill_queue"][slug] = [year-1, year-2, year-3, year-4, year-5]` excluding the year just processed. The backfill widget in `_render_latam_tab()` picks this up on the next render.

**Subsequent loads:** On `_auto_load_existing_latam()`, for each existing company, call `_check_missing_years(slug, country)` which reads `financials.parquet` and computes the gap between the 5-year window and existing rows. If any years are missing, queue them silently.

### Anti-Patterns to Avoid

- **Modify `latam_processor.process()`:** It already handles multi-year append with dedup. Never add backfill logic there.
- **Batch validation panel:** Do NOT try to validate all years at once. Validate one year, persist to parquet, then move to the next.
- **Blocking Streamlit main thread with Playwright:** ALL Playwright calls MUST go through `ThreadPoolExecutor` + `asyncio.ProactorEventLoop()`. The listing crawler is no exception.
- **Running backfill during every `_render_latam_tab()` call:** Guard with `latam_backfill_queue` — only run when queue is non-empty and not currently processing.
- **Using `sync_playwright` in thread worker:** Use `async_playwright` + ProactorEventLoop — `sync_playwright` raises `NotImplementedError` on Windows in ThreadPoolExecutor.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PDF download with validation | Custom requests code | `latam_scraper._download_pdf()` | Handles Content-Type edge cases, magic bytes check, deduplication, streaming |
| Year detection from filename | New regex logic | `re.search(r'20(\d{2})', Path(pdf_path).name)` — already in LatamAgent.run() | Same pattern, validated on MiRed IPS filenames |
| T1/T2/T3 tier scoring | Custom keyword checks | `latam_scraper._detect_doc_tier()` + `_score_pdf_link()` | Full keyword sets already defined |
| Partial-year rejection | New URL analysis | `latam_scraper._is_partial_year_url()` | Already handles semester/trimestre/Q1-Q4 patterns |
| Parquet append + dedup | Manual concat logic | `latam_processor.process()` | Already does `drop_duplicates(subset=["fiscal_year"], keep="last")` + sort |
| Validation intercept | New UI form | `latam_validation.render_latam_validation_panel()` | Already handles low-confidence intercept, confirm/discard, session state cleanup |
| PDF link scoring | New scoring function | `latam_scraper._score_pdf_link()` | Tier 1/2/3 scoring already calibrated |
| Playwright async on Windows | asyncio.run() | `ThreadPoolExecutor` + `asyncio.ProactorEventLoop()` | Required pattern — sync_playwright raises on Windows in Streamlit |

**Key insight:** Phase 13 is purely orchestration. Every component exists. The backfiller is a coordinator, not a builder.

---

## Common Pitfalls

### Pitfall 1: Listing Page Only Shows Current Year
**What goes wrong:** Some portals (WordPress, Supersalud) show the current year's PDF prominently but paginate older years behind "Ver más" / "Cargar más" buttons or pagination links.
**Why it happens:** JavaScript-driven pagination; static HTML parser sees only page 1.
**How to avoid:** After collecting PDFs from the initial listing page, check if we have < 3 years and look for pagination links: `a[href*="page="]`, `a[href*="pagina"]`, `a[href*="p="]`, buttons with text "anterior"/"siguiente"/"older". Follow up to 3 pagination levels (discretion area).
**Warning signs:** Only 1–2 years found despite company having 5+ years of data.

### Pitfall 2: Year Extraction Failure — Ambiguous Filenames
**What goes wrong:** PDF filename like `informe_gestion.pdf` or `estados_financieros_definitivo.pdf` contains no year.
**Why it happens:** Some portals use stable filenames that get overwritten each year, relying on directory structure for year context.
**How to avoid:** Check the URL path for a year segment (`/2022/`, `/2021/03/`); check link text adjacent to the PDF anchor; if still ambiguous, skip (log warning) — do not guess. Store as `year=None` and exclude from the year-grouped dict.
**Warning signs:** All PDFs map to the same year or year=None after collection.

### Pitfall 3: Validation Panel Loop — Backfill Never Advances
**What goes wrong:** The backfill queue is processed one year per Streamlit rerun, but if the validation panel intercepts and the analyst does nothing, the app appears frozen.
**Why it happens:** `latam_pending_extraction` in session state blocks `_render_latam_tab()` from showing the queue progress.
**How to avoid:** In the backfill queue processing logic, only pop the next year from the queue when `latam_pending_extraction` is NOT set. The analyst must confirm or discard before the next year is processed. The summary table shows which years are done.

### Pitfall 4: Re-downloading Already-Existing PDFs
**What goes wrong:** The `raw/` directory already has `ESTADOS-FINANCIEROS-2023.pdf` from a prior run. The backfiller re-downloads it, wasting time and network.
**Why it happens:** `_download_pdf()` already handles this: it checks `if pdf_path.exists(): return ScraperResult(ok=True, ...)`. BUT the backfiller must still call `_years_already_in_parquet()` to skip extraction entirely when the year is already in the parquet (even if the PDF was re-used).
**How to avoid:** Two-level skip: (1) check parquet first — if year in parquet, skip entirely; (2) `_download_pdf()` automatically skips re-download if file exists.

### Pitfall 5: Profile Pattern Year Substitution for Multiple Years
**What goes wrong:** `pdf_url_pattern` for MiRed IPS is `"https://miredbarranquilla.com/wp-content/uploads/*/03/ESTADOS-FINANCIEROS-A-CORTE-DE-DICIEMBRE-31-DEL-2024.pdf"`. Applying `re.sub(r"\*|\b20\d{2}\b", str(year), pattern)` for year=2022 gives the wrong URL if the upload path structure is `2022/03/` not `*/03/`.
**Why it happens:** The wildcard `*` was placed at the directory level (year of upload), and month `/03/` is hardcoded. Different years may have different month paths.
**How to avoid:** For backfill, DO NOT use `_try_profile_pattern()` — that is optimized for the most recent year. Instead, use the listing-page crawl approach which discovers actual URLs from the live site. Pattern replay is a fast-path for the most recent year only.

### Pitfall 6: KPI Cards Showing Wrong "Latest Year" After Backfill
**What goes wrong:** After backfilling 5 years, the KPI card still shows the year that was current before backfill (e.g., the company was registered with 2024 data, backfill adds 2019–2023, but the card still says "2024").
**Why it happens:** `_render_latam_kpi_cards()` already uses `kpi_series.iloc[-1]` after `sort_values("fiscal_year")`, which correctly shows the latest year. BUT `st.session_state["latam_kpis"][slug]` must be refreshed from disk after backfill completes.
**How to avoid:** After each backfill year completes (parquet write), call `st.session_state["latam_kpis"][slug] = _load_latam_kpis(slug, country)` and `st.session_state["latam_financials"][slug] = _load_latam_financials(slug, country)` to force reload. Then `st.rerun()`.

### Pitfall 7: Streamlit Session State Lost Between Reruns
**What goes wrong:** `latam_backfill_queue` disappears on Streamlit rerun because the backfill stored intermediate state in a local variable.
**Why it happens:** Streamlit re-executes the entire script on each interaction. Local variables are gone.
**How to avoid:** ALL backfill state MUST live in `st.session_state` with `latam_` prefix:
  - `st.session_state["latam_backfill_queue"][slug]` — years still to process
  - `st.session_state["latam_backfill_status"][slug]` — status per year (for display)
  - `st.session_state["latam_backfill_current_year"][slug]` — year currently being processed

---

## Code Examples

### Collecting All Annual PDFs from a Listing Page

```python
# Source: latam_scraper._async_crawl_corporate + _async_find_pdf_link_on_page patterns
# latam_backfiller.py

import asyncio
import concurrent.futures
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urljoin

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from loguru import logger

from latam_scraper import (
    _is_partial_year_url, _score_pdf_link, _detect_doc_tier,
    _make_absolute, _is_on_domain, NAV_FINANCIAL_KEYWORDS,
)

BACKFILL_YEARS = 5  # number of fiscal years to look back


def _extract_year_from_text(text: str) -> Optional[int]:
    """Extract a 4-digit year (2019–current) from URL or link text."""
    from datetime import datetime
    matches = re.findall(r'\b(20[12]\d)\b', text)
    current = datetime.now().year
    for m in matches:
        y = int(m)
        if 2015 <= y <= current:
            return y
    return None


def collect_listing_pdfs(listing_url: str, domain: str) -> dict[int, str]:
    """
    Crawl the portal listing page and return {fiscal_year: best_pdf_url}.

    Runs Playwright in a ThreadPoolExecutor with ProactorEventLoop (Windows-safe).
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_thread_collect_listing_pdfs, listing_url, domain)
        try:
            return future.result(timeout=180)
        except Exception as e:
            logger.warning(f"collect_listing_pdfs: failed for {listing_url}: {e}")
            return {}


def _thread_collect_listing_pdfs(listing_url: str, domain: str) -> dict[int, str]:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_async_collect_listing_pdfs(listing_url, domain))
    finally:
        loop.close()


async def _async_collect_listing_pdfs(listing_url: str, domain: str) -> dict[int, str]:
    parsed = urlparse(listing_url if listing_url.startswith("http") else f"https://{listing_url}")
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    target_domain = parsed.netloc.lower().lstrip("www.")

    # {year: [(score, url), ...]}
    candidates: dict[int, list[tuple[int, str]]] = {}

    async def _harvest_page(url: str) -> None:
        try:
            await page.goto(url, timeout=25_000, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeout:
                pass
        except Exception as e:
            logger.debug(f"_async_collect_listing_pdfs: failed to load {url}: {e}")
            return

        try:
            all_links = await page.locator("a[href]").all()
        except Exception:
            return

        for link in all_links:
            try:
                href = (await link.get_attribute("href") or "").strip()
                if not href:
                    continue
                href_lower = href.lower()
                if not (href_lower.endswith(".pdf") or ".pdf?" in href_lower):
                    continue
                text = ""
                try:
                    text = (await link.inner_text() or "").lower()
                except Exception:
                    pass
                if _is_partial_year_url(href) or _is_partial_year_url(text):
                    continue
                year = _extract_year_from_text(href + " " + text)
                if year is None:
                    continue
                abs_url = _make_absolute(href, base_origin)
                if not _is_on_domain(abs_url, target_domain):
                    continue
                score = _score_pdf_link(href, text, year)
                if score > 0:
                    candidates.setdefault(year, []).append((score, abs_url))
            except Exception:
                continue

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await _harvest_page(listing_url)

            # Pagination: follow up to 3 pages if we have < 3 years
            if len(candidates) < 3:
                pagination_links = []
                try:
                    all_links = await page.locator("a[href]").all()
                    for link in all_links:
                        try:
                            href = await link.get_attribute("href") or ""
                            text = (await link.inner_text() or "").lower()
                            if any(p in href.lower() for p in ["page=", "pagina=", "p=", "/page/", "/pagina/"]) \
                               or any(t in text for t in ["anterior", "siguiente", "older", "newer", "próxima", "previa"]):
                                abs_url = _make_absolute(href, base_origin)
                                if _is_on_domain(abs_url, target_domain):
                                    pagination_links.append(abs_url)
                        except Exception:
                            continue
                except Exception:
                    pass
                for pag_url in pagination_links[:3]:
                    await _harvest_page(pag_url)
                    if len(candidates) >= 5:
                        break
        finally:
            await browser.close()

    # Return best PDF per year (highest score wins; T1 naturally scores higher)
    result = {}
    for year, year_candidates in candidates.items():
        year_candidates.sort(key=lambda x: x[0], reverse=True)
        result[year] = year_candidates[0][1]
    return result
```

### Skip-Year Guard

```python
# Source: latam_processor.py pattern — read parquet, check fiscal_year column
import pandas as pd
from pathlib import Path

def _years_already_in_parquet(parquet_path: Path) -> set[int]:
    """Return set of fiscal years already written to financials.parquet."""
    if not parquet_path.exists():
        return set()
    try:
        df = pd.read_parquet(parquet_path, columns=["fiscal_year"])
        return set(df["fiscal_year"].dropna().astype(int).tolist())
    except Exception:
        return set()
```

### Backfill Queue Initialization (app.py addition)

```python
# After agent.run() succeeds for a NEW company — trigger backfill
from datetime import datetime as _dt

def _maybe_queue_backfill(slug: str, country: str, url: str, just_processed_year: int) -> None:
    """Queue missing years for backfill when a new company is registered."""
    from company_registry import make_storage_path
    from pathlib import Path

    storage_path = make_storage_path(Path("data"), country, slug)
    parquet_path = storage_path / "financials.parquet"
    existing_years = _years_already_in_parquet(parquet_path)

    current_year = _dt.now().year
    target_years = [current_year - i for i in range(1, 6)]  # last 5 completed years
    missing = [y for y in target_years if y not in existing_years]

    if missing:
        if "latam_backfill_queue" not in st.session_state:
            st.session_state["latam_backfill_queue"] = {}
        st.session_state["latam_backfill_queue"][slug] = missing

        if "latam_backfill_status" not in st.session_state:
            st.session_state["latam_backfill_status"] = {}
        st.session_state["latam_backfill_status"][slug] = {
            y: "skipped" if y in existing_years else "pending"
            for y in target_years
        }
```

### Per-Year Status Display

```python
# In _render_latam_tab() — after company is selected
def _render_backfill_status(slug: str) -> None:
    """Show per-year progress table if backfill is active or recently completed."""
    status_map = st.session_state.get("latam_backfill_status", {}).get(slug, {})
    if not status_map:
        return

    STATUS_ICONS = {
        "skipped": "—",
        "pending": "⏳",
        "running": "⏳ descargando...",
        "ok": "✓ OK",
        "low_conf": "⚠️ baja confianza",
        "not_found": "✗ PDF no encontrado",
        "validated": "✓ validado",
    }

    st.markdown("#### Estado de ingesta histórica")
    for year in sorted(status_map, reverse=True):
        status = status_map[year]
        icon = STATUS_ICONS.get(status, status)
        st.markdown(f"**{year}** — {icon}")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single-year scrape (most recent only) | Multi-year listing crawl + per-year download | Phase 13 | Enables 5-year trend charts |
| `search_and_download()` returns single PDF | `collect_listing_pdfs()` returns `{year: url}` dict | Phase 13 | One crawl discovers all years |
| LatamAgent.run() processes one ExtractionResult | Backfiller iterates multiple ExtractionResults, one per year | Phase 13 | Each year validated individually |

**Existing infrastructure that Phase 13 leverages (not changes):**
- `latam_extractor.extract()` already returns `list[ExtractionResult]` (added Phase 12-04)
- `latam_processor.process()` already accepts `list[ExtractionResult]` and deduplicates by fiscal_year
- `latam_validation.render_latam_validation_panel()` already intercepts low-confidence extractions
- `latam_scraper._download_pdf()` already deduplicates downloads (checks `if pdf_path.exists()`)
- `_render_latam_kpi_cards()` already uses `sort_values("fiscal_year")` + `iloc[-1]` for latest year
- `build_trend_figure()` already shows multi-year trend when `len(df_sorted) > 1`

---

## Open Questions

1. **MiRed IPS listing page location**
   - What we know: `scraper_profile["domain"] = "https://miredbarranquilla.com/"` and `pdf_url_pattern` shows uploads in `/wp-content/uploads/YYYY/03/`
   - What's unclear: Does miredbarranquilla.com have a dedicated "estados financieros" listing page, or are PDFs scattered across WordPress posts?
   - Recommendation: The backfiller should first try the known `nav_path` from the profile (if stored) to reach the financial section, then harvest all PDF links from that section. If `nav_path` is absent, fall back to the root crawl approach. In either case, inspect `/wp-content/uploads/` directory listing is unreliable (Apache often disables it). Rely on the same Playwright nav crawl.

2. **What to do when listing crawl finds 0 PDFs**
   - What we know: Some portals require authentication or use JavaScript rendering that Playwright can handle but may not find listing-format pages
   - What's unclear: For companies where `strategy="corporate_crawl"` succeeded for the most recent year but the listing approach yields nothing, should we fall back to per-year DDGS search?
   - Recommendation (discretion area): If listing crawl finds 0 results, fall back to per-year `latam_scraper.search()` for each missing year. Cap at 3 DDGS calls per backfill run to avoid rate limiting.

3. **`scraper_profiles.json` per-year metadata storage**
   - What we know: Current profile schema stores `last_success`, `strategy`, `pdf_url_pattern`, `doc_tier` — all single-valued for the most recent year
   - What's unclear: Should we store discovered PDF URLs for all years to avoid re-crawling on subsequent runs?
   - Recommendation (discretion area): Add `historical_pdfs: {year: url}` field to the profile entry for the slug. This is an append-only dict that grows as years are discovered. On subsequent backfill runs, check `historical_pdfs` before triggering a new crawl.

---

## Sources

### Primary (HIGH confidence)
- `C:/Users/Seb/AI 2026/latam_scraper.py` — full source, all crawl/download/scoring functions inspected
- `C:/Users/Seb/AI 2026/LatamAgent.py` — full source, run() pipeline inspected
- `C:/Users/Seb/AI 2026/latam_processor.py` — full source, process() dedup logic inspected
- `C:/Users/Seb/AI 2026/latam_validation.py` — validation intercept pattern inspected
- `C:/Users/Seb/AI 2026/app.py` — _render_latam_tab(), _run_latam_pipeline(), session state patterns inspected
- `C:/Users/Seb/AI 2026/data/latam/scraper_profiles.json` — MiRed IPS profile schema confirmed

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` decisions section — all v2.0 architectural decisions (Playwright/Windows pattern, session state keys, etc.)
- `.planning/phases/13-multi-year-historical-pdf-ingestion/13-CONTEXT.md` — locked user decisions

### Tertiary (LOW confidence)
- None — no WebSearch required; all information derived from codebase inspection

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all libraries already installed and in use
- Architecture: HIGH — patterns derived directly from existing working code in latam_scraper.py + LatamAgent.py
- Pitfalls: HIGH — derived from existing bug history documented in STATE.md and MEMORY.md; patterns are specific to this codebase

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (30 days — stack is stable; no fast-moving dependencies)
