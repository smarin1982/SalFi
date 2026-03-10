"""
latam_processor.py

KPI mapping layer for LATAM financial filings.

Converts an ExtractionResult (produced by latam_extractor.py) into Parquet files
that are schema-identical to the US pipeline output (data/clean/{TICKER}/).

Design constraints:
  - calculate_kpis() and save_parquet() are imported from processor.py — never modified.
  - All monetary values are converted from native LATAM currency to USD before writing.
  - Prior-year rows are appended to enable growth KPI continuity (revenue_growth_yoy, etc.)
  - process() is idempotent: running twice on the same input produces identical output.
  - process() never enforces human-validation gating — that is the caller's responsibility.

IMPORTANT: calculate_kpis and save_parquet are imported from processor.py — never copy or modify them here

Exports:
    process             - main entry point
    FINANCIALS_COLUMNS  - 24-column canonical schema (matches data/clean/AAPL/financials.parquet)
"""

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from processor import calculate_kpis, save_parquet   # KPI-01: import, never modify
from currency import to_usd
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

def process(
    company_slug: str,
    extraction_result: ExtractionResult,
    country: str = "",
    data_dir: str = "data",
) -> dict:
    """
    Convert an ExtractionResult into financials.parquet and kpis.parquet.

    Steps:
      1. Build a one-row dict with canonical column names; convert each non-NaN
         monetary field from native currency to USD via currency.to_usd().
      2. Enforce schema dtypes (fiscal_year int64, all monetary cols float64).
      3. Determine output directory under data/latam/{country?}/{slug}/.
      4. If prior-year Parquet exists, concat + deduplicate so growth KPIs are
         computable (Pitfall 5: single row always yields NaN for yoy growth).
      5. Call calculate_kpis() from processor.py (unchanged).
      6. Write financials.parquet and kpis.parquet atomically via save_parquet().
      7. Log summary and return a status dict.

    Args:
        company_slug:      Slug identifier (e.g. "grupo-keralty") — used as ticker.
        extraction_result: Output of latam_extractor.extract().
        country:           Country slug (e.g. "colombia"); used in directory path.
        data_dir:          Root data directory (default "data").

    Returns:
        dict with keys: slug, fiscal_year, confidence, fields_extracted, rows_in_parquet
    """

    # ------------------------------------------------------------------
    # Step 1: Build one-row dict with canonical names + USD conversion
    # ------------------------------------------------------------------
    row: dict = {
        "ticker": company_slug,
        "fiscal_year": extraction_result.fiscal_year,
    }

    for canonical in _MONETARY_COLUMNS:
        native_value = extraction_result.fields.get(canonical, np.nan)
        if native_value is np.nan or (isinstance(native_value, float) and np.isnan(native_value)):
            row[canonical] = np.nan
        else:
            row[canonical] = to_usd(
                float(native_value),
                extraction_result.currency_code,
                extraction_result.fiscal_year,
            )

    # ------------------------------------------------------------------
    # Step 2: Build DataFrame and enforce schema dtypes
    # ------------------------------------------------------------------
    df_new = pd.DataFrame([row], columns=FINANCIALS_COLUMNS)
    df_new["fiscal_year"] = df_new["fiscal_year"].astype("int64")
    for col in _MONETARY_COLUMNS:
        df_new[col] = df_new[col].astype("float64")
    df_new["ticker"] = df_new["ticker"].astype("object")

    # ------------------------------------------------------------------
    # Step 3: Determine output directory
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
        df_combined = df_combined.sort_values("fiscal_year").reset_index(drop=True)
        # Re-enforce float64 dtypes after concat (nullable integer/object pollution guard)
        for col in _MONETARY_COLUMNS:
            df_combined[col] = df_combined[col].astype("float64")
    else:
        df_combined = df_new

    # ------------------------------------------------------------------
    # Step 5: Calculate KPIs (unchanged call to processor.calculate_kpis)
    # ------------------------------------------------------------------
    df_kpis = calculate_kpis(df_combined)

    # ------------------------------------------------------------------
    # Step 6: Write Parquet atomically (unchanged processor.save_parquet)
    # ------------------------------------------------------------------
    save_parquet(df_combined, out_dir / "financials.parquet")
    save_parquet(df_kpis, out_dir / "kpis.parquet")

    # ------------------------------------------------------------------
    # Step 7: Log and return summary dict
    # ------------------------------------------------------------------
    logger.info(
        f"latam_processor: wrote {len(df_combined)} rows for {company_slug} "
        f"({extraction_result.confidence} confidence)"
    )

    return {
        "slug": company_slug,
        "fiscal_year": extraction_result.fiscal_year,
        "fiscal_years": sorted(df_combined["fiscal_year"].dropna().astype(int).tolist()),
        "confidence": extraction_result.confidence,
        "fields_extracted": len(extraction_result.fields),
        "rows_in_parquet": len(df_combined),
    }
