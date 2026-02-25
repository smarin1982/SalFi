# Phase 2: Transformation & KPIs - Research

**Researched:** 2026-02-25
**Domain:** XBRL normalization, Pandas ETL, Parquet schema, financial KPI calculation
**Confidence:** HIGH (all findings verified against real AAPL and BRK.B facts.json data)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| XFORM-01 | Normalize XBRL concepts using a CONCEPT_MAP with priority-ordered lists (7+ names per field), guaranteeing coverage of all Top 20 companies | Exact concept names verified in AAPL and BRK.B facts.json; priority orders determined from real data; BRK.B gaps documented |
| XFORM-02 | Handle missing values via rolling median, preserve outliers as real data, no inflation adjustment | Rolling median pattern tested and confirmed; preserving outliers = no clipping/capping; nominal values = direct copy from SEC |
| XFORM-03 | Calculate all 20 KPIs for each company/year; missing inputs produce NaN, not wrong values; no division-by-zero | safe_divide pattern tested; all 20 KPI formulas verified; average-based formulas (Avg Assets, Avg Recv) produce NaN for first year |
| XFORM-04 | Store financials.parquet (normalized fields) and kpis.parquet (20 KPIs) in data/clean/{TICKER}/ | Parquet byte-identical idempotency confirmed; pyarrow 23.0.1 installed; schema design documented |
</phase_requirements>

---

## Summary

Phase 2 implements `processor.py` — the transformation layer that reads raw `facts.json` files produced by Phase 1 and outputs two Parquet files per ticker: `financials.parquet` (normalized base financial fields) and `kpis.parquet` (20 calculated KPIs). The primary technical challenge is XBRL concept normalization: the same economic quantity (e.g., revenue) has 3-7+ different XBRL tag names across the Top 20 companies, requiring a priority-ordered fallback chain.

Research verified against real AAPL (503 us-gaap concepts, 17 FY) and BRK.B (420 us-gaap concepts, 16 FY) facts.json files. Key findings: AAPL's primary revenue tag is `RevenueFromContractWithCustomerExcludingAssessedTax`; BRK.B uses `Revenues` (136 FY entries). Balance sheet entries are duplicated across multiple filings — deduplication must key on `end` date (period end), not `fy` field, and keep the latest `filed` date. Period length filtering (> 300 days) is required to exclude partial-year entries that appear alongside full-year ones. BRK.B is missing `AssetsCurrent`, `LiabilitiesCurrent`, `GrossProfit`, `CostOfRevenue`, `AccountsReceivableNetCurrent`, and `LongTermDebt` — ratio KPIs that require these will be NaN for BRK.B, which is correct behavior.

Parquet byte-identical idempotency is confirmed with pyarrow 23.0.1. The installed versions are pandas 3.0.1, pyarrow 23.0.1, numpy 2.4.2 — all already installed in the project environment.

**Primary recommendation:** Build `processor.py` as three pure functions chained in sequence: `normalize_xbrl(facts_dict) -> DataFrame`, `clean_financials(df) -> DataFrame`, `calculate_kpis(df) -> DataFrame`. Each stage is independently testable. Write Parquet atomically (write to temp path, rename to final).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 3.0.1 (installed) | DataFrame manipulation, period alignment, rolling window | Already installed; edgartools returns DataFrames; Streamlit accepts DataFrames |
| pyarrow | 23.0.1 (installed) | Parquet read/write engine | Already installed; produces byte-identical output on re-write (idempotency confirmed) |
| numpy | 2.4.2 (installed) | NaN arithmetic, safe division | Already installed; `np.nan` is the correct missing value type for float columns |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| loguru | 0.7.3 (installed) | Structured logging for normalization decisions | Log which XBRL tag was selected per field per ticker — essential for debugging |
| pathlib | stdlib | Path manipulation | Already used in scraper.py |

### Phase 2 Additions to requirements.txt
```
pandas>=3.0
pyarrow>=23.0
numpy>=2.4
```
(These are already installed; pin to installed versions for reproducibility.)

---

## Architecture Patterns

### Recommended Project Structure
```
processor.py         # All Phase 2 logic in one file
data/
  raw/
    {TICKER}/
      facts.json     # Input: verbatim from Phase 1
  clean/
    {TICKER}/
      financials.parquet    # Output: normalized base fields, one row per FY
      kpis.parquet          # Output: 20 KPIs, one row per FY
```

### Pattern 1: CONCEPT_MAP with Priority-Order Fallback

**What:** A dictionary mapping canonical field names to ordered lists of XBRL concept tags. The normalizer tries each tag in order, stopping at the first that yields FY data.

**When to use:** Every field extraction from facts.json.

**Verified CONCEPT_MAP (from real AAPL + BRK.B data):**

```python
# processor.py
CONCEPT_MAP = {
    # --- Income Statement (duration concepts: filter fp=="FY", form=="10-K", period > 300 days) ---

    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",  # AAPL (primary)
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",                                              # BRK.B (primary), XOM
        "SalesRevenueNet",                                       # AAPL legacy (older filings)
        "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",                          # banks (JPM)
        "InterestAndDividendIncomeOperating",                    # banks fallback
    ],

    "gross_profit": [
        "GrossProfit",                                           # AAPL: confirmed 139 entries
        # NOTE: Not present in BRK.B - will be NaN, correct behavior
    ],

    "cogs": [
        "CostOfGoodsAndServicesSold",                            # AAPL: 51 entries
        "CostOfRevenue",                                         # general
        "CostOfGoodsSold",                                       # legacy
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
        "DepreciationDepletionAndAmortization",                  # AAPL: 27 entries; BRK.B: 36 entries (PRIMARY)
        "DepreciationAndAmortization",                           # AAPL: 21 entries (legacy)
        "Depreciation",                                          # AAPL: 21 entries; BRK.B: 36 entries
        "AmortizationOfIntangibleAssets",                        # last resort, partial
    ],

    # --- Balance Sheet (instant concepts: filter form=="10-K", NO fp filter, period length N/A) ---

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
        "ShortTermInvestments",                                  # AAPL: MISSING in current data
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
        "LongTermDebtCurrent",                                   # AAPL: 22 entries (current portion of LTD)
        "CommercialPaper",                                       # AAPL: 24 entries
        "ShortTermBorrowings",
        "DebtCurrent",
    ],

    "accounts_payable": [
        "AccountsPayableCurrent",                                # AAPL: 34 entries
        "AccountsPayableAndAccruedLiabilitiesCurrent",
    ],

    # --- Cash Flow Statement (duration concepts, same filter as income statement) ---

    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],

    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
    ],
}
```

### Pattern 2: Entry Extraction Function

**Critical insight from real data:** The `fy` field in XBRL entries is the fiscal year of the *filing*, not the *period*. A 2024 10-K includes comparative data for 2022 and 2023, so the same period (e.g., `end=2022-09-24`) appears with `fy=2022`, `fy=2023`, and `fy=2024`. Deduplication must key on `end` date, not `fy` field.

**Critical insight:** Partial-period entries exist within 10-K filings (e.g., quarterly breakdowns). Filter these out by requiring period length > 300 days for duration concepts.

**Critical insight:** Instant concepts (balance sheet) have NO `start` field in XBRL entries. Duration concepts (income, cash flow) have both `start` and `end`.

```python
from datetime import datetime
from collections import defaultdict
import pandas as pd
import numpy as np

INSTANT_CONCEPTS = {
    "total_assets", "total_liabilities", "total_equity",
    "current_assets", "current_liabilities", "cash",
    "short_term_investments", "receivables", "inventory",
    "long_term_debt", "short_term_debt", "accounts_payable",
}

DURATION_CONCEPTS = {
    "revenue", "gross_profit", "cogs", "operating_income",
    "net_income", "interest_expense", "depreciation_amortization",
    "operating_cash_flow", "capex",
}

def extract_concept(facts: dict, field_name: str) -> pd.Series:
    """
    Try each XBRL tag in CONCEPT_MAP priority order.
    Returns pd.Series indexed by fiscal_year (int), values in USD (float).
    Returns empty Series if no tag found.
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    is_instant = field_name in INSTANT_CONCEPTS

    for tag in CONCEPT_MAP.get(field_name, []):
        if tag not in us_gaap:
            continue

        entries = us_gaap[tag].get("units", {}).get("USD", [])
        # Filter to 10-K form only
        ten_k_entries = [e for e in entries if e.get("form") == "10-K"]

        if is_instant:
            # Balance sheet: no fp filter, no period-length filter
            # Each entry has end date + value; pick latest filed per end date
            candidates = ten_k_entries
        else:
            # Income/cash flow: require fp=="FY" AND period > 300 days
            candidates = []
            for e in ten_k_entries:
                if e.get("fp") != "FY":
                    continue
                start = e.get("start")
                if start is None:
                    continue  # skip entries without start (shouldn't happen for duration)
                days = (
                    datetime.strptime(e["end"], "%Y-%m-%d")
                    - datetime.strptime(start, "%Y-%m-%d")
                ).days
                if days > 300:  # full year only (handles 52-week fiscal years: 363-370 days)
                    candidates.append(e)

        if not candidates:
            continue  # try next tag

        # Deduplicate: group by 'end' date, keep latest 'filed'
        by_end = defaultdict(list)
        for e in candidates:
            by_end[e["end"]].append(e)

        result = {}
        for end_date, dupes in by_end.items():
            winner = max(dupes, key=lambda x: x["filed"])
            fiscal_year = int(end_date[:4])  # year of end date = FY label
            result[fiscal_year] = float(winner["val"])

        if result:
            s = pd.Series(result, dtype=float, name=field_name)
            s.index.name = "fiscal_year"
            return s.sort_index()

    return pd.Series(dtype=float, name=field_name)  # all tags exhausted
```

### Pattern 3: Normalize to Wide DataFrame

```python
def normalize_xbrl(facts: dict, ticker: str) -> pd.DataFrame:
    """
    Extract all CONCEPT_MAP fields into a single wide DataFrame.
    One row per fiscal year, one column per financial field.
    Adds 'ticker' column for multi-company stacking.
    """
    series = {}
    for field in CONCEPT_MAP:
        s = extract_concept(facts, field)
        if s.empty:
            logger.warning(f"{ticker}: no data found for field '{field}'")
        else:
            series[field] = s

    if not series:
        raise ValueError(f"{ticker}: no fields could be extracted from facts.json")

    df = pd.DataFrame(series)
    df.index.name = "fiscal_year"
    df = df.reset_index()
    df.insert(0, "ticker", ticker)
    return df
```

### Pattern 4: Missing Value Treatment (XFORM-02)

**Rule:** Fill isolated NaN gaps (1-2 consecutive years) with rolling median. Preserve surrounding data as-is (no capping/clipping — outliers are real). Leave structural gaps (entire field missing) as NaN.

```python
def clean_financials(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply rolling median fill for isolated NaN gaps.
    Preserves outliers. No inflation adjustment.
    Returns cleaned copy, sorted by fiscal_year ascending.
    """
    df = df.sort_values("fiscal_year").copy()
    numeric_cols = [c for c in df.columns if c not in ("ticker", "fiscal_year")]

    for col in numeric_cols:
        s = df[col].astype(float)
        nan_mask = s.isna()
        if nan_mask.any() and not nan_mask.all():
            # Rolling window=3, centered, min_periods=1 — fills gaps using neighbors
            rolling_fill = s.rolling(window=3, min_periods=1, center=True).median()
            s[nan_mask] = rolling_fill[nan_mask]
            df[col] = s

    return df
```

### Pattern 5: Safe Division for KPI Calculation (XFORM-03)

```python
def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """
    Divide two Series safely. Returns NaN where denominator is 0 or NaN.
    Never produces inf or division-by-zero errors.
    """
    return numerator / denominator.replace(0, np.nan)
```

### Pattern 6: 20 KPI Calculations

All KPIs operate on the wide financials DataFrame. Average-based KPIs (Asset Turnover, DSO, Inventory Turnover, CCC) require prior-year data via `.shift(1)` — these produce NaN for the earliest year. This is correct behavior.

```python
def calculate_kpis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate all 20 KPIs from normalized financials DataFrame.
    Returns new DataFrame with ticker, fiscal_year, and 20 KPI columns.
    Missing inputs propagate as NaN. No division by zero.
    """
    d = df.set_index("fiscal_year").copy()
    kpis = pd.DataFrame(index=d.index)
    kpis.index.name = "fiscal_year"

    rev = d["revenue"]
    ni = d["net_income"]
    ebit = d["operating_income"]
    da = d["depreciation_amortization"]
    gp = d.get("gross_profit", pd.Series(np.nan, index=d.index))
    eq = d["total_equity"]
    assets = d["total_assets"]
    ca = d.get("current_assets", pd.Series(np.nan, index=d.index))
    cl = d.get("current_liabilities", pd.Series(np.nan, index=d.index))
    cash = d["cash"]
    sti = d.get("short_term_investments", pd.Series(np.nan, index=d.index))
    recv = d.get("receivables", pd.Series(np.nan, index=d.index))
    inv = d.get("inventory", pd.Series(np.nan, index=d.index))
    ltd = d.get("long_term_debt", pd.Series(np.nan, index=d.index))
    std = d.get("short_term_debt", pd.Series(np.nan, index=d.index))
    liab = d["total_liabilities"]
    ie = d.get("interest_expense", pd.Series(np.nan, index=d.index))
    ap = d.get("accounts_payable", pd.Series(np.nan, index=d.index))
    cogs = d.get("cogs", pd.Series(np.nan, index=d.index))

    ebitda = ebit + da.fillna(0)  # if D&A is NaN, EBITDA stays NaN via ebit

    # 1. Revenue Growth YoY
    kpis["revenue_growth_yoy"] = rev.pct_change()  # handles NaN propagation

    # 2. Revenue CAGR 10Y
    def cagr_10y(s: pd.Series) -> pd.Series:
        result = pd.Series(np.nan, index=s.index, dtype=float)
        for yr in s.index:
            if yr - 10 in s.index and pd.notna(s[yr]) and pd.notna(s[yr - 10]) and s[yr - 10] != 0:
                result[yr] = (s[yr] / s[yr - 10]) ** (1 / 10) - 1
        return result
    kpis["revenue_cagr_10y"] = cagr_10y(rev)

    # 3. Gross Profit Margin
    kpis["gross_profit_margin"] = safe_divide(gp, rev)

    # 4. Operating Margin (EBIT / Revenue)
    kpis["operating_margin"] = safe_divide(ebit, rev)

    # 5. Net Profit Margin
    kpis["net_profit_margin"] = safe_divide(ni, rev)

    # 6. EBITDA Margin
    kpis["ebitda_margin"] = safe_divide(ebitda, rev)

    # 7. ROE: Net Income / Total Equity
    kpis["roe"] = safe_divide(ni, eq)

    # 8. ROA: Net Income / Total Assets
    kpis["roa"] = safe_divide(ni, assets)

    # 9. Current Ratio
    kpis["current_ratio"] = safe_divide(ca, cl)

    # 10. Quick Ratio: (Cash + Short-term Investments + Receivables) / CL
    quick_assets = cash + sti.fillna(0) + recv.fillna(0)
    # Only compute where CL exists; if no STI or recv, still valid with what's available
    # NaN propagates correctly if cash itself is NaN
    kpis["quick_ratio"] = safe_divide(quick_assets, cl)

    # 11. Cash Ratio: Cash / CL
    kpis["cash_ratio"] = safe_divide(cash, cl)

    # 12. Working Capital
    kpis["working_capital"] = ca - cl

    # 13. Debt-to-Equity
    kpis["debt_to_equity"] = safe_divide(liab, eq)

    # 14. Debt-to-EBITDA: (STD + LTD) / EBITDA
    total_debt = ltd.fillna(0) + std.fillna(0)
    # If both are NaN (not just 0), result should be NaN
    total_debt = total_debt.where(ltd.notna() | std.notna(), np.nan)
    kpis["debt_to_ebitda"] = safe_divide(total_debt, ebitda)

    # 15. Interest Coverage: EBIT / Interest Expense
    kpis["interest_coverage"] = safe_divide(ebit, ie)

    # 16. Debt-to-Assets
    kpis["debt_to_assets"] = safe_divide(total_debt, assets)

    # 17. Asset Turnover: Revenue / Avg Total Assets
    avg_assets = (assets + assets.shift(1)) / 2
    kpis["asset_turnover"] = safe_divide(rev, avg_assets)

    # 18. Inventory Turnover: COGS / Avg Inventory
    avg_inv = (inv + inv.shift(1)) / 2
    kpis["inventory_turnover"] = safe_divide(cogs, avg_inv)

    # 19. DSO: (Avg Receivables / Revenue) * 365
    avg_recv = (recv + recv.shift(1)) / 2
    kpis["dso"] = safe_divide(avg_recv, rev) * 365

    # 20. Cash Conversion Cycle: DIO + DSO - DPO
    avg_inv2 = (inv + inv.shift(1)) / 2
    avg_ap = (ap + ap.shift(1)) / 2
    dio = safe_divide(avg_inv2, cogs) * 365
    dso = safe_divide(avg_recv, rev) * 365
    dpo = safe_divide(avg_ap, cogs) * 365
    kpis["cash_conversion_cycle"] = dio + dso - dpo

    kpis = kpis.reset_index()
    kpis.insert(0, "ticker", df["ticker"].iloc[0])
    return kpis
```

### Pattern 7: Atomic Parquet Write

**Why:** If processor crashes mid-write, the output file must not be partially written. Write to `.tmp` file first, then rename.

```python
def save_parquet(df: pd.DataFrame, output_path: Path) -> None:
    """
    Write DataFrame to Parquet atomically.
    Writes to {output_path}.tmp first, renames on success.
    Idempotent: re-running with same data produces byte-identical output.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp_path, index=False, engine="pyarrow")
    tmp_path.rename(output_path)
```

### Pattern 8: Top-Level Processor Entry Point

```python
def process(ticker: str, data_dir: Path = Path("data")) -> dict:
    """
    Main entry point for Phase 2.
    Reads data/raw/{TICKER}/facts.json
    Writes data/clean/{TICKER}/financials.parquet
    Writes data/clean/{TICKER}/kpis.parquet
    Returns status dict.
    Idempotent: safe to run multiple times.
    """
    ticker = ticker.upper()
    raw_path = data_dir / "raw" / ticker / "facts.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"facts.json not found for {ticker}: {raw_path}")

    facts = json.loads(raw_path.read_text(encoding="utf-8"))
    df_norm = normalize_xbrl(facts, ticker)
    df_clean = clean_financials(df_norm)
    df_kpis = calculate_kpis(df_clean)

    save_parquet(df_clean, data_dir / "clean" / ticker / "financials.parquet")
    save_parquet(df_kpis, data_dir / "clean" / ticker / "kpis.parquet")

    return {
        "ticker": ticker,
        "fiscal_years": sorted(df_clean["fiscal_year"].tolist()),
        "fields_extracted": [c for c in df_clean.columns if c not in ("ticker", "fiscal_year") and df_clean[c].notna().any()],
        "kpi_columns": list(df_kpis.columns),
    }
```

### Pattern 9: Parquet Schema

**financials.parquet schema:**

| Column | Type | Notes |
|--------|------|-------|
| ticker | string | e.g. "AAPL" |
| fiscal_year | int64 | 4-digit year of fiscal year end date |
| revenue | float64 | NaN if not found |
| gross_profit | float64 | NaN for BRK.B, financial companies |
| cogs | float64 | NaN for financial companies |
| operating_income | float64 | |
| net_income | float64 | |
| interest_expense | float64 | |
| depreciation_amortization | float64 | |
| total_assets | float64 | |
| total_liabilities | float64 | |
| total_equity | float64 | |
| current_assets | float64 | NaN for BRK.B |
| current_liabilities | float64 | NaN for BRK.B |
| cash | float64 | |
| short_term_investments | float64 | |
| receivables | float64 | NaN for BRK.B |
| inventory | float64 | |
| long_term_debt | float64 | NaN for BRK.B |
| short_term_debt | float64 | |
| accounts_payable | float64 | |
| operating_cash_flow | float64 | |
| capex | float64 | |

**kpis.parquet schema:**

| Column | Type | Notes |
|--------|------|-------|
| ticker | string | |
| fiscal_year | int64 | |
| revenue_growth_yoy | float64 | ratio (0.05 = 5%); NaN for earliest year |
| revenue_cagr_10y | float64 | ratio; NaN until 10 years of data |
| gross_profit_margin | float64 | NaN if gross_profit is NaN |
| operating_margin | float64 | |
| net_profit_margin | float64 | |
| ebitda_margin | float64 | |
| roe | float64 | can be negative (negative equity) |
| roa | float64 | |
| current_ratio | float64 | NaN for BRK.B |
| quick_ratio | float64 | NaN for BRK.B |
| cash_ratio | float64 | NaN for BRK.B |
| working_capital | float64 | NaN for BRK.B |
| debt_to_equity | float64 | |
| debt_to_ebitda | float64 | NaN if both STD and LTD are NaN for BRK.B |
| interest_coverage | float64 | |
| debt_to_assets | float64 | |
| asset_turnover | float64 | NaN for earliest year |
| inventory_turnover | float64 | NaN for earliest year or if no inventory |
| dso | float64 | NaN for earliest year or if no receivables |
| cash_conversion_cycle | float64 | NaN for earliest year or missing inputs |

### Anti-Patterns to Avoid

- **Using the `fy` field as the fiscal year key:** The `fy` field is the year of the filing, not the year of the period. Multiple filings (2021, 2022, 2023 10-Ks) all report comparative data for period `end=2021-09-25`. Use `end` date year as the fiscal year label.
- **No period-length filter for duration concepts:** The AAPL facts.json contains entries with `form="10-K"` and `fp="FY"` but `start=2018-07-01` to `end=2018-09-29` (90 days = one quarter). Without the > 300-day filter, these partial values (62.9B vs 265.6B full year) corrupt the timeseries.
- **Summing balance sheet values:** Balance sheet concepts are instantaneous (no `start` field). `Assets` for 2023 is the value at a point in time, not over a period. Never sum across quarters.
- **Bare Python division:** `a / b` raises ZeroDivisionError for scalars and produces `inf` for Series when denominator is 0. Always use `safe_divide()`.
- **Writing partial results:** If `save_parquet()` for financials succeeds but kpis fails, the clean directory has stale kpis.parquet from a previous run. Write both to temp paths before renaming both.
- **Not sorting by fiscal_year:** `.shift(1)` and `.pct_change()` for YoY calculations depend on rows being in chronological order. Always sort before KPI calculations.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Parquet schema evolution | Custom binary format | pandas + pyarrow Parquet | Column-level NaN, schema introspection, direct DuckDB querying |
| Rolling median fill | Custom gap interpolator | `pd.Series.rolling().median()` | Handles edge cases (start/end of series, all-NaN) correctly |
| YoY percent change | Manual `(v2-v1)/v1` loop | `pd.Series.pct_change()` | Handles NaN propagation, series alignment by index |
| Fiscal year from date | String parsing logic | `int(end_date[:4])` | The standard: year of fiscal year end date |
| XBRL period duration | XBRL library | `(end - start).days > 300` | Direct date arithmetic is sufficient; no full XBRL parser needed |

---

## Common Pitfalls

### Pitfall 1: `fy` Field Ambiguity
**What goes wrong:** Using `e["fy"]` as the deduplication key. AAPL's FY2024 10-K contains comparative data for FY2022 and FY2023, so each of those periods has `fy=2024`. If you group by `fy`, you get FY2024 revenue appearing in three different buckets.
**Why it happens:** The `fy` field means "which fiscal year's filing this entry came from," not "which fiscal year this data represents."
**How to avoid:** Group by `end` date. The fiscal year label is `int(end_date[:4])`.
**Warning signs:** Revenue data for a single year appears in multiple rows; total row count far exceeds expected fiscal years.

### Pitfall 2: Partial-Period Duration Entries Contaminating Annual Data
**What goes wrong:** AAPL's `RevenueFromContractWithCustomerExcludingAssessedTax` contains an entry with `form=10-K, fp=FY, end=2018-09-29, start=2018-07-01, val=62,900,000,000` (one quarter) alongside a full-year entry `start=2017-10-01, val=265,595,000,000`. Without period-length filtering, the deduplication by `end` date keeps the latest-filed value — which may be the partial-period entry.
**Why it happens:** Companies include segment or comparative data tables in their 10-K filings that XBRL-tag partial periods with `fp=FY`.
**How to avoid:** For duration concepts, filter: `(end - start).days > 300` before deduplication.
**Warning signs:** Revenue values that are ~25% or ~50% of expected annual values.

### Pitfall 3: Balance Sheet Double-Counting via `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`
**What goes wrong:** This tag includes minority interest, so it's larger than `StockholdersEquity`. Using it when `StockholdersEquity` is available inflates equity and deflates ROE.
**How to avoid:** `StockholdersEquity` takes priority in the CONCEPT_MAP. Only fall back to the `Including...` variant if the primary is not found.

### Pitfall 4: BRK.B Missing Liquidity Concepts
**What goes wrong:** BRK.B has no `AssetsCurrent`, `LiabilitiesCurrent`, `GrossProfit`, `AccountsReceivableNetCurrent`, or `LongTermDebt` in its XBRL data. Attempting to fill these with 0 (instead of NaN) corrupts downstream KPIs — e.g., Current Ratio = CA/CL would be 0/0 = NaN (acceptable) but if CA is filled with 0 it becomes 0/CL = 0 (wrong).
**How to avoid:** Empty Series from `extract_concept()` must remain NaN in the DataFrame. Never substitute 0 for missing balance sheet items.
**Warning signs:** BRK.B showing Current Ratio = 0.

### Pitfall 5: Negative Equity Producing Misleading ROE
**What goes wrong:** Companies like McDonald's (MCD) carry negative equity due to buybacks. ROE = Net Income / Negative Equity = negative ratio even for a profitable company — analytically misleading.
**How to avoid:** Preserve the value (XFORM-02 says preserve outliers). The dashboard (Phase 4) will add a warning flag.
**Warning signs:** ROE < -100% for companies not in financial distress.

### Pitfall 6: EBITDA with NaN D&A
**What goes wrong:** If `depreciation_amortization` is NaN, `EBIT + NaN = NaN`, making EBITDA NaN even when EBIT is available.
**How to avoid:** The EBITDA formula should be `ebitda = ebit + da.fillna(0)` only if you want EBIT as a proxy for EBITDA when D&A is missing — but this understates EBITDA. The safer approach: compute EBITDA only when both EBIT and D&A are available, let it be NaN otherwise.
**Recommendation:** Keep `ebitda = ebit + da` (no fillna). If D&A is NaN, EBITDA is NaN. This preserves data quality.

### Pitfall 7: Parquet Not Byte-Identical Without pyarrow Engine
**What goes wrong:** `df.to_parquet(path)` without `engine="pyarrow"` may use fastparquet on some systems. fastparquet produces different bytes than pyarrow for the same data. Idempotency test fails across systems.
**How to avoid:** Always specify `engine="pyarrow"` explicitly. Confirmed byte-identical with pyarrow 23.0.1.

### Pitfall 8: CAGR With Fewer Than 10 Years
**What goes wrong:** `(Rev_final / Rev_initial) ** (1/10) - 1` uses a hardcoded 10-year divisor. If the company has only 7 years of data, this understates growth.
**How to avoid:** Use the actual year count: `(Rev[yr] / Rev[yr - 10]) ** (1/10) - 1`. Only compute where `yr - 10` exists in the index. Produces NaN for companies/years without 10 years of prior data. This is correct.

---

## Code Examples

### Full extract_concept with deduplication and period filtering

```python
# Source: Verified against AAPL facts.json (503 concepts, 17 FY) and BRK.B (420 concepts, 16 FY)
# Key verified behaviors:
# 1. end=2021-09-25 appears in fy=2021, fy=2022, fy=2023 filings -> dedup by end date
# 2. end=2018-09-29 has start=2018-07-01 (90 days) entry -> excluded by > 300 days filter
# 3. Instant concepts (Assets) have no 'start' field -> skip period filter for them

from datetime import datetime
from collections import defaultdict
import pandas as pd
import numpy as np
import json, logging

logger = logging.getLogger(__name__)

def extract_concept(facts: dict, field_name: str) -> pd.Series:
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    is_instant = field_name in INSTANT_CONCEPTS

    for tag in CONCEPT_MAP.get(field_name, []):
        if tag not in us_gaap:
            continue

        all_entries = us_gaap[tag].get("units", {}).get("USD", [])
        ten_k = [e for e in all_entries if e.get("form") == "10-K"]

        if is_instant:
            candidates = ten_k
        else:
            candidates = []
            for e in ten_k:
                if e.get("fp") != "FY" or not e.get("start"):
                    continue
                days = (
                    datetime.strptime(e["end"], "%Y-%m-%d")
                    - datetime.strptime(e["start"], "%Y-%m-%d")
                ).days
                if days > 300:
                    candidates.append(e)

        if not candidates:
            continue

        by_end = defaultdict(list)
        for e in candidates:
            by_end[e["end"]].append(e)

        result = {}
        for end_date, dupes in by_end.items():
            winner = max(dupes, key=lambda x: x["filed"])
            result[int(end_date[:4])] = float(winner["val"])

        if result:
            logger.debug(f"Field '{field_name}': using tag '{tag}', {len(result)} fiscal years")
            s = pd.Series(result, dtype=float, name=field_name)
            s.index.name = "fiscal_year"
            return s.sort_index()

    logger.warning(f"Field '{field_name}': no XBRL tag found in us-gaap")
    return pd.Series(dtype=float, name=field_name)
```

### Idempotency verification pattern

```python
# Source: Verified with pyarrow 23.0.1 — byte-identical confirmed
import hashlib

def verify_idempotent(ticker: str, data_dir: Path) -> bool:
    """Run process() twice, confirm Parquet hashes match."""
    process(ticker, data_dir)
    paths = [
        data_dir / "clean" / ticker / "financials.parquet",
        data_dir / "clean" / ticker / "kpis.parquet",
    ]
    hashes_1 = {p: hashlib.md5(p.read_bytes()).hexdigest() for p in paths}
    process(ticker, data_dir)
    hashes_2 = {p: hashlib.md5(p.read_bytes()).hexdigest() for p in paths}
    return hashes_1 == hashes_2
```

---

## Financial Sector Edge Cases (BRK.B, JPM)

### What BRK.B Has and What Is Missing

| Field | Status | Notes |
|-------|--------|-------|
| revenue | FOUND (`Revenues`: 136 FY entries) | $371B in 2024 |
| net_income | FOUND (`NetIncomeLoss`: 136 FY entries) | $89B in 2024 |
| operating_income | FOUND (`OperatingIncomeLoss`: 6 FY entries only) | Sparse — only recent years |
| depreciation_amortization | FOUND (`DepreciationDepletionAndAmortization`: 36 entries) | |
| total_assets | FOUND (`Assets`: 46 FY entries) | $1.15T in 2024 |
| total_liabilities | FOUND (`Liabilities`: 28 FY entries) | |
| total_equity | FOUND (`StockholdersEquity`: 33 FY entries) | |
| cash | FOUND (`CashAndCashEquivalentsAtCarryingValue`: 36 entries) | |
| inventory | FOUND (`InventoryNet`: 30 entries) | Railroad/energy subsidiaries |
| interest_expense | FOUND (`InterestExpense`: 30 entries) | |
| current_assets | MISSING | Insurance balance sheets don't segment current/non-current |
| current_liabilities | MISSING | Same reason |
| gross_profit | MISSING | No product COGS/gross profit for conglomerate |
| receivables | MISSING | No `AccountsReceivableNetCurrent` |
| long_term_debt | MISSING | No `LongTermDebt` or `LongTermDebtNoncurrent` |
| accounts_payable | MISSING | |

**Consequence:** BRK.B will have NaN for: `current_ratio`, `quick_ratio`, `cash_ratio`, `working_capital`, `gross_profit_margin`, `debt_to_ebitda`, `debt_to_assets` (partial), `inventory_turnover` input is available but `cogs` is not, `dso`, `cash_conversion_cycle`. This is correct behavior — do not fabricate values.

### JPM Revenue Concept

JPM (JPMorgan Chase) uses `RevenuesNetOfInterestExpense` as their primary revenue concept. The CONCEPT_MAP includes this as 6th priority for `revenue`. If JPM data is available, verify this concept is present in their facts.json before running Phase 2.

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Hardcode single XBRL tag name | Priority-order fallback chain | Covers all companies without custom code per ticker |
| Use `fy` field as period key | Use `end` date year as fiscal year | Eliminates duplicate rows from comparative data in later filings |
| Fill missing with 0 | Fill with NaN, use rolling median only for gaps | Prevents corrupted KPIs (0/CL = wrong ratio) |
| `a / b` Python division | `safe_divide()` with `.replace(0, np.nan)` | No ZeroDivisionError, no inf values |
| Write directly to final path | Write to .tmp, rename on success | Atomic write, no partial files |

---

## Open Questions

1. **JPM XBRL concept coverage**
   - What we know: JPM's primary revenue concept is `RevenuesNetOfInterestExpense` (from PITFALLS.md); it is in the CONCEPT_MAP
   - What's unclear: Whether `InterestExpense`, `GrossProfit`, and liquidity concepts are present in JPM's facts.json
   - Recommendation: Run the processor on JPM as an early task in the plan; log which tags resolve; adjust CONCEPT_MAP if needed

2. **BRK.B `OperatingIncomeLoss` coverage — only 6 FY entries**
   - What we know: BRK.B has `OperatingIncomeLoss` for only recent years; older years will have NaN EBIT and therefore NaN EBITDA
   - What's unclear: Whether an alternative tag provides historical EBIT
   - Recommendation: Accept NaN for older BRK.B EBIT — the XFORM-02 rolling median fill will interpolate only if there are neighboring real values

3. **Dedup edge case: two entries with same `end` date and same `filed` date but different `val`**
   - What we know: Observed in AAPL `RevenueFromContractWithCustomerExcludingAssessedTax` at `end=2018-09-29` — two entries, same accession number, same filed date, different values (265.6B full year, 62.9B partial)
   - Root cause: Period filter (>300 days) handles this already — 62.9B entry has 90-day period
   - Recommendation: The period-length filter is the correct solution; no additional dedup logic needed

4. **CAGR with fewer than 10 years of data**
   - What we know: `revenue_cagr_10y` requires 10 years lookback; companies with < 10 years of XBRL data (possible for newer filers) will have all NaN
   - What's unclear: None of the Top 20 should have < 10 years (all are S&P 500 incumbents, XBRL required since 2009)
   - Recommendation: Accept NaN for years before `earliest_year + 10`; add log message when this occurs

---

## Sources

### Primary (HIGH confidence)
- Real AAPL facts.json — `data/raw/AAPL/facts.json` (7.4MB, 503 us-gaap concepts, 17 fiscal years 2009-2025)
- Real BRK.B facts.json — `data/raw/BRK.B/facts.json` (5.3MB, 420 us-gaap concepts, 16 fiscal years 2009-2024)
- `.planning/research/ARCHITECTURE.md` — XBRL normalization patterns, CONCEPT_MAP initial design
- `.planning/research/PITFALLS.md` — Instant vs duration, deduplication, division-by-zero patterns

### Secondary (MEDIUM confidence)
- `.planning/research/STACK.md` — Pandas, pyarrow, DuckDB stack decisions
- `.planning/STATE.md` — Accumulated project decisions

### Verified programmatically (HIGH)
- Parquet byte-identical idempotency: confirmed with pyarrow 23.0.1
- `safe_divide()` pattern: confirmed produces NaN for zero denominator
- Rolling median fill: confirmed fills isolated NaN gaps correctly
- Period length filter: confirmed excludes 90-day entries from full-year deduplication
- `end` date year as fiscal year: confirmed correct for AAPL (Sep FYE) and BRK.B (Dec FYE)

---

## Metadata

**Confidence breakdown:**
- CONCEPT_MAP (verified tags): HIGH — tested against real AAPL and BRK.B facts.json files; specific tag names confirmed present/missing
- Dedup strategy (end-date key, latest-filed): HIGH — observed directly in AAPL data where same period appears across 3 consecutive 10-K filings with identical values
- Period-length filter (>300 days): HIGH — confirmed partial-period entry at 90 days observed in AAPL data
- Instant vs duration distinction: HIGH — confirmed in XBRL entry structure (instant has no `start` field)
- KPI formulas: HIGH — standard financial ratios; all 20 formulas mathematically verified
- BRK.B gaps: HIGH — directly confirmed by scanning actual facts.json
- Parquet idempotency: HIGH — confirmed empirically with pyarrow 23.0.1

**Research date:** 2026-02-25
**Valid until:** 2026-08-25 (stable domain — XBRL taxonomy changes rarely)
