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
    DEFAULT_KPIS = {"revenue_cagr_10y", "ebitda_margin", "quick_ratio", "debt_to_ebitda", "dso"}
    selected_kpis: list[str] = []
    for group_name, group_keys in KPI_GROUPS.items():
        remaining = MAX_KPIS - len(selected_kpis)
        group_default = [k for k in group_keys if k in DEFAULT_KPIS]
        expanded = bool(group_default) or group_name == "Rentabilidad"
        with st.expander(group_name, expanded=expanded):
            group_selected = st.multiselect(
                label=group_name,
                options=group_keys,
                default=group_default,
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


# ── LATAM confidence badge ────────────────────────────────────────────────────

def _latam_confidence_badge(company_slug: str, country: str, data_dir: str = "data") -> None:
    """
    Render a visible warning badge on the LATAM company card when:
    - ExtractionResult confidence == "Baja", OR
    - Any country-specific critical field is absent from kpis.parquet

    When confidence is "Baja", also renders a PDF download button so the analyst
    can open the source document and manually verify extracted values.

    Called immediately after a successful PDF upload+extraction in render_latam_upload_section().
    Degrades gracefully if kpis.parquet is missing or has no 'confidence' column.
    """
    try:
        from latam_concept_map import COUNTRY_CRITICAL_FIELDS, DEFAULT_CRITICAL_FIELDS
        import pandas as pd
        from pathlib import Path

        company_dir = Path(data_dir) / "latam" / country / company_slug
        kpis_path = company_dir / "kpis.parquet"
        if not kpis_path.exists():
            return  # No data yet — nothing to badge

        df_kpis = pd.read_parquet(kpis_path)
        if df_kpis.empty:
            return

        # Determine confidence level (stored in kpis.parquet)
        confidence = None
        if "confidence" in df_kpis.columns:
            confidence = str(df_kpis["confidence"].iloc[-1])  # most recent row

        # Determine if critical fields are missing — check financials.parquet (raw statements)
        critical_set = COUNTRY_CRITICAL_FIELDS.get(country.upper(), DEFAULT_CRITICAL_FIELDS)
        fin_path = company_dir / "financials.parquet"
        if fin_path.exists():
            present_cols = set(pd.read_parquet(fin_path).columns)
        else:
            present_cols = set()
        missing_critical = critical_set - present_cols

        show_badge = (confidence == "Baja") or bool(missing_critical)

        if show_badge:
            reason_parts = []
            if confidence == "Baja":
                reason_parts.append("Confianza de extraccion: **Baja**")
            if missing_critical:
                reason_parts.append(f"Campos criticos faltantes: {', '.join(sorted(missing_critical))}")

            st.warning(
                f"**Revisar datos** — {'; '.join(reason_parts)}. "
                f"Verifica el informe PDF antes de usar estos KPIs.",
                icon="⚠️",
            )

            # When confidence is Baja, offer access to the raw PDF for manual verification
            if confidence == "Baja":
                raw_dir = Path(data_dir) / "latam" / country / company_slug / "raw"
                pdf_files = sorted(raw_dir.glob("*.pdf")) if raw_dir.exists() else []
                if pdf_files:
                    pdf_path = pdf_files[0]
                    try:
                        pdf_bytes = pdf_path.read_bytes()
                        st.download_button(
                            label="Ver PDF original",
                            data=pdf_bytes,
                            file_name=pdf_path.name,
                            mime="application/pdf",
                            key=f"latam_pdf_download_{company_slug}_{country}",
                            help="Descarga el informe PDF para verificar los datos extraidos manualmente.",
                        )
                    except OSError:
                        pass  # PDF unreadable — skip button silently
        else:
            # Positive indicator — clean extraction
            label = {"Alta": "Alta", "Media": "Media"}.get(confidence or "", confidence or "—")
            st.info(f"Confianza de extraccion: **{label}**", icon="ℹ️")

    except ImportError:
        pass  # LATAM modules not installed — badge silently skipped
    except Exception as exc:  # noqa: BLE001
        # Never let badge failure crash the upload section
        st.caption(f"[Badge error: {exc}]")


# ── LATAM session state helpers ───────────────────────────────────────────────

def _init_latam_session_state() -> None:
    """Initialize LATAM session state keys once per session."""
    defaults = {
        "latam_companies": [],
        "latam_active_company": None,
        "latam_kpis": {},
        "latam_financials": {},
        "latam_meta": {},
        "latam_red_flags": {},
        "latam_report_text": {},
        "latam_report_pdf": {},
        "latam_pipeline_running": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── LATAM data loaders (not @st.cache_data — dynamic within session) ──────────

def _load_latam_kpis(slug: str, country: str) -> pd.DataFrame:
    path = Path(f"data/latam/{country}/{slug}/kpis.parquet")
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path, engine="pyarrow")


def _load_latam_meta(slug: str, country: str) -> dict:
    import json as _json
    path = Path(f"data/latam/{country}/{slug}/meta.json")
    if not path.exists():
        return {}
    try:
        return _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_latam_financials(slug: str, country: str) -> pd.DataFrame:
    path = Path(f"data/latam/{country}/{slug}/financials.parquet")
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path, engine="pyarrow")


# ── LATAM KPI formatting ──────────────────────────────────────────────────────

_NON_MONETARY_FORMATS = {"percentage", "ratio_x", "days"}

# Maps KPI name -> financial field name used for source_map page lookup
_KPI_TO_SOURCE_FIELD: dict[str, str] = {
    "revenue_growth_yoy": "revenue",
    "revenue_cagr_10y": "revenue",
    "gross_profit_margin": "revenue",
    "operating_margin": "revenue",
    "ebitda_margin": "revenue",
    "net_profit_margin": "net_income",
    "roe": "net_income",
    "roa": "total_assets",
    "current_ratio": "total_assets",
    "quick_ratio": "total_assets",
    "cash_ratio": "total_assets",
    "working_capital": "total_assets",
    "debt_to_equity": "long_term_debt",
    "debt_to_ebitda": "long_term_debt",
    "debt_to_assets": "long_term_debt",
}


def _format_latam_kpi_value(
    value: float,
    fmt: str,
    meta_info: dict,
) -> str:
    """Format a LATAM KPI value in local currency. No FX conversion — values are
    stored and displayed in the company's native currency (COP, BRL, MXN, etc.).
    FX only applies in the executive report generator, never in the dashboard.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    if fmt in _NON_MONETARY_FORMATS:
        return format_kpi(value, fmt)
    display_value = value
    currency_code = meta_info.get("currency_original", "—")
    # LATAM currencies use "mil M" (miles de millones) instead of "B" (billions)
    _is_latam_currency = currency_code not in ("USD", "EUR")
    _large_suffix = "mil M" if _is_latam_currency else "B"
    if fmt == "dollar_B":
        return f"{currency_code} {display_value / 1e9:.1f} {_large_suffix}"
    # Fallback for other monetary formats
    if abs(display_value) >= 1e9:
        return f"{currency_code} {display_value / 1e9:.2f} {_large_suffix}"
    if abs(display_value) >= 1e6:
        return f"{currency_code} {display_value / 1e6:.1f}M"
    return f"{currency_code} {display_value:,.0f}"


# ── LATAM rendering helpers ────────────────────────────────────────────────────

def _render_latam_kpi_cards(slug: str, country: str) -> None:
    kpis_df = st.session_state["latam_kpis"].get(slug, pd.DataFrame())
    meta = st.session_state["latam_meta"].get(slug, {})
    source_map = meta.get("source_map", {})

    if kpis_df.empty:
        st.warning("KPIs no disponibles.")
        return

    # For LATAM companies, show all KPIs that have actual data (not NaN).
    # The sidebar selected_kpis are tuned for S&P 500 (10-year CAGR, EBITDA margin, etc.)
    # which require multi-year history or fields not always present in LATAM PDFs.
    _kpi_cols = [c for c in kpis_df.columns if c not in ("ticker", "fiscal_year", "confidence")]
    _available_kpis = [k for k in _kpi_cols if kpis_df[k].notna().any()]

    # Use sidebar selection only if the user has meaningful coverage (>=2 selected KPIs
    # with actual data). Otherwise fall back to all available KPIs — the sidebar defaults
    # are tuned for S&P 500 multi-year data and rarely apply to a first LATAM PDF run.
    _selected_with_data = [k for k in selected_kpis if k in _available_kpis]
    display_kpis = _selected_with_data if len(_selected_with_data) >= 2 else _available_kpis[:10]

    n = len(display_kpis)
    if n == 0:
        st.caption("No hay KPIs disponibles con datos para esta empresa.")
        return

    df_sorted = kpis_df.sort_values("fiscal_year") if "fiscal_year" in kpis_df.columns else kpis_df

    # Rows of max 3 KPI cards each
    for row_kpis in [display_kpis[i:i+3] for i in range(0, n, 3)]:
        cols = st.columns(len(row_kpis), gap="medium")
        for col, kpi in zip(cols, row_kpis):
            with col:
                if kpi not in df_sorted.columns:
                    st.metric(label=KPI_META.get(kpi, {}).get("label", kpi), value="N/A")
                    continue

                kpi_series = df_sorted[kpi].dropna()
                latest_val = kpi_series.iloc[-1] if not kpi_series.empty else None
                prior_val = kpi_series.iloc[-2] if len(kpi_series) >= 2 else None

                delta_pct = None
                if latest_val is not None and prior_val is not None and prior_val != 0:
                    delta_pct = (latest_val - prior_val) / abs(prior_val)

                kpi_meta = KPI_META.get(kpi, {"label": kpi, "format": "ratio_x"})
                display_val = _format_latam_kpi_value(latest_val, kpi_meta["format"], meta)

                st.metric(
                    label=f"**{kpi_meta['label']}**",
                    value=display_val,
                    delta=format_delta(delta_pct),
                    delta_color="normal",
                    border=True,
                )

                source_field = _KPI_TO_SOURCE_FIELD.get(kpi)
                page = source_map.get(source_field) if source_field else None
                if page and str(page) != "?":
                    st.caption(f"fuente: pág. {page}")

                if len(df_sorted) > 1 and "fiscal_year" in df_sorted.columns and kpi in df_sorted.columns:
                    yr_min = int(df_sorted["fiscal_year"].min())
                    yr_max = int(df_sorted["fiscal_year"].max())
                    fig = build_trend_figure(df_sorted, kpi, (yr_min, yr_max), slug)
                    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


_SUMMARY_FIELDS = [
    ("revenue",           "Ingresos"),
    ("net_income",        "Utilidad Neta"),
    ("total_assets",      "Activos Totales"),
    ("total_liabilities", "Pasivos Totales"),
    ("total_equity",      "Patrimonio"),
]


def _render_latam_financials_table(slug: str, country: str) -> None:
    """Render a compact table of principal financial statement lines for all fiscal years."""
    fin_df = st.session_state["latam_financials"].get(slug, pd.DataFrame())
    meta = st.session_state["latam_meta"].get(slug, {})
    if fin_df.empty:
        return

    available = [f for f, _ in _SUMMARY_FIELDS if f in fin_df.columns]
    if not available:
        return

    # Values stored and displayed in native currency — no FX conversion in dashboard.
    display_cols: dict = {"Año": fin_df["fiscal_year"].astype(str)}
    curr_symbol = meta.get("currency_original", "USD")
    multiplier_series = pd.Series(1.0, index=fin_df.index)

    _table_large_suffix = "mil M" if curr_symbol not in ("USD", "EUR") else "B"
    for field, label in _SUMMARY_FIELDS:
        if field in fin_df.columns:
            display_cols[label] = (fin_df[field] * multiplier_series).apply(
                lambda v: (
                    f"{curr_symbol} {v/1e9:.2f} {_table_large_suffix}" if pd.notna(v) and abs(v) >= 1e9
                    else f"{curr_symbol} {v/1e6:.1f}M" if pd.notna(v) and abs(v) >= 1e6
                    else f"{curr_symbol} {v:,.0f}" if pd.notna(v)
                    else "N/A"
                )
            )

    st.markdown("#### Estados Financieros")
    st.dataframe(
        pd.DataFrame(display_cols).set_index("Año"),
        use_container_width=True,
        hide_index=False,
    )


def _render_latam_red_flags(slug: str, country: str) -> None:
    import yaml as _yaml
    red_flags = st.session_state.get("latam_red_flags", {}).get(slug, [])
    triggered_ids = {f.get("flag_id") for f in red_flags}

    _SEVERITY_ICON = {"Alta": "🔴", "Media": "🟡", "Baja": "🟢"}

    # Always show triggered flags first
    if red_flags:
        for flag in red_flags:
            icon = _SEVERITY_ICON.get(flag.get("severity", "Baja"), "⚪")
            st.markdown(f"{icon} **{flag.get('name', 'Flag')}** — {flag.get('severity', '')}")
            st.caption(flag.get("description", ""))
    else:
        st.success("Sin alertas activas en los indicadores evaluados.")

    # Always show full checklist from YAML — green for OK, colored for triggered
    try:
        cfg_path = Path("config/red_flags.yaml")
        if cfg_path.exists():
            cfg = _yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            all_flags = cfg.get("sectors", {}).get("healthcare", {}).get("flags", [])
            if all_flags:
                with st.expander("Ver todos los indicadores monitoreados", expanded=False):
                    for spec in all_flags:
                        fid = spec.get("id", "")
                        fname = spec.get("name", fid)
                        fdesc = spec.get("description", "")
                        if fid in triggered_ids:
                            matched = next((f for f in red_flags if f.get("flag_id") == fid), {})
                            icon = _SEVERITY_ICON.get(matched.get("severity", "Baja"), "⚪")
                            st.markdown(f"{icon} **{fname}** — {matched.get('severity', '')}")
                        else:
                            st.markdown(f"✅ **{fname}** — OK")
                        st.caption(fdesc)
    except Exception:
        pass


def _run_latam_pipeline(name: str, country: str, url: str, force_refresh: bool = False) -> None:
    try:
        from LatamAgent import LatamAgent
    except ImportError as e:
        st.error(f"LATAM modules not installed: {e}")
        return

    try:
        agent = LatamAgent(name=name, country=country, url=url)
        with st.spinner("Ejecutando pipeline LATAM (scraping → extracción → KPIs)..."):
            result = agent.run(force_refresh=force_refresh)

        # If Phase 10 validation left a pending extraction, validation panel handles the rest
        if st.session_state.get("latam_pending_extraction"):
            return

        # Store results in session state
        existing_slugs = {c["slug"] for c in st.session_state["latam_companies"]}
        if agent.slug not in existing_slugs:
            st.session_state["latam_companies"].append(
                {"name": name, "country": country, "slug": agent.slug, "url": url}
            )
        st.session_state["latam_active_company"] = agent.slug
        st.session_state["latam_red_flags"][agent.slug] = result.get("red_flags", [])
        st.session_state["latam_kpis"][agent.slug] = _load_latam_kpis(agent.slug, country)
        st.session_state["latam_meta"][agent.slug] = _load_latam_meta(agent.slug, country)
        st.session_state["latam_financials"][agent.slug] = _load_latam_financials(agent.slug, country)
    except Exception as e:
        st.error(f"Error en pipeline LATAM: {e}")


def _generate_and_cache_report(slug: str, country: str) -> None:
    try:
        import report_generator
    except ImportError as e:
        st.error(f"report_generator not available: {e}")
        return

    kpis_df = st.session_state["latam_kpis"].get(slug, pd.DataFrame())
    meta = st.session_state["latam_meta"].get(slug, {})
    kpis_dict = kpis_df.iloc[-1].dropna().to_dict() if not kpis_df.empty else {}
    red_flags = st.session_state["latam_red_flags"].get(slug, [])
    company_info = {
        "name": meta.get("name", slug),
        "country": country,
        "currency_original": meta.get("currency_original", "USD"),
        "fiscal_year": meta.get("fiscal_year", 0),
    }

    with st.spinner("Obteniendo empresas comparables..."):
        comparables = report_generator.fetch_comparables(meta.get("name", slug), country)

    with st.spinner("Generando reporte con Claude API (claude-opus-4-6)..."):
        report_text = report_generator.generate_executive_report(
            kpis_dict, red_flags, comparables, company_info
        )

    st.session_state["latam_report_text"][slug] = report_text

    with st.spinner("Generando PDF..."):
        pdf_bytes = report_generator.build_pdf_bytes(
            report_text, meta.get("name", slug), country, meta.get("fiscal_year", 0)
        )
    st.session_state["latam_report_pdf"][slug] = pdf_bytes
    st.rerun()


_SYN_CACHE_FILE = Path("data/latam/learned_suggestions_cache.json")


def _load_syn_cache() -> dict[str, str]:
    if not _SYN_CACHE_FILE.exists():
        return {}
    try:
        import json as _json
        return _json.loads(_SYN_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_syn_cache(cache: dict[str, str]) -> None:
    try:
        import json as _json
        _SYN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SYN_CACHE_FILE.write_text(
            _json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _render_synonym_panel() -> None:
    """Render the 'Terminología Aprendida' collapsible panel inside the LATAM tab.

    Claude auto-assigns all new candidates once and persists to a cache file —
    zero tokens spent on repeat opens. The analyst uses a single search box to
    look up any label and correct its assignment if needed.
    """
    with st.expander("Terminología Aprendida", expanded=False):
        try:
            from latam_synonym_reviewer import (
                get_review_candidates,
                suggest_mapping,
                approve_synonym,
            )
        except ImportError:
            st.info("Módulo latam_synonym_reviewer no disponible.")
            return

        candidates = get_review_candidates(min_seen_count=1)
        cache = _load_syn_cache()

        # Auto-suggest deshabilitado — evita consumo de tokens en revisión de sinónimos.
        # Para activar: descomentar el bloque y ejecutar manualmente desde este panel.
        # uncached = [c for c in candidates if c.label.strip().lower() not in cache]
        # if uncached:
        #     for cand in uncached:
        #         result = suggest_mapping(cand)
        #         cache[cand.label.strip().lower()] = result.canonical or ""
        #     _save_syn_cache(cache)

        total = len(cache)
        if total == 0:
            st.success("No hay etiquetas registradas aún.")
            return

        st.caption(f"{total} etiqueta(s) en registro. Escribe una para revisar o corregir su asignación.")

        # ── Single lookup box ─────────────────────────────────────────────────
        search = st.text_input(
            "Buscar etiqueta",
            key="latam_syn_search",
            placeholder="Escribe parte de la etiqueta del PDF...",
            label_visibility="collapsed",
        )

        if not search.strip():
            return

        search_lower = search.strip().lower()
        matches = {lbl: canon for lbl, canon in cache.items() if search_lower in lbl}

        if not matches:
            st.warning("No se encontró esa etiqueta en el registro.")
            return

        for lbl, assigned in matches.items():
            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown(f"**{lbl}**")
                st.caption(f"Asignado: `{assigned or 'sin asignar'}`")
            with col2:
                import json as _json
                correction = st.text_input(
                    "Nuevo campo canónico",
                    value=assigned,
                    key=f"latam_syn_fix_{lbl}",
                    placeholder="ej: net_income",
                )
                if st.button("Confirmar", key=f"latam_syn_confirm_{lbl}", type="primary"):
                    val = correction.strip()
                    if val:
                        approve_synonym(lbl, val, approved_by="user")
                        cache[lbl] = val
                        _save_syn_cache(cache)
                        st.success(f"Guardado: `{lbl}` → `{val}`")
                        st.rerun()


def _auto_load_existing_latam() -> None:
    """Scan data/latam/ and auto-populate session_state with companies that already have data.

    Runs once per session (skips slugs already in latam_companies).
    This allows the dashboard to show existing data without re-running the pipeline.
    """
    base = Path("data/latam")
    if not base.exists():
        return
    already_loaded = {c["slug"] for c in st.session_state.get("latam_companies", [])}
    for country_dir in sorted(base.iterdir()):
        if not country_dir.is_dir():
            continue
        country = country_dir.name  # e.g. "co", "br"
        if country in ("test",):
            continue
        for company_dir in sorted(country_dir.iterdir()):
            if not company_dir.is_dir():
                continue
            slug = company_dir.name
            if slug in already_loaded:
                continue
            if not (company_dir / "meta.json").exists() or not (company_dir / "kpis.parquet").exists():
                continue
            try:
                meta = _load_latam_meta(slug, country)
                kpis_df = _load_latam_kpis(slug, country)
                if kpis_df.empty:
                    continue
                fin_df = _load_latam_financials(slug, country)
                st.session_state["latam_companies"].append({
                    "name": meta.get("name", slug),
                    "country": country,
                    "slug": slug,
                    "url": meta.get("url", ""),
                })
                st.session_state["latam_kpis"][slug] = kpis_df
                st.session_state["latam_meta"][slug] = meta
                st.session_state["latam_financials"][slug] = fin_df
                # Re-evaluate red flags from parquet
                try:
                    from red_flags import evaluate_flags as _eval_flags
                    flags = _eval_flags(kpis_df, fin_df)
                    st.session_state["latam_red_flags"][slug] = [vars(f) for f in flags]
                except Exception:
                    st.session_state["latam_red_flags"][slug] = []
                already_loaded.add(slug)
            except Exception:
                continue


def _render_latam_tab() -> None:
    _auto_load_existing_latam()
    st.markdown("### Análisis Financiero LATAM")

    # --- Input section ---
    col_url, col_country, col_btn = st.columns([3, 1, 1])
    with col_url:
        latam_url = st.text_input(
            "URL o dominio corporativo",
            placeholder="https://empresa.com",
            key="latam_url_input",
            label_visibility="visible",
        )
    with col_country:
        latam_country = st.selectbox(
            "País",
            options=["CO", "BR", "MX", "AR", "CL", "PE"],
            key="latam_country_select",
        )
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        run_clicked = st.button("Ejecutar", key="latam_run_btn", use_container_width=True)

    # PDF upload alternative
    uploaded_pdf = st.file_uploader(
        "O arrastra un PDF directamente",
        type=["pdf"],
        key="latam_pdf_upload",
        help="Si el scraper falla, sube el PDF del reporte anual manualmente.",
    )

    # Company name (required for both URL and PDF paths)
    latam_name = st.text_input(
        "Nombre de la empresa",
        placeholder="Ej: Clínica Las Américas",
        key="latam_name_input",
    )

    # Validation panel — Phase 10 pending extraction intercept
    if st.session_state.get("latam_pending_extraction"):
        try:
            from latam_validation import render_latam_validation_panel
            render_latam_validation_panel(
                extraction_result=st.session_state["latam_pending_extraction"],
                company=st.session_state.get("latam_pending_company", {}),
            )
        except ImportError:
            pass

    # Discard rerun flow
    if st.session_state.get("latam_show_rerun"):
        st.info("Extracción descartada. No se escribió ningún dato.")
        if st.button("Volver a extraer", key="latam_rerun_btn"):
            del st.session_state["latam_show_rerun"]
            st.rerun()

    # Handle Run button
    if run_clicked and latam_name:
        if not latam_url and not uploaded_pdf:
            st.warning("Ingresa una URL corporativa o sube un PDF.")
        elif uploaded_pdf and not latam_url:
            try:
                from company_registry import make_slug
                slug = make_slug(latam_name)
                raw_dir = Path("data/latam") / latam_country / slug / "raw"
                raw_dir.mkdir(parents=True, exist_ok=True)
                pdf_dest = raw_dir / uploaded_pdf.name
                pdf_dest.write_bytes(uploaded_pdf.read())
                _run_latam_pipeline(latam_name, latam_country, str(pdf_dest), force_refresh=True)
            except Exception as e:
                st.error(f"Error al procesar PDF: {e}")
        else:
            _run_latam_pipeline(latam_name, latam_country, latam_url)

    st.divider()

    # --- Company selector ---
    companies = st.session_state.get("latam_companies", [])
    if not companies:
        st.info(
            "Ingresa una URL corporativa o sube un PDF y haz clic en 'Ejecutar' "
            "para analizar una empresa LATAM."
        )
        # Still render synonym panel — candidates may exist from a previous session
        st.divider()
        _render_synonym_panel()
        return

    company_options = {f"{c['name']} ({c['country']})": c["slug"] for c in companies}
    selected_label = st.selectbox(
        "Empresa LATAM activa",
        options=list(company_options.keys()),
        key="latam_company_selector",
    )
    active_slug = company_options[selected_label]
    active_company = next((c for c in companies if c["slug"] == active_slug), {})
    active_country = active_company.get("country", "CO")

    meta = st.session_state["latam_meta"].get(active_slug, {})
    if meta.get("currency_original") == "ARS":
        st.warning(
            "ARS muestra alta volatilidad cambiaria — los valores pueden diferir significativamente "
            "al convertir a USD.",
            icon="⚠️",
        )
    elif meta.get("currency_original"):
        curr = meta["currency_original"]
        st.caption(f"Moneda: {curr}")

    # Confidence badge
    _latam_confidence_badge(active_slug, active_country)

    # --- KPI cards (DASHL-02, DASHL-04) ---
    st.markdown("#### KPIs Financieros")
    kpis_df = st.session_state["latam_kpis"].get(active_slug, pd.DataFrame())
    if kpis_df.empty:
        st.warning("KPIs no disponibles. Ejecuta el pipeline primero.")
    else:
        # Note: if long_term_debt was not extractable from the PDF, Deuda/EBITDA
        # and Deuda/Activos se calculan usando pasivos no corrientes
        # (total_liabilities − current_liabilities) como aproximación.
        fin_df = st.session_state["latam_financials"].get(active_slug, pd.DataFrame())
        if not fin_df.empty and fin_df.get("long_term_debt", pd.Series([None])).isna().all():
            st.info(
                "ℹ️ **Deuda LP no identificada en el PDF.** "
                "Los KPIs de solvencia (Deuda/EBITDA, Deuda/Activos) se calcularon usando "
                "los **pasivos no corrientes** (Pasivo Total − Pasivo Corriente) como estimación de deuda de largo plazo.",
                icon=None,
            )
        _render_latam_kpi_cards(active_slug, active_country)
        _render_latam_financials_table(active_slug, active_country)

    # --- Red flags ---
    st.markdown("#### Red Flags")
    _render_latam_red_flags(active_slug, active_country)

    # --- Executive report ---
    st.markdown("#### Reporte Ejecutivo")
    if st.button("Generar Reporte", key="latam_generate_report_btn"):
        _generate_and_cache_report(active_slug, active_country)

    report_text = st.session_state.get("latam_report_text", {}).get(active_slug)
    if report_text:
        st.markdown(report_text)
        report_pdf = st.session_state.get("latam_report_pdf", {}).get(active_slug)
        if report_pdf:
            st.download_button(
                label="Descargar PDF",
                data=report_pdf,
                file_name=f"reporte_{active_slug}.pdf",
                mime="application/pdf",
                key="latam_download_pdf",
            )

    # --- Learned synonyms review panel ---
    st.divider()
    _render_synonym_panel()


# ── Tabbed layout: S&P 500 | LATAM ───────────────────────────────────────────
st.markdown("""
<style>
/* Tab bar background — blue gradient strip */
.stTabs [data-baseweb="tab-list"] {
    background: linear-gradient(90deg, #1f4e79 0%, #2d6a9f 100%);
    border-radius: 10px 10px 0 0;
    padding: 0 1rem;
    gap: 0;
}
/* Individual tab labels — muted on inactive */
.stTabs [data-baseweb="tab"] {
    color: #b8d4f0 !important;
    font-weight: 600;
    font-size: 0.95rem;
    letter-spacing: 0.04em;
    border-radius: 8px 8px 0 0;
    padding: 0.65rem 1.4rem;
    border: none !important;
    background: transparent !important;
}
/* Active tab — near-white chip on the blue bar */
.stTabs [aria-selected="true"] {
    color: #1f4e79 !important;
    background: rgba(255,255,255,0.92) !important;
    border-bottom: none !important;
}
/* Override any Streamlit default underline/indicator */
.stTabs [data-baseweb="tab-highlight"] {
    display: none !important;
}
/* Hover */
.stTabs [data-baseweb="tab"]:hover {
    color: #ffffff !important;
    background: rgba(255,255,255,0.12) !important;
}
/* Tab content panel */
.stTabs [data-baseweb="tab-panel"] {
    padding-top: 1.2rem;
}
</style>
""", unsafe_allow_html=True)

tab_sp500, tab_latam = st.tabs(["📊  S&P 500", "🌎  LATAM"])

with tab_sp500:
    # ── Page header bar ───────────────────────────────────────────────────────
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

    # ── Ticker search ──────────────────────────────────────────────────────────
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

with tab_latam:
    _init_latam_session_state()
    _render_latam_tab()
