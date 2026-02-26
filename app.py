"""
S&P 500 KPI Dashboard — Phase 4
Bloomberg/FT-style executive dashboard for HD and PG financial KPIs.
Single-file Streamlit app. Run: streamlit run app.py
"""
from __future__ import annotations
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ── MUST be first st.* call ──────────────────────────────────────────────────
st.set_page_config(
    page_title="S&P 500 KPI Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Set global Plotly template — applies to all figures in this session
pio.templates.default = "plotly_white"

# ── Company colors (Bloomberg-sober palette) ─────────────────────────────────
COMPANY_COLORS: dict[str, str] = {
    "HD": "#1f4e79",   # dark navy blue
    "PG": "#2e7d32",   # dark forest green
}

# ── KPI Metadata Registry ────────────────────────────────────────────────────
# Keys match KPI_REGISTRY in processor.py exactly.
# format: "percentage" | "ratio_x" | "dollar_B" | "days"
# category: used for sidebar grouping via st.expander
KPI_META: dict[str, dict] = {
    # Crecimiento (Growth)
    "revenue_growth_yoy": {
        "label": "Revenue Growth YoY",
        "format": "percentage",
        "tick_format": ".1%",
        "category": "Crecimiento",
    },
    "revenue_cagr_10y": {
        "label": "Revenue CAGR (10Y)",
        "format": "percentage",
        "tick_format": ".1%",
        "category": "Crecimiento",
    },
    # Rentabilidad (Profitability)
    "gross_profit_margin": {
        "label": "Gross Margin",
        "format": "percentage",
        "tick_format": ".1%",
        "category": "Rentabilidad",
    },
    "operating_margin": {
        "label": "Operating Margin",
        "format": "percentage",
        "tick_format": ".1%",
        "category": "Rentabilidad",
    },
    "net_profit_margin": {
        "label": "Net Margin",
        "format": "percentage",
        "tick_format": ".1%",
        "category": "Rentabilidad",
    },
    "ebitda_margin": {
        "label": "EBITDA Margin",
        "format": "percentage",
        "tick_format": ".1%",
        "category": "Rentabilidad",
    },
    "roe": {
        "label": "Return on Equity (ROE)",
        "format": "percentage",
        "tick_format": ".1%",
        "category": "Rentabilidad",
    },
    "roa": {
        "label": "Return on Assets (ROA)",
        "format": "percentage",
        "tick_format": ".1%",
        "category": "Rentabilidad",
    },
    # Liquidez (Liquidity)
    "current_ratio": {
        "label": "Current Ratio",
        "format": "ratio_x",
        "tick_format": ".2f",
        "category": "Liquidez",
    },
    "quick_ratio": {
        "label": "Quick Ratio",
        "format": "ratio_x",
        "tick_format": ".2f",
        "category": "Liquidez",
    },
    "cash_ratio": {
        "label": "Cash Ratio",
        "format": "ratio_x",
        "tick_format": ".2f",
        "category": "Liquidez",
    },
    "working_capital": {
        "label": "Working Capital",
        "format": "dollar_B",
        "tick_format": ".1f",
        "category": "Liquidez",
    },
    # Solvencia (Solvency / Leverage)
    "debt_to_equity": {
        "label": "Debt / Equity",
        "format": "ratio_x",
        "tick_format": ".2f",
        "category": "Solvencia",
    },
    "debt_to_ebitda": {
        "label": "Debt / EBITDA",
        "format": "ratio_x",
        "tick_format": ".2f",
        "category": "Solvencia",
    },
    "interest_coverage": {
        "label": "Interest Coverage",
        "format": "ratio_x",
        "tick_format": ".1f",
        "category": "Solvencia",
    },
    "debt_to_assets": {
        "label": "Debt / Assets",
        "format": "percentage",
        "tick_format": ".1%",
        "category": "Solvencia",
    },
    # Eficiencia (Efficiency)
    "asset_turnover": {
        "label": "Asset Turnover",
        "format": "ratio_x",
        "tick_format": ".2f",
        "category": "Eficiencia",
    },
    "inventory_turnover": {
        "label": "Inventory Turns",
        "format": "ratio_x",
        "tick_format": ".1f",
        "category": "Eficiencia",
    },
    "dso": {
        "label": "Days Sales Outstanding",
        "format": "days",
        "tick_format": ".0f",
        "category": "Eficiencia",
    },
    "cash_conversion_cycle": {
        "label": "Cash Conversion Cycle",
        "format": "days",
        "tick_format": ".0f",
        "category": "Eficiencia",
    },
}

# ── KPI category grouping for sidebar (order matters for display) ─────────────
KPI_GROUPS: dict[str, list[str]] = {
    "Crecimiento": ["revenue_growth_yoy", "revenue_cagr_10y"],
    "Rentabilidad": ["gross_profit_margin", "operating_margin", "net_profit_margin",
                     "ebitda_margin", "roe", "roa"],
    "Liquidez": ["current_ratio", "quick_ratio", "cash_ratio", "working_capital"],
    "Solvencia": ["debt_to_equity", "debt_to_ebitda", "interest_coverage", "debt_to_assets"],
    "Eficiencia": ["asset_turnover", "inventory_turnover", "dso", "cash_conversion_cycle"],
}

MAX_KPIS = 5  # Global max — enforced in app logic, not per-widget

# ── Cached data loaders ──────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_kpis(ticker: str) -> pd.DataFrame:
    """Load kpis.parquet for a ticker. Cache keyed on ticker string."""
    path = Path(f"data/clean/{ticker}/kpis.parquet")
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path, engine="pyarrow")


@st.cache_data(ttl=3600)
def get_available_tickers() -> list[str]:
    """Return sorted list of tickers with existing kpis.parquet files."""
    return sorted([p.parent.name for p in Path("data/clean").glob("*/kpis.parquet")])


# ── KPI value formatting ──────────────────────────────────────────────────────

def format_kpi(value: float, fmt: str) -> str:
    """
    Format a KPI value for display in the Big Number position.
    Returns "N/A" for NaN or None.
    fmt: "percentage" | "ratio_x" | "dollar_B" | "days"
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    if fmt == "percentage":
        return f"{value * 100:+.1f}%" if value < 0 else f"{value * 100:.1f}%"
    if fmt == "ratio_x":
        return f"{value:.2f}x"
    if fmt == "dollar_B":
        return f"${value / 1e9:.1f}B"
    if fmt == "days":
        return f"{value:.0f}d"
    return str(round(value, 4))


def format_delta(delta_pct: float | None) -> str | None:
    """Format delta percentage for st.metric delta param. Returns None if unavailable."""
    if delta_pct is None or pd.isna(delta_pct):
        return None
    return f"{delta_pct * 100:+.1f}%"


# ── Placeholder for rendering and layout (filled in Plan 04-02) ──────────────
# The app renders its UI in Plan 04-02. This file is valid to import as-is.

if __name__ == "__main__":
    st.info("Run with: streamlit run app.py")
