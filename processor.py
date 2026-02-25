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
