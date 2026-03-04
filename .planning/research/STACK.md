# Stack Research: LATAM Financial Analysis Pipeline (v2.0 additions)

**Domain:** Python ETL pipeline — web scraping, PDF extraction, currency normalization, web search, PDF export
**Researched:** 2026-03-03
**Confidence:** HIGH (versions verified via live PyPI and official docs search)
**Scope:** NEW additions only. Existing v1.0 stack (edgartools, Streamlit, Plotly, Pandas, PyArrow, loguru, Windows Task Scheduler) is validated and not re-researched here.

---

## Existing Stack (v1.0 — Do Not Change)

| Component | Library | Notes |
|-----------|---------|-------|
| EDGAR scraping | `edgartools>=2.0` | XBRL-native, rate-limited |
| Storage | Parquet via `pyarrow>=16.0` | Immutable archive layer |
| Processing | `pandas>=2.1` | DataFrame transforms, KPI calc |
| Dashboard | `streamlit>=1.35` | Local UI |
| Charts | `plotly>=5.22` | Interactive, native Streamlit |
| Logging | `loguru>=0.7` | Consistent across pipeline modules |
| Scheduling | Windows Task Scheduler | Quarterly ETL trigger |

The LATAM pipeline is additive — it plugs in as a new adapter under the same `FinancialAgent` interface. None of the above change.

---

## New Stack for v2.0 LATAM Pipeline

### Core Technologies (New)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `playwright` | `>=1.48` (latest: 1.58.0, Jan 2026) | Headless browser scraping of JS-rendered corporate websites | Only free Python library that handles JavaScript SPAs reliably; handles navigation, clicks, waits. Firecrawl/Splash are either paid or unmaintained. No API key needed. |
| `PyMuPDF` (import: `fitz`) | `>=1.24` (latest: 1.27.1, Feb 2026) | PDF text and table extraction; primary layer before OCR fallback | Fastest Python PDF library; extracts structured text + bounding boxes from machine-readable PDFs. Used as first pass — if text is extractable, skip OCR entirely. Requires Python >=3.10. |
| `pdfplumber` | `>=0.11` (latest: 0.11.9, Jan 2026) | Table extraction from PDFs where PyMuPDF text output lacks structure | Excels at identifying and parsing table grids in financial statements. Complement to PyMuPDF: use PyMuPDF for full-document text, pdfplumber for table-specific extraction where layout is critical. Already in environment from v1.0 adjacency. |
| `pytesseract` | `>=0.3.13` (latest stable: 0.3.13, Aug 2024) | OCR fallback for scanned/image-only PDFs | Required for LATAM filings that are scanned documents (common for older filings and some regulatory archives). Wraps Tesseract 5.x engine. Must install Tesseract binary separately. |
| `requests` | `>=2.32` (already in env) | HTTP client for Frankfurter currency API calls | Already present via edgartools dependency. Synchronous, simple, appropriate for a single API endpoint with no auth. No new dependency. |
| `ddgs` | `>=9.0` (latest: 9.11.1, Mar 2026) | Web search for sector context and regulatory source discovery | The successor package to `duckduckgo-search` (same author, deedy5). Free, no API key, aggregates multiple search engines. Use this — NOT `duckduckgo-search` which now shows a deprecation warning. |
| `weasyprint` | `>=68.0` (latest: 68.1, Feb 2026) | HTML-to-PDF export of executive report | Pure-Python rendering pipeline (no browser needed); integrates cleanly with Streamlit's `st.download_button`. Requires GTK3/Pango system libraries on Windows — see installation section. |

### Supporting Libraries (New)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `Pillow` | `>=10.0` | Image pre-processing before pytesseract OCR | Required by pytesseract. Also used to deskew, threshold, and enhance scanned PDF pages before OCR. |
| `langdetect` | `>=1.0.9` | Language detection on extracted PDF text | Detect whether a document is in Spanish/Portuguese before applying language-specific OCR tessdata. Lightweight, no external dependencies. |

### Frankfurter API (No Library Needed)

The Frankfurter currency API (`https://api.frankfurter.dev/v1/`) is called directly via `requests`. No wrapper package needed.

- **No API key required.** Published by the ECB (European Central Bank) daily rates.
- **Annual average calculation:** The API does not provide a pre-computed annual average endpoint. Use the time-series range endpoint and compute the mean in pandas:

```python
import requests
import pandas as pd

def get_annual_avg_rate(currency: str, year: int) -> float:
    """Return annual average exchange rate to USD for a given currency and year."""
    url = f"https://api.frankfurter.dev/v1/{year}-01-01..{year}-12-31"
    resp = requests.get(url, params={"from": currency, "to": "USD"}, timeout=10)
    resp.raise_for_status()
    rates = resp.json()["rates"]  # dict: {"2020-01-02": {"USD": 1.12}, ...}
    values = [v["USD"] for v in rates.values()]
    return sum(values) / len(values)
```

- **Supported LATAM currencies:** MXN (Mexico), COP (Colombia), PEN (Peru), CLP (Chile), ARS (Argentina), BRL (Brazil). All covered by ECB reference rates.
- **Limitation:** ARS (Argentine Peso) rates are nominal official rates, not parallel/blue market rates. This is by design — project uses nominal values per PROJECT.md constraints.

---

## Installation

### 1. Python packages

```bash
# Activate your conda environment first
conda activate ai2026   # or whatever your env name is

# Core new dependencies
pip install "playwright>=1.48"
pip install "PyMuPDF>=1.24"
pip install "pdfplumber>=0.11"
pip install "pytesseract>=0.3.13"
pip install "ddgs>=9.0"
pip install "weasyprint>=68.0"
pip install "Pillow>=10.0"
pip install "langdetect>=1.0.9"

# requests is already installed — verify
pip show requests
```

### 2. Playwright browser binaries

After `pip install playwright`, download the Chromium binary. Use Chromium only — it is the smallest download and sufficient for scraping:

```bash
playwright install chromium
# This downloads ~130MB to %LOCALAPPDATA%\ms-playwright\
```

Do NOT run `playwright install` without specifying a browser — it downloads Chromium + Firefox + WebKit (~600MB total). For scraping, Chromium is all you need.

### 3. Tesseract OCR engine (Windows 11)

pytesseract is a Python wrapper — it requires the Tesseract binary to be installed separately.

**Step 1 — Download installer from UB Mannheim (the maintained Windows build):**
```
https://github.com/UB-Mannheim/tesseract/wiki
```
Download `tesseract-ocr-w64-setup-*.exe` (64-bit). Run the installer.
Default install path: `C:\Program Files\Tesseract-OCR\`

**Step 2 — Add Tesseract to PATH:**
Add `C:\Program Files\Tesseract-OCR` to your Windows system PATH environment variable.
(Or set it explicitly in code — see integration section below.)

**Step 3 — Install Spanish and Portuguese language packs:**
During the UB Mannheim installer, check the "Additional language data (download)" option and select:
- `spa` — Spanish
- `por` — Portuguese

Alternatively, manually download `.traineddata` files from:
```
https://github.com/tesseract-ocr/tessdata
```
And place them in `C:\Program Files\Tesseract-OCR\tessdata\`.

**Step 4 — Verify:**
```bash
tesseract --version
tesseract --list-langs
```
Expected output includes `spa` and `por` in the list.

### 4. WeasyPrint system dependencies (Windows 11)

WeasyPrint requires GTK3 (Pango, Cairo, GDK-PixBuf) system libraries. This is the most complex installation step.

**Recommended method: MSYS2 (as of WeasyPrint 65.0+, GTK3 Runtime standalone installer is outdated)**

```bash
# 1. Download and install MSYS2 from https://www.msys2.org/
# 2. Open MSYS2 terminal and run:
pacman -S mingw-w64-x86_64-pango

# 3. Add MSYS2 bin directory to Windows PATH:
# C:\msys64\mingw64\bin
```

**Set WEASYPRINT_DLL_DIRECTORIES environment variable** if WeasyPrint cannot find the GTK DLLs:
```bash
# In your conda environment or .env:
set WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin
```

**Verify:**
```python
import weasyprint
weasyprint.HTML(string="<h1>test</h1>").write_pdf("test.pdf")
```

**Note:** If WeasyPrint installation proves too complex for the local Windows environment, the fallback is `xhtml2pdf` (pure Python, no system dependencies, simpler CSS support). The PDF report for this project is text-heavy and table-based — `xhtml2pdf` handles that adequately. See "Alternatives Considered" below.

---

## Windows-Specific Gotchas

### Playwright + Windows event loop

**Problem:** Playwright's async API requires `ProactorEventLoop` on Windows. Streamlit runs its own event loop. Mixing them causes `RuntimeError: The event loop is already running`.

**Solution:** Run Playwright scraping as a **separate subprocess or background thread, never inside the Streamlit render loop**. Architecture pattern for this project:

```python
# latam_scraper.py — runs as standalone ETL script (called from Task Scheduler or subprocess)
from playwright.sync_api import sync_playwright

def scrape_company_docs(url: str) -> list[str]:
    """Returns list of PDF URLs found on the corporate IR page."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        # ... navigation logic ...
        browser.close()
```

```python
# In Streamlit app.py — trigger ETL as subprocess, don't call scraper directly
import subprocess
if st.button("Run LATAM ETL"):
    subprocess.Popen(["python", "latam_etl.py", "--company", company_name])
    st.info("ETL started in background. Results will appear when complete.")
```

The Playwright scraper runs outside Streamlit's event loop entirely. Streamlit polls for new Parquet files and renders them — it never touches Playwright directly. This is the correct architecture for this project.

### pytesseract PATH on Windows

If Tesseract is not on PATH or you are running inside a conda environment where the system PATH may not be inherited:

```python
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Set this once at module initialization in `latam_pdf_extractor.py`.

### PyMuPDF import name

PyMuPDF is installed as `PyMuPDF` but imported as `fitz`:
```python
import fitz  # this is PyMuPDF
```

This is a known naming quirk. Both `pip install pymupdf` and `pip install PyMuPDF` work — they are the same package.

---

## Integration Points with Existing Stack

| Integration | How |
|-------------|-----|
| LATAM data storage | Same Parquet format as US pipeline: `data/latam/{COMPANY}_{COUNTRY}/{financials,kpis}.parquet`. PyArrow already present. |
| Dashboard integration | LATAM section added to `app.py` as a new tab or page. Reads from `data/latam/` Parquet files via same `@st.cache_data` pattern. |
| Logging | Use existing `loguru` setup. LATAM scraper/extractor modules import the same logger config from `scraper.py` or a shared `config.py`. |
| KPI calculation | Same `processor.py` KPI calculation functions apply. Currency normalization (USD conversion) is the only pre-processing addition before KPI calc. |
| PDF export button | `st.download_button` with the WeasyPrint-generated PDF bytes. No additional Streamlit components needed. |
| FinancialAgent class | LATAM adapter implements same interface as US adapter (documented in PROJECT.md). Swap the data source, keep the interface. |
| Task Scheduler | Existing quarterly trigger can call a new `latam_etl.py` script. Or add a separate Task Scheduler entry for LATAM (different companies update at different times than SEC filings). |

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `playwright` | `selenium` | Only if you have an existing Selenium test suite. Playwright is faster, has better async support, and auto-manages browser binaries. For new code, Playwright is the correct choice in 2026. |
| `playwright` | `httpx` + `BeautifulSoup` | Use this for sites that render server-side HTML (no JavaScript). If the corporate website's financial docs are in plain HTML links without JS, skip Playwright entirely and use httpx+BS4. It is faster and simpler. |
| `PyMuPDF` + `pdfplumber` | `pypdf` (formerly PyPDF2) | pypdf is good for PDF manipulation (split, merge, metadata) but inferior for text/table extraction. Use PyMuPDF+pdfplumber for extraction tasks. |
| `ddgs` | `duckduckgo-search` | Do NOT use `duckduckgo-search` — it is deprecated, the same author renamed the package to `ddgs`. Using the old package shows a RuntimeWarning and will eventually stop working. |
| `weasyprint` | `xhtml2pdf` | If WeasyPrint's GTK3 dependency causes installation pain on Windows, xhtml2pdf is pure Python with no system dependencies. CSS support is more limited, but for a text+table financial report it is sufficient. `pip install xhtml2pdf` — no system prerequisites. |
| `weasyprint` | `reportlab` | Use ReportLab only if you need full programmatic PDF control (drawing, custom page layouts). For HTML-to-PDF conversion from a dashboard template, WeasyPrint is simpler. |
| `pytesseract` + Tesseract | `easyocr` | EasyOCR is easier to install on Windows (pure pip, no binary) and supports 80+ languages including Spanish/Portuguese. Trade-off: 300–500MB model download, slower inference. If Tesseract installation on Windows proves difficult, EasyOCR is a viable fallback. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `duckduckgo-search` | Deprecated — same author renamed the package to `ddgs`. Shows RuntimeWarning, will break eventually. | `ddgs>=9.0` |
| `Firecrawl` | Paid API — explicitly out of scope per PROJECT.md | `playwright` |
| `Tavily` | Paid API — explicitly out of scope per PROJECT.md | `ddgs` |
| `scrapy` | Framework overhead unjustified for targeted corporate website scraping (single page per company). Playwright handles JS; scrapy does not natively. | `playwright` with `sync_playwright` |
| `Splash` (Scrapinghub) | Unmaintained Lua-based JS rendering service. Docker dependency. Playwright obsoletes it. | `playwright` |
| `openpyxl` / Excel output | Explicitly out of scope per PROJECT.md. | Parquet + Streamlit dashboard |
| `easyocr` as primary OCR | 300–500MB model download, GPU recommended for reasonable speed. Tesseract 5 is faster and smaller for structured document OCR. | `pytesseract` + Tesseract 5 |
| `async_playwright` inside Streamlit | Causes `RuntimeError: The event loop is already running`. Playwright scraping must run outside the Streamlit process. | Run scraper as subprocess; Streamlit only reads Parquet results. |

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `playwright>=1.48` | Python >=3.9, Windows 11 | Requires separate `playwright install chromium` step. Browsers stored in `%LOCALAPPDATA%\ms-playwright\`. |
| `PyMuPDF>=1.24` | Python >=3.10 | Pip wheel available for Windows x64 — no build tools required. |
| `pdfplumber>=0.11` | Python >=3.8, `pdfminer.six`, `Pillow`, `pypdfium2` | Auto-installs its own dependencies. Already validated in v1.0 environment. |
| `pytesseract>=0.3.13` | Python >=3.8, Tesseract 5.x binary | Tesseract 5 must be installed separately from UB Mannheim. Not pip-installable. |
| `ddgs>=9.0` | Python >=3.10 | Breaking rename from `duckduckgo-search`. Do not import both in the same environment. |
| `weasyprint>=68.0` | Python >=3.10, GTK3 (Pango, Cairo) | System libraries (MSYS2) required on Windows. Verify with a test PDF before building against it. |

---

## Full New Dependencies for requirements.txt

```
# LATAM Pipeline additions (v2.0)
playwright>=1.48
PyMuPDF>=1.24
pdfplumber>=0.11
pytesseract>=0.3.13
Pillow>=10.0
ddgs>=9.0
weasyprint>=68.0
langdetect>=1.0.9

# requests already present (edgartools dependency) — no change needed
```

**Post-install steps (Windows 11, in order):**
1. `playwright install chromium`
2. Install Tesseract 5 binary from UB Mannheim with `spa` and `por` language packs
3. Install MSYS2 + `mingw-w64-x86_64-pango` for WeasyPrint
4. Add `C:\msys64\mingw64\bin` to PATH (or set `WEASYPRINT_DLL_DIRECTORIES`)
5. Optionally add `pytesseract.pytesseract.tesseract_cmd` config to `latam_pdf_extractor.py` if PATH is not inherited inside conda

---

## Sources

- [playwright PyPI](https://pypi.org/project/playwright/) — version 1.58.0, Jan 2026. MEDIUM-HIGH confidence.
- [Playwright Python docs — Installation](https://playwright.dev/python/docs/intro) — Windows 11+ supported, `playwright install chromium` step confirmed.
- [PyMuPDF PyPI](https://pypi.org/project/PyMuPDF/) — version 1.27.1, Feb 2026. HIGH confidence.
- [pdfplumber PyPI](https://pypi.org/project/pdfplumber/) — version 0.11.9, Jan 2026. HIGH confidence.
- [pytesseract PyPI / GitHub releases](https://github.com/madmaze/pytesseract/releases) — version 0.3.13, Aug 2024. HIGH confidence (no newer release as of Mar 2026).
- [ddgs PyPI](https://pypi.org/project/ddgs/) — version 9.11.1, Mar 2026. HIGH confidence. Confirmed successor to `duckduckgo-search`.
- [weasyprint PyPI](https://pypi.org/project/weasyprint/) — version 68.1, Feb 2026. HIGH confidence.
- [WeasyPrint Windows docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) — MSYS2 recommended over GTK3 standalone installer. HIGH confidence.
- [Frankfurter API](https://frankfurter.dev/) — Free, no key, ECB reference rates, daily historical data available. HIGH confidence. Annual average must be computed from time-series endpoint — no built-in avg endpoint.
- [Playwright + Streamlit async issues](https://discuss.streamlit.io/t/using-playwright-with-streamlit/28380) — confirmed: scraper must run outside Streamlit process. MEDIUM confidence (multiple sources agree).

---

*Stack research for: LATAM Financial Analysis Pipeline (v2.0 additions)*
*Researched: 2026-03-03*
*Previous v1.0 STACK.md content preserved for reference — this file now covers both v1.0 (unchanged) and v2.0 new additions.*
