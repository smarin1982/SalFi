"""LatamAgent.py — Phase 9 Plan 02: LATAM pipeline orchestrator.

Mirrors FinancialAgent from agent.py exactly, substituting LATAM-specific
parameters and using per-company meta.json instead of metadata.parquet.

Usage:
    from LatamAgent import LatamAgent

    agent = LatamAgent(name="Grupo Keralty", country="CO", url="https://keralty.com")
    result = agent.run()
    # result["red_flags"]  → list of RedFlag dicts
    # result["status"]     → "success" | "skipped_scrape"
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from loguru import logger

import latam_scraper        # Phase 7 — search_and_download()
import latam_extractor      # Phase 8 — extract()
import latam_processor      # Phase 8 — process()
import web_search           # Phase 9 Plan 01 — search_sector_context()
from company_registry import make_slug, make_storage_path  # Phase 6
from red_flags import evaluate_flags                        # Phase 9 Plan 01
from currency import get_annual_avg_rate                    # Phase 6 — FX lookup for meta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# base_dir passed to make_storage_path() — that function appends "latam/{country}/{slug}"
# resulting in: data/latam/{country}/{slug}/
DATA_DIR = Path(__file__).parent / "data"

# ISO 4217 currency code per LATAM country code
COUNTRY_CURRENCY: dict[str, str] = {
    "CO": "COP",
    "BR": "BRL",
    "MX": "MXN",
    "AR": "ARS",
    "CL": "CLP",
    "PE": "PEN",
}


# ---------------------------------------------------------------------------
# Staleness detection helper — copied VERBATIM from agent.py lines 122-136
# ---------------------------------------------------------------------------

def _same_quarter(ts1: pd.Timestamp, ts2: pd.Timestamp) -> bool:
    """
    Returns True if both timestamps fall in the same calendar year AND quarter.
    Q1: Jan-Mar (1), Q2: Apr-Jun (2), Q3: Jul-Sep (3), Q4: Oct-Dec (4).

    Verified edge cases:
      Jan 1 2026  → (2026, 1)
      Mar 31 2026 → (2026, 1) — same ✓
      Apr 1 2026  → (2026, 2) — different ✓
      Dec 31 2026 → (2026, 4)
      Jan 1 2027  → (2027, 1) — different year ✓
    """
    def _q(ts: pd.Timestamp) -> tuple:
        return (ts.year, (ts.month - 1) // 3 + 1)
    return _q(ts1) == _q(ts2)


# ---------------------------------------------------------------------------
# LatamAgent — KPI-02: LATAM pipeline orchestrator
# ---------------------------------------------------------------------------

class LatamAgent:
    """Orchestrates the full LATAM ETL pipeline for one company.

    Mirrors FinancialAgent from agent.py. All persistent state lives in
    per-company meta.json — never in data/cache/metadata.parquet.

    Pipeline steps in run():
      1. needs_update() check (skip-scrape path)
      2. latam_scraper.search_and_download()
      3. latam_extractor.extract()
      4. latam_processor.process()
      5. evaluate_flags() — reads Parquet files written by step 4
      6. web_search.search_sector_context() — NON-BLOCKING
      7. _save_meta() — ONLY after Parquet files confirmed on disk

    Args:
        name: Full Unicode company name (e.g., "Clínica Las Américas").
        country: ISO 2-letter country code, uppercased (e.g., "CO", "BR", "AR").
        url: Source URL or domain for scraper (e.g., "https://clinica.com").
        data_dir: Project data root. Defaults to DATA_DIR (data/).
    """

    def __init__(
        self,
        name: str,
        country: str,
        url: str,
        data_dir: Path = DATA_DIR,
    ) -> None:
        self.name = name
        self.country = country.upper()
        self.url = url
        self.slug = make_slug(name)
        self.storage_path = make_storage_path(data_dir, country, self.slug)
        self.meta_path = self.storage_path / "meta.json"

    # ------------------------------------------------------------------
    # Staleness detection
    # ------------------------------------------------------------------

    def needs_update(self) -> bool:
        """Returns True if the company should be re-scraped.

        Re-scrape if:
          (a) meta.json does not exist, OR
          (b) last_downloaded is missing/None, OR
          (c) last_downloaded is in a previous calendar quarter.

        Returns False (skip scrape) if data was downloaded this calendar quarter.
        """
        if not self.meta_path.exists():
            logger.debug(f"[{self.name}] No meta.json found — needs update")
            return True

        meta = self._load_meta()
        last_dl_str = meta.get("last_downloaded")
        if not last_dl_str:
            logger.debug(f"[{self.name}] last_downloaded missing in meta.json — needs update")
            return True

        try:
            last_dl = pd.Timestamp(last_dl_str)
        except (ValueError, TypeError) as exc:
            logger.warning(
                f"[{self.name}] Malformed last_downloaded '{last_dl_str}': {exc!r} — needs update"
            )
            return True

        current = _same_quarter(last_dl, pd.Timestamp.now())
        logger.debug(
            f"[{self.name}] last_downloaded={last_dl.date()}, current_quarter={current}"
        )
        return not current

    # ------------------------------------------------------------------
    # Main pipeline entry point
    # ------------------------------------------------------------------

    def run(self, force_refresh: bool = False) -> dict:
        """Run the full LATAM ETL pipeline for this company.

        Returns a dict with status, processed data, red flags, and sector context.

        If force_refresh=False and needs_update() is False (current-quarter data):
            Skips scrape/extract/process — re-evaluates red flags only.
            Returns {"status": "skipped_scrape", ...}

        Otherwise runs all 6 pipeline steps.

        Web search failure (Step 5) is NON-BLOCKING — pipeline succeeds even
        if web_search.search_sector_context() raises.

        meta.json is written ONLY after latam_processor.process() completes and
        Parquet files are confirmed on disk — never before.

        Args:
            force_refresh: If True, re-scrapes even if data is current-quarter.

        Returns:
            dict with keys: status, name, country, slug, fiscal_years,
                           red_flags, sector_context, and all process_result fields.
        """
        logger.info(f"[{self.name}] Starting LATAM ETL run (force_refresh={force_refresh})")

        # Skip-scrape path: current-quarter data already present AND parquets exist
        parquets_exist = (
            (self.storage_path / "kpis.parquet").exists()
            and (self.storage_path / "financials.parquet").exists()
        )
        if not force_refresh and not self.needs_update() and parquets_exist:
            logger.info(f"[{self.name}] Current-quarter data found — skipping scrape")
            return self._process_existing(skipped_scrape=True)

        # --- Step 1: Scrape (or use local PDF if url is a file path) ---
        from pathlib import Path as _Path
        _url_path = _Path(self.url)
        if _url_path.suffix.lower() == ".pdf" and _url_path.exists():
            logger.info(f"[{self.name}] Step 1: Using uploaded PDF directly — {self.url}")
            pdf_path = _url_path
        else:
            logger.info(f"[{self.name}] Step 1: Scraping from {self.url}")
            pdf_path = latam_scraper.search_and_download(
                domain=self.url,
                slug=self.slug,
                storage_path=self.storage_path,
            )

        # --- Step 2: Extract ---
        logger.info(f"[{self.name}] Step 2: Extracting from {pdf_path}")
        from datetime import datetime as _dt
        import re as _re
        _currency = COUNTRY_CURRENCY.get(self.country, "USD")
        _default_year = _dt.now().year - 1

        # Infer fiscal year from the PDF filename — the scraper may have downloaded
        # a prior-year annual report (e.g. 2024) as a fallback when the current-year
        # document was only a partial (first-semester) report.  Inferring the year
        # from the filename prevents the extractor from looking for a "2025" column
        # inside a PDF that only contains 2024 and 2023 data columns.
        _fiscal_year = _default_year
        if pdf_path:
            _year_match = _re.search(r'20(\d{2})', Path(pdf_path).name)
            if _year_match:
                _inferred = int(_year_match.group(0))
                if 2018 <= _inferred <= _dt.now().year:
                    if _inferred != _default_year:
                        logger.info(
                            f"[{self.name}] PDF filename suggests fiscal_year={_inferred} "
                            f"(default was {_default_year}) — using inferred year"
                        )
                    _fiscal_year = _inferred

        # extract() returns list[ExtractionResult] — one per fiscal year found in PDF
        extraction_results = latam_extractor.extract(
            pdf_path,
            currency_code=_currency,
            fiscal_year=_fiscal_year,
            country=self.country,
        )
        logger.info(
            f"[{self.name}] Extracted {len(extraction_results)} fiscal year(s) from PDF"
        )
        # extraction_results: list[ExtractionResult] — primary result is [0]
        extraction_result = extraction_results[0]  # kept for _build_meta compat

        # --- Step 3: Process (writes financials.parquet and kpis.parquet) ---
        logger.info(f"[{self.name}] Step 3: Processing extracted data")
        process_result = latam_processor.process(
            company_slug=self.slug,
            extraction_result=extraction_results,  # pass full list for multi-year write
            country=self.country,
            data_dir=str(DATA_DIR),
        )

        # --- Step 3b: Inline historical backfill (non-blocking) ---
        # The initial PDF typically yields only 2 years (current + comparative).
        # Crawl the company site for older PDFs to reach the last 5 completed years.
        _url_is_pdf = _url_path.suffix.lower() == ".pdf" and _url_path.exists()
        if not _url_is_pdf and self.url:
            try:
                from latam_backfiller import (
                    LatamBackfiller,
                    collect_listing_pdfs,
                    _years_already_in_parquet,
                )
                _target_years = [_dt.now().year - i for i in range(1, 6)]
                _have_years = _years_already_in_parquet(self.storage_path / "financials.parquet")
                _missing_years = [y for y in _target_years if y not in _have_years]
                if _missing_years:
                    logger.info(
                        f"[{self.name}] Step 3b: Searching for historical PDFs — "
                        f"missing years: {_missing_years}"
                    )
                    # Seed from scraper_profiles.json before Playwright crawl
                    _profile_hist: dict[int, str] = {}
                    try:
                        import json as _json_hist
                        _prof_path = Path("data/latam/scraper_profiles.json")
                        if _prof_path.exists():
                            _prof_data = _json_hist.loads(
                                _prof_path.read_text(encoding="utf-8")
                            )
                            _profile_hist = {
                                int(k): v
                                for k, v in _prof_data.get(self.slug, {})
                                                       .get("historical_pdfs", {}).items()
                            }
                    except Exception:
                        pass

                    _crawled_hist = collect_listing_pdfs(self.url, self.url)
                    # Profile entries take precedence (already validated)
                    _hist_pdf_map = {**_crawled_hist, **_profile_hist}
                    if _hist_pdf_map:
                        self._update_historical_pdfs(_hist_pdf_map)
                        _bf = LatamBackfiller(
                            self.slug, self.country, self.storage_path, self.url
                        )
                        for _yr in sorted(_missing_years, reverse=True):
                            _pdf_url = _hist_pdf_map.get(_yr)
                            if not _pdf_url:
                                logger.info(
                                    f"[{self.name}] Step 3b: no PDF found for year={_yr}"
                                )
                                continue
                            _res = _bf.run_year(_yr, _pdf_url, _currency)
                            if _res.status in ("ok", "low_conf"):
                                _bf.write_year(_res)
                                logger.info(
                                    f"[{self.name}] Step 3b: year={_yr} written "
                                    f"(conf={_res.confidence})"
                                )
                            else:
                                logger.info(
                                    f"[{self.name}] Step 3b: year={_yr} "
                                    f"status={_res.status}"
                                )
                    else:
                        logger.info(
                            f"[{self.name}] Step 3b: no historical PDFs discovered on site"
                        )
            except Exception as _hist_exc:
                logger.warning(
                    f"[{self.name}] Step 3b: historical backfill failed (non-blocking): "
                    f"{_hist_exc!r}"
                )

        # --- Step 4: Evaluate red flags (ONLY after Parquet files exist on disk) ---
        logger.info(f"[{self.name}] Step 4: Evaluating red flags")
        kpis_df = pd.read_parquet(self.storage_path / "kpis.parquet")
        financials_df = pd.read_parquet(self.storage_path / "financials.parquet")
        flags = evaluate_flags(kpis_df, financials_df)

        # --- Step 5: Web search enrichment (NON-BLOCKING) ---
        logger.info(f"[{self.name}] Step 5: Web search enrichment")
        sector_context = []
        try:
            sector_context = web_search.search_sector_context(self.name, self.country)
        except Exception as exc:
            logger.warning(f"[{self.name}] Web search failed (non-blocking): {exc!r}")

        # --- Step 6: Write meta.json (only after steps 1-5 complete successfully) ---
        logger.info(f"[{self.name}] Step 6: Writing meta.json")
        meta = self._build_meta(
            extraction_result=extraction_result,
            process_result=process_result,
            flags=flags,
            pdf_path=pdf_path,
            scraped=True,
        )
        self._save_meta(meta)

        logger.info(
            f"[{self.name}] Done (success): "
            f"{len(process_result.get('fiscal_years', []))} FY, "
            f"{len(flags)} red flags"
        )

        return {
            "status": "success",
            "name": self.name,
            "country": self.country,
            "slug": self.slug,
            "fiscal_years": process_result.get("fiscal_years", []),
            "red_flags": [vars(f) for f in flags],
            "sector_context": sector_context,
            **process_result,
        }

    # ------------------------------------------------------------------
    # Skip-scrape path
    # ------------------------------------------------------------------

    def _process_existing(self, skipped_scrape: bool = True) -> dict:
        """Called when needs_update() is False — re-evaluate red flags only.

        Reads existing Parquet files and re-evaluates red flags (thresholds
        may have changed in red_flags.yaml since last run).
        Updates red_flags_evaluated_at and red_flags_count in meta.json.

        Returns same dict structure as run() but with status="skipped_scrape".
        """
        logger.info(f"[{self.name}] Re-evaluating red flags from existing Parquet files")

        from processor import calculate_kpis, save_parquet as _save_parquet
        financials_df = pd.read_parquet(self.storage_path / "financials.parquet")
        kpis_df = calculate_kpis(financials_df)
        _save_parquet(kpis_df, self.storage_path / "kpis.parquet")
        flags = evaluate_flags(kpis_df, financials_df)

        # Update meta.json: refresh red flags fields only
        meta = self._load_meta()
        meta["red_flags_evaluated_at"] = pd.Timestamp.now().isoformat()
        meta["red_flags_count"] = len(flags)
        self._save_meta(meta)

        # Collect fiscal years from KPI dataframe
        fiscal_years = sorted(kpis_df["fiscal_year"].dropna().astype(int).tolist())

        logger.info(
            f"[{self.name}] Done (skipped_scrape): "
            f"{len(fiscal_years)} FY, {len(flags)} red flags"
        )

        return {
            "status": "skipped_scrape",
            "name": self.name,
            "country": self.country,
            "slug": self.slug,
            "fiscal_years": fiscal_years,
            "red_flags": [vars(f) for f in flags],
            "sector_context": [],
        }

    # ------------------------------------------------------------------
    # Meta.json helpers
    # ------------------------------------------------------------------

    def _build_meta(
        self,
        extraction_result: dict,
        process_result: dict,
        flags: list,
        pdf_path,
        scraped: bool,
    ) -> dict:
        """Build the meta.json dict with all required fields.

        Args:
            extraction_result: from latam_extractor.extract()
            process_result: from latam_processor.process()
            flags: list of RedFlag objects from evaluate_flags()
            pdf_path: Path to the downloaded PDF, or None
            scraped: True if scrape ran this call; False to preserve last_downloaded

        Returns:
            dict ready for json.dumps()
        """
        now_iso = pd.Timestamp.now().isoformat()

        # Preserve last_downloaded when not re-scraped (skip-scrape path)
        if scraped:
            last_downloaded = now_iso
        else:
            existing = self._load_meta()
            last_downloaded = existing.get("last_downloaded")

        # FX fields — needed by dashboard to reverse USD normalisation for display
        currency_original = COUNTRY_CURRENCY.get(self.country, "USD")
        fiscal_year = extraction_result.fiscal_year
        try:
            fx_rate_usd = get_annual_avg_rate(currency_original, fiscal_year)
        except Exception:
            fx_rate_usd = None  # Dashboard falls back to 1.0 (shows USD unchanged)

        return {
            "name": self.name,
            "country": self.country,
            "slug": self.slug,
            "url": self.url,
            "last_downloaded": last_downloaded,
            "last_processed": now_iso,
            "fiscal_years": process_result.get("fiscal_years", []),
            "fy_count": len(process_result.get("fiscal_years", [])),
            "status": "success",
            "error_message": None,
            "extraction_method": extraction_result.extraction_method,
            "confidence": extraction_result.confidence,
            "approximated_fx": process_result.get("approximated_fx", False),
            # FX-02: Argentine peso devaluation warning — always True for AR companies
            "ars_warning": self.country == "AR",
            "fields_missing": process_result.get("fields_missing", []),
            "source_pdf_path": str(pdf_path) if pdf_path else None,
            "red_flags_evaluated_at": now_iso,
            "red_flags_count": len(flags),
            # FX display fields — used by dashboard _format_latam_kpi_value and
            # _render_latam_financials_table to reverse USD normalisation for local currency
            "currency_original": currency_original,
            "fx_rate_usd": fx_rate_usd,
        }

    def _save_meta(self, meta: dict) -> None:
        """Atomic write of meta.json using NTFS-safe tmp-then-rename pattern.

        Mirrors agent.py _save_metadata() NTFS pattern:
          write to .json.tmp → unlink existing .json → rename .tmp to .json

        This prevents partial writes from corrupting the state file on Windows.
        """
        self.storage_path.mkdir(parents=True, exist_ok=True)
        tmp = self.meta_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if self.meta_path.exists():
            self.meta_path.unlink()  # Windows NTFS: unlink before rename
        tmp.rename(self.meta_path)
        logger.debug(f"[{self.name}] meta.json written to {self.meta_path}")

    def _load_meta(self) -> dict:
        """Load meta.json, returning {} if file does not exist."""
        if not self.meta_path.exists():
            return {}
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def _update_historical_pdfs(self, year_url_map: dict) -> None:
        """Merge discovered {year: pdf_url} into this company's scraper profile
        under the 'historical_pdfs' key. Append-only — existing URLs are never
        overwritten (they are already validated).

        Args:
            year_url_map: dict mapping int fiscal year to PDF URL string.
                          Keys can also be strings (JSON-safe).
        """
        profiles_path = Path("data/latam/scraper_profiles.json")
        profiles: dict = {}
        if profiles_path.exists():
            try:
                with open(profiles_path, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
            except Exception:
                profiles = {}

        entry = profiles.get(self.slug, {})
        historical = entry.get("historical_pdfs", {})
        for year, url in year_url_map.items():
            key = str(year)
            if key not in historical:  # append-only: never overwrite validated entries
                historical[key] = url
        entry["historical_pdfs"] = historical
        profiles[self.slug] = entry

        try:
            profiles_path.parent.mkdir(parents=True, exist_ok=True)
            with open(profiles_path, "w", encoding="utf-8") as f:
                json.dump(profiles, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"LatamAgent._update_historical_pdfs failed: {e}")
