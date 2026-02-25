"""
processor.py — Phase 2: Transformation & KPIs
Sole responsibility: turn raw data/raw/{TICKER}/facts.json into
data/clean/{TICKER}/financials.parquet and data/clean/{TICKER}/kpis.parquet.
No SEC API calls. No Streamlit. Pure transformation.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONCEPT_MAP — priority-ordered XBRL tag lists per canonical field name
# Verified against real AAPL (503 concepts, 17 FY) and BRK.B (420 concepts, 16 FY) facts.json
# ---------------------------------------------------------------------------

CONCEPT_MAP = {
    # --- Income Statement (duration: fp=="FY", form=="10-K", period > 300 days) ---
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",  # AAPL primary (51 entries)
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",                                              # BRK.B primary (136 entries), XOM
        "SalesRevenueNet",                                       # AAPL legacy older filings
        "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",                          # JPM primary
        "InterestAndDividendIncomeOperating",                    # banks fallback
    ],
    "gross_profit": [
        "GrossProfit",                                           # AAPL: 139 entries; BRK.B: MISSING
    ],
    "cogs": [
        "CostOfGoodsAndServicesSold",                            # AAPL: 51 entries
        "CostOfRevenue",
        "CostOfGoodsSold",
        "BenefitsLossesAndExpenses",                             # insurance companies
    ],
    "operating_income": [
        "OperatingIncomeLoss",                                   # AAPL: 51 entries; BRK.B: 6 entries
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "net_income": [
        "NetIncomeLoss",                                         # AAPL: 139 entries; BRK.B: 136 entries
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
    ],
    "interest_expense": [
        "InterestExpense",                                       # AAPL: 33 entries; BRK.B: 30 entries
        "InterestAndDebtExpense",
        "InterestExpenseNonoperating",
    ],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",                  # AAPL: 27 entries; BRK.B: 36 entries
        "DepreciationAndAmortization",                           # AAPL: 21 entries legacy
        "Depreciation",
        "AmortizationOfIntangibleAssets",                        # last resort, partial
    ],
    # --- Balance Sheet (instant: form=="10-K" only, no fp filter, no period filter) ---
    "total_assets": [
        "Assets",                                                # AAPL: 36 entries; BRK.B: 46 entries
    ],
    "total_liabilities": [
        "Liabilities",                                           # AAPL: 34 entries; BRK.B: 28 entries
        "LiabilitiesAndStockholdersEquity",                      # fallback (equals Assets)
    ],
    "total_equity": [
        "StockholdersEquity",                                    # AAPL: 68 entries; BRK.B: 33 entries
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "current_assets": [
        "AssetsCurrent",                                         # AAPL: 34 entries; BRK.B: MISSING
    ],
    "current_liabilities": [
        "LiabilitiesCurrent",                                    # AAPL: 34 entries; BRK.B: MISSING
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",                 # AAPL: 54 entries; BRK.B: 36 entries
        "CashCashEquivalentsAndShortTermInvestments",
        "Cash",
    ],
    "short_term_investments": [
        "ShortTermInvestments",
        "AvailableForSaleSecuritiesCurrent",
        "MarketableSecuritiesCurrent",
    ],
    "receivables": [
        "AccountsReceivableNetCurrent",                          # AAPL: 34 entries; BRK.B: MISSING
        "ReceivablesNetCurrent",
        "TradeAndOtherReceivablesNetCurrent",
    ],
    "inventory": [
        "InventoryNet",                                          # AAPL: 34 entries; BRK.B: 30 entries
        "Inventories",
        "InventoryGross",
    ],
    "long_term_debt": [
        "LongTermDebtNoncurrent",                                # AAPL: 22 entries; BRK.B: MISSING
        "LongTermDebt",
        "LongTermNotesPayable",
        "LongTermDebtAndCapitalLeaseObligations",
    ],
    "short_term_debt": [
        "LongTermDebtCurrent",                                   # AAPL: 22 entries (current portion)
        "CommercialPaper",                                       # AAPL: 24 entries
        "ShortTermBorrowings",
        "DebtCurrent",
    ],
    "accounts_payable": [
        "AccountsPayableCurrent",                                # AAPL: 34 entries
        "AccountsPayableAndAccruedLiabilitiesCurrent",
    ],
    "shares_outstanding": [
        "CommonStockSharesOutstanding",                          # AAPL: 36 entries; BRK.B: 46 entries
        "CommonStockSharesIssuedAndOutstanding",
    ],
    # --- Cash Flow Statement (duration, same filter as income statement) ---
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
    ],
}

# Instant concepts have no 'start' field in XBRL entries (balance sheet point-in-time)
# Duration concepts have both 'start' and 'end' (income/cash flow over a period)
INSTANT_CONCEPTS = {
    "total_assets", "total_liabilities", "total_equity",
    "current_assets", "current_liabilities", "cash",
    "short_term_investments", "receivables", "inventory",
    "long_term_debt", "short_term_debt", "accounts_payable",
    "shares_outstanding",
}

DURATION_CONCEPTS = {
    "revenue", "gross_profit", "cogs", "operating_income",
    "net_income", "interest_expense", "depreciation_amortization",
    "operating_cash_flow", "capex",
}

# ---------------------------------------------------------------------------
# XFORM-01: XBRL concept extraction with priority fallback
# ---------------------------------------------------------------------------

def extract_concept(facts: dict, field_name: str) -> pd.Series:
    """
    Try each XBRL tag in CONCEPT_MAP priority order.
    Returns pd.Series indexed by fiscal_year (int), values in USD (float).
    Returns empty Series (not an exception) if no tag yields data.

    Key rules verified against real AAPL + BRK.B facts.json:
    - Use end-date year as fiscal_year (NOT fy field — fy is the filing year)
    - Duration concepts: require fp=="FY" AND period > 300 days to exclude partials
    - Instant concepts: form=="10-K" filter only, no period-length check
    - Dedup by end date: keep entry with latest 'filed' date
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    is_instant = field_name in INSTANT_CONCEPTS

    for tag in CONCEPT_MAP.get(field_name, []):
        if tag not in us_gaap:
            continue

        all_entries = us_gaap[tag].get("units", {}).get("USD", [])
        ten_k = [e for e in all_entries if e.get("form") == "10-K"]

        if is_instant:
            # Balance sheet: point-in-time value, no period filter needed
            candidates = ten_k
        else:
            # Income/cash flow: must be full fiscal year (FY) with period > 300 days
            candidates = []
            for e in ten_k:
                if e.get("fp") != "FY" or not e.get("start"):
                    continue
                try:
                    days = (
                        datetime.strptime(e["end"], "%Y-%m-%d")
                        - datetime.strptime(e["start"], "%Y-%m-%d")
                    ).days
                except (ValueError, KeyError):
                    continue
                if days > 300:
                    candidates.append(e)

        if not candidates:
            continue  # try next tag in priority list

        # Deduplication: group by end date, keep latest filed
        by_end: dict = defaultdict(list)
        for e in candidates:
            by_end[e["end"]].append(e)

        result = {}
        for end_date, dupes in by_end.items():
            winner = max(dupes, key=lambda x: x["filed"])
            fiscal_year = int(end_date[:4])
            result[fiscal_year] = float(winner["val"])

        if result:
            logger.debug(
                f"Field '{field_name}': using tag '{tag}', {len(result)} fiscal years"
            )
            s = pd.Series(result, dtype=float, name=field_name)
            s.index.name = "fiscal_year"
            return s.sort_index()

    logger.warning(f"Field '{field_name}': no XBRL tag found in us-gaap namespace")
    return pd.Series(dtype=float, name=field_name)


def normalize_xbrl(facts: dict, ticker: str) -> pd.DataFrame:
    """
    Extract all CONCEPT_MAP fields into a single wide DataFrame.
    One row per fiscal year, one column per financial field.
    Adds 'ticker' column for multi-company stacking.

    Columns with no data are included as all-NaN float columns.
    This ensures the schema is consistent across all tickers (BRK.B has NaN
    for current_assets, etc. — that is correct, not an error).

    Raises ValueError only if zero fields could be extracted (completely broken JSON).
    """
    series_dict = {}
    for field in CONCEPT_MAP:
        s = extract_concept(facts, field)
        series_dict[field] = s  # always store, even if empty (becomes NaN column)

    # Build DataFrame from all series, aligning on fiscal_year index
    non_empty = {k: v for k, v in series_dict.items() if not v.empty}
    if not non_empty:
        raise ValueError(
            f"{ticker}: zero fields extracted from facts.json — "
            "file may be malformed or contain no us-gaap data"
        )

    df = pd.DataFrame(non_empty)
    df.index.name = "fiscal_year"

    # Add missing columns as NaN (ensures consistent schema across all tickers)
    for field in CONCEPT_MAP:
        if field not in df.columns:
            df[field] = np.nan

    df = df.reset_index()
    df.insert(0, "ticker", ticker)
    # Sort columns: ticker, fiscal_year, then CONCEPT_MAP order
    col_order = ["ticker", "fiscal_year"] + list(CONCEPT_MAP.keys())
    df = df[[c for c in col_order if c in df.columns]]
    return df.sort_values("fiscal_year").reset_index(drop=True)


# ---------------------------------------------------------------------------
# XFORM-02: Missing value treatment
# ---------------------------------------------------------------------------

def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """
    Divide two Series safely. Returns NaN where denominator is 0 or NaN.
    Never produces inf or raises ZeroDivisionError.
    Uses denominator.replace(0, np.nan) to convert zeros to NaN before division.
    """
    return numerator / denominator.replace(0, np.nan)


def clean_financials(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply rolling median fill for isolated NaN gaps (1-2 consecutive years).
    Preserves outliers as-is (no capping or clipping — XFORM-02: outliers = real data).
    No inflation adjustment (XFORM-02: nominal values only).
    Structural NaN (entire field missing, e.g. BRK.B current_assets) remains NaN.

    Rolling fill rule: window=3, centered, min_periods=1.
    Only fills NaN positions; does not modify existing values.
    """
    df = df.sort_values("fiscal_year").copy()
    numeric_cols = [c for c in df.columns if c not in ("ticker", "fiscal_year")]

    for col in numeric_cols:
        s = df[col].astype(float)
        nan_mask = s.isna()
        # Only fill if there is at least one non-NaN value to interpolate from
        if nan_mask.any() and not nan_mask.all():
            rolling_fill = s.rolling(window=3, min_periods=1, center=True).median()
            s = s.where(~nan_mask, other=rolling_fill)
            df[col] = s

    return df


# ---------------------------------------------------------------------------
# XFORM-03: 20 KPI calculations
# ---------------------------------------------------------------------------

def calculate_kpis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate all 20 KPIs from normalized financials DataFrame.
    Returns new DataFrame with ticker, fiscal_year, and 20 KPI columns.

    Rules:
    - Missing inputs propagate as NaN (do not substitute 0 for missing balance sheet items)
    - No division-by-zero: all ratio KPIs use safe_divide()
    - Average-based KPIs use .shift(1) for prior-year values; NaN for earliest year is correct
    - Outliers preserved as-is (XFORM-02)
    - df must be sorted by fiscal_year ascending before calling (clean_financials ensures this)
    """
    d = df.set_index("fiscal_year").copy()
    kpis = pd.DataFrame(index=d.index)
    kpis.index.name = "fiscal_year"

    # Helper: get column as Series, returning all-NaN Series if column missing
    def col(name: str) -> pd.Series:
        if name in d.columns:
            return d[name].astype(float)
        return pd.Series(np.nan, index=d.index, dtype=float)

    rev    = col("revenue")
    ni     = col("net_income")
    ebit   = col("operating_income")
    da     = col("depreciation_amortization")
    gp     = col("gross_profit")
    eq     = col("total_equity")
    assets = col("total_assets")
    ca     = col("current_assets")
    cl     = col("current_liabilities")
    cash   = col("cash")
    sti    = col("short_term_investments")
    recv   = col("receivables")
    inv    = col("inventory")
    ltd    = col("long_term_debt")
    std    = col("short_term_debt")
    liab   = col("total_liabilities")
    ie     = col("interest_expense")
    ap     = col("accounts_payable")
    cogs   = col("cogs")

    # EBITDA: EBIT + D&A. If D&A is NaN, EBITDA is NaN (do NOT use fillna(0) — understates EBITDA)
    ebitda = ebit + da

    # Total debt: STD + LTD. If BOTH are NaN, total_debt = NaN. If only one is NaN, treat as 0.
    total_debt = ltd.fillna(0) + std.fillna(0)
    total_debt = total_debt.where(ltd.notna() | std.notna(), other=np.nan)

    # --- KPI 1: Revenue Growth YoY ---
    kpis["revenue_growth_yoy"] = rev.pct_change()

    # --- KPI 2: Revenue CAGR 10Y ---
    def cagr_10y(s: pd.Series) -> pd.Series:
        result = pd.Series(np.nan, index=s.index, dtype=float)
        for yr in s.index:
            yr_minus_10 = yr - 10
            if (yr_minus_10 in s.index
                    and pd.notna(s[yr])
                    and pd.notna(s[yr_minus_10])
                    and s[yr_minus_10] != 0):
                result[yr] = (s[yr] / s[yr_minus_10]) ** (1 / 10) - 1
        return result
    kpis["revenue_cagr_10y"] = cagr_10y(rev)

    # --- KPI 3: Gross Profit Margin ---
    kpis["gross_profit_margin"] = safe_divide(gp, rev)

    # --- KPI 4: Operating Margin (EBIT / Revenue) ---
    kpis["operating_margin"] = safe_divide(ebit, rev)

    # --- KPI 5: Net Profit Margin ---
    kpis["net_profit_margin"] = safe_divide(ni, rev)

    # --- KPI 6: EBITDA Margin ---
    kpis["ebitda_margin"] = safe_divide(ebitda, rev)

    # --- KPI 7: ROE (Net Income / Total Equity) ---
    kpis["roe"] = safe_divide(ni, eq)

    # --- KPI 8: ROA (Net Income / Total Assets) ---
    kpis["roa"] = safe_divide(ni, assets)

    # --- KPI 9: Current Ratio ---
    kpis["current_ratio"] = safe_divide(ca, cl)

    # --- KPI 10: Quick Ratio ((Cash + STI + Receivables) / CL) ---
    quick_assets = cash + sti.fillna(0) + recv.fillna(0)
    kpis["quick_ratio"] = safe_divide(quick_assets, cl)

    # --- KPI 11: Cash Ratio ---
    kpis["cash_ratio"] = safe_divide(cash, cl)

    # --- KPI 12: Working Capital ---
    kpis["working_capital"] = ca - cl

    # --- KPI 13: Debt-to-Equity ---
    kpis["debt_to_equity"] = safe_divide(liab, eq)

    # --- KPI 14: Debt-to-EBITDA ((STD + LTD) / EBITDA) ---
    kpis["debt_to_ebitda"] = safe_divide(total_debt, ebitda)

    # --- KPI 15: Interest Coverage (EBIT / Interest Expense) ---
    kpis["interest_coverage"] = safe_divide(ebit, ie)

    # --- KPI 16: Debt-to-Assets ---
    kpis["debt_to_assets"] = safe_divide(total_debt, assets)

    # --- KPI 17: Asset Turnover (Revenue / Avg Total Assets) ---
    avg_assets = (assets + assets.shift(1)) / 2
    kpis["asset_turnover"] = safe_divide(rev, avg_assets)

    # --- KPI 18: Inventory Turnover (COGS / Avg Inventory) ---
    avg_inv = (inv + inv.shift(1)) / 2
    kpis["inventory_turnover"] = safe_divide(cogs, avg_inv)

    # --- KPI 19: DSO (Avg Receivables / Revenue * 365) ---
    avg_recv = (recv + recv.shift(1)) / 2
    kpis["dso"] = safe_divide(avg_recv, rev) * 365

    # --- KPI 20: Cash Conversion Cycle (DIO + DSO - DPO) ---
    avg_inv2 = (inv + inv.shift(1)) / 2
    avg_ap   = (ap + ap.shift(1)) / 2
    dio = safe_divide(avg_inv2, cogs) * 365
    dso = safe_divide(avg_recv, rev) * 365
    dpo = safe_divide(avg_ap, cogs) * 365
    kpis["cash_conversion_cycle"] = dio + dso - dpo

    kpis = kpis.reset_index()
    kpis.insert(0, "ticker", df["ticker"].iloc[0])
    return kpis


# ---------------------------------------------------------------------------
# XFORM-04: Atomic Parquet write
# ---------------------------------------------------------------------------

def save_parquet(df: pd.DataFrame, output_path: Path) -> None:
    """
    Write DataFrame to Parquet atomically.
    Writes to {output_path}.tmp first, renames to final path on success.
    If process crashes after write but before rename, .tmp is left (safe — rename is atomic on NTFS).
    Always uses engine='pyarrow' for byte-identical idempotency.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp_path, index=False, engine="pyarrow")
    # On Windows, rename to existing file requires explicit unlink first
    if output_path.exists():
        output_path.unlink()
    tmp_path.rename(output_path)
    logger.debug(f"Parquet written: {output_path} ({output_path.stat().st_size // 1024} KB)")


# ---------------------------------------------------------------------------
# Top-level entry point — XFORM-01 through XFORM-04 orchestrated
# ---------------------------------------------------------------------------

def process(ticker: str, data_dir: "Path | str" = "data") -> dict:
    """
    Main entry point for Phase 2. Idempotent: safe to run multiple times.

    Reads:   data/raw/{TICKER}/facts.json  (produced by Phase 1 scraper.py)
    Writes:  data/clean/{TICKER}/financials.parquet
             data/clean/{TICKER}/kpis.parquet

    Returns status dict:
      {ticker, fiscal_years, fields_extracted, fields_missing, kpi_columns}

    Raises FileNotFoundError if facts.json does not exist.
    Raises ValueError if facts.json contains no us-gaap data.
    """
    data_dir = Path(data_dir)
    ticker = ticker.upper()
    raw_path = data_dir / "raw" / ticker / "facts.json"

    if not raw_path.exists():
        raise FileNotFoundError(
            f"facts.json not found for {ticker}: {raw_path}\n"
            f"Run scraper.py first: python scraper.py {ticker}"
        )

    logger.info(f"Processing {ticker} from {raw_path}")
    facts = json.loads(raw_path.read_text(encoding="utf-8"))

    df_norm  = normalize_xbrl(facts, ticker)
    df_clean = clean_financials(df_norm)
    df_kpis  = calculate_kpis(df_clean)

    clean_dir = data_dir / "clean" / ticker
    save_parquet(df_clean, clean_dir / "financials.parquet")
    save_parquet(df_kpis,  clean_dir / "kpis.parquet")

    numeric_cols = [c for c in df_clean.columns if c not in ("ticker", "fiscal_year")]
    fields_extracted = [c for c in numeric_cols if df_clean[c].notna().any()]
    fields_missing   = [c for c in numeric_cols if df_clean[c].isna().all()]

    result = {
        "ticker": ticker,
        "fiscal_years": sorted(df_clean["fiscal_year"].tolist()),
        "fields_extracted": fields_extracted,
        "fields_missing": fields_missing,
        "kpi_columns": [c for c in df_kpis.columns if c not in ("ticker", "fiscal_year")],
    }

    logger.info(
        f"{ticker}: {len(result['fiscal_years'])} fiscal years "
        f"({result['fiscal_years'][0]}–{result['fiscal_years'][-1]}), "
        f"{len(fields_extracted)} fields extracted, "
        f"{len(fields_missing)} fields missing (NaN)"
    )
    return result


# ---------------------------------------------------------------------------
# CLI: python processor.py TICKER [TICKER2 ...]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage: python processor.py TICKER [TICKER2 ...]")
        print("Examples:")
        print("  python processor.py AAPL")
        print("  python processor.py AAPL BRK.B MSFT")
        sys.exit(1)

    tickers = [t.upper() for t in sys.argv[1:]]
    data_dir = Path(__file__).parent / "data"
    errors = []

    for tick in tickers:
        try:
            result = process(tick, data_dir)
            print(f"[OK] {tick}: {len(result['fiscal_years'])} FY "
                  f"({result['fiscal_years'][0]}–{result['fiscal_years'][-1]}), "
                  f"{len(result['fields_extracted'])} fields, "
                  f"{len(result['kpi_columns'])} KPIs")
            if result["fields_missing"]:
                print(f"     Missing (NaN): {', '.join(result['fields_missing'])}")
        except (FileNotFoundError, ValueError) as e:
            print(f"[ERROR] {tick}: {e}")
            errors.append(tick)

    if errors:
        print(f"\nFailed tickers: {errors}")
        sys.exit(1)
