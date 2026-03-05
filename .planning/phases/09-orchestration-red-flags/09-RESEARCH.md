# Phase 9: Orchestration & Red Flags - Research

**Researched:** 2026-03-04
**Domain:** Python orchestration pattern mirroring FinancialAgent + YAML-configurable financial red flags engine
**Confidence:** HIGH (FinancialAgent source code directly inspected; ddgs API verified; PyYAML verified; red flags thresholds cross-referenced from FEATURES.md research)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SCRAP-03 | El sistema ejecuta búsquedas web (ddgs) para obtener contexto sectorial y empresas comparables del sector salud | ddgs DDGS.text() API documented; tenacity retry pattern with RatelimitException; graceful degradation pattern established |
| KPI-02 | LatamAgent orquesta el pipeline completo (scrape → extraer → normalizar → procesar) con detección de datos desactualizados vía needs_update() | FinancialAgent interface fully documented from source; meta.json schema defined; staleness logic (_same_quarter pattern) confirmed |
| FLAG-01 | El sistema detecta automáticamente red flags financieras (Deuda/EBITDA > 4x, FCO negativo con utilidad positiva, pérdidas consecutivas ≥ 2 años, etc.) y asigna severidad Alta/Media/Baja | KPI_REGISTRY inspected — all required KPI column names confirmed; flag logic patterns and severity tiers documented |
| FLAG-02 | Los umbrales de red flags son configurables por sector en un archivo YAML | PyYAML 6.0.2+ confirmed on PyPI; yaml.safe_load() pattern; YAML structure for sector thresholds designed |
</phase_requirements>

---

## Summary

Phase 9 builds two self-contained components that snap onto the pipeline built in Phases 6-8:

**Component 1 — LatamAgent** (`LatamAgent.py`): An orchestrator that mirrors the exact interface of `FinancialAgent` from `agent.py`. It accepts `(name, country, url)` instead of `(ticker)`, delegates to `latam_scraper → latam_extractor → latam_processor`, and writes `meta.json` to `data/latam/{country}/{slug}/` instead of updating `metadata.parquet`. Staleness detection is quarter-based — same `_same_quarter()` pattern as `FinancialAgent.needs_update()`. ddgs web search for sector context is called as an optional enrichment step that must not block the pipeline when it fails.

**Component 2 — Red Flags Engine** (`red_flags.py`): A pure-Python rules engine that reads thresholds from `config/red_flags.yaml`, evaluates a company's `kpis.parquet` (multi-year) against those rules, and returns a list of `RedFlag` objects with severity Alta/Media/Baja. The mandatory flags from the requirements spec (Deuda/EBITDA > 4x, FCO negativo con utilidad positiva, pérdidas consecutivas ≥ 2 años) are implemented first; all 20 KPI columns confirmed present in existing `kpis.parquet`.

**Primary recommendation:** Build `LatamAgent.py` in Plan 09-01 and `red_flags.py` + `config/red_flags.yaml` in Plan 09-02. Both components are independently testable — red flags engine can be smoke-tested against any existing kpis.parquet before LatamAgent is complete.

---

## Standard Stack

### Core (No New Dependencies for This Phase)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ddgs` | `>=9.0` (9.11.1 as of Mar 2026) | Web search for sector context and comparable companies | Already specified in STACK.md; successor to deprecated `duckduckgo-search`; free, no API key |
| `tenacity` | `>=8.3` (already in requirements.txt) | Exponential backoff retry decorator on DDGS.text() calls | Already in requirements.txt from Phase 1; exact pattern confirmed for DDGS rate limit handling |
| `PyYAML` | `>=6.0` (6.0.3 latest on PyPI) | Load `config/red_flags.yaml` threshold file at runtime | Standard Python YAML library; `yaml.safe_load()` for security; NOT in requirements.txt yet — must add |
| `pandas` | `>=3.0` (already present) | Read kpis.parquet, evaluate multi-year flag logic (consecutive losses) | Already present |
| `pyarrow` | `>=23.0` (already present) | Read/write meta.json is plain JSON; Parquet reads for red flags | Already present |
| `pathlib` | stdlib | Path handling for `data/latam/{country}/{slug}/` | No install needed |
| `json` | stdlib | Read/write meta.json | No install needed |
| `loguru` | `>=0.7` (already present) | Consistent logging across all LATAM modules | Already present |

### What Is NOT New in This Phase

The following were added in earlier phases and are used here:
- `latam_scraper.py` (Phase 7) — LatamAgent calls `latam_scraper.search()` and `latam_scraper.download()`
- `latam_extractor.py` (Phase 8) — LatamAgent calls `latam_extractor.extract()`
- `latam_processor.py` (Phase 8) — LatamAgent calls `latam_processor.process()`
- `currency.py` (Phase 6) — called inside `latam_processor.py`, not directly from LatamAgent
- `company_registry.py` (Phase 6) — provides `make_slug()` and storage path helpers

### Installation (only new dependency)

```bash
pip install "PyYAML>=6.0"
```

Then add to `requirements.txt`:
```
# Phase 9: Orchestration & Red Flags
PyYAML>=6.0
```

`ddgs` should already be in requirements.txt from Phase 7 (SCRAP-01). Verify before adding duplicate.

---

## Architecture Patterns

### Recommended Project Structure (Phase 9 additions)

```
AI 2026/
├── LatamAgent.py            # NEW — orchestrator (mirrors FinancialAgent)
├── red_flags.py             # NEW — red flags engine
├── web_search.py            # NEW — ddgs wrapper with tenacity backoff
├── config/
│   └── red_flags.yaml       # NEW — YAML threshold file (sector-configurable)
└── data/
    └── latam/
        └── {country}/
            └── {slug}/
                ├── financials.parquet   # written by latam_processor (Phase 8)
                ├── kpis.parquet         # written by latam_processor (Phase 8)
                ├── meta.json            # NEW — written by LatamAgent
                └── raw/                 # downloaded PDFs (Phase 7-8)
```

### Pattern 1: FinancialAgent Interface — Mirror Exactly

The FinancialAgent interface (from `agent.py`, directly inspected) is the authoritative reference:

```python
# agent.py (existing — do not modify)
class FinancialAgent:
    def __init__(self, ticker: str, data_dir: Path = DATA_DIR):
        self.ticker = ticker.upper()
        self.data_dir = data_dir

    def needs_update(self) -> bool:
        """True if data should be re-scraped (no metadata OR not current quarter)."""
        ...

    def run(self, force_refresh: bool = False) -> dict:
        """Full ETL. Returns dict with 'status', 'ticker', fiscal_years, etc."""
        ...
```

**LatamAgent mirrors this exactly, substituting LATAM-specific parameters:**

```python
# LatamAgent.py (new)
from pathlib import Path
import json
from datetime import datetime

from loguru import logger

import latam_scraper
import latam_extractor
import latam_processor
import web_search
from company_registry import make_slug, make_storage_path
from red_flags import evaluate_flags

DATA_DIR = Path(__file__).parent / "data" / "latam"

class LatamAgent:
    """
    Orchestrates the full LATAM ETL pipeline for one company.
    Mirrors FinancialAgent interface: same run(), needs_update(), force_refresh pattern.
    State is persisted in meta.json (not metadata.parquet — no ticker key available).
    """

    def __init__(self, name: str, country: str, url: str, data_dir: Path = DATA_DIR):
        self.name = name
        self.country = country.upper()  # e.g., "CO", "PE", "CL"
        self.url = url
        self.slug = make_slug(name)
        self.storage_path = make_storage_path(data_dir, country, self.slug)
        self.meta_path = self.storage_path / "meta.json"

    def needs_update(self) -> bool:
        """
        Returns True if company data should be re-scraped.
        Mirrors FinancialAgent.needs_update(): checks current calendar quarter.
        Returns False if meta.json exists and last_downloaded is current quarter.
        """
        if not self.meta_path.exists():
            return True
        meta = self._load_meta()
        last_dl_str = meta.get("last_downloaded")
        if not last_dl_str:
            return True
        last_dl = pd.Timestamp(last_dl_str)
        return not _same_quarter(last_dl, pd.Timestamp.now())

    def run(self, force_refresh: bool = False) -> dict:
        """
        Full LATAM ETL for this company.
        Steps: (1) scrape PDF, (2) extract financials, (3) normalize + process,
               (4) evaluate red flags, (5) enrich with web search context,
               (6) write meta.json.
        Web search failure does NOT block pipeline (try/except around web_search calls).
        Returns dict with status, company info, fiscal_years, red_flags, ...
        """
        ...
```

### Pattern 2: Staleness Detection via meta.json

FinancialAgent uses `metadata.parquet` indexed by ticker. LatamAgent uses `meta.json` because there is no ticker — the key is `(country, slug)`.

**meta.json schema:**

```json
{
  "name": "Grupo Keralty",
  "country": "CO",
  "slug": "grupo-keralty",
  "url": "https://keralty.com",
  "regulatory_id": "900123456-7",
  "last_downloaded": "2026-01-15T14:32:00",
  "last_processed": "2026-01-15T14:35:00",
  "fiscal_years": [2021, 2022, 2023],
  "fy_count": 3,
  "status": "success",
  "error_message": null,
  "extraction_method": "pdfplumber",
  "confidence": "Alta",
  "approximated_fx": false,
  "ars_warning": false,
  "fields_missing": [],
  "source_pdf_path": "data/latam/colombia/grupo-keralty/raw/estados_financieros_2023.pdf",
  "red_flags_evaluated_at": "2026-01-15T14:36:00",
  "red_flags_count": 2
}
```

**Key fields:**
- `last_downloaded` — ISO 8601 timestamp; used by `needs_update()` for quarter comparison
- `confidence` — Alta/Media/Baja from `latam_extractor`
- `approximated_fx` — True when FX rate came from secondary API (not Frankfurter)
- `ars_warning` — True when country is AR (Argentine peso devaluation warning)
- `extraction_method` — "pdfplumber" | "pymupdf" | "pytesseract" (audit trail)

**Staleness logic (same as FinancialAgent):**

```python
import pandas as pd

def _same_quarter(ts1: pd.Timestamp, ts2: pd.Timestamp) -> bool:
    """True if both timestamps are in the same calendar year AND quarter."""
    def _q(ts):
        return (ts.year, (ts.month - 1) // 3 + 1)
    return _q(ts1) == _q(ts2)
```

Source: Copied verbatim from `agent.py` lines 122-136. LATAM companies publish annually (not quarterly), but the quarter-based staleness check ensures the pipeline does not re-scrape within the same calendar quarter it was last run — consistent behavior with the US pipeline.

### Pattern 3: web_search.py Wrapper with Graceful Degradation

ddgs raises `RatelimitException` (HTTP 202) and `DuckDuckGoSearchException` as the main failure modes. The wrapper must:
1. Retry with exponential backoff using `tenacity` (already in requirements.txt)
2. Return an empty list (not raise) when all retries fail — pipeline continues

```python
# web_search.py — NEW
from __future__ import annotations
from typing import Any

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

try:
    from ddgs import DDGS
    from ddgs.exceptions import RatelimitException, DuckDuckGoSearchException
    _DDGS_AVAILABLE = True
except ImportError:
    _DDGS_AVAILABLE = False
    RatelimitException = Exception
    DuckDuckGoSearchException = Exception


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=30),
    retry=retry_if_exception_type((RatelimitException, DuckDuckGoSearchException)),
    reraise=False,
)
def _search_with_retry(query: str, max_results: int) -> list[dict]:
    """Inner search — retried up to 3 times with exponential backoff."""
    with DDGS() as ddgs:
        return ddgs.text(query, max_results=max_results)


def search_sector_context(company_name: str, country: str, sector: str = "salud") -> list[dict]:
    """
    Search for sector context and comparable companies.
    SCRAP-03: Returns list of dicts with 'title', 'href', 'body'.
    Returns [] on failure — NEVER raises, never blocks pipeline.

    Args:
        company_name: e.g., "Grupo Keralty"
        country: ISO 2-letter code, e.g., "CO"
        sector: e.g., "salud"

    Returns:
        list[dict] with keys 'title', 'href', 'body'. Empty list on any failure.
    """
    if not _DDGS_AVAILABLE:
        logger.warning("ddgs not installed — web search skipped")
        return []

    query = f"{company_name} sector {sector} {country} comparables financieros"
    try:
        results = _search_with_retry(query, max_results=5)
        logger.info(f"Web search returned {len(results or [])} results for '{query}'")
        return results or []
    except Exception as exc:
        logger.warning(f"Web search failed (non-blocking): {exc!r}")
        return []


def search_comparable_companies(sector: str, country: str, max_results: int = 3) -> list[dict]:
    """
    Search for comparable healthcare companies in same country.
    Used by RPT-03 (executive report with 2-3 comparables) — Phase 11.
    Returns [] on failure.
    """
    if not _DDGS_AVAILABLE:
        return []

    query = f"empresas sector {sector} {country} estados financieros comparables"
    try:
        results = _search_with_retry(query, max_results=max_results)
        return results or []
    except Exception as exc:
        logger.warning(f"Comparable search failed (non-blocking): {exc!r}")
        return []
```

**DDGS.text() return format** (verified from ddgs 9.x):
```python
[
    {
        "title": "Grupo Keralty - Informe Financiero 2023",
        "href": "https://example.com/informe.pdf",
        "body": "Texto del snippet de búsqueda..."
    },
    ...
]
```

### Pattern 4: Red Flags Engine — YAML-Configurable Thresholds

**config/red_flags.yaml structure:**

```yaml
# config/red_flags.yaml
# Threshold file for red flags engine.
# Changing values here takes effect on the NEXT pipeline run — no Python changes needed.
# Severity: Alta (critical), Media (warning), Baja (watch)

version: "1.0"
default_sector: "healthcare"

sectors:
  healthcare:
    flags:
      # FLAG: Deuda/EBITDA excesivo (KPI-02 mandatory)
      - id: FLAG-001
        name: "Deuda/EBITDA elevado"
        kpi: "debt_to_ebitda"
        description: "Ratio de deuda sobre EBITDA excesivo para el sector salud"
        thresholds:
          Alta: { gt: 4.0 }
          Media: { gt: 2.5, lte: 4.0 }
          Baja:  { gt: 1.5, lte: 2.5 }

      # FLAG: Liquidez crítica
      - id: FLAG-002
        name: "Liquidez crítica"
        kpi: "current_ratio"
        description: "Ratio corriente por debajo de niveles saludables"
        thresholds:
          Alta: { lt: 1.0 }
          Media: { gte: 1.0, lt: 1.5 }
          Baja:  { gte: 1.5, lt: 2.0 }

      # FLAG: Cobertura de intereses insuficiente
      - id: FLAG-003
        name: "Cobertura de intereses insuficiente"
        kpi: "interest_coverage"
        description: "EBIT no cubre los intereses de deuda"
        thresholds:
          Alta: { lt: 1.5 }
          Media: { gte: 1.5, lt: 2.5 }
          Baja:  { gte: 2.5, lt: 3.5 }

      # FLAG: Margen operativo negativo
      - id: FLAG-004
        name: "Margen operativo negativo"
        kpi: "operating_margin"
        description: "La operación principal genera pérdidas"
        thresholds:
          Alta: { lt: 0.0 }
          Media: { gte: 0.0, lt: 0.03 }
          Baja:  { gte: 0.03, lt: 0.05 }

      # FLAG: Margen neto negativo
      - id: FLAG-005
        name: "Margen neto negativo"
        kpi: "net_profit_margin"
        description: "La empresa genera pérdidas netas"
        thresholds:
          Alta: { lt: -0.05 }
          Media: { gte: -0.05, lt: 0.0 }
          Baja:  { gte: 0.0, lt: 0.02 }

      # FLAG: Apalancamiento excesivo
      - id: FLAG-006
        name: "Apalancamiento excesivo"
        kpi: "debt_to_equity"
        description: "Relación deuda/patrimonio por encima de límites sectoriales"
        thresholds:
          Alta: { gt: 2.0 }
          Media: { gt: 1.0, lte: 2.0 }
          Baja:  { gt: 0.8, lte: 1.0 }

      # FLAG: Deterioro de ingresos
      - id: FLAG-007
        name: "Deterioro de ingresos"
        kpi: "revenue_growth_yoy"
        description: "Caída significativa de ingresos año sobre año"
        thresholds:
          Alta: { lt: -0.10 }
          Media: { gte: -0.10, lt: 0.0 }
          Baja:  { gte: 0.0, lt: 0.03 }

# Special flags requiring multi-year logic (not single-KPI threshold)
# These are evaluated separately in red_flags.py using custom logic
special_flags:
  - id: FLAG-S01
    name: "FCO negativo con utilidad positiva"
    description: "Flujo de caja operativo negativo mientras la utilidad neta es positiva — posible problema de calidad de ganancias"
    severity: "Alta"
    logic: "operating_cash_flow < 0 AND net_income > 0"

  - id: FLAG-S02
    name: "Pérdidas consecutivas"
    description: "Pérdidas netas durante 2 o más años consecutivos"
    thresholds:
      Alta: { consecutive_loss_years: { gte: 2 } }
      Media: { consecutive_loss_years: { gte: 1 } }
    logic: "consecutive years where net_income < 0"
```

**Red flags engine implementation pattern:**

```python
# red_flags.py — NEW
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from loguru import logger

CONFIG_PATH = Path(__file__).parent / "config" / "red_flags.yaml"


@dataclass
class RedFlag:
    flag_id: str
    name: str
    description: str
    severity: str          # "Alta" | "Media" | "Baja"
    kpi: str | None        # None for special/multi-year flags
    kpi_value: float | None
    fiscal_year: int | None
    threshold_triggered: dict


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Load YAML threshold file. Raises FileNotFoundError if missing."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _evaluate_threshold(value: float, threshold: dict) -> bool:
    """
    Check if value triggers a threshold spec.
    Threshold dict keys: gt, lt, gte, lte.
    All conditions must be True for the threshold to trigger.
    """
    checks = {
        "gt":  lambda v, t: v > t,
        "lt":  lambda v, t: v < t,
        "gte": lambda v, t: v >= t,
        "lte": lambda v, t: v <= t,
    }
    return all(fn(value, threshold[k]) for k, fn in checks.items() if k in threshold)


def evaluate_flags(
    kpis_df: pd.DataFrame,
    financials_df: pd.DataFrame,
    sector: str = "healthcare",
    config_path: Path = CONFIG_PATH,
) -> list[RedFlag]:
    """
    Evaluate all flags against a company's KPI and financials DataFrames.
    Uses the most recent fiscal year for single-KPI flags.
    Uses full multi-year history for consecutive-loss and FCO flags.

    Args:
        kpis_df: DataFrame from kpis.parquet (columns: fiscal_year + 20 KPI columns)
        financials_df: DataFrame from financials.parquet (columns: fiscal_year + raw fields)
        sector: sector key from YAML config (default: "healthcare")
        config_path: path to red_flags.yaml

    Returns:
        List of RedFlag objects, sorted by severity (Alta first).
    """
    config = load_config(config_path)
    flags: list[RedFlag] = []

    # Sort by fiscal_year ascending for multi-year logic
    kpis_sorted = kpis_df.sort_values("fiscal_year")
    financials_sorted = financials_df.sort_values("fiscal_year")

    # Latest year for single-KPI threshold flags
    latest_year = kpis_sorted["fiscal_year"].max()
    latest_kpis = kpis_sorted[kpis_sorted["fiscal_year"] == latest_year].iloc[0]

    sector_config = config["sectors"].get(sector, config["sectors"]["healthcare"])

    # --- Single-KPI threshold flags ---
    for flag_spec in sector_config.get("flags", []):
        kpi_name = flag_spec["kpi"]
        if kpi_name not in latest_kpis or pd.isna(latest_kpis[kpi_name]):
            logger.debug(f"Flag {flag_spec['id']}: KPI '{kpi_name}' missing — skipping")
            continue

        value = float(latest_kpis[kpi_name])
        triggered_severity = None
        triggered_threshold = None

        for severity in ["Alta", "Media", "Baja"]:
            threshold = flag_spec["thresholds"].get(severity)
            if threshold and _evaluate_threshold(value, threshold):
                triggered_severity = severity
                triggered_threshold = threshold
                break

        if triggered_severity:
            flags.append(RedFlag(
                flag_id=flag_spec["id"],
                name=flag_spec["name"],
                description=flag_spec["description"],
                severity=triggered_severity,
                kpi=kpi_name,
                kpi_value=value,
                fiscal_year=int(latest_year),
                threshold_triggered=triggered_threshold,
            ))

    # --- Special multi-year flags ---
    flags.extend(_evaluate_special_flags(kpis_sorted, financials_sorted, config))

    # Sort: Alta > Media > Baja
    severity_order = {"Alta": 0, "Media": 1, "Baja": 2}
    flags.sort(key=lambda f: severity_order.get(f.severity, 3))
    return flags


def _evaluate_special_flags(
    kpis_sorted: pd.DataFrame,
    financials_sorted: pd.DataFrame,
    config: dict,
) -> list[RedFlag]:
    """Evaluate special flags requiring multi-year or cross-KPI logic."""
    flags = []

    # FLAG-S01: FCO negativo con utilidad positiva (most recent year)
    if "operating_cash_flow" in financials_sorted.columns and "net_income" in financials_sorted.columns:
        latest = financials_sorted.iloc[-1]
        fcf = latest.get("operating_cash_flow")
        net = latest.get("net_income")
        if pd.notna(fcf) and pd.notna(net) and fcf < 0 and net > 0:
            flags.append(RedFlag(
                flag_id="FLAG-S01",
                name="FCO negativo con utilidad positiva",
                description="Flujo de caja operativo negativo mientras la utilidad neta es positiva",
                severity="Alta",
                kpi=None,
                kpi_value=None,
                fiscal_year=int(latest["fiscal_year"]),
                threshold_triggered={"operating_cash_flow": float(fcf), "net_income": float(net)},
            ))

    # FLAG-S02: Pérdidas consecutivas >= 2 años
    if "net_profit_margin" in kpis_sorted.columns:
        net_margins = kpis_sorted[["fiscal_year", "net_profit_margin"]].dropna()
        if not net_margins.empty:
            consecutive = 0
            max_consecutive = 0
            last_loss_year = None
            for _, row in net_margins.iterrows():
                if row["net_profit_margin"] < 0:
                    consecutive += 1
                    last_loss_year = int(row["fiscal_year"])
                    max_consecutive = max(max_consecutive, consecutive)
                else:
                    consecutive = 0

            if max_consecutive >= 2:
                flags.append(RedFlag(
                    flag_id="FLAG-S02",
                    name="Pérdidas consecutivas",
                    description=f"Pérdidas netas durante {max_consecutive} año(s) consecutivo(s)",
                    severity="Alta",
                    kpi="net_profit_margin",
                    kpi_value=None,
                    fiscal_year=last_loss_year,
                    threshold_triggered={"consecutive_loss_years": max_consecutive},
                ))
            elif max_consecutive == 1:
                flags.append(RedFlag(
                    flag_id="FLAG-S02",
                    name="Pérdidas consecutivas",
                    description="Pérdida neta en al menos 1 año reciente",
                    severity="Media",
                    kpi="net_profit_margin",
                    kpi_value=None,
                    fiscal_year=last_loss_year,
                    threshold_triggered={"consecutive_loss_years": max_consecutive},
                ))

    return flags
```

### Pattern 5: LatamAgent Full run() Flow

```python
# LatamAgent.py run() skeleton

def run(self, force_refresh: bool = False) -> dict:
    logger.info(f"[{self.name}] Starting LATAM ETL run (force_refresh={force_refresh})")

    if not force_refresh and not self.needs_update():
        logger.info(f"[{self.name}] Current-quarter data found — skipping scrape")
        # Still re-evaluate red flags in case thresholds changed
        return self._process_existing(skipped_scrape=True)

    # Step 1: Scrape PDF
    logger.info(f"[{self.name}] Scraping PDF from {self.url}")
    pdf_path = latam_scraper.search_and_download(
        domain=self.url,
        slug=self.slug,
        storage_path=self.storage_path,
    )

    # Step 2: Extract financials
    logger.info(f"[{self.name}] Extracting financials from {pdf_path}")
    extraction_result = latam_extractor.extract(pdf_path)
    # extraction_result: {"data": {...}, "confidence": "Alta", "method": "pdfplumber", "source_map": {...}}

    # Step 3: Process + normalize + write Parquet (latam_processor handles FX)
    logger.info(f"[{self.name}] Processing financials")
    process_result = latam_processor.process(
        company_name=self.name,
        country=self.country,
        extracted=extraction_result["data"],
        storage_path=self.storage_path,
    )

    # Step 4: Evaluate red flags
    kpis_df = pd.read_parquet(self.storage_path / "kpis.parquet")
    financials_df = pd.read_parquet(self.storage_path / "financials.parquet")
    flags = evaluate_flags(kpis_df, financials_df)

    # Step 5: Web search context (optional — NEVER blocks)
    sector_context = web_search.search_sector_context(self.name, self.country)

    # Step 6: Write meta.json
    meta = self._build_meta(
        extraction_result=extraction_result,
        process_result=process_result,
        flags=flags,
        pdf_path=pdf_path,
        scraped=True,
    )
    self._save_meta(meta)

    logger.info(f"[{self.name}] Done: {len(process_result['fiscal_years'])} FY, "
                f"{len(flags)} red flags")
    return {
        "status": "success",
        "name": self.name,
        "country": self.country,
        "slug": self.slug,
        "fiscal_years": process_result["fiscal_years"],
        "red_flags": [vars(f) for f in flags],
        "sector_context": sector_context,
        **process_result,
    }
```

### Anti-Patterns to Avoid

- **Web search in the critical path:** Never put `web_search.search_*()` calls before Parquet is written. If ddgs fails mid-run, the pipeline must still complete. Put web search AFTER `_save_meta()` or in a separate enrichment step.
- **Mutating metadata.parquet from LatamAgent:** The US `metadata.parquet` is indexed by ticker — LATAM companies have no ticker. Use `meta.json` per company. Do NOT add LATAM entries to `metadata.parquet`.
- **Raising from web_search.py:** The web search wrapper must return `[]` and log a warning on any failure. Raising propagates into `LatamAgent.run()` and blocks the pipeline — violates KPI-02 and the graceful degradation requirement.
- **Loading YAML on every flag evaluation:** Load the YAML config once per `evaluate_flags()` call, not per flag. YAML parsing is cheap but avoids repeated file I/O in batch scenarios.
- **Using yaml.load() instead of yaml.safe_load():** `yaml.load()` can execute arbitrary Python code. Always use `yaml.safe_load()` for config files.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exponential backoff retry for ddgs | Custom sleep loops with try/except | `tenacity` `@retry` decorator | Handles jitter, max attempts, specific exception types; already in requirements.txt |
| YAML parsing | Custom INI/JSON config format | `yaml.safe_load()` via PyYAML | YAML supports nested structures for thresholds; anchors for DRY config; standard format analysts can edit |
| Quarter comparison logic | Date arithmetic from scratch | Copy `_same_quarter()` from `agent.py` | Exact same logic — copy verbatim to ensure consistent behavior |
| Multi-year consecutive loss detection | Complex stateful loops | Pandas rolling/cumsum on sorted DataFrame | Clean, tested, handles NaN correctly |
| Red flag severity ordering | String comparison | Explicit severity_order dict `{"Alta": 0, "Media": 1, "Baja": 2}` | String sort gives wrong order (Alta < Baja alphabetically) |

---

## Common Pitfalls

### Pitfall 1: ddgs RatelimitException Propagates to LatamAgent

**What goes wrong:** `DDGS().text()` raises `RatelimitException` (HTTP 202). If not caught, the exception propagates through `web_search.search_sector_context()` into `LatamAgent.run()`, blocking the pipeline and leaving meta.json unwritten.

**Why it happens:** ddgs does not have built-in retry logic (confirmed from WebSearch). Rate limits occur frequently in production use without delays between requests.

**How to avoid:** The `web_search.py` wrapper uses tenacity for up to 3 retry attempts with 4-30 second exponential backoff. Additionally, the outer try/except in `search_sector_context()` catches ANY exception type and returns `[]` — this is the non-negotiable safety net.

**Warning signs:** Pipeline hangs after PDF extraction step; meta.json not written for company; logs show `RatelimitException` without "non-blocking" message.

### Pitfall 2: meta.json Written Before Parquet Files Exist

**What goes wrong:** `_save_meta()` is called before `latam_processor.process()` completes. If the processor later fails, meta.json claims `"status": "success"` with a `last_downloaded` timestamp, causing `needs_update()` to return False next run — the company's bad data is never re-processed.

**How to avoid:** Write meta.json ONLY after `latam_processor.process()` returns successfully AND Parquet files are confirmed on disk. The write order is: (1) Parquet files, (2) red flags evaluation, (3) meta.json. On any failure before step 3, do not write meta.json — let the next run retry.

**Warning signs:** meta.json exists but `kpis.parquet` is missing or has 0 rows.

### Pitfall 3: YAML File Absent on First Run

**What goes wrong:** `red_flags.py` calls `load_config()` which raises `FileNotFoundError` if `config/red_flags.yaml` does not exist. This crashes the red flags evaluation step.

**How to avoid:** The `config/` directory and `red_flags.yaml` must be created as part of Phase 9 Wave 0 setup — before any implementation. Add `config/red_flags.yaml` to version control. The `evaluate_flags()` function should handle missing config gracefully with a fallback: `if not config_path.exists(): logger.warning("No red_flags.yaml — skipping flag evaluation"); return []`.

**Warning signs:** `FileNotFoundError: config/red_flags.yaml` in logs during first run.

### Pitfall 4: KPI Column Names Mismatch Between kpis.parquet and YAML Config

**What goes wrong:** The YAML `kpi` field (e.g., `"debt_to_ebitda"`) does not match the actual column name in `kpis.parquet`. The flag is silently skipped.

**How to avoid:** The full list of KPI column names (confirmed from processor.py inspection):

```
revenue_growth_yoy, revenue_cagr_10y, gross_profit_margin, operating_margin,
net_profit_margin, ebitda_margin, roe, roa, current_ratio, quick_ratio,
cash_ratio, working_capital, debt_to_equity, debt_to_ebitda, interest_coverage,
debt_to_assets, asset_turnover, inventory_turnover, dso, cash_conversion_cycle
```

All YAML `kpi` values must be from this exact list. The `evaluate_flags()` function logs a DEBUG message when a KPI is missing from the DataFrame — verify with smoke test against real kpis.parquet.

**Warning signs:** All flags return empty list; DEBUG log shows "KPI missing" for every flag.

### Pitfall 5: needs_update() Returns False Because meta.json Has Wrong Timestamp Format

**What goes wrong:** `meta.json` is written with a non-ISO timestamp format (e.g., `"15/01/2026"` or a locale-specific format). `pd.Timestamp(last_dl_str)` fails to parse it, raising a ValueError that propagates through `needs_update()`.

**How to avoid:** Always write `last_downloaded` as `pd.Timestamp.now().isoformat()` (produces `"2026-01-15T14:32:00.123456"`). `pd.Timestamp()` parses ISO 8601 reliably.

**Warning signs:** `needs_update()` raises ValueError; pipeline crashes before ETL step.

### Pitfall 6: Red Flags Engine on Single-Year Companies

**What goes wrong:** `_evaluate_special_flags()` calculates consecutive losses across multiple years. A company with only 1 year of data will never trigger `FLAG-S02` (consecutive losses), even if that year is a loss. The flag correctly shows 0 consecutive years.

**How to avoid:** This is correct behavior — not a bug. Document it: consecutive flags require at least 2 years of data. Single-year companies only get single-KPI threshold flags. No code change needed; add a comment in `_evaluate_special_flags()`.

---

## Code Examples

### Reading kpis.parquet and Running Flags

```python
# Verified pattern — mirrors existing processor.py Parquet read pattern
import pandas as pd
from pathlib import Path
from red_flags import evaluate_flags

storage_path = Path("data/latam/colombia/grupo-keralty")
kpis_df = pd.read_parquet(storage_path / "kpis.parquet")
financials_df = pd.read_parquet(storage_path / "financials.parquet")

flags = evaluate_flags(kpis_df, financials_df, sector="healthcare")
for flag in flags:
    print(f"[{flag.severity}] {flag.name}: {flag.description}")
# Expected: [Alta] Deuda/EBITDA elevado: Ratio de deuda sobre EBITDA excesivo...
```

### Loading YAML Config

```python
# Source: PyYAML official docs — yaml.safe_load() pattern
import yaml
from pathlib import Path

def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config = load_config(Path("config/red_flags.yaml"))
sectors = config.get("sectors", {})
healthcare_flags = sectors.get("healthcare", {}).get("flags", [])
```

### meta.json Read/Write

```python
# Atomic write pattern (mirrors agent.py NTFS-safe save_parquet pattern)
import json
from pathlib import Path
from datetime import datetime

def _save_meta(meta_path: Path, meta: dict) -> None:
    """Atomic write: write to .tmp then rename (NTFS-safe on Windows)."""
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if meta_path.exists():
        meta_path.unlink()  # Windows NTFS: unlink before rename
    tmp.rename(meta_path)

def _load_meta(meta_path: Path) -> dict:
    if not meta_path.exists():
        return {}
    return json.loads(meta_path.read_text(encoding="utf-8"))
```

### ddgs text() Usage (verified ddgs 9.x API)

```python
# Source: ddgs 9.x PyPI and GitHub documentation
from ddgs import DDGS

with DDGS() as ddgs:
    results = ddgs.text(
        "Grupo Keralty sector salud Colombia comparables financieros",
        max_results=5
    )
# results: list[dict] with keys 'title', 'href', 'body'
# Empty list if no results found (not None)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `duckduckgo-search` package | `ddgs` package (same author) | 2024-2025 | `duckduckgo-search` shows RuntimeWarning; `ddgs` is the active package |
| Hardcoded thresholds in Python | YAML config file | v2.0 design decision | Analyst can tune thresholds without code changes or deployments |
| Per-ticker metadata.parquet (US pipeline) | Per-company meta.json (LATAM) | v2.0 design | LATAM companies have no ticker — JSON file per company is the correct keying strategy |

**Deprecated/outdated:**
- `duckduckgo-search`: Do NOT use — deprecated by same author, renamed to `ddgs`. Per STACK.md.
- `yaml.load()` without Loader: Security risk — arbitrary code execution. Use `yaml.safe_load()` always.

---

## Open Questions

1. **ddgs availability in requirements.txt**
   - What we know: STACK.md specifies `ddgs>=9.0`. Phase 7 (SCRAP-01) uses ddgs for URL discovery.
   - What's unclear: Whether Phase 7 already added `ddgs` to `requirements.txt`. Current `requirements.txt` shows only Phase 1-4 packages.
   - Recommendation: Verify at plan start. If ddgs is already there (Phase 7 added it), Phase 9 only adds `PyYAML>=6.0`. If not, add both.

2. **latam_processor.process() return contract**
   - What we know: Phase 8 builds `latam_processor.py` before Phase 9. The return dict should mirror `processor.process()` which returns `{"fiscal_years": [...], "fields_extracted": [...], "kpi_columns": [...]}`.
   - What's unclear: Exact field names in latam_processor return dict (depends on Phase 8 implementation).
   - Recommendation: Phase 9 plan should reference Phase 8 output explicitly. If latam_processor.process() is not yet built, stub it for Phase 9 development.

3. **`operating_cash_flow` field in financials.parquet for LATAM**
   - What we know: US `processor.py` has `operating_cash_flow` in CONCEPT_MAP (line 122). LATAM financials may call it "Flujo de efectivo de operaciones" or "FCO" — mapped by `latam_concept_map.py` (Phase 8).
   - What's unclear: Whether Phase 8 successfully extracts cash flow statements from LATAM PDFs (cash flow is often the hardest statement to extract reliably from PDFs).
   - Recommendation: FLAG-S01 (FCO negativo con utilidad positiva) should handle missing `operating_cash_flow` gracefully — check for column existence and use `pd.notna()` before evaluating.

---

## Validation Architecture

> `workflow.nyquist_validation` is not set in `.planning/config.json` — skipping this section.

Note: config.json has `"workflow": {"research": true, "plan_check": true, "verifier": true}` but no `nyquist_validation` key. Validation Architecture section omitted per instructions.

---

## Sources

### Primary (HIGH confidence)

- `agent.py` (direct source inspection) — FinancialAgent constructor, needs_update(), run() interface, _same_quarter() logic, metadata write pattern, NTFS atomic rename pattern
- `processor.py` (direct source inspection) — KPI_REGISTRY full column list (20 KPIs confirmed), CONCEPT_MAP fields, calculate_kpis() signature
- `.planning/research/STACK.md` — ddgs>=9.0 as standard; tenacity>=8.3 already in requirements.txt; confirmed library choices
- `.planning/research/FEATURES.md` — Red flags thresholds table (healthcare sector benchmarks), multi-currency complexity, FEATURES context
- `.planning/research/ARCHITECTURE.md` — LatamAgent placement in architecture, web_search.py as standalone module, meta.json location
- [PyYAML PyPI](https://pypi.org/project/PyYAML/) — version 6.0.3, actively maintained, yaml.safe_load() is the correct API

### Secondary (MEDIUM confidence)

- [ddgs PyPI / GitHub](https://github.com/deedy5/ddgs) — DDGS.text() return format `list[dict]` with keys 'title', 'href', 'body'; version 9.11.1 (Mar 2026)
- [WebSearch: ddgs RatelimitException tenacity pattern] — tenacity retry with `retry_if_exception_type(RatelimitException)` confirmed as community standard pattern; multiple sources agree
- [WebSearch: ddgs 9.x API] — `max_results` parameter, `with DDGS() as ddgs:` context manager pattern confirmed

### Tertiary (LOW confidence)

- Red flags threshold values from FEATURES.md — marked MEDIUM confidence in that document ("thresholds calibrated for US healthcare; LATAM may differ"). Thresholds are configurable via YAML so incorrect values can be corrected without code changes.

---

## Metadata

**Confidence breakdown:**
- LatamAgent interface design: HIGH — FinancialAgent source code directly inspected; mirrors exactly
- meta.json schema: HIGH — derived from FinancialAgent metadata patterns + ARCHITECTURE.md
- web_search.py pattern: HIGH — ddgs API verified; tenacity pattern confirmed from multiple sources
- Red flags engine architecture: HIGH — KPI column names confirmed from processor.py; YAML pattern standard
- Red flags threshold values: MEDIUM — healthcare sector benchmarks; configurable via YAML as mitigation
- PyYAML availability: HIGH — PyPI confirmed; must add to requirements.txt (not currently present)

**Research date:** 2026-03-04
**Valid until:** 2026-06-01 (stable libraries; ddgs may have API changes if rate limit behavior changes)
