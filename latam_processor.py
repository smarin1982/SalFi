"""
latam_processor.py

KPI mapping layer for LATAM financial filings.

Converts one or more ExtractionResult objects (produced by latam_extractor.py) into
Parquet files that are schema-identical to the US pipeline output (data/clean/{TICKER}/).

Design constraints:
  - calculate_kpis() and save_parquet() are imported from processor.py — never modified.
  - All monetary values are converted from native LATAM currency to USD before writing.
  - Prior-year rows are appended to enable growth KPI continuity (revenue_growth_yoy, etc.)
  - process() is idempotent: running twice on the same input produces identical output.
  - process() never enforces human-validation gating — that is the caller's responsibility.
  - process() accepts both a single ExtractionResult and a list[ExtractionResult] — the
    single-result form is preserved for backwards compatibility with existing call sites.

IMPORTANT: calculate_kpis and save_parquet are imported from processor.py — never copy or modify them here

Exports:
    process             - main entry point
    FINANCIALS_COLUMNS  - 24-column canonical schema (matches data/clean/AAPL/financials.parquet)
"""

from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd
from loguru import logger

from processor import calculate_kpis, save_parquet   # KPI-01: import, never modify
from latam_extractor import ExtractionResult


# ---------------------------------------------------------------------------
# Canonical schema — must exactly match data/clean/AAPL/financials.parquet columns
# ---------------------------------------------------------------------------

FINANCIALS_COLUMNS = [
    "ticker", "fiscal_year",
    "revenue", "gross_profit", "cogs", "operating_income", "net_income",
    "interest_expense", "depreciation_amortization",
    "total_assets", "total_liabilities", "total_equity",
    "current_assets", "current_liabilities",
    "cash", "short_term_investments", "receivables", "inventory",
    "long_term_debt", "short_term_debt", "accounts_payable", "shares_outstanding",
    "operating_cash_flow", "capex",
]

# The 22 monetary / numeric columns (all columns except ticker and fiscal_year)
_MONETARY_COLUMNS = FINANCIALS_COLUMNS[2:]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _build_row(extraction_result: ExtractionResult, company_slug: str) -> dict:
    """Build a single financials row dict from one ExtractionResult.

    Values are stored in native local currency (COP, BRL, MXN, etc.) — NOT USD.
    USD conversion is done at display time only, using the per-year FX rate.
    This preserves the integrity of YoY growth and multi-year KPI calculations,
    which would be distorted if stored in USD with different annual exchange rates.
    """
    row: dict = {
        "ticker": company_slug,
        "fiscal_year": extraction_result.fiscal_year,
    }
    for canonical in _MONETARY_COLUMNS:
        native_value = extraction_result.fields.get(canonical, np.nan)
        if native_value is np.nan or (isinstance(native_value, float) and np.isnan(native_value)):
            row[canonical] = np.nan
        else:
            v = float(native_value)
            # D&A is always a positive add-back; OCR sometimes stores it as a negative expense.
            # Normalise to positive here so financials.parquet is always consistent.
            if canonical == "depreciation_amortization" and v < 0:
                v = abs(v)
            row[canonical] = v  # store in local currency
    return row


def process(
    company_slug: str,
    extraction_result: Union[ExtractionResult, list[ExtractionResult]],
    country: str = "",
    data_dir: str = "data",
) -> dict:
    """
    Convert one or more ExtractionResult objects into financials.parquet and kpis.parquet.

    Accepts either a single ExtractionResult (backwards compatible) or a list
    (returned by latam_extractor.extract() after multi-year support was added in 12-04).

    Steps:
      1. Normalise input to list[ExtractionResult] for uniform processing.
      2. Build one row per ExtractionResult with canonical column names; values stored
         in native local currency (COP, BRL, MXN, etc.) — no FX conversion applied.
      3. Enforce schema dtypes (fiscal_year int64, all monetary cols float64).
      4. Determine output directory under data/latam/{country?}/{slug}/.
      5. If prior-year Parquet exists, concat + deduplicate so growth KPIs are
         computable (Pitfall 5: single row always yields NaN for yoy growth).
      6. Call calculate_kpis() from processor.py (unchanged).
      7. Write financials.parquet and kpis.parquet atomically via save_parquet().
      8. Log summary and return a status dict.

    Args:
        company_slug:      Slug identifier (e.g. "grupo-keralty") — used as ticker.
        extraction_result: Output of latam_extractor.extract() — single or list.
        country:           Country slug (e.g. "colombia"); used in directory path.
        data_dir:          Root data directory (default "data").

    Returns:
        dict with keys: slug, fiscal_year, confidence, fields_extracted, rows_in_parquet
    """
    # ------------------------------------------------------------------
    # Step 1: Normalise to list (backwards compat — single ExtractionResult)
    # ------------------------------------------------------------------
    if isinstance(extraction_result, ExtractionResult):
        extraction_results: list[ExtractionResult] = [extraction_result]
    else:
        extraction_results = list(extraction_result)

    # ------------------------------------------------------------------
    # Step 2: Build one row per result with canonical names + USD conversion
    # ------------------------------------------------------------------
    rows = [_build_row(er, company_slug) for er in extraction_results]

    # ------------------------------------------------------------------
    # Step 3: Build DataFrame and enforce schema dtypes
    # ------------------------------------------------------------------
    df_new = pd.DataFrame(rows, columns=FINANCIALS_COLUMNS)
    df_new["fiscal_year"] = df_new["fiscal_year"].astype("int64")
    for col in _MONETARY_COLUMNS:
        df_new[col] = df_new[col].astype("float64")
    df_new["ticker"] = df_new["ticker"].astype("object")

    # ------------------------------------------------------------------
    # Step 4: Determine output directory
    # ------------------------------------------------------------------
    if country:
        out_dir = Path(data_dir) / "latam" / country / company_slug
    else:
        out_dir = Path(data_dir) / "latam" / company_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 4: Append prior-year data for growth KPI continuity (Pitfall 5)
    # ------------------------------------------------------------------
    existing_path = out_dir / "financials.parquet"
    if existing_path.exists():
        df_existing = pd.read_parquet(existing_path)
        df_combined = pd.concat([df_existing, df_new]).drop_duplicates(
            subset=["fiscal_year"], keep="last"
        )
        # Re-enforce float64 dtypes after concat (nullable integer/object pollution guard)
        for col in _MONETARY_COLUMNS:
            df_combined[col] = df_combined[col].astype("float64")
    else:
        df_combined = df_new

    # Always sort ascending by fiscal_year so pct_change() and shift(1) KPIs
    # (revenue_growth_yoy, DSO, inventory_turnover, etc.) compute in the correct
    # forward-time direction. This must happen even on first run (else branch above)
    # because df_new comes from the extractor in [primary, comparative] order which
    # is typically [2024, 2023] — descending.
    df_combined = df_combined.sort_values("fiscal_year").reset_index(drop=True)

    # ------------------------------------------------------------------
    # Step 4b: Balance sheet equation validation — Assets = Liabilities + Equity
    #
    # OCR PDFs often map "Total Pasivos y Patrimonio" (= total_assets) to
    # total_liabilities because the synonym "total pasivos" is a substring.
    # Detection: if total_liabilities ≈ total_assets (within 1%), the wrong
    # line was captured.  Correction: total_liabilities = total_assets - total_equity.
    # ------------------------------------------------------------------
    for idx in df_combined.index:
        ta = df_combined.at[idx, "total_assets"]
        tl = df_combined.at[idx, "total_liabilities"]
        te = df_combined.at[idx, "total_equity"]
        fy = df_combined.at[idx, "fiscal_year"]
        if pd.notna(ta) and pd.notna(tl) and pd.notna(te) and ta != 0:
            if abs(tl - ta) / abs(ta) < 0.01:          # liabilities ≈ assets → wrong
                corrected = ta - te
                df_combined.at[idx, "total_liabilities"] = corrected
                logger.debug(
                    f"Balance sheet correction FY{fy}: total_liabilities "
                    f"{tl:,.0f} → {corrected:,.0f} (= assets − equity)"
                )
            elif tl / abs(ta) < 0.01:                  # liabilities < 1% of assets → truncated OCR
                corrected = ta - te
                df_combined.at[idx, "total_liabilities"] = corrected
                logger.debug(
                    f"Balance sheet reconstruction FY{fy}: total_liabilities "
                    f"{tl:,.0f} → {corrected:,.0f} (OCR truncation, = assets − equity)"
                )

    # ------------------------------------------------------------------
    # Step 4c: Income statement sanity check — gross_profit OCR artifact detection
    #
    # OCR artifacts sometimes produce a tiny gross_profit (e.g. COP 10,845) from
    # a partial number read off the page.  Detection: gross_profit is < 0.1% of
    # revenue AND operating_income is > 1% of revenue (operating income is plausible
    # but gross_profit is not).  Under NIIF, operating_income can exceed gross_profit
    # legitimately, so we avoid a simple gp < oi comparison.
    # ------------------------------------------------------------------
    for idx in df_combined.index:
        gp  = df_combined.at[idx, "gross_profit"]
        rev = df_combined.at[idx, "revenue"]
        oi  = df_combined.at[idx, "operating_income"]
        fy  = df_combined.at[idx, "fiscal_year"]
        if (
            pd.notna(gp) and pd.notna(rev) and pd.notna(oi)
            and rev > 0 and oi > 0
            and abs(gp) / rev < 0.001          # gross_profit < 0.1% of revenue
            and abs(oi) / rev > 0.01           # but operating_income is plausible (> 1%)
        ):
            logger.debug(
                f"Sanity check FY{fy}: gross_profit={gp:,.0f} is < 0.1% of revenue "
                f"but operating_income={oi:,.0f} is plausible — OCR artifact, "
                f"setting gross_profit/cogs to NaN"
            )
            df_combined.at[idx, "gross_profit"] = float("nan")
            df_combined.at[idx, "cogs"] = float("nan")

    # ------------------------------------------------------------------
    # Step 5: Calculate KPIs (unchanged call to processor.calculate_kpis)
    # ------------------------------------------------------------------
    df_kpis = calculate_kpis(df_combined)

    # ------------------------------------------------------------------
    # Step 5b: Override NaN KPIs with directly-extracted indicator values.
    #
    # Some T2 management reports (e.g. CO informe de gestión) include a
    # financial indicators table with pre-computed ratios (razón corriente,
    # EBITDA, DSO, DPO). These are extracted into ExtractionResult.fields
    # but are NOT in FINANCIALS_COLUMNS so they don't reach financials.parquet.
    # When the KPI computation yields NaN (because balance sheet is absent),
    # use the directly-extracted values as overrides.
    # ------------------------------------------------------------------
    _KPI_OVERRIDE_FIELDS = ("current_ratio", "dso", "dpo")
    for er in extraction_results:
        fy = er.fiscal_year
        if fy is None:
            continue
        mask = df_kpis["fiscal_year"] == fy
        if not mask.any():
            continue
        for kpi_field in _KPI_OVERRIDE_FIELDS:
            extracted_val = er.fields.get(kpi_field)
            if extracted_val is None:
                continue
            try:
                extracted_val = float(extracted_val)
            except (TypeError, ValueError):
                continue
            if kpi_field in df_kpis.columns:
                existing = df_kpis.loc[mask, kpi_field]
                # Only override when computed value is NaN
                if existing.isna().all():
                    df_kpis.loc[mask, kpi_field] = extracted_val
                    logger.debug(
                        f"latam_processor: overriding NaN {kpi_field}={extracted_val} "
                        f"from extracted indicator (fy={fy}, company={company_slug})"
                    )

    # ------------------------------------------------------------------
    # Step 6: Write Parquet atomically (unchanged processor.save_parquet)
    # ------------------------------------------------------------------
    save_parquet(df_combined, out_dir / "financials.parquet")
    save_parquet(df_kpis, out_dir / "kpis.parquet")

    # ------------------------------------------------------------------
    # Step 7: Log and return summary dict
    # ------------------------------------------------------------------
    # Use primary result (first in list) for summary fields
    primary = extraction_results[0]
    logger.info(
        f"latam_processor: wrote {len(df_combined)} rows for {company_slug} "
        f"({primary.confidence} confidence)"
    )

    return {
        "slug": company_slug,
        "fiscal_year": primary.fiscal_year,
        "fiscal_years": sorted(df_combined["fiscal_year"].dropna().astype(int).tolist()),
        "confidence": primary.confidence,
        "fields_extracted": len(primary.fields),
        "rows_in_parquet": len(df_combined),
    }
