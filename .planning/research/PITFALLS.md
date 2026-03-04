# Pitfalls Research: LATAM Financial Analysis Pipeline (v2.0)

**Domain:** Adding LATAM web scraping + PDF extraction to existing Python/Streamlit financial dashboard on Windows 11
**Researched:** 2026-03-03
**Confidence:** HIGH (Windows-specific issues verified via official docs and community issue trackers; currency coverage verified against ECB/Frankfurter source)

> These pitfalls are specific to v2.0 additions. Pitfalls for the v1.0 S&P 500 pipeline
> are documented in the original PITFALLS.md and are not repeated here.

---

## Critical Pitfalls

### Pitfall 1: Playwright Sync API Crashes Inside Streamlit's Asyncio Loop

**What goes wrong:**
Calling any `sync_playwright()` function from within a Streamlit app raises:
```
Error: It looks like you are using Playwright Sync API inside the asyncio loop.
Please use the Async API instead.
```
On Windows 11, this is compounded by a second incompatibility: Playwright requires the `ProactorEventLoop` (to run browser subprocesses), but Streamlit's Tornado server uses the `SelectorEventLoop`. The result is either a crash with `NotImplementedError` or a silent hang.

**Why it happens:**
Streamlit runs an asyncio event loop internally (via Tornado). Playwright's synchronous API detects the running loop and refuses to execute. The Windows `SelectorEventLoop` additionally cannot handle subprocess communication, which Playwright requires to talk to its browser driver process. This is a Windows-specific aggravation of a general Playwright + async environment conflict.

**How to avoid:**
Run all Playwright scraping in a dedicated background thread with its own event loop — never in the Streamlit main thread. The correct pattern:

```python
import concurrent.futures
import asyncio
from playwright.sync_api import sync_playwright

def _scrape_in_thread(url: str) -> str:
    """Must be called via ThreadPoolExecutor, not from Streamlit main thread."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=30000)
        content = page.content()
        browser.close()
    return content

def scrape_url(url: str) -> str:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_scrape_in_thread, url)
        return future.result(timeout=60)
```

Each thread must have its own `sync_playwright()` instance — Playwright is not thread-safe across instances. Do NOT use `nest_asyncio` as a fix: it allows nesting but does not resolve the `ProactorEventLoop` requirement on Windows.

**Warning signs:**
- `NotImplementedError` or `RuntimeError: This event loop is already running` on first Playwright call from a Streamlit button
- App hangs indefinitely when a user triggers scraping
- Works fine when run from a plain `python script.py` but fails inside Streamlit

**Phase to address:** Phase 1 (LATAM scraper foundation) — validate the thread isolation pattern before writing any scraping logic. Add a single-URL smoke test that calls from the Streamlit UI context.

---

### Pitfall 2: Playwright Browser Binaries Not Found After pip install

**What goes wrong:**
After `pip install playwright`, running the scraper raises:
```
playwright._impl._errors.Error: Executable doesn't exist at ...
Run: playwright install
```
The Python package and the browser binaries are two separate install steps. In a conda environment on Windows, the `playwright install` command must be run inside the activated environment, and it downloads Chromium to `%USERPROFILE%\AppData\Local\ms-playwright` (shared across environments by default, but this path can diverge if `PLAYWRIGHT_BROWSERS_PATH` is set).

**Why it happens:**
`pip install playwright` only installs the Python wrapper. Browser executables (~300 MB for Chromium) must be downloaded separately via `playwright install chromium`. This step is easily missed in documentation, CI setups, or when moving between machines. On Windows, the download path is not on `PATH` — it is looked up by the Playwright driver at runtime — so it fails silently until first use.

**How to avoid:**
Add `playwright install chromium` to your environment setup script (e.g., `setup_env.bat`). Verify the install by running:
```bash
python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop(); print('OK')"
```
If moving to a different machine or rebuilding the conda env, re-run `playwright install chromium`. Optionally pin the browser path with `PLAYWRIGHT_BROWSERS_PATH` to a stable, non-user-profile location.

**Warning signs:**
- `Executable doesn't exist` error on first scrape attempt
- Works on dev machine, fails on a freshly cloned repo

**Phase to address:** Phase 1 — document in project README and environment setup script. Automate the `playwright install chromium` step in any `make setup` or `setup_env.bat` script.

---

### Pitfall 3: pytesseract Fails With TesseractNotFoundError on Windows

**What goes wrong:**
```
pytesseract.pytesseract.TesseractNotFoundError:
tesseract is not installed or it's not in your PATH.
```
This occurs even if Tesseract is installed, because pytesseract looks for the binary via `PATH` or an explicit `tesseract_cmd` variable. Windows `PATH` is not automatically updated by the Tesseract installer unless the user explicitly checks the "Add to PATH" option — which is unchecked by default in older installer versions.

**Why it happens:**
pytesseract is a Python wrapper; the actual OCR engine is a separate Windows binary (`tesseract.exe`). The installer puts it in `C:\Program Files\Tesseract-OCR\` but does not always add it to `PATH`. Additionally, language packs for Spanish (`spa`) must be selected during installation — they are not installed by default — or downloaded manually as `.traineddata` files.

**How to avoid:**
Add explicit path configuration at the top of the OCR module:

```python
import pytesseract
import os

TESSERACT_CMD = os.environ.get(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
```

During Tesseract installation:
1. Select "Additional language data (download)" in the installer.
2. Check `Spanish (spa)` and `Spanish (Old) (spa_old)` from the language list.
3. After install, verify with: `tesseract --list-langs` (should include `spa`).

For Spanish + number recognition in financial tables: use `lang='eng+spa'` to combine both language models.

**Warning signs:**
- `TesseractNotFoundError` on first pytesseract call
- OCR produces empty output or garbage for Spanish text (missing `spa` language pack)
- Works on one machine, fails on another — PATH inconsistency across machines

**Phase to address:** Phase 2 (PDF extractor) — add a startup check that validates `tesseract_cmd` points to an existing file and that `spa` is in `tesseract --list-langs` output. Fail fast with a clear error message, not a silent empty string.

---

### Pitfall 4: WeasyPrint Cannot Load GTK DLLs on Windows

**What goes wrong:**
```
OSError: cannot load library 'gobject-2.0': error 0x7e
OSError: dlopen() failed to load a library: cairo / cairo-2
```
WeasyPrint requires Pango, cairo, and GDK-PixBuf — native GTK libraries that must be installed as separate Windows binaries. These are not Python packages; they are system DLLs that WeasyPrint loads at runtime via cffi. Without them, `import weasyprint` itself may work, but `weasyprint.HTML(...).write_pdf()` will crash immediately.

**Why it happens:**
WeasyPrint v52+ (which dropped the old GTK+ Runtime installer) now recommends MSYS2 for the Windows GTK stack. The old "GTK3 Runtime" Windows installer is discontinued. Users following outdated tutorials install the old runtime, which puts DLLs in a location WeasyPrint can't find, or installs the wrong DLL filenames (e.g., `libgobject-2.0-0.dll` vs. `gobject-2.0-0.dll`).

**How to avoid:**
Use MSYS2 for GTK dependencies (the only officially supported path as of WeasyPrint v52+):

```bash
# 1. Install MSYS2 from https://www.msys2.org/
# 2. In MSYS2 shell:
pacman -S mingw-w64-x86_64-pango

# 3. Add to Windows PATH (System Environment Variables):
C:\msys64\mingw64\bin

# 4. Set WeasyPrint DLL directory:
set WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin
```

Then in Python code, set the DLL path explicitly before importing weasyprint:
```python
import os
os.environ.setdefault("WEASYPRINT_DLL_DIRECTORIES", r"C:\msys64\mingw64\bin")
import weasyprint
```

**Alternative if MSYS2 is too complex:** Replace WeasyPrint with `reportlab` or `fpdf2`. Both are pure-Python with no system dependencies and work on Windows without any extra install. ReportLab supports complex layouts with tables and charts; FPDF2 is simpler but sufficient for executive summary PDFs. Consider this trade-off seriously before committing to WeasyPrint on Windows.

**Warning signs:**
- `OSError: cannot load library` on first `weasyprint.HTML().write_pdf()` call
- Error references `gobject`, `cairo`, `pango`, or `gdk_pixbuf`
- Works on Linux/Mac CI but fails on Windows

**Phase to address:** Phase 4 (PDF report generation) — validate WeasyPrint OR make the call to switch to reportlab/fpdf2 before building any report templates. Do not assume WeasyPrint works until it has been tested end-to-end on the actual Windows machine.

---

### Pitfall 5: Frankfurter API Does Not Support Most LATAM Currencies

**What goes wrong:**
Calls to `https://api.frankfurter.app/latest?from=ARS&to=USD` return:
```json
{"message": "not found"}
```
or an HTTP 422 error. The Frankfurter API is backed by the European Central Bank (ECB), which tracks only 31 currencies — primarily major currencies. Of the key LATAM currencies for this project:

| Currency | Code | Frankfurter Support |
|----------|------|---------------------|
| Brazilian Real | BRL | YES |
| Mexican Peso | MXN | YES |
| Argentine Peso | ARS | NO |
| Chilean Peso | CLP | NO |
| Colombian Peso | COP | NO |
| Peruvian Sol | PEN | NO |

ARS, CLP, COP, and PEN are absent from ECB tracking and therefore unavailable. This is a hard API limitation, not a rate limit or temporary outage.

**Why it happens:**
The project description selected Frankfurter as a "free, no-key-required" API for FX normalization. This is correct for BRL and MXN, but the selection was not validated against the full list of needed LATAM currencies. ARS in particular is not ECB-tracked due to Argentina's exchange rate instability and capital controls.

**How to avoid:**
Use a tiered fallback strategy per currency:

1. **BRL, MXN** — Frankfurter API (reliable, ECB-backed)
2. **ARS, CLP, COP, PEN** — `exchangerate-api.com` free tier (no key, 1500 req/month) or `open.er-api.com` (no key required, covers 160+ currencies including all LATAM)
3. **All currencies** — hardcoded annual averages as last-resort fallback (from Banco Central, BCRP, SFC official publications)

The FX normalizer module must accept a currency code and route to the correct source transparently. Never assume Frankfurter covers the full LATAM currency set.

**Warning signs:**
- HTTP 422 or `{"message": "not found"}` from Frankfurter for ARS/CLP/COP/PEN
- All financial figures for Argentine/Chilean/Colombian/Peruvian companies show as `None` or `0` after normalization
- No error logged — the API call "succeeds" with an error JSON that the code silently ignores

**Phase to address:** Phase 3 (currency normalization) — before writing the normalizer, enumerate all currency codes that will appear in LATAM data and test each one against Frankfurter. Implement the tiered fallback immediately, not as a future enhancement.

---

### Pitfall 6: Scanned PDFs Return Empty Strings Without OCR Fallback

**What goes wrong:**
`pdfplumber.open(path).pages[0].extract_text()` returns `""` or `None` for a large proportion of LATAM financial reports. The PDF appears to have content visually (it renders correctly in a PDF viewer), but all text extraction returns empty.

**Why it happens:**
Many LATAM financial documents — especially from health sector regulators (Supersalud, SMV) and privately-held companies — are scanned documents: images embedded in a PDF wrapper, with no text layer. pdfplumber is built on pdfminer, which only processes text layers and cannot OCR image content. Additionally, some LATAM PDFs use non-standard embedded fonts or encryption that prevents text extraction even when a text layer exists.

**How to avoid:**
Implement a detection-and-fallback pipeline:

```python
def extract_text(path: str) -> str:
    with pdfplumber.open(path) as pdf:
        text = " ".join(
            page.extract_text() or "" for page in pdf.pages
        ).strip()

    if len(text) < 50:  # threshold: fewer than 50 chars = likely scanned
        # Fallback: render page as image, then OCR
        text = _ocr_pdf(path)

    return text

def _ocr_pdf(path: str) -> str:
    import fitz  # pymupdf
    doc = fitz.open(path)
    pages_text = []
    for page in doc:
        # Render at 300 DPI for OCR quality
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        pages_text.append(pytesseract.image_to_string(img, lang="eng+spa"))
    return "\n".join(pages_text)
```

The 50-character threshold is a heuristic; calibrate against your actual document corpus.

**Warning signs:**
- `extract_text()` returns empty string for visually non-empty PDFs
- Tables extract as `None` even when clearly visible in the document
- Different results for PDFs from the same company across years (some are scanned, some are born-digital)

**Phase to address:** Phase 2 (PDF extractor) — always implement the OCR fallback from day one. Do not build the extractor assuming all LATAM PDFs are born-digital; the health sector in particular has high scanned-document prevalence.

---

### Pitfall 7: duckduckgo-search Gets Rate-Limited or Blocked Without Warning

**What goes wrong:**
After a moderate number of requests, `DDGS().text(query)` raises:
```
duckduckgo_search.exceptions.RatelimitException: 202 Ratelimit
```
or returns empty results without raising an exception, making it appear that no search results exist for the query. The library has no configurable rate limit setting — it relies on DuckDuckGo's undocumented tolerance thresholds, which vary by backend (`html`, `lite`) and by IP.

**Why it happens:**
DuckDuckGo does not have a public API for programmatic search. The `duckduckgo-search` library reverse-engineers the DuckDuckGo web interface, which means DuckDuckGo can change rate limits, block patterns, or alter HTML structure without notice. Multiple reported incidents in early 2025 show rate limiting triggering at as few as 10-20 requests per session, particularly on home IP addresses.

**How to avoid:**
1. Cache all search results to disk (by query hash) — never repeat the same search in the same session.
2. Add randomized delays between searches: `time.sleep(random.uniform(2, 5))`.
3. Limit web search to the "context enrichment" phase only — do not call it in a tight loop or for every company on every run.
4. Wrap all DDGS calls in retry logic with exponential backoff and explicit `RatelimitException` handling:

```python
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import RatelimitException
import time, random

def search_with_retry(query: str, max_results: int = 5) -> list[dict]:
    for attempt in range(3):
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except RatelimitException:
            wait = (2 ** attempt) * random.uniform(3, 7)
            time.sleep(wait)
    return []  # graceful degradation — context enrichment is optional
```

5. Treat DDGS results as supplementary context, not as required data. If search fails, the pipeline continues without it.

**Warning signs:**
- `RatelimitException` after fewer than 20 queries in a session
- Empty results for clearly findable queries (e.g., company name + "informe financiero")
- Results inconsistent between runs for the same query

**Phase to address:** Phase 3 (web search integration) — design as optional/degradable from the start. Never make the pipeline block on search results; always log and continue.

---

## Moderate Pitfalls

### Pitfall 8: pdfplumber vs. pymupdf: Wrong Tool for the Job

**What goes wrong:**
Using pdfplumber for large, complex LATAM annual reports causes excessive memory use and slow processing. Using pymupdf (fitz) for structured table extraction on well-formatted PDFs misses the table bounding box detection that pdfplumber provides. Swapping libraries mid-project requires rewriting the extraction layer.

**Why it happens:**
pdfplumber excels at table extraction with visual bounding-box analysis, but it is significantly slower and more memory-intensive than pymupdf. pymupdf excels at raw text and image extraction speed but lacks pdfplumber's table detection. Many projects start with one and hit the other's limitations.

**How to avoid:**
Use both, each for what it does best:

| Task | Library | Reason |
|------|---------|--------|
| Table extraction from born-digital PDFs | pdfplumber | Bounding box analysis, column detection |
| Fast text extraction for overview/triage | pymupdf | 5-10x faster than pdfplumber for text |
| Page-to-image conversion for OCR | pymupdf | Built-in `page.get_pixmap()` at arbitrary DPI |
| Detecting scanned vs. text PDFs | pymupdf | `page.get_text()` fast check before pdfplumber |

Use pymupdf as the first-pass triage tool, then route to pdfplumber only for pages where table extraction is needed.

**Warning signs:**
- pdfplumber taking 30+ seconds per PDF for large reports
- Missing table data when using pymupdf alone
- Running both on every page unnecessarily

**Phase to address:** Phase 2 (PDF extractor architecture) — document the two-library strategy in the extractor module design before implementation.

---

### Pitfall 9: Spanish Character Encoding in Company Name Slugs for Storage Paths

**What goes wrong:**
Company names like `"Clínica Alemana"`, `"Organización Sanitas"`, or `"EPS Sánitas"` generate storage paths like `data/latam/Cl?nica Alemana/` on Windows, or cause `OSError: [WinError 123] The filename, directory name, or volume label syntax is incorrect` when the path contains characters Windows does not allow in file names (`<>:"/\|?*`).

**Why it happens:**
Windows NTFS technically supports Unicode filenames, but many characters that are valid in Spanish (`ñ`, accented vowels) can trigger encoding issues when conda/Python uses the system code page (CP1252 or CP850) instead of UTF-8. Additionally, Windows forbids certain characters in paths that are valid on Linux/macOS. Python's default file operations on Windows may not normalize paths correctly unless the code explicitly handles it.

**How to avoid:**
Generate slugs for all storage paths — never use raw company names as directory or file names:

```python
import unicodedata
import re

def make_slug(name: str, country: str) -> str:
    """Convert 'Clínica Alemana' + 'CL' -> 'clinica-alemana_CL'"""
    # Normalize unicode: decompose accented chars, then drop accents
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    # Lowercase, replace spaces/special chars with hyphen
    slug = re.sub(r"[^\w\s-]", "", ascii_name).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", slug)
    return f"{slug}_{country.upper()}"

# Result: "clinica-alemana_CL", "organizacion-sanitas_CO"
```

Store the display name (with accents) separately in metadata; use only the slug for filesystem paths. Alternatively use `python-slugify` library which handles this robustly.

**Warning signs:**
- `OSError` or `FileNotFoundError` for paths containing Spanish company names
- Paths display as `????` in Windows Explorer
- Parquet files saved but cannot be reopened due to path encoding mismatch

**Phase to address:** Phase 1 (LATAM data storage design) — define the slug function and storage path convention before writing any data to disk. Retrofitting this after data is saved forces a migration.

---

### Pitfall 10: Streamlit Widget Key Collisions When Adding LATAM Section

**What goes wrong:**
Adding LATAM widgets to `app.py` causes `streamlit.errors.DuplicateWidgetID` errors that break the entire app, including the existing S&P 500 section. Examples: `st.text_input("Company", key="company")` already exists in the S&P 500 section; adding a second `st.text_input("Company", key="company")` for LATAM breaks both sections.

**Why it happens:**
Streamlit generates a unique ID per widget based on its `key` parameter (or its position if no key is given). When the same key appears twice in the same script run, Streamlit raises `DuplicateWidgetID`. This is especially easy to trigger when copying widget code from the existing S&P 500 section as a starting point for the LATAM section.

**How to avoid:**
Namespace all new LATAM widget keys with a prefix:

```python
# S&P 500 section (existing — do not touch)
ticker = st.text_input("Ticker", key="sp500_ticker")

# LATAM section (new)
company_url = st.text_input("Corporate URL", key="latam_company_url")
country = st.selectbox("Country", options=LATAM_COUNTRIES, key="latam_country")
```

Use a consistent prefix (`latam_`) for all new widgets. Initialize all LATAM session state keys in a separate `init_latam_session_state()` function called at the top of the LATAM section.

**Warning signs:**
- `DuplicateWidgetID` error immediately after adding new widgets
- The error appears in the S&P 500 section, not the LATAM section — confusing because the new code is elsewhere
- App was working before the LATAM section was added

**Phase to address:** Phase 5 (dashboard LATAM section integration) — adopt the `latam_` namespace prefix as a convention from the very first widget added. Code review should check all new widget keys against existing ones.

---

### Pitfall 11: Backwards Compatibility — Existing S&P 500 Imports Break on New Dependencies

**What goes wrong:**
Adding `import playwright` or `import weasyprint` at the top of `app.py` causes the entire app to fail to load if those packages are not installed or if their native dependencies (GTK, Playwright browsers) are not configured. This breaks the S&P 500 section — which has no dependency on any of these packages — for users who have not yet set up the LATAM environment.

**Why it happens:**
Top-level imports in Python execute at module load time. If `weasyprint` raises an `OSError` (missing GTK DLL) or `playwright` raises an import error, the entire `app.py` module fails to load. The S&P 500 section, which was working fine, becomes unavailable due to a failed import for a feature it does not use.

**How to avoid:**
Use lazy imports scoped to the LATAM section functions:

```python
# BAD — top-level import breaks the whole app if GTK is missing
import weasyprint

# GOOD — import only when the LATAM feature is actually used
def generate_pdf_report(html_content: str) -> bytes:
    try:
        import weasyprint
        return weasyprint.HTML(string=html_content).write_pdf()
    except ImportError:
        raise RuntimeError(
            "WeasyPrint not installed. Run: pip install weasyprint "
            "and install GTK dependencies."
        )
```

Similarly, wrap LATAM section rendering in a `try/except ImportError` that shows a setup instructions panel instead of crashing.

**Warning signs:**
- S&P 500 section stops working after adding LATAM code
- App fails to start with an import error referencing a LATAM-only package
- No error in LATAM code itself — error is at module load time

**Phase to address:** Phase 5 (dashboard integration) — establish a "lazy import" pattern for all LATAM dependencies from the first integration commit. Never add LATAM imports to the top-level `app.py` import block.

---

### Pitfall 12: LATAM PDF Table Extraction Fails Due to IFRS vs. Local GAAP Structural Differences

**What goes wrong:**
Table extraction logic that works for one LATAM country fails for another because the structure of financial statements differs — not just in language, but in the number of line items, the nesting depth, the label conventions, and the presence/absence of subtotals. An extractor calibrated on Chilean CMF PDFs (which follow IFRS closely) produces garbage results on Colombian Supersalud filings (which use local GAAP with custom account codes).

**Why it happens:**
LATAM countries use a mix of IFRS (Chile, Colombia, Peru, Mexico — for publicly listed companies), local adaptations (Colombian health sector uses PCG-Salud, Peru uses NIIF-SMCF), and purely local GAAP (smaller private entities). Statement labels, line item names, currency placement, and column orders vary substantially. There is no standardized XBRL taxonomy equivalent for LATAM health sector filings.

**How to avoid:**
1. Build per-country extraction configurations (or adapters) rather than a single universal parser.
2. Use heuristic label matching (`"ingresos" in row_label.lower()` rather than `row_label == "Revenues"`).
3. Extract a "raw table" with all rows first; apply label normalization in a post-processing step.
4. Treat the extraction layer as inherently lossy — design the pipeline to surface confidence scores and flag manual review when extraction quality is below threshold (e.g., fewer than 5 recognizable financial line items extracted).

**Warning signs:**
- Extraction produces tables with correct column count but meaningless row labels
- Totals don't balance (extracted Revenue != sum of extracted line items)
- Same extractor works for Brazil but fails for Colombia

**Phase to address:** Phase 2 (PDF extractor) — design the extractor with a country-adapter pattern from the start. Budget significant time for per-country calibration in Phase 2.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Using Frankfurter for all LATAM FX | Simple single-API implementation | ARS/CLP/COP/PEN always return None; silent data corruption | Never — must implement tiered fallback before first use |
| Single universal PDF extractor | Faster to build | Fails on 30-50% of LATAM PDFs due to country/format variation | Never — use country adapters from day one |
| Top-level LATAM imports in app.py | Simpler code structure | Breaks S&P 500 section if any LATAM dep fails to load | Never for optional features |
| Raw company names as filesystem paths | No slug function to write | OSError on Spanish characters; cross-platform inconsistency | Never on Windows with Unicode names |
| Calling Playwright from Streamlit main thread | Simpler code | Crashes with NotImplementedError on Windows | Never — always use thread isolation |
| Skipping OCR fallback for "simple" cases | Faster initial build | 30-50% of LATAM PDFs are scanned; pipeline silently returns empty | Never — implement fallback from day one |
| Hardcoding Tesseract path as C:\Program Files\Tesseract-OCR\tesseract.exe | Works on dev machine | Breaks on any machine with different Tesseract install path | Only in rapid prototyping; use env var before any shared use |
| Not namespacing Streamlit widget keys | Less verbose code | DuplicateWidgetID errors that break both SP500 and LATAM sections | Never when adding to existing app |

---

## Integration Gotchas

Common mistakes when connecting to external services and components.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Frankfurter API | Assuming all LATAM currencies are available | Check supported currency list first; ARS, CLP, COP, PEN are absent — use fallback API |
| Frankfurter API | Not handling date-range gaps (weekends/holidays) | Request `start_date` to `end_date` range; API returns business days only — compute average from available dates |
| duckduckgo-search | Calling in a loop without caching | Cache results by query hash; add 2-5s randomized delay between calls |
| duckduckgo-search | Treating empty results as "no data found" | Empty results may be rate limiting, not absence of data — retry with backoff |
| Playwright | Calling sync API from Streamlit main thread | Always use `ThreadPoolExecutor` to isolate Playwright in its own thread |
| Playwright | Running `playwright install` once globally then switching conda envs | Re-run `playwright install chromium` in each new env; browser binaries are path-dependent |
| pytesseract | Calling without setting `tesseract_cmd` on Windows | Always set `pytesseract.pytesseract.tesseract_cmd` explicitly; do not rely on PATH |
| weasyprint | Importing at module top level | Use lazy import inside the PDF generation function; GTK errors are runtime, not import-time |
| pdfplumber | Assuming non-empty output means good extraction | Check: (1) character count reasonable? (2) recognizable financial keywords present? (3) numbers extractable? |
| LATAM regulatory sites | Assuming stable URL patterns for annual reports | LATAM regulator websites change URL structure frequently; validate URL accessibility before running ETL |

---

## Performance Traps

Patterns that work for a small test set but fail at scale.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Running Playwright headless for every PDF download | Works for 5 companies; 10-minute timeout for 50 | Use Playwright only for JS-rendered pages; use `requests` for direct PDF URLs once found | Beyond ~10 simultaneous scrapes |
| Running pytesseract on full PDF without DPI control | OCR produces garbled output; accuracy <50% | Use 300 DPI for `page.get_pixmap(dpi=300)`; 150 DPI minimum | Any scan below 200 DPI |
| Loading all LATAM PDFs into memory simultaneously | RAM exhaustion on large annual reports (50-200 MB each) | Process one PDF at a time; close pdfplumber handles after extraction | 3+ large PDFs in memory |
| Re-scraping the same LATAM URL on every Streamlit rerun | Playwright launches on every button click | Cache scraped HTML to disk; check cache before launching browser | First time user clicks button twice |
| Calling duckduckgo-search 10+ times per company analysis | RatelimitException mid-pipeline | Batch all search queries; run once per analysis session, cache to JSON | 5+ companies in same session |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Playwright scraper:** Tested with a URL from an actual LATAM health company website — not just `https://example.com`. JS-heavy sites (common in LATAM corporates) require `page.wait_for_load_state("networkidle")`.
- [ ] **OCR fallback:** Tested against an actual scanned PDF from a LATAM regulator, not just a born-digital test PDF. Confirm `spa` language model produces readable Spanish output.
- [ ] **Currency normalizer:** Tested with ARS, CLP, COP, PEN — not just BRL and MXN. Frankfurter fallback path exercised.
- [ ] **PDF report (WeasyPrint):** Tested `write_pdf()` end-to-end on the Windows machine — not just that `import weasyprint` succeeds. GTK DLL errors only appear at `write_pdf()` time.
- [ ] **Slug generation:** Tested with `ñ`, `á`, `é`, `í`, `ó`, `ú`, `ü`, spaces, and parentheses in company names. Windows path created and reopened successfully.
- [ ] **LATAM section in app.py:** Confirmed existing S&P 500 section still works after adding LATAM imports. Run the app with LATAM packages uninstalled to verify graceful degradation.
- [ ] **Widget keys:** Confirmed no `DuplicateWidgetID` error by searching `app.py` for duplicate `key=` values after adding LATAM widgets.
- [ ] **Tesseract configuration:** Run `tesseract --list-langs` and confirm `spa` appears. Run a test OCR on a Spanish-language image — not just an English test.
- [ ] **duckduckgo-search:** Tested that `RatelimitException` is caught and pipeline continues — does not require results to proceed.

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Playwright crashes from asyncio conflict | LOW | Move all Playwright calls into `ThreadPoolExecutor`; no data loss |
| Playwright browser binaries missing | LOW | Run `playwright install chromium`; 2-minute fix |
| pytesseract TesseractNotFound | LOW | Set `tesseract_cmd` explicitly; add env var to `.env` file |
| WeasyPrint GTK DLLs missing | MEDIUM | Install MSYS2 + pango, add to PATH, set `WEASYPRINT_DLL_DIRECTORIES`; OR switch to reportlab/fpdf2 (2-4 hours if switching libraries) |
| Frankfurter missing ARS/CLP/COP/PEN | MEDIUM | Implement tiered FX fallback; all previously normalized data for those currencies is `None` and must be re-processed |
| duckduckgo-search blocked | LOW | Add retry + delay + cache; pipeline degrades gracefully without search results |
| Scanned PDFs returning empty | MEDIUM | Add OCR fallback; re-run extraction on all previously processed PDFs (may be slow) |
| LATAM section breaks S&P 500 | LOW | Move LATAM imports to lazy import pattern; no data loss, 30-minute fix |
| Widget key collision | LOW | Add `latam_` prefix to all new keys; no data loss, 15-minute fix |
| Slug generation breaks paths | MEDIUM | Add slug function; rename existing LATAM data directories; update all references |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Playwright + asyncio event loop conflict | Phase 1 — scraper foundation | Smoke test: call scraper function from a Streamlit button; confirm no NotImplementedError |
| Playwright browser binaries missing | Phase 1 — environment setup | Run `python -c "from playwright.sync_api import sync_playwright; ..."` in the conda env |
| pytesseract TesseractNotFoundError | Phase 2 — PDF extractor | Startup check verifies `tesseract_cmd` exists and `spa` is in `--list-langs` |
| WeasyPrint GTK DLL failures | Phase 4 — PDF report generation | Call `weasyprint.HTML(string="<p>test</p>").write_pdf()` before building templates |
| Frankfurter missing LATAM currencies | Phase 3 — currency normalizer | Unit test: normalize values for ARS, CLP, COP, PEN — all must return a float, not None |
| Scanned PDFs return empty | Phase 2 — PDF extractor | Integration test: run extraction on a known scanned PDF; confirm non-empty output |
| duckduckgo-search rate limiting | Phase 3 — web search integration | Integration test: trigger `RatelimitException` deliberately; confirm pipeline continues |
| pdfplumber vs. pymupdf wrong tool | Phase 2 — PDF extractor | Benchmark both on 3 representative LATAM PDFs; document decision |
| Spanish character slugs on Windows | Phase 1 — data storage design | Create test paths with all special characters; confirm round-trip open/read |
| Widget key collision | Phase 5 — dashboard integration | Search `app.py` for `key=` values; confirm no duplicates across S&P 500 and LATAM sections |
| Backwards compatibility imports | Phase 5 — dashboard integration | Start app with LATAM packages uninstalled; S&P 500 section must load cleanly |
| IFRS vs. local GAAP table structure | Phase 2 — PDF extractor | Test on one PDF from each target country (CO, PE, CL, MX, AR, BR) |

---

## Sources

- [Streamlit + Playwright asyncio conflict — GitHub Issue #7825](https://github.com/streamlit/streamlit/issues/7825)
- [Playwright sync API inside asyncio loop — GitHub Issue #462](https://github.com/microsoft/playwright-python/issues/462)
- [Playwright sync API + Streamlit workaround — Streamlit Community](https://discuss.streamlit.io/t/using-playwright-with-streamlit/28380)
- [Playwright thread safety discussion — GitHub Issue #470](https://github.com/microsoft/playwright-python/issues/470)
- [Playwright Installation — Official Docs](https://playwright.dev/python/docs/intro)
- [pytesseract TesseractNotFoundError — GitHub Issue #348](https://github.com/madmaze/pytesseract/issues/348)
- [WeasyPrint Windows GTK install — Official Docs v52.5](https://doc.courtbouillon.org/weasyprint/v52.5/install.html)
- [WeasyPrint MSYS2 recommendation — GitHub Issue #2105](https://github.com/Kozea/WeasyPrint/issues/2105)
- [WeasyPrint gobject DLL error — GitHub Issue #971](https://github.com/Kozea/WeasyPrint/issues/971)
- [Frankfurter API currency list — Official Site](https://frankfurter.dev/)
- [Frankfurter currency requests tracker — GitHub Issue #144](https://github.com/lineofflight/frankfurter/issues/144)
- [duckduckgo-search RatelimitException — open-webui Discussion #6624](https://github.com/open-webui/open-webui/discussions/6624)
- [duckduckgo-search rate limit — agno community](https://community.agno.com/t/duckduckgo-search-rate-limit-issue/1021)
- [pdfplumber + OCR fallback guide — Woteq Softwares](https://woteq.com/how-to-read-scanned-pdfs-using-pdfplumber-and-ocr/)
- [PDF parsers comparison 2025 — Medium](https://onlyoneaman.medium.com/i-tested-7-python-pdf-extractors-so-you-dont-have-to-2025-edition-c88013922257)
- [PyMuPDF installation — Official Docs](https://pymupdf.readthedocs.io/en/latest/installation.html)
- [python-slugify — PyPI](https://pypi.org/project/python-slugify/)
- [Streamlit DuplicateWidgetID — Community](https://discuss.streamlit.io/t/duplicate-widgetid-error/4739)
- [ReportLab vs WeasyPrint on Windows — DEV Community](https://dev.to/claudeprime/generate-pdfs-in-python-weasyprint-vs-reportlab-ifi)

---
*Pitfalls research for: LATAM Financial Analysis Pipeline (v2.0 addition to existing Streamlit dashboard)*
*Researched: 2026-03-03*
*Confidence: HIGH — all Windows-specific issues traced to official docs or community issue trackers with confirmed resolutions*
