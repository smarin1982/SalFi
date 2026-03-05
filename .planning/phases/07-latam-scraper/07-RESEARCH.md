# Phase 7: LATAM Scraper - Research

**Researched:** 2026-03-04
**Domain:** Web scraping (ddgs semantic search + Playwright fallback), regulatory portal access, PDF download, Streamlit drag-and-drop upload
**Confidence:** MEDIUM-HIGH (ddgs API and Playwright patterns HIGH; regulatory portal URL structures LOW — require live validation)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SCRAP-01 | Semantic search (`ddgs site:empresa.com filetype:pdf "Estado de Situación Financiera"`) as primary PDF discovery; Playwright as fallback only when no direct PDF URL returned | `DDGS().text()` confirmed to support `site:` and `filetype:` operators; return dict has `href` key for direct URL; fallback pattern researched |
| SCRAP-02 | Search financial documents in regulatory portals (Supersalud CO, SMV PE, SFC CO, CMF CL, CNV AR, CNBV MX) using regulatory ID as key | Portal URL patterns researched — all LOW confidence; SMV has open-data API; CMF has IFRS query interface; Supersalud is JS-heavy; all need live validation |
| SCRAP-04 | Analyst can drag & drop a PDF via `st.file_uploader` in dashboard; routes through identical extraction pipeline as scraped PDF | `st.file_uploader` confirmed returns UploadedFile (file-like object); BytesIO + `save_as(path)` pattern researched; lazy import pattern required |
</phase_requirements>

---

## Summary

Phase 7 builds the three-path PDF acquisition layer that feeds Phase 8's extractor: (1) semantic ddgs search as primary strategy, (2) Playwright browser as fallback when search yields no direct PDF URL, and (3) `st.file_uploader` drag-and-drop as the emergency manual path. All three paths must converge on the same output format — a PDF file written to `data/latam/{country}/{slug}/raw/{filename}.pdf` — so Phase 8's extractor sees no difference in provenance.

The critical architectural decision from STATE.md that governs this entire phase: **Playwright is always called via ThreadPoolExecutor, never from the Streamlit main thread** (asyncio conflict on Windows 11). Phase 6's smoke test validated this pattern; Phase 7 extends it into production scraping logic. The `latam_scraper.py` module established in Phase 6 gets its full implementation here.

The most significant uncertainty in this phase is the **regulatory portal URL structures** — all LATAM portals (Supersalud, SMV, CMF, SFC, CNV, CNBV) use obfuscated URL parameters or JavaScript-rendered interfaces, making reliable programmatic scraping difficult without live validation. The research recommends treating portal adapters as a "best effort" layer with Playwright as the universal fallback, and documenting portal-specific quirks as they are discovered during implementation.

**Primary recommendation:** Build and test the ddgs semantic search path first (no browser needed, fast feedback), then the Playwright fallback, then the `st.file_uploader` handler, and finally the portal adapters — in that order, since each adds complexity.

---

## Standard Stack

### Core (Phase 7 specific)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ddgs` | `>=9.0` (latest: 9.11.1 as of Mar 2026) | Primary PDF discovery via semantic `site:domain filetype:pdf` search | Successor to deprecated `duckduckgo-search`; free, no API key; supports `site:`, `filetype:`, and exact-phrase operators natively; confirmed working in Phase 6 STACK research |
| `requests` | `>=2.32` (already installed) | Streaming PDF download once URL is known | Already present; `stream=True` + `iter_content(8192)` pattern for large PDFs |
| `playwright` | `>=1.48` (installed in Phase 6) | Playwright fallback — JS-rendered corporate sites where ddgs returns no direct PDF URL | Thread isolation pattern confirmed working in Phase 6 smoke test |
| `streamlit` | `>=1.54` (already installed) | `st.file_uploader` widget for drag-and-drop PDF upload | Built-in; returns `UploadedFile` which is a file-like object compatible with `pdfplumber` and `PyMuPDF` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pathlib` | stdlib | Path construction for `data/latam/{country}/{slug}/raw/` | Always — consistent with existing codebase |
| `hashlib` | stdlib | SHA-256 fingerprint for downloaded PDFs | Deduplication: if same file already exists (by hash), skip write |
| `dataclasses` | stdlib | `ScraperResult` structured return type | Replace bare `dict` with typed result that makes status/error handling explicit |
| `loguru` | `>=0.7` (already installed) | Log every scraping attempt, strategy used, outcome | Consistent with existing pipeline logging |
| `time` + `random` | stdlib | Randomized delays between ddgs retries | Required to avoid RatelimitException |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ddgs` for primary search | `httpx` + direct Google SERP parse | Google has stronger anti-scraping; ddgs multi-backend fallback is more resilient |
| `requests` streaming download | `httpx` streaming | Both work; `requests` is already in env, no new dep |
| `dataclasses.dataclass` for result | `TypedDict` | TypedDict requires Python 3.8+ type checking but not runtime enforcement; dataclass gives `__repr__` and field defaults for free |

**Installation (no new deps — all installed in Phase 6):**
```bash
# All required packages were installed in Phase 6
# Verify:
python -c "from ddgs import DDGS; from playwright.sync_api import sync_playwright; import requests; print('OK')"
```

---

## Architecture Patterns

### Recommended Project Structure (Phase 7 files)

```
AI 2026/
├── latam_scraper.py           # EXTEND from Phase 6 skeleton — full implementation here
│                              #   search() — ddgs primary path
│                              #   scrape_with_playwright() — Playwright fallback
│                              #   download_pdf() — shared download helper
│                              #   _playwright_worker() — thread-isolated worker
│                              #   ScraperResult — dataclass return type
├── portal_adapters/           # NEW directory — one adapter per regulatory portal
│   ├── __init__.py
│   ├── supersalud.py          # CO — Supersalud (health sector only)
│   ├── sfc.py                 # CO — SFC (financial sector)
│   ├── smv.py                 # PE — SMV
│   ├── cmf.py                 # CL — CMF
│   ├── cnv.py                 # AR — CNV
│   └── cnbv.py               # MX — CNBV
├── data/latam/
│   └── {country}/{slug}/
│       └── raw/               # Raw PDF storage — created by download_pdf()
└── tests/
    ├── test_latam_scraper.py  # NEW — ddgs search, download, error return tests
    └── test_portal_adapters.py # NEW — portal adapter URL construction tests
```

### Pattern 1: ScraperResult Dataclass (Structured Return)

**What:** All scraping functions return `ScraperResult` — never raise exceptions for "not found" conditions. Exceptions propagate only for genuine programming errors.

**When to use:** Every function that attempts to acquire a PDF. Callers check `.ok` before proceeding.

**Example:**
```python
# latam_scraper.py
# Source: Python stdlib dataclasses — no external dependency
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

@dataclass
class ScraperResult:
    ok: bool
    pdf_path: Optional[Path] = None
    strategy: str = ""          # "ddgs", "playwright", "portal", "upload"
    source_url: Optional[str] = None
    error: Optional[str] = None
    attempts: list[str] = field(default_factory=list)  # log of strategies tried

    @property
    def failed(self) -> bool:
        return not self.ok

# Usage:
# result = search("empresa.com", 2024)
# if result.ok:
#     extract(result.pdf_path)
# else:
#     logger.warning(f"Scrape failed: {result.error}; tried: {result.attempts}")
```

### Pattern 2: DDGS Semantic Search — Primary Path

**What:** Construct `site:domain filetype:pdf "Estado de Situación Financiera" {year}` query, run through DDGS, extract `href` from first result that ends in `.pdf`. Download with `requests`.

**When to use:** First strategy for every company. No browser required — runs in Streamlit main thread safely.

**DDGS API facts (confirmed):**
- Import: `from ddgs import DDGS`
- Method: `DDGS().text(query, max_results=N, backend="auto")`
- Return: list of dicts with keys `title`, `href`, `body`
- Operator support: `site:`, `filetype:`, `intitle:`, exact phrases — all confirmed working
- Exceptions: `DDGSException` (base), `RatelimitException`, `TimeoutException` — import from `ddgs.exceptions`
- Backend options: `"auto"`, `"google"`, `"bing"`, `"brave"`, `"duckduckgo"`, `"yahoo"`, `"yandex"`, etc.

**Example:**
```python
# latam_scraper.py
# Source: ddgs 9.x official docs + DeepWiki deedy5/ddgs (2026-03-04)
import time
import random
from ddgs import DDGS
from ddgs.exceptions import RatelimitException, TimeoutException, DDGSException

SEARCH_KEYWORDS_ES = '"Estado de Situación Financiera"'
SEARCH_KEYWORDS_ALT = '"informe anual" "estados financieros"'

def search(domain: str, year: int) -> ScraperResult:
    """
    Primary strategy: semantic ddgs search for annual report PDF.
    Returns ScraperResult with ok=True and pdf_path set if PDF found and downloaded.
    Returns ScraperResult with ok=False and error message if nothing found.
    Never raises.
    """
    attempts = []
    queries = [
        f'site:{domain} filetype:pdf {SEARCH_KEYWORDS_ES} {year}',
        f'site:{domain} filetype:pdf {SEARCH_KEYWORDS_ALT} {year}',
        f'site:{domain} filetype:pdf "informe anual" {year}',
    ]

    for query in queries:
        attempts.append(f"ddgs:{query[:60]}")
        pdf_url = _ddgs_first_pdf_url(query)
        if pdf_url:
            return _download_pdf(pdf_url, strategy="ddgs", attempts=attempts)
        time.sleep(random.uniform(2.0, 4.0))  # Rate limit avoidance

    return ScraperResult(
        ok=False,
        strategy="ddgs",
        error=f"No PDF URL found for domain={domain} year={year} after {len(queries)} queries",
        attempts=attempts,
    )

def _ddgs_first_pdf_url(query: str, max_results: int = 5) -> Optional[str]:
    """Return first href ending in .pdf from DDGS search, or None."""
    for attempt in range(3):
        try:
            results = DDGS().text(query, max_results=max_results, backend="auto")
            for r in results:
                href = r.get("href", "")
                if href.lower().endswith(".pdf"):
                    return href
            return None  # Results found but none are direct PDF links
        except RatelimitException:
            wait = (2 ** attempt) * random.uniform(3.0, 6.0)
            time.sleep(wait)
        except (TimeoutException, DDGSException):
            return None
    return None
```

### Pattern 3: Playwright PDF Discovery — Fallback Path

**What:** When ddgs returns no direct PDF URL, Playwright navigates to the corporate website, looks for PDF links using heuristics, and downloads the first match.

**When to use:** Only when `search()` returns `ok=False`. Always called via `ThreadPoolExecutor` — never from Streamlit main thread.

**Heuristics for finding PDF links on LATAM corporate sites:**
1. CSS selector `a[href$=".pdf"]` — anchor tags with href ending in `.pdf`
2. CSS selector `a[href*="/informe"], a[href*="/reporte"], a[href*="/annual"]` — common IR path fragments
3. Check common LATAM IR page URL fragments: `relaciones-con-inversionistas`, `informes-anuales`, `inversionistas`, `sala-de-prensa`, `informacion-financiera`
4. `page.wait_for_load_state("networkidle")` before querying — many LATAM sites are JS-heavy SPAs

**Example:**
```python
# latam_scraper.py
# Source: Playwright Python docs (playwright.dev/python) + confirmed thread pattern from Phase 6
import concurrent.futures
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

PDF_LINK_SELECTORS = [
    'a[href$=".pdf"]',
    'a[href*="informe"][href*=".pdf"]',
    'a[href*="reporte"][href*=".pdf"]',
    'a[href*="annual"][href*=".pdf"]',
    'a[href*="estados-financieros"]',
    'a[href*="memoria-anual"]',
]

IR_PAGE_FRAGMENTS = [
    "relaciones-con-inversionistas",
    "informes-anuales",
    "sala-de-inversionistas",
    "informacion-financiera",
    "inversionistas",
    "investor-relations",
    "annual-report",
]

def scrape_with_playwright(base_url: str, year: int, attempts: list) -> ScraperResult:
    """Fallback: launch browser, find PDF link via heuristics, download."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_playwright_find_pdf, base_url, year)
        try:
            pdf_url = future.result(timeout=120)
        except concurrent.futures.TimeoutError:
            return ScraperResult(ok=False, strategy="playwright",
                                 error="Browser timeout after 120s", attempts=attempts)
    if pdf_url:
        return _download_pdf(pdf_url, strategy="playwright", attempts=attempts)
    return ScraperResult(ok=False, strategy="playwright",
                         error=f"No PDF link found on {base_url}", attempts=attempts)

def _playwright_find_pdf(base_url: str, year: int) -> Optional[str]:
    """
    Runs in its own thread — creates its own sync_playwright() instance.
    Navigates to base_url, tries to find a PDF link for the given year.
    Returns PDF URL or None.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(base_url, timeout=30_000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=15_000)

            # Try direct PDF links on current page
            pdf_url = _find_pdf_link_on_page(page, year)
            if pdf_url:
                return pdf_url

            # Try navigating to IR sub-pages
            for fragment in IR_PAGE_FRAGMENTS:
                try:
                    ir_link = page.locator(f'a[href*="{fragment}"]').first
                    if ir_link.count() > 0:
                        ir_link.click(timeout=5_000)
                        page.wait_for_load_state("networkidle", timeout=10_000)
                        pdf_url = _find_pdf_link_on_page(page, year)
                        if pdf_url:
                            return pdf_url
                except PlaywrightTimeout:
                    continue
        finally:
            browser.close()
    return None

def _find_pdf_link_on_page(page, year: int) -> Optional[str]:
    """Scan current page for PDF anchors. Prefer links containing the year."""
    for selector in PDF_LINK_SELECTORS:
        links = page.locator(selector).all()
        for link in links:
            href = link.get_attribute("href") or ""
            if str(year) in href or str(year) in (link.inner_text() or ""):
                return href  # Prefer year-matched links first
        if links:
            # Fallback: return first PDF link even without year match
            href = links[0].get_attribute("href") or ""
            if href:
                return href
    return None
```

### Pattern 4: PDF Download Helper (Streaming, Validated)

**What:** Shared utility called by all scraping strategies. Validates content-type, streams download to avoid memory exhaustion, names file from URL.

**When to use:** Called by `search()`, `scrape_with_playwright()`, and portal adapters — the single download path.

**Example:**
```python
# latam_scraper.py
# Source: requests docs + confirmed pattern (requests.readthedocs.io)
import hashlib
import re

def _download_pdf(
    url: str,
    out_dir: Path,
    strategy: str,
    attempts: list,
    timeout: int = 30,
) -> ScraperResult:
    """
    Download PDF from URL to out_dir/raw/{filename}.pdf with streaming.
    Validates Content-Type. Returns ScraperResult.
    """
    try:
        head = requests.head(url, timeout=timeout, allow_redirects=True)
        content_type = head.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
            return ScraperResult(
                ok=False, strategy=strategy,
                error=f"URL does not appear to be a PDF (Content-Type: {content_type})",
                attempts=attempts,
            )

        filename = _normalize_filename(url)
        raw_dir = out_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = raw_dir / filename

        if pdf_path.exists():
            return ScraperResult(ok=True, pdf_path=pdf_path,
                                 strategy=strategy, source_url=url, attempts=attempts)

        resp = requests.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()

        with pdf_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return ScraperResult(ok=True, pdf_path=pdf_path, strategy=strategy,
                             source_url=url, attempts=attempts)

    except requests.RequestException as e:
        return ScraperResult(ok=False, strategy=strategy,
                             error=f"Download failed: {e}", attempts=attempts)

def _normalize_filename(url: str) -> str:
    """Extract filename from URL; fall back to SHA-256 prefix if not deterministic."""
    name = url.rstrip("/").split("/")[-1]
    name = re.sub(r"[^\w.\-]", "_", name)  # Windows-safe chars only
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    # If name is generic (e.g., "download.php.pdf"), prefix with URL hash
    if len(name) < 8 or name.startswith("download"):
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
        name = f"{url_hash}_{name}"
    return name
```

### Pattern 5: st.file_uploader — Manual Upload Path

**What:** Dashboard accepts a manually uploaded PDF via Streamlit drag-and-drop. Writes to `data/latam/{country}/{slug}/raw/` and returns same `ScraperResult` format as automated paths.

**When to use:** When analyst clicks "Subir PDF manualmente" in the LATAM section of the dashboard.

**Key facts about `st.file_uploader` (confirmed from official docs):**
- Returns `UploadedFile` object, which is a file-like object
- `uploaded_file.getvalue()` → `bytes`
- `uploaded_file.name` → original filename
- Compatible directly with `pdfplumber.open(uploaded_file)` and `fitz.open(stream=bytes, filetype="pdf")`
- Widget `key` MUST use `latam_` prefix to avoid DuplicateWidgetID

**Example:**
```python
# In app.py LATAM section — Phase 11 will integrate; Phase 7 defines the handler
# Source: Streamlit official docs (docs.streamlit.io/develop/api-reference/widgets/st.file_uploader)

def handle_upload(uploaded_file, out_dir: Path) -> ScraperResult:
    """
    Save an UploadedFile from st.file_uploader to data/latam/.../raw/.
    Returns ScraperResult for downstream pipeline compatibility.
    SCRAP-04: pipeline is identical regardless of PDF origin.
    """
    try:
        raw_dir = out_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = raw_dir / _normalize_filename_from_upload(uploaded_file.name)
        pdf_path.write_bytes(uploaded_file.getvalue())
        return ScraperResult(ok=True, pdf_path=pdf_path,
                             strategy="upload", source_url=None,
                             attempts=["upload:drag-and-drop"])
    except Exception as e:
        return ScraperResult(ok=False, strategy="upload",
                             error=f"Upload save failed: {e}",
                             attempts=["upload:drag-and-drop"])

# In app.py (LATAM section — lazy import pattern REQUIRED):
# def render_latam_upload_section(out_dir: Path):
#     try:
#         import latam_scraper
#     except ImportError:
#         st.error("latam_scraper module not found. Check installation.")
#         return
#     uploaded = st.file_uploader(
#         "Subir PDF anual manualmente",
#         type=["pdf"],
#         key="latam_pdf_upload",        # latam_ prefix mandatory
#     )
#     if uploaded is not None:
#         result = latam_scraper.handle_upload(uploaded, out_dir)
#         if result.ok:
#             st.session_state["latam_scraped_pdf"] = str(result.pdf_path)
#             st.success(f"PDF guardado: {result.pdf_path.name}")
```

### Pattern 6: Portal Adapter Interface

**What:** Each regulatory portal gets its own adapter module with a single `find_pdf(regulatory_id, year)` function returning `Optional[str]` (a direct PDF URL or None).

**When to use:** Called from `latam_scraper.search_portal()` when the user provides a regulatory ID (NIT, RUC, RUT).

**Example:**
```python
# portal_adapters/smv.py — Peru SMV adapter skeleton
# NOTE: URL patterns are LOW confidence — validate live before completing
from typing import Optional
from loguru import logger
import requests

def find_pdf(ruc: str, year: int) -> Optional[str]:
    """
    Try to find annual report PDF for a company registered with Peru's SMV.
    ruc: 11-digit Peruvian RUC number (e.g., "20100003539")
    year: fiscal year (e.g., 2023)
    Returns direct PDF URL or None.
    NOTE: SMV SIMV uses obfuscated ?data= parameters — direct URL construction
    is not reliable. Use Open Data API or Playwright fallback.
    """
    # Attempt 1: SMV Open Data API (best effort — requires live validation)
    # SMV Open Data portal: mvnet.smv.gob.pe/SMV.OpenData.Web/
    # Empresa listing includes RUC for search
    try:
        # SMV temp PDF path pattern (observed from search results):
        # https://www.smv.gob.pe/ConsultasP8/temp/{DOCUMENT_ID}.pdf
        # No reliable programmatic URL construction via RUC without JS execution.
        # Log and return None — Playwright fallback will handle.
        logger.warning(f"SMV adapter: no direct URL construction for RUC={ruc}, year={year}. "
                       "Playwright fallback required.")
        return None
    except Exception as e:
        logger.debug(f"SMV adapter failed: {e}")
        return None
```

### Anti-Patterns to Avoid

- **Raising exceptions for "not found":** All `search()`, `scrape_with_playwright()`, and portal adapter functions must return `ScraperResult` with `ok=False`. Only programming errors (bugs) should raise.
- **Calling `DDGS().text()` in a tight loop without delay:** RatelimitException triggers at 10-20 requests/session from home IPs. Add `time.sleep(random.uniform(2, 4))` between calls.
- **Calling Playwright from Streamlit main thread:** Raises `NotImplementedError` on Windows 11. Always use `ThreadPoolExecutor`.
- **Sharing one playwright instance across threads:** Playwright is not thread-safe. Each thread needs its own `sync_playwright()` call.
- **Using `a[href*=".pdf"]` as a CSS selector:** Use `a[href$=".pdf"]` (ends-with) for strict PDF links; `a[href*=".pdf"]` may match `.pdf.html` or tracking URLs. Use `*=` only as secondary fallback.
- **Assuming Content-Type `application/pdf` is always set:** Some LATAM servers return `application/octet-stream` or `binary/octet-stream` for PDFs. Fall back to checking URL extension when Content-Type is ambiguous.
- **Importing `latam_scraper` at the top of `app.py`:** Must use lazy import inside function with `try/except ImportError` — breaking the S&P 500 section is unacceptable.
- **Building portal adapters without live testing the URL patterns:** Every LATAM regulatory portal uses JS-rendered pages, obfuscated parameters, or session-based URLs. Treat all portal URL patterns as LOW confidence until validated live during implementation.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rate-limited web search | Custom retry/backoff from scratch | `ddgs` with `RatelimitException` catch + `random.uniform(2,4)` sleep | Proven pattern from existing codebase pattern (PITFALLS.md); ddgs handles backend rotation |
| PDF URL extraction from search results | Custom regex on HTML | `DDGS().text()` → filter `result["href"]` for `.pdf` suffix | ddgs returns clean `href` dict key — no HTML parsing needed |
| Structured error passing across scraping paths | dict with `"status"` key | `@dataclass ScraperResult` | Typed fields prevent key-name bugs; `__repr__` aids debugging; stdlib, no new dep |
| Browser-based file download | Playwright `page.goto(pdf_url)` | `requests.get(url, stream=True)` once URL is known | Once you have the URL, `requests` is faster, simpler, no browser overhead |
| Content-Type sniffing for PDFs | Custom magic-byte check | Check `Content-Type` header + URL extension fallback | Sufficient for known LATAM regulatory sources; magic-byte check adds complexity with no practical benefit at this scale |

**Key insight:** The hardest part of LATAM scraping is URL *discovery*, not download. Once a PDF URL is known (from ddgs or Playwright), plain `requests` streaming is the correct download tool — don't use Playwright for the actual download step.

---

## Common Pitfalls

### Pitfall 1: DDGS Returns Results But None Are Direct PDF URLs

**What goes wrong:** `DDGS().text('site:empresa.com filetype:pdf "Estado de Situación Financiera" 2023')` returns 5 results, but all `href` values point to search result pages, tracker redirects, or HTML pages — not `.pdf` files. The search "succeeded" but produced no actionable URL.

**Why it happens:** The `filetype:pdf` operator is a hint to the search engine, not a guarantee. Some backends (especially in certain regions) return partial results or ignore filetype filters. Corporate websites may serve PDFs through download scripts (`/download.php?id=123`) that don't have `.pdf` extensions.

**How to avoid:**
1. Check `href` ends with `.pdf` OR contains `.pdf?` (before query string)
2. If no direct `.pdf` URL found after all query variants, do NOT treat as "no PDF exists" — trigger Playwright fallback
3. Add a secondary query without `filetype:pdf` operator: `site:domain "Estado de Situación Financiera" {year} informe anual` — let Playwright handle the resulting HTML page

**Warning signs:** All returned `href` values contain `duckduckgo.com/y.js` or similar tracker domains; `ok=False` on companies known to have public PDFs.

---

### Pitfall 2: DDGS RatelimitException Triggers Mid-Pipeline

**What goes wrong:** After 10-20 queries in a session (common when processing multiple companies in batch), `DDGS().text()` raises `RatelimitException`. If not caught, the entire pipeline crashes.

**Why it happens:** DuckDuckGo rate-limits programmatic access by IP. The threshold is undocumented and varies by backend, time of day, and IP reputation. Home IP addresses are more likely to be rate-limited than datacenter IPs.

**How to avoid:**
1. Catch `RatelimitException` explicitly (not just `DDGSException`) with exponential backoff
2. Add `time.sleep(random.uniform(2.0, 4.0))` between every query, not just on failure
3. Limit to 3 query variants per company per session
4. Cache results to `data/cache/ddgs_cache.json` keyed by `(domain, year)` — never repeat the same search twice in the same session

**Warning signs:** `RatelimitException: 202 Ratelimit` appears in logs; empty results for well-known companies.

---

### Pitfall 3: Playwright Opens PDF in Browser Instead of Downloading

**What goes wrong:** Playwright clicks a PDF link and Chromium opens a PDF viewer tab instead of triggering a download event. The `page.expect_download()` context never fires.

**Why it happens:** Chromium's built-in PDF viewer intercepts PDF navigation by default. This is the default behavior unless the Playwright launch flags disable the PDF viewer plugin.

**How to avoid:** Two strategies:
1. **Preferred:** Extract the `href` attribute from the PDF link and download with `requests` — never click the link in the browser.
2. **Fallback:** Launch Chromium with `args=["--disable-pdf-viewer"]` or use `page.route()` to intercept PDF responses and abort navigation (forcing download behavior).

```python
# Preferred pattern — get URL, download with requests (not via browser)
pdf_links = page.locator('a[href$=".pdf"]').all()
if pdf_links:
    href = pdf_links[0].get_attribute("href")
    # Make absolute if relative
    if href.startswith("/"):
        href = base_url.rstrip("/") + href
    return href  # Caller downloads with requests
```

**Warning signs:** Playwright script hangs waiting for download event; memory usage spikes (browser keeps PDF in memory).

---

### Pitfall 4: Regulatory Portal URLs Are Session-Dependent or JavaScript-Rendered

**What goes wrong:** For SMV (Peru), CMF (Chile), and Supersalud (Colombia), the financial document URLs contain obfuscated `?data=HEX_ENCODED_STRING` parameters that encode session IDs, company codes, and time ranges. These URLs are not constructable from a RUC/NIT/RUT alone — they require a valid browser session.

**Why it happens:** LATAM regulatory portals frequently use enterprise Java frameworks (e.g., Oracle ADF) that generate one-time session tokens baked into URLs. The "URL" visible in the browser address bar is not a persistent resource identifier.

**How to avoid:**
1. Treat portal adapters as "best effort" — always fall through to Playwright fallback if no direct URL can be constructed
2. For SMV: use the Open Data API endpoint (`mvnet.smv.gob.pe/SMV.OpenData.Web/`) which provides structured data, rather than scraping the SIMV interface
3. For CMF: use the IFRS query interface (`cmfchile.cl/institucional/estadisticas/merc_valores/sa_eeff_ifrs/`) which has more stable URL patterns for bank/entity lookups
4. For Supersalud: no stable URL pattern found — Playwright fallback is the primary path
5. Document portal status (working/broken) in `portal_adapters/__init__.py` as constants

**Warning signs:** Portal adapter returns None for every company; URL pattern from research doesn't resolve to a valid document.

---

### Pitfall 5: st.file_uploader Widget Causes DuplicateWidgetID

**What goes wrong:** Adding `st.file_uploader("PDF", type=["pdf"])` in the LATAM section causes `streamlit.errors.DuplicateWidgetID` if the `key` parameter is absent or uses a generic name already in use.

**Why it happens:** Streamlit 1.35+ requires unique `key` for all widgets. Copying widget code from the S&P 500 section without changing the key is the most common source.

**How to avoid:** Always pass `key="latam_pdf_upload"` (or similar `latam_`-prefixed key). Rule: every widget in the LATAM section must have a `latam_` prefix in its key.

**Warning signs:** `DuplicateWidgetID` error immediately after adding the upload widget; error references the S&P 500 section even though the bug is in the LATAM section.

---

### Pitfall 6: Downloaded PDF Is HTML Error Page, Not PDF

**What goes wrong:** `download_pdf()` succeeds (HTTP 200), `pdf_path` is written, but the file contains HTML (`<!DOCTYPE html>`) — a CAPTCHA page, login redirect, or "access denied" page — rather than a PDF.

**Why it happens:** Some LATAM corporate sites serve 200 OK for bot-detected requests but return an HTML interstitial page instead of the requested PDF. The download function trusts the HTTP status code.

**How to avoid:** After download, validate the first 4 bytes: PDF files start with `%PDF` (bytes `25 50 44 46`). If the magic bytes don't match, delete the file and return `ScraperResult(ok=False, error="Downloaded file is not a valid PDF")`.

```python
def _validate_pdf_magic(path: Path) -> bool:
    """Returns True if file starts with %PDF magic bytes."""
    with path.open("rb") as f:
        return f.read(4) == b"%PDF"
```

**Warning signs:** Phase 8 extractor raises `pdfplumber.exceptions.PSException` on "successfully" downloaded files; file size is suspiciously small (< 10 KB).

---

## Code Examples

Verified patterns from official sources:

### DDGS Search — Confirmed API

```python
# Source: ddgs 9.x official docs (github.com/deedy5/ddgs) — confirmed 2026-03-04
# Return format: list[dict] with keys: title, href, body
from ddgs import DDGS
from ddgs.exceptions import RatelimitException, TimeoutException

results = DDGS().text(
    'site:clinicalasamericas.com.co filetype:pdf "Estado de Situación Financiera" 2023',
    max_results=5,
    backend="auto",  # "auto" = multi-backend with Wikipedia priority
)
# results = [{"title": "...", "href": "https://..../informe-2023.pdf", "body": "..."}, ...]
pdf_urls = [r["href"] for r in results if r["href"].lower().endswith(".pdf")]
```

### Playwright PDF Link Discovery

```python
# Source: Playwright Python docs (playwright.dev/python/docs/locators) — confirmed 2026-03-04
# CSS attribute selector: href$=".pdf" means href ENDS WITH ".pdf"
pdf_links = page.locator('a[href$=".pdf"]').all()
for link in pdf_links:
    href = link.get_attribute("href")  # returns str or None
    text = link.inner_text()           # visible link text for year matching
```

### Streaming PDF Download

```python
# Source: requests docs (requests.readthedocs.io) — confirmed pattern
import requests

resp = requests.get(pdf_url, stream=True, timeout=30)
resp.raise_for_status()
with open(output_path, "wb") as f:
    for chunk in resp.iter_content(chunk_size=8192):
        f.write(chunk)
```

### st.file_uploader — Confirmed API

```python
# Source: Streamlit docs (docs.streamlit.io/develop/api-reference/widgets/st.file_uploader)
# UploadedFile is a file-like object compatible with pdfplumber and fitz
uploaded = st.file_uploader(
    "Subir informe anual PDF",
    type=["pdf"],
    key="latam_pdf_upload",   # MUST use latam_ prefix
    accept_multiple_files=False,
)
if uploaded is not None:
    pdf_bytes = uploaded.getvalue()    # bytes
    filename = uploaded.name           # original filename
    # Write to disk:
    output_path.write_bytes(pdf_bytes)
    # OR pass directly to pdfplumber:
    # import pdfplumber; pdfplumber.open(uploaded)
```

### ScraperResult Usage Pattern

```python
# Primary flow in latam_agent.py (Phase 9 will use this):
result = latam_scraper.search(domain="empresa.com.co", year=2023)
if result.failed:
    result = latam_scraper.scrape_with_playwright(
        base_url="https://empresa.com.co", year=2023, attempts=result.attempts
    )
if result.failed:
    result = portal_adapters.supersalud.find_and_download(nit="800058016", year=2023)
if result.failed:
    logger.error(f"All strategies failed: {result.error}; tried: {result.attempts}")
    return result  # Caller decides: show upload prompt or abort
# Proceed to extraction:
extraction_result = latam_extractor.extract(result.pdf_path)
```

---

## Regulatory Portal Status

| Portal | Country | ID Type | URL Pattern Confidence | Primary Entry Point | Notes |
|--------|---------|---------|----------------------|---------------------|-------|
| Supersalud | CO | NIT | LOW | `docs.supersalud.gov.co/PortalWeb/` | JS-heavy; URL pattern requires session; Playwright fallback primary |
| SMV SIMV | PE | RUC | LOW | `smv.gob.pe/SIMV/` | Obfuscated `?data=HEX` params; Open Data API at `mvnet.smv.gob.pe/SMV.OpenData.Web/` is more stable |
| CMF | CL | RUT | LOW-MEDIUM | `cmfchile.cl/bancos/estados_anuales/{year}/` | Bank sector: stable URL pattern `{year}MM-{code}.pdf`; non-bank IFRS portal is JS-rendered |
| SFC | CO | NIT | LOW | `superfinanciera.gov.co/entidades/` | Financial sector (banks, insurance); separate from Supersalud health sector |
| CNV | AR | CUIT | LOW | `cnv.gov.ar` | Argentine peso instability adds context; site structure not researched in depth |
| CNBV | MX | RFC | LOW | `cnbv.gob.mx` | Mexican banking regulator; not researched in depth |

**Critical note for Phase 7 planning:** All portal URL patterns are LOW confidence. The Phase 7 plan MUST include a "live validation spike" task for each portal adapter before committing the adapter implementation. The spike confirms whether the URL pattern works and, if not, pivots to Playwright-based navigation of that portal.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `duckduckgo-search` package | `ddgs` package | 2024-2025 | `duckduckgo-search` is deprecated; `ddgs` supports multi-backend (Google, Bing, Brave, etc.) |
| `DDGS().text(backend="html")` | `backend="auto"` | ddgs 9.x | Auto mode rotates backends automatically; more resilient to single-backend rate limits |
| Playwright click-to-download | Extract href + requests download | Always preferred | Avoids Chromium PDF viewer interception; faster; no browser memory overhead for download |
| Single monolithic scraper | Strategy pattern with ScraperResult | Best practice | Enables isolated testing of each strategy; structured error reporting |

**Deprecated/outdated:**
- `duckduckgo-search` (pip package): deprecated; use `ddgs>=9.0` instead
- `backend="html"` in DDGS: older backend mode; use `"auto"` in ddgs 9.x for multi-backend rotation

---

## Open Questions

1. **SMV Open Data API: can it be queried by RUC to find annual report PDF directly?**
   - What we know: `mvnet.smv.gob.pe/SMV.OpenData.Web/Views/Datasets/Empresas_Inscritas.aspx` lists companies by RUC; web service mentioned but not documented
   - What's unclear: Whether the web service returns direct PDF links or just company metadata
   - Recommendation: Phase 7 plan session 1 spike — HTTP GET to the Open Data endpoint with a known RUC; log response structure; 30-minute timebox

2. **CMF Bank sector vs. non-bank sector URL patterns**
   - What we know: Bank PDFs follow `cmfchile.cl/bancos/estados_anuales/{year}/Bancos-{year}/{YYYYMM}-{code}.pdf` — seems machine-readable; non-bank IFRS portal is JS-rendered
   - What's unclear: The `{code}` component — is it the RUT? A CMF internal code? Needs validation
   - Recommendation: Test with Banco de Chile RUT (`97006000-6`) against the discovered URL pattern; if `code` maps to a known field in COMP-02 registry, implement a simple URL constructor; otherwise use Playwright

3. **ddgs `filetype:pdf` operator effectiveness for LATAM domains**
   - What we know: `filetype:pdf` is a confirmed operator in ddgs 9.x; it works for Google and Bing backends; DuckDuckGo backend may ignore it
   - What's unclear: Effectiveness rate for Latin American corporate domains that may not be well-indexed for filetype-specific searches
   - Recommendation: Test in Phase 7 session 1 against 2-3 known LATAM companies with public PDFs; if effectiveness is below 50%, add `informe anual filetype:pdf site:` as a secondary query before triggering Playwright

4. **Supersalud: does it have a machine-readable endpoint?**
   - What we know: `docs.supersalud.gov.co/PortalWeb/` is the document base URL; Supersalud hosts statistics at `/cifras-y-estadisticas`; the portal appears to be traditional CMS with direct PDF storage
   - What's unclear: Whether there is a search API or whether PDF discovery requires crawling the portal
   - Recommendation: Try a ddgs search `site:docs.supersalud.gov.co filetype:pdf {company_name} {year}` — if the docs subdomain is indexed, this may work without portal scraping

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none (rootdir auto-detected as `C:\Users\Seb\AI 2026`) |
| Quick run command | `python -m pytest tests/test_latam_scraper.py -v` |
| Full suite command | `python -m pytest tests/ -v` |
| Estimated runtime | ~15-20 seconds (unit tests with mocked ddgs; integration tests with live URL ~30s) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCRAP-01 | `search("empresa.com", 2023)` returns `ScraperResult(ok=True, pdf_path=...)` when ddgs returns a `.pdf` href | unit (mock ddgs) | `python -m pytest tests/test_latam_scraper.py::test_search_success -x` | Wave 0 gap |
| SCRAP-01 | `search("empresa.com", 2023)` returns `ScraperResult(ok=False)` when ddgs returns no `.pdf` href | unit (mock ddgs) | `python -m pytest tests/test_latam_scraper.py::test_search_no_pdf -x` | Wave 0 gap |
| SCRAP-01 | `RatelimitException` from ddgs causes retry with backoff; returns ok=False after 3 attempts | unit (mock) | `python -m pytest tests/test_latam_scraper.py::test_search_ratelimit -x` | Wave 0 gap |
| SCRAP-01 | Playwright fallback: `scrape_with_playwright("https://example.com", 2023)` returns `ScraperResult` (ok True or False, no exception) | integration (live) | `python -m pytest tests/test_latam_scraper.py::test_playwright_fallback -x` | Wave 0 gap |
| SCRAP-01 | `_validate_pdf_magic(path)` returns False for HTML file, True for valid PDF | unit | `python -m pytest tests/test_latam_scraper.py::test_pdf_magic -x` | Wave 0 gap |
| SCRAP-02 | Portal adapter: `smv.find_pdf("20100003539", 2023)` returns str or None (no exception) | unit (mock requests) | `python -m pytest tests/test_portal_adapters.py::test_smv_find_pdf -x` | Wave 0 gap |
| SCRAP-02 | Portal adapter: `cmf.find_pdf("97006000-6", 2023)` returns str or None (no exception) | unit (mock requests) | `python -m pytest tests/test_portal_adapters.py::test_cmf_find_pdf -x` | Wave 0 gap |
| SCRAP-04 | `handle_upload(uploaded_file, out_dir)` saves PDF to `out_dir/raw/` and returns `ScraperResult(ok=True)` | unit (BytesIO mock) | `python -m pytest tests/test_latam_scraper.py::test_handle_upload -x` | Wave 0 gap |
| SCRAP-04 | `handle_upload` with corrupted file (HTML bytes) still writes file (validation is Phase 8's responsibility) | unit (BytesIO mock) | `python -m pytest tests/test_latam_scraper.py::test_handle_upload_non_pdf -x` | Wave 0 gap |

### Nyquist Sampling Rate

- **Minimum sample interval:** After every committed task → run: `python -m pytest tests/test_latam_scraper.py -v`
- **Full suite trigger:** Before merging final task of any plan wave → `python -m pytest tests/ -v`
- **Phase-complete gate:** All scraper + portal adapter tests green, plus live smoke test against one real LATAM company before `/gsd:verify-work` runs
- **Estimated feedback latency per task:** ~15-20 seconds for unit tests; ~60 seconds including live integration tests

### Wave 0 Gaps (must be created before implementation)

- [ ] `tests/test_latam_scraper.py` — covers SCRAP-01 (ddgs search), SCRAP-04 (upload handler), PDF magic validation, Playwright fallback smoke
- [ ] `tests/test_portal_adapters.py` — covers SCRAP-02: at minimum SMV and CMF adapter tests (mock network)
- [ ] `portal_adapters/` directory with `__init__.py` — created before adapter implementations

*(Existing `tests/test_kpi_registry.py` is unrelated to Phase 7; no regression expected)*

---

## Sources

### Primary (HIGH confidence)

- ddgs 9.x GitHub (github.com/deedy5/ddgs) — `DDGS().text()` signature, return format, exception types, operator support (2026-03-04)
- ddgs PyPI (pypi.org/project/ddgs/) — version 9.11.1, Mar 2026; confirms successor to `duckduckgo-search` (2026-03-04)
- Playwright Python docs (playwright.dev/python/docs/locators) — `page.locator()`, `get_attribute("href")`, `all()` API (2026-03-04)
- Streamlit docs (docs.streamlit.io/develop/api-reference/widgets/st.file_uploader) — `UploadedFile.getvalue()`, `type=["pdf"]`, `key=` parameter (2026-03-04)
- Phase 6 RESEARCH.md — ThreadPoolExecutor + sync_playwright() per-thread pattern confirmed working (2026-03-04)
- Phase 6 PITFALLS.md — Playwright asyncio conflict, ddgs rate limit patterns, Windows-specific issues (2026-03-03)
- requests docs (requests.readthedocs.io) — streaming download with `stream=True` + `iter_content(8192)` (2026-03-04)

### Secondary (MEDIUM confidence)

- CMF Chile (cmfchile.cl) — bank sector PDF URL pattern `cmfchile.cl/bancos/estados_anuales/{year}/Bancos-{year}/{YYYYMM}-{code}.pdf` observed from search results (2026-03-04) — needs live validation
- DeepWiki deedy5/ddgs (deepwiki.com/deedy5/ddgs) — exception hierarchy and backend parameter docs (2026-03-04)
- SMV Peru (smv.gob.pe/SIMV/) + Open Data portal — `?data=HEX` obfuscation pattern observed; Open Data API mentioned (2026-03-04)
- Supersalud Colombia (supersalud.gov.co) — `docs.supersalud.gov.co/PortalWeb/` URL structure observed from search results (2026-03-04)

### Tertiary (LOW confidence)

- SFC Colombia (superfinanciera.gov.co) — URL structure not validated; entities page exists but programmatic access not confirmed (2026-03-04)
- CNV Argentina, CNBV Mexico — only identified as portal targets; URL patterns and access methods not researched (2026-03-04)
- ddgs `filetype:pdf` effectiveness for LATAM domains — confirmed operator syntax; effectiveness rate for LATAM corporate sites not empirically tested (2026-03-04)

---

## Metadata

**Confidence breakdown:**
- ddgs API (DDGS().text, operators, exceptions): HIGH — confirmed from official GitHub and ddgs 9.x docs
- Playwright PDF discovery patterns: HIGH — locator API confirmed from official docs; heuristic selectors are MEDIUM (reasonable but not live-tested on LATAM sites)
- ScraperResult dataclass pattern: HIGH — standard Python stdlib pattern
- st.file_uploader handler: HIGH — confirmed from official Streamlit docs
- Regulatory portal URL patterns: LOW — all require live validation; treat as hypotheses until confirmed during implementation
- PDF download + magic-byte validation: HIGH — confirmed requests streaming pattern + standard PDF header

**Research date:** 2026-03-04
**Valid until:** 2026-04-04 (ddgs version stable; regulatory portal structures LOW confidence — validate immediately during Phase 7 implementation)
