"""
tests/test_kpi_registry.py — RED phase: these fail until KPI_REGISTRY is added to processor.py
"""
import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import processor

# Minimal financials DataFrame matching processor.py schema (2 fiscal years)
def _make_df(ticker="TEST"):
    return pd.DataFrame({
        "ticker": [ticker, ticker],
        "fiscal_year": [2023, 2024],
        "revenue": [100e9, 110e9],
        "gross_profit": [40e9, 44e9],
        "operating_income": [25e9, 27e9],
        "net_income": [20e9, 22e9],
        "depreciation_amortization": [5e9, 5.5e9],
        "total_equity": [50e9, 55e9],
        "total_assets": [200e9, 220e9],
        "current_assets": [80e9, 88e9],
        "current_liabilities": [40e9, 44e9],
        "cash": [20e9, 22e9],
        "short_term_investments": [10e9, 11e9],
        "receivables": [15e9, 16.5e9],
        "inventory": [5e9, 5.5e9],
        "long_term_debt": [90e9, 99e9],
        "short_term_debt": [10e9, 11e9],
        "total_liabilities": [150e9, 165e9],
        "interest_expense": [3e9, 3.3e9],
        "accounts_payable": [8e9, 8.8e9],
        "cogs": [60e9, 66e9],
        "operating_cash_flow": [30e9, 33e9],
        "capex": [8e9, 8.8e9],
        "shares_outstanding": [15e9, 14.8e9],
    })

def test_registry_has_20_kpis():
    """KPI_REGISTRY must exist and contain exactly 20 entries."""
    assert hasattr(processor, "KPI_REGISTRY"), "processor.KPI_REGISTRY not found"
    assert len(processor.KPI_REGISTRY) == 20, (
        f"Expected 20 KPIs, got {len(processor.KPI_REGISTRY)}: {list(processor.KPI_REGISTRY.keys())}"
    )

def test_bad_kpi_does_not_fail_others():
    """A KPI lambda that raises must not abort the loop — all other KPIs still produce output."""
    # Temporarily inject a bad KPI
    original = dict(processor.KPI_REGISTRY)
    processor.KPI_REGISTRY["_bad_test_kpi"] = lambda d: 1 / 0  # ZeroDivisionError
    try:
        df = _make_df()
        result = processor.calculate_kpis(df)
        # The bad KPI column must be NaN, not missing entirely
        assert "_bad_test_kpi" in result.columns, "Bad KPI column missing from output"
        assert result["_bad_test_kpi"].isna().all(), "Bad KPI must be all-NaN"
        # All original 20 KPIs must still be present
        for kpi in original:
            assert kpi in result.columns, f"KPI '{kpi}' missing after bad KPI injection"
    finally:
        # Restore registry
        processor.KPI_REGISTRY.clear()
        processor.KPI_REGISTRY.update(original)

def test_output_schema():
    """calculate_kpis() output must have ticker, fiscal_year, and all 20 KPI columns."""
    df = _make_df()
    result = processor.calculate_kpis(df)
    assert "ticker" in result.columns
    assert "fiscal_year" in result.columns
    assert len(result) == 2, f"Expected 2 rows (one per FY), got {len(result)}"
    kpi_cols = [c for c in result.columns if c not in ("ticker", "fiscal_year")]
    assert len(kpi_cols) == 20, f"Expected 20 KPI columns, got {len(kpi_cols)}: {kpi_cols}"

def test_registry_output_matches_inline():
    """After refactor, calculate_kpis() output for a known DataFrame must be numerically stable."""
    df = _make_df()
    result = processor.calculate_kpis(df)
    # Spot-check gross_profit_margin for 2024: 44e9 / 110e9 = 0.4
    row_2024 = result[result["fiscal_year"] == 2024].iloc[0]
    assert abs(row_2024["gross_profit_margin"] - 0.4) < 1e-9, (
        f"gross_profit_margin mismatch: {row_2024['gross_profit_margin']}"
    )
    # Spot-check net_profit_margin for 2024: 22e9 / 110e9 = 0.2
    assert abs(row_2024["net_profit_margin"] - 0.2) < 1e-9
