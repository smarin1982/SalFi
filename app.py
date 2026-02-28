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


# ── Session state initialization ─────────────────────────────────────────────
if "loaded_tickers" not in st.session_state:
    st.session_state.loaded_tickers = ["HD", "PG"]

# ── Page header bar ───────────────────────────────────────────────────────────
st.markdown("""
<div style="
    background: linear-gradient(90deg, #1f4e79 0%, #2d6a9f 100%);
    padding: 1.2rem 2rem;
    border-radius: 10px;
    margin-bottom: 1.2rem;
    text-align: center;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
">
    <h1 style="color: #ffffff; margin: 0; font-size: 2rem; font-weight: 700; letter-spacing: 0.02em;">
        S&P 500 KPI Dashboard
    </h1>
    <p style="color: #b8d4f0; margin: 0.3rem 0 0 0; font-size: 0.85rem; letter-spacing: 0.05em;">
        Datos oficiales 10-K &nbsp;·&nbsp; SEC EDGAR &nbsp;·&nbsp; Años fiscales 2007–2025
    </p>
</div>
""", unsafe_allow_html=True)

# ── Ticker search — main area, below header ────────────────────────────────
with st.container():
    st.markdown("""
    <p style="font-size:0.8rem; color:#666; margin-bottom:0.3rem; font-weight:600; letter-spacing:0.06em; text-transform:uppercase;">
        Agregar compañía al análisis
    </p>
    """, unsafe_allow_html=True)
    col_input, col_btn, col_msg = st.columns([2, 0.6, 3])
    with col_input:
        new_ticker_input = st.text_input(
            "Ticker",
            placeholder="Ej: AAPL, MSFT, TSLA…",
            key="new_ticker_input",
            label_visibility="collapsed",
        ).upper().strip()
    with col_btn:
        load_clicked = st.button("Cargar", key="load_ticker_btn", use_container_width=True)
    with col_msg:
        if load_clicked and new_ticker_input:
            if new_ticker_input in st.session_state.loaded_tickers:
                st.info(f"{new_ticker_input} ya está cargado.")
            else:
                with st.spinner(f"Ejecutando ETL para {new_ticker_input}…"):
                    try:
                        import agent as financial_agent
                        fa = financial_agent.FinancialAgent(new_ticker_input)
                        fa.run()
                        st.session_state.loaded_tickers.append(new_ticker_input)
                        st.cache_data.clear()
                        st.success(f"✓ {new_ticker_input} cargado.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error: {exc}")

st.divider()

# Company selector — horizontal radio
company_mode = st.radio(
    label="Compañía",
    options=st.session_state.loaded_tickers + ["Comparativo"],
    horizontal=True,
    index=0,
    label_visibility="collapsed",
)
st.divider()

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    # Sidebar header
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #1f4e79 0%, #2d6a9f 100%);
        padding: 0.9rem 1rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        text-align: center;
    ">
        <p style="color:#ffffff; margin:0; font-size:0.75rem; letter-spacing:0.1em; text-transform:uppercase; font-weight:700;">
            Panel de Control
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Year range slider (DASH-02)
    st.markdown("**Rango de años**")
    year_range: tuple[int, int] = st.slider(
        "Rango de años",
        min_value=2007,
        max_value=2025,
        value=(2015, 2025),
        step=1,
        help="Restringe todos los gráficos al rango seleccionado",
        label_visibility="collapsed",
    )

    st.markdown("---")

    # KPI section title
    st.markdown("""
    <div style="
        background: #f0f4f8;
        border-left: 4px solid #1f4e79;
        padding: 0.5rem 0.8rem;
        border-radius: 0 6px 6px 0;
        margin-bottom: 0.8rem;
    ">
        <p style="margin:0; font-size:0.8rem; font-weight:700; color:#1f4e79; letter-spacing:0.05em; text-transform:uppercase;">
            Indicadores KPI
        </p>
        <p style="margin:0; font-size:0.7rem; color:#666;">Selecciona hasta 5</p>
    </div>
    """, unsafe_allow_html=True)

    # KPI selection: one expander per category, per-group multiselect
    selected_kpis: list[str] = []
    for group_name, group_keys in KPI_GROUPS.items():
        remaining = MAX_KPIS - len(selected_kpis)
        expanded = group_name == "Rentabilidad"
        with st.expander(group_name, expanded=expanded):
            group_selected = st.multiselect(
                label=group_name,
                options=group_keys,
                default=[],
                format_func=lambda k: KPI_META[k]["label"],
                label_visibility="collapsed",
                max_selections=min(remaining, len(group_keys)),
                key=f"kpi_{group_name}",
            )
            selected_kpis.extend(group_selected)

    if len(selected_kpis) == 0:
        st.caption("Selecciona al menos un KPI para ver los datos.")


# ── Chart builders ────────────────────────────────────────────────────────────

def build_trend_figure(
    df: pd.DataFrame,
    kpi: str,
    year_range: tuple[int, int],
    ticker: str,
) -> go.Figure:
    """Single-company Plotly trend chart. Bloomberg-minimal chrome."""
    meta = KPI_META[kpi]
    filtered = df[
        (df["fiscal_year"] >= year_range[0]) & (df["fiscal_year"] <= year_range[1])
    ].copy()
    color = COMPANY_COLORS.get(ticker, "#4a4a4a")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=filtered["fiscal_year"],
        y=filtered[kpi],
        mode="lines+markers",
        line=dict(color=color, width=2.5),
        marker=dict(size=5),
        hovertemplate=f"%{{x}}: %{{y:{meta['tick_format']}}}<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_white",
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
        hovermode="x unified",
        height=200,
    )
    fig.update_xaxes(showgrid=False, tickformat="d", dtick=2)
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False, tickformat=meta["tick_format"])
    return fig


def build_comparativo_figure(
    dfs: dict[str, pd.DataFrame],
    kpi: str,
    year_range: tuple[int, int],
) -> go.Figure:
    """Multi-company overlay — one trace per loaded ticker on same figure (DASH-01 Comparativo mode)."""
    # Extended color palette for additional tickers beyond HD/PG
    _EXTRA_COLORS = ["#c0392b", "#8e44ad", "#e67e22", "#16a085", "#2c3e50"]
    meta = KPI_META[kpi]
    fig = go.Figure()
    tickers = list(dfs.keys())
    for idx, ticker in enumerate(tickers):
        df = dfs[ticker]
        color = COMPANY_COLORS.get(ticker, _EXTRA_COLORS[idx % len(_EXTRA_COLORS)])
        d = df[
            (df["fiscal_year"] >= year_range[0]) & (df["fiscal_year"] <= year_range[1])
        ]
        fig.add_trace(go.Scatter(
            x=d["fiscal_year"],
            y=d[kpi],
            name=ticker,
            mode="lines+markers",
            line=dict(color=color, width=2.5),
            marker=dict(size=5),
            hovertemplate=f"{ticker} %{{x}}: %{{y:{meta['tick_format']}}}<extra></extra>",
        ))
    fig.update_layout(
        template="plotly_white",
        title=dict(text=meta["label"], font=dict(size=14, color="#333")),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
        margin=dict(l=0, r=0, t=50, b=0),
        height=260,
    )
    fig.update_xaxes(showgrid=False, tickformat="d", dtick=2)
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False, tickformat=meta["tick_format"])
    return fig


def render_kpi_card(
    kpi: str,
    df: pd.DataFrame,
    year_range: tuple[int, int],
    ticker: str,
) -> None:
    """
    Executive Card = headline label + big number (latest) + delta pill (YoY %) + Plotly trend chart.
    Uses st.metric for headline/number/delta, then st.plotly_chart for trend.
    """
    meta = KPI_META[kpi]
    col_data = df[kpi].dropna() if kpi in df.columns else pd.Series(dtype=float)

    # Filter to year_range for display
    df_filtered = df[
        (df["fiscal_year"] >= year_range[0]) & (df["fiscal_year"] <= year_range[1])
    ]
    col_filtered = df_filtered[kpi].dropna() if kpi in df_filtered.columns else pd.Series(dtype=float)

    latest_val = col_filtered.iloc[-1] if not col_filtered.empty else None
    prior_val = col_filtered.iloc[-2] if len(col_filtered) >= 2 else None

    if latest_val is not None and prior_val is not None and prior_val != 0:
        delta_pct = (latest_val - prior_val) / abs(prior_val)
    else:
        delta_pct = None

    # Big Number and Delta Pill via st.metric
    st.metric(
        label=f"**{meta['label']}**",
        value=format_kpi(latest_val, meta["format"]),
        delta=format_delta(delta_pct),
        delta_color="normal",  # green=positive, red=negative
        border=True,
    )

    # Historical Trend via Plotly (NOT st.metric sparkline — use Plotly for Bloomberg aesthetic)
    if not col_data.empty:
        fig = build_trend_figure(df, kpi, year_range, ticker)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    else:
        st.caption("Sin datos disponibles.")


# ── Main canvas ───────────────────────────────────────────────────────────────
if not selected_kpis:
    st.info("Selecciona KPIs en la barra lateral para comenzar el análisis.")
else:
    n = len(selected_kpis)

    if company_mode == "Comparativo":
        # Comparativo mode: overlay all loaded tickers on same figure per KPI
        dfs_comp = {t: load_kpis(t) for t in st.session_state.loaded_tickers}
        dfs_comp = {t: df for t, df in dfs_comp.items() if not df.empty}
        if not dfs_comp:
            st.error("No se encontraron datos. Ejecuta el ETL primero.")
        else:
            # Same dynamic grid as single-company mode
            if n == 5:
                # 2+3 layout: two separate row calls
                row1 = st.columns(2, gap="medium")
                for i in range(2):
                    with row1[i]:
                        fig = build_comparativo_figure(dfs_comp, selected_kpis[i], year_range)
                        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                row2 = st.columns(3, gap="medium")
                for i in range(3):
                    with row2[i]:
                        fig = build_comparativo_figure(dfs_comp, selected_kpis[2 + i], year_range)
                        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            else:
                cols = st.columns(n if n <= 4 else 4, gap="medium")
                for i, kpi in enumerate(selected_kpis):
                    with cols[i % len(cols)]:
                        fig = build_comparativo_figure(dfs_comp, kpi, year_range)
                        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    else:
        # Single-company mode: HD or PG
        ticker = company_mode  # "HD" or "PG"
        df = load_kpis(ticker)
        if df.empty:
            st.error(f"No se encontraron datos para {ticker}. Ejecuta el ETL primero.")
        else:
            if n == 1:
                render_kpi_card(selected_kpis[0], df, year_range, ticker)
            elif n == 5:
                # 2+3 layout: two row calls
                row1 = st.columns(2, gap="medium")
                for i in range(2):
                    with row1[i]:
                        render_kpi_card(selected_kpis[i], df, year_range, ticker)
                row2 = st.columns(3, gap="medium")
                for i in range(3):
                    with row2[i]:
                        render_kpi_card(selected_kpis[2 + i], df, year_range, ticker)
            else:
                # 2, 3, or 4 KPIs: n equal columns
                cols = st.columns(n, gap="medium")
                for i, kpi in enumerate(selected_kpis):
                    with cols[i]:
                        render_kpi_card(kpi, df, year_range, ticker)
