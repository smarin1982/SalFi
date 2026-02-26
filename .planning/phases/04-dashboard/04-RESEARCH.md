# Phase 4: Dashboard - Research

**Researched:** 2026-02-26
**Domain:** Streamlit 1.54 + Plotly 6.5 financial dashboard
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Framework: Streamlit (single-page app, `app.py` entry point)
- Charts: Plotly with `plotly_white` template (clean financial look)
- Data sources: `data/clean/HD/kpis.parquet` and `data/clean/PG/kpis.parquet` (Phase 3 output)
- Performance: `@st.cache_data` for all Parquet reads
- Layout: `st.set_page_config(layout="wide")`
- Company selector: [HD, PG, Comparativo] at top of page
- Comparativo mode: overlay both companies on same chart (two traces per figure)
- Sidebar: 20 KPIs in multiselect, grouped by category (Growth, Profitability, Liquidity, Solvency, Efficiency)
- Max 5 KPIs simultaneously
- Layout auto-reconfigures: 1 KPI = full width, 2 = 2 cols, 3-4 = 2 cols, 5 = 2+3 split
- Each KPI = "Executive Card": KPI Headline + Big Number (latest value) + Delta Pill (% vs prior) + Historical Trend chart
- Color: sober palette, color only for deltas and company differentiation in Comparativo mode

### Claude's Discretion
- KPI formatting details (which are %, which are ratios, which are x multiples, which are days)
- Exact color values for HD vs PG in Comparativo mode
- Hover template formatting on Plotly charts
- Temporal filter widget type (slider or select_slider)
- Dynamic ticker input UX (text_input + button vs on_change)
- Whether to use `st.metric` built-in sparklines or separate Plotly chart per card

### Deferred Ideas (OUT OF SCOPE)
- AI narratives/chat interface
- Real-time price data
- Multi-page app structure (v1 is single-page `app.py`)
- Export to CSV/DataFrame (v2 feature ANLYT-04)
- Screener/multi-metric filtering (v2 feature ANLYT-01)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DASH-01 | Dashboard shows comparative line charts (Streamlit + Plotly) for multiple companies, any KPI from the 20-KPI catalog | `go.Figure` + `add_trace(go.Scatter(...))` pattern enables multi-company overlay; `st.plotly_chart(fig, width="stretch")` renders responsively |
| DASH-02 | Dashboard includes temporal filter (slider or selector) for adjusting analysis window within 10 years | `st.slider(min, max, (start, end))` with tuple value creates range slider; integer year values work natively |
| DASH-03 | User types any S&P 500 ticker, system resolves CIK, runs ETL, adds company to analysis without restart | `st.text_input` + `st.button` triggers `FinancialAgent(ticker).run()`; `st.session_state` tracks loaded tickers across reruns |
| DASH-04 | `@st.cache_data` on all Parquet queries — no re-reads on interaction | `@st.cache_data(ttl=3600)` decorator on `pd.read_parquet(path)` function; cache key includes file path |
</phase_requirements>

---

## Summary

The dashboard is a single-file Streamlit app (`app.py`) reading from already-generated Parquet files in `data/clean/{TICKER}/kpis.parquet`. The ETL pipeline is fully complete — the dashboard's only job is visualization and interactive exploration. The critical design decision is the "Executive Card" pattern: each selected KPI renders as a self-contained card with a headline, big number (latest value), delta pill (YoY % change), and a historical trend chart.

Streamlit 1.54 (latest as of Feb 2026) ships with all required primitives: `st.metric` now supports sparklines via `chart_data`/`chart_type` parameters (added ~2025), `st.multiselect` with `max_selections=5`, `st.columns` with variable width specs, and `st.cache_data` for caching. A critical discovery: `use_container_width` in `st.plotly_chart` is deprecated and replaced by `width="stretch"` — use the new API. Plotly 6.5 (latest) supports `plotly_white` template, multi-trace figures via `add_trace()`, and clean axis configuration.

The one confirmed limitation: `st.multiselect` does NOT natively support grouped options (optgroups). A workaround is to prefix option labels with the category name (e.g., `"[Growth] revenue_growth_yoy"`) or use `st.sidebar.markdown` headers as visual separators with separate multiselects per category. The actual KPI columns in `kpis.parquet` are the 20 keys from `KPI_REGISTRY` in `processor.py` — these differ from the names described in the context (e.g., the actual column is `revenue_growth_yoy`, not `revenue_growth`).

**Primary recommendation:** Build `app.py` as a single-file Streamlit app. Use `st.metric(label, value, delta, chart_data=historical_values, chart_type="area", border=True)` for each Executive Card — the built-in sparkline eliminates the need for separate Plotly figures per KPI. Reserve full Plotly figures only for Comparativo mode where two company traces must overlay on the same chart.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | 1.54.0 | App framework, layout, widgets, caching | Latest stable; ships with all required primitives |
| plotly | 6.5.2 | Interactive charts for Comparativo overlay and trend charts | Only charting lib with proper multi-trace overlay |
| pandas | 3.0.1 | Already installed; Parquet reads, KPI filtering, delta calc | Already in use throughout project |
| pyarrow | 23.0.1 | Already installed; Parquet engine for `pd.read_parquet` | Project-wide engine, already verified working |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| plotly.graph_objects | bundled with plotly | Low-level figure construction for Comparativo mode | Required for two-trace (HD + PG) overlay charts |
| plotly.express | bundled with plotly | Quick single-company line charts | Simpler KPI cards when not in Comparativo mode |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| plotly | altair or bokeh | Altair has no `st.altair_chart` multi-trace overlay story; bokeh removed from Streamlit 1.52+ |
| st.metric sparklines | separate plotly figure per card | st.metric sparklines are simpler but less customizable; Plotly gives full Bloomberg styling — use plotly per card for consistent look |
| st.multiselect (flat) | multiple st.multiselect per category | Separate per-category widgets = cleaner UX for grouped KPIs |

**Installation:**
```bash
pip install "streamlit>=1.54.0" "plotly>=6.5.0"
# pandas>=3.0.1 and pyarrow>=23.0.1 already installed
```

---

## Architecture Patterns

### Recommended Project Structure
```
AI 2026/
├── app.py               # Single entry point — ALL dashboard code here
├── data/
│   ├── clean/
│   │   ├── HD/
│   │   │   ├── kpis.parquet      # 19 rows × 22 cols (fiscal_year 2007-2025)
│   │   │   └── financials.parquet
│   │   └── PG/
│   │       ├── kpis.parquet
│   │       └── financials.parquet
│   └── cache/
│       └── metadata.parquet      # ETL staleness tracking
├── processor.py         # (existing) KPI definitions
├── scraper.py           # (existing) SEC ETL
├── agent.py             # (existing) FinancialAgent.run()
└── requirements.txt     # Add streamlit>=1.54.0, plotly>=6.5.0
```

### Pattern 1: App Entry Point (st.set_page_config)
**What:** Must be the first Streamlit call in the script. Sets wide layout, page title, sidebar state.
**When to use:** Always — once per app, cannot be called twice.
```python
# Source: https://docs.streamlit.io/develop/api-reference/configuration/st.set_page_config
import streamlit as st

st.set_page_config(
    page_title="S&P 500 KPI Dashboard",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
    initial_sidebar_state="expanded",
)
```

### Pattern 2: Cached Parquet Loading
**What:** `@st.cache_data` wraps `pd.read_parquet()` — cache keyed on file path. Returns copy on each call.
**When to use:** Every data load call — prevents re-reading Parquet on every widget interaction.
```python
# Source: https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data
@st.cache_data(ttl=3600)
def load_kpis(ticker: str) -> pd.DataFrame:
    path = f"data/clean/{ticker}/kpis.parquet"
    return pd.read_parquet(path, engine="pyarrow")

# Usage: cache is keyed on (ticker,) — HD and PG cached separately
df_hd = load_kpis("HD")
df_pg = load_kpis("PG")
```

### Pattern 3: Dynamic Column Grid (1-5 KPIs)
**What:** `st.columns()` with variable spec produces responsive grid. Spec is a list of proportional widths.
**When to use:** Rendering the Executive Card grid based on number of selected KPIs.
```python
# Source: https://docs.streamlit.io/develop/api-reference/layout/st.columns
def get_column_spec(n: int) -> list[int]:
    """Returns column width spec for n KPIs."""
    specs = {
        1: [1],           # Full width
        2: [1, 1],        # 2 equal columns
        3: [1, 1, 1],     # 3 equal columns (or [1,1] with wrap)
        4: [1, 1, 1, 1],  # 4 equal columns
        5: [1, 1, 1, 1, 1],  # 5 equal columns
    }
    return specs.get(n, [1] * n)

# Render cards
cols = st.columns(get_column_spec(len(selected_kpis)), gap="medium")
for i, kpi_name in enumerate(selected_kpis):
    with cols[i % len(cols)]:
        render_kpi_card(kpi_name, df_company, comparativo_df)
```

**Note on 2+3 layout for 5 KPIs:** The context requests 2+3 rows (2 cards first row, 3 second). Standard `st.columns(5)` creates 5 equal columns in one row. To create two rows with 2 and 3 columns respectively, render two separate `st.columns` calls:
```python
if len(selected_kpis) == 5:
    row1 = st.columns(2, gap="medium")
    for i in range(2):
        with row1[i]:
            render_kpi_card(selected_kpis[i], ...)
    row2 = st.columns(3, gap="medium")
    for i in range(3):
        with row2[i]:
            render_kpi_card(selected_kpis[2 + i], ...)
```

### Pattern 4: Executive Card with st.metric
**What:** `st.metric` renders headline + big number + delta pill in one call. `chart_data` adds sparkline.
**When to use:** Single-company mode (HD or PG) — clean, minimal card.
```python
# Source: https://docs.streamlit.io/develop/api-reference/data/st.metric
def render_kpi_card(kpi_name: str, df: pd.DataFrame, kpi_meta: dict) -> None:
    """Render one Executive Card: headline + big number + delta + sparkline."""
    col_data = df[kpi_name].dropna()
    if col_data.empty:
        st.metric(label=kpi_meta["label"], value="N/A")
        return

    latest_val = col_data.iloc[-1]
    prior_val = col_data.iloc[-2] if len(col_data) >= 2 else None
    delta_pct = ((latest_val - prior_val) / abs(prior_val)) if prior_val else None

    formatted_value = format_kpi(latest_val, kpi_meta["format"])
    formatted_delta = f"{delta_pct*100:+.1f}%" if delta_pct is not None else None

    st.metric(
        label=kpi_meta["label"],
        value=formatted_value,
        delta=formatted_delta,
        delta_color="normal",   # green=up, red=down
        chart_data=col_data.tolist(),
        chart_type="line",
        border=True,
    )
```

### Pattern 5: Comparativo Mode — Two-Trace Plotly Chart
**What:** When Comparativo is selected, build one `go.Figure` with two `go.Scatter` traces (HD + PG).
**When to use:** Company selector = "Comparativo". Replaces `st.metric` card with full Plotly figure.
```python
# Source: https://plotly.com/python/line-charts/
import plotly.graph_objects as go

COMPANY_COLORS = {
    "HD": "#1f4e79",   # dark blue (sober, professional)
    "PG": "#2e7d32",   # dark green
}

def render_comparativo_card(kpi_name: str, df_hd: pd.DataFrame, df_pg: pd.DataFrame,
                             kpi_meta: dict, year_range: tuple) -> None:
    """Render Comparativo overlay: two traces on same Plotly figure."""
    # Filter to year range
    hd = df_hd[(df_hd.fiscal_year >= year_range[0]) & (df_hd.fiscal_year <= year_range[1])]
    pg = df_pg[(df_pg.fiscal_year >= year_range[0]) & (df_pg.fiscal_year <= year_range[1])]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hd["fiscal_year"], y=hd[kpi_name],
        name="HD", mode="lines+markers",
        line=dict(color=COMPANY_COLORS["HD"], width=2),
    ))
    fig.add_trace(go.Scatter(
        x=pg["fiscal_year"], y=pg[kpi_name],
        name="PG", mode="lines+markers",
        line=dict(color=COMPANY_COLORS["PG"], width=2),
    ))
    fig.update_layout(
        template="plotly_white",
        title=kpi_meta["label"],
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False, tickformat="d")
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", tickformat=kpi_meta["tick_format"])

    st.plotly_chart(fig, width="stretch")  # NOT use_container_width (deprecated)
```

### Pattern 6: KPI Grouping Workaround
**What:** `st.multiselect` does NOT support optgroups natively. Use separate multiselect per category + `st.sidebar.markdown` headers.
**When to use:** Sidebar KPI selection with 5 categories.
```python
# Source: Verified via https://github.com/streamlit/streamlit/issues/12350 (unimplemented)
KPI_GROUPS = {
    "Growth": ["revenue_growth_yoy", "revenue_cagr_10y"],
    "Profitability": ["gross_profit_margin", "operating_margin", "net_profit_margin",
                      "ebitda_margin", "roe", "roa"],
    "Liquidity": ["current_ratio", "quick_ratio", "cash_ratio", "working_capital"],
    "Solvency": ["debt_to_equity", "debt_to_ebitda", "interest_coverage", "debt_to_assets"],
    "Efficiency": ["asset_turnover", "inventory_turnover", "dso", "cash_conversion_cycle"],
}

# In sidebar: each group gets its own expander + multiselect
selected_kpis = []
with st.sidebar:
    st.markdown("### KPI Selection (max 5 total)")
    remaining = 5 - len(selected_kpis)
    for group_name, group_kpis in KPI_GROUPS.items():
        with st.expander(group_name, expanded=(group_name == "Profitability")):
            selected = st.multiselect(
                label=group_name,
                options=group_kpis,
                default=[],
                format_func=lambda k: KPI_META[k]["label"],
                label_visibility="collapsed",
                max_selections=min(remaining, len(group_kpis)),
            )
            selected_kpis.extend(selected)
            remaining = max(0, 5 - len(selected_kpis))
```

### Pattern 7: Dynamic Ticker Input (DASH-03)
**What:** `st.text_input` + `st.button` triggers `FinancialAgent.run()` and stores ticker in session_state.
**When to use:** Implementing DASH-03 — user adds any S&P 500 ticker on demand.
```python
# Source: https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state
import agent as financial_agent

# Initialize session state
if "loaded_tickers" not in st.session_state:
    st.session_state.loaded_tickers = ["HD", "PG"]

with st.sidebar:
    st.markdown("### Add Company")
    new_ticker = st.text_input("S&P 500 ticker", placeholder="e.g. AAPL").upper().strip()
    if st.button("Load") and new_ticker:
        if new_ticker not in st.session_state.loaded_tickers:
            with st.spinner(f"Running ETL for {new_ticker}..."):
                try:
                    fa = financial_agent.FinancialAgent(new_ticker)
                    fa.run()
                    st.session_state.loaded_tickers.append(new_ticker)
                    st.cache_data.clear()  # Invalidate cache so new parquet is read
                    st.success(f"{new_ticker} loaded!")
                except Exception as e:
                    st.error(f"Failed: {e}")
```

### Pattern 8: Year Range Filter (DASH-02)
**What:** `st.slider` with tuple default creates a range slider for integer year selection.
**When to use:** Sidebar temporal filter — restricts all charts to selected year range.
```python
# Source: https://docs.streamlit.io/develop/api-reference/widgets/st.slider
min_year, max_year = 2007, 2025  # from actual parquet data
year_range = st.sidebar.slider(
    "Year Range",
    min_value=min_year,
    max_value=max_year,
    value=(2015, max_year),   # default: last ~10 years
    step=1,
)
```

### Anti-Patterns to Avoid
- **`use_container_width=True` in `st.plotly_chart`:** Deprecated in Streamlit 1.40+. Use `width="stretch"` instead. Will be removed post-2025-12-31.
- **Loading Parquet inside the render loop:** Every widget interaction reruns the script. Without `@st.cache_data`, each company × KPI interaction re-reads disk.
- **Calling `st.set_page_config` after other Streamlit commands:** Must be the absolute first `st` call. Putting it inside a function that gets called after `st.sidebar` will raise `StreamlitAPIException`.
- **Separate Streamlit app files for multi-page when single-page suffices:** The context says single-page `app.py`. Avoid `st.navigation` / `st.Page` pattern — adds complexity with no v1 benefit.
- **Using `st.write(fig)` instead of `st.plotly_chart(fig)`:** `st.write` auto-detects Plotly figures but bypasses the `width` and `config` parameters. Always use `st.plotly_chart` explicitly.
- **`go.Figure()` for single-company trend when `st.metric` sparklines suffice:** Adds rendering overhead. Use `st.metric(chart_data=...)` for single-company cards, reserve `go.Figure` for Comparativo overlays.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Delta pill with color | Custom HTML/CSS `<span>` elements | `st.metric(delta=..., delta_color="normal")` | Built-in green/red coloring, hover tooltip, responsive sizing |
| Sparkline charts | Custom `go.Figure` per card | `st.metric(chart_data=values, chart_type="line")` | Native, single-call, no separate chart rendering overhead |
| Parquet load caching | LRU cache or global dict | `@st.cache_data(ttl=3600)` | Thread-safe, session-aware, automatic invalidation |
| Responsive column layout | CSS grid or custom JS | `st.columns([spec], gap="medium")` | Streamlit-native, works in all environments |
| Year slider | Date picker or custom JS | `st.slider(min, max, (start, end))` | Integer range slider works natively for years |
| Company color palette | Random color picker | Hard-coded `COMPANY_COLORS = {"HD": "#1f4e79", "PG": "#2e7d32"}` | Consistent, professional, Bloomberg-style |

**Key insight:** Streamlit 1.54 has matured enough that the "Executive Card" pattern (headline + big number + delta + sparkline) is a single `st.metric` call. Avoid the temptation to build custom HTML cards — the native widget handles theme compatibility, accessibility, and responsive sizing.

---

## KPI Formatting Reference

This is critical for the `format_kpi()` function and Plotly `tickformat`. The actual column names are from `processor.py`'s `KPI_REGISTRY`.

| KPI Column | Display Label | Format Type | Format Rule | Example |
|------------|---------------|-------------|-------------|---------|
| `revenue_growth_yoy` | Revenue Growth YoY | percentage | `f"{v*100:.1f}%"` | `4.5%` |
| `revenue_cagr_10y` | Revenue CAGR (10Y) | percentage | `f"{v*100:.1f}%"` | `8.2%` |
| `gross_profit_margin` | Gross Margin | percentage | `f"{v*100:.1f}%"` | `33.4%` |
| `operating_margin` | Operating Margin | percentage | `f"{v*100:.1f}%"` | `13.5%` |
| `net_profit_margin` | Net Margin | percentage | `f"{v*100:.1f}%"` | `9.3%` |
| `ebitda_margin` | EBITDA Margin | percentage | `f"{v*100:.1f}%"` | `15.6%` |
| `roe` | Return on Equity | percentage | `f"{v*100:.1f}%"` | `222.9%` |
| `roa` | Return on Assets | percentage | `f"{v*100:.1f}%"` | `15.4%` |
| `current_ratio` | Current Ratio | ratio_x | `f"{v:.2f}x"` | `1.11x` |
| `quick_ratio` | Quick Ratio | ratio_x | `f"{v:.2f}x"` | `0.23x` |
| `cash_ratio` | Cash Ratio | ratio_x | `f"{v:.2f}x"` | `0.06x` |
| `working_capital` | Working Capital | dollar_B | `f"${v/1e9:.1f}B"` | `$3.0B` |
| `debt_to_equity` | Debt / Equity | ratio_x | `f"{v:.2f}x"` | `13.5x` |
| `debt_to_ebitda` | Debt / EBITDA | ratio_x | `f"{v:.2f}x"` | `2.1x` |
| `interest_coverage` | Interest Coverage | ratio_x | `f"{v:.1f}x"` | `11.1x` |
| `debt_to_assets` | Debt / Assets | percentage | `f"{v*100:.1f}%"` | `45.2%` |
| `asset_turnover` | Asset Turnover | ratio_x | `f"{v:.2f}x"` | `1.85x` |
| `inventory_turnover` | Inventory Turns | ratio_x | `f"{v:.1f}x"` | `4.8x` |
| `dso` | Days Sales Outstanding | days | `f"{v:.0f}d"` | `9d` |
| `cash_conversion_cycle` | Cash Conversion Cycle | days | `f"{v:.0f}d"` | `48d` |

**ROE edge case:** HD's ROE can exceed 100% (e.g., 222.9%) because equity is very low relative to earnings. This is mathematically correct — do NOT cap or flag as error.

**NaN handling:** `revenue_cagr_10y` will be NaN for years < 2017 (needs 10 years of prior data). `debt_to_ebitda` and `debt_to_assets` may be NaN for some years. Display as "N/A" in big number.

---

## Common Pitfalls

### Pitfall 1: `use_container_width` Deprecation
**What goes wrong:** `st.plotly_chart(fig, use_container_width=True)` generates a DeprecationWarning in Streamlit 1.40+ and will be removed after 2025-12-31.
**Why it happens:** Streamlit migrated to a unified `width` parameter across all chart types.
**How to avoid:** Always use `st.plotly_chart(fig, width="stretch")`.
**Warning signs:** Console warning: `use_container_width is deprecated`.

### Pitfall 2: Streamlit Script Re-runs on Every Interaction
**What goes wrong:** Without `@st.cache_data`, switching between KPIs re-reads Parquet files from disk on every interaction. With 20 companies × 2 files each = 40 potential reads per interaction.
**Why it happens:** Streamlit re-runs the entire Python script top-to-bottom on every widget change.
**How to avoid:** Every `pd.read_parquet()` call must be inside a `@st.cache_data`-decorated function. The function's arguments are the cache key — include `ticker` as an argument, not a closure variable.
**Warning signs:** Slow response on KPI toggle; profiling shows Parquet I/O on every interaction.

### Pitfall 3: `st.set_page_config` Not First
**What goes wrong:** `StreamlitAPIException: set_page_config() can only be called once per app and must be called as the first Streamlit command`.
**Why it happens:** Any `st.*` call before `st.set_page_config` (including imports that render widgets) violates the constraint.
**How to avoid:** `st.set_page_config(...)` must be the very first `st.*` call after imports. Never put it inside a function that's called after other Streamlit commands.
**Warning signs:** `StreamlitAPIException` on startup.

### Pitfall 4: Session State Not Initialized
**What goes wrong:** `KeyError: 'loaded_tickers'` on first run when accessing `st.session_state.loaded_tickers`.
**Why it happens:** Session state keys don't exist until explicitly set; checking them without initialization raises KeyError.
**How to avoid:** Always guard with `if "key" not in st.session_state:` before first access.
**Warning signs:** KeyError on first page load (not on subsequent reruns).

### Pitfall 5: Plotly Figure Reuse Across Reruns
**What goes wrong:** Mutating a cached `go.Figure` object modifies the cached value, causing traces to accumulate across reruns.
**Why it happens:** `@st.cache_data` returns copies of DataFrames but Plotly figures are mutable objects created inside render functions.
**How to avoid:** Always create `go.Figure()` inside the render function (not at module level), never cache Plotly figures.
**Warning signs:** Charts show double/triple traces after KPI switching.

### Pitfall 6: NaN Values Break st.metric and Plotly
**What goes wrong:** `st.metric(value=float('nan'))` renders as `NaN` in the UI. `go.Scatter(y=[nan, nan])` renders as gaps.
**Why it happens:** `revenue_cagr_10y` is NaN for recent years with no 10-year prior data; `working_capital` can be NaN for financial sector companies.
**How to avoid:** Always check `pd.notna(value)` before formatting. Use `"N/A"` string as the `value` when NaN. Plotly renders NaN as gaps in line charts — this is often desirable for missing data (don't fill with zeros).
**Warning signs:** "NaN" appearing in the big number display.

### Pitfall 7: Grouped Multiselect Total Exceeds 5
**What goes wrong:** With separate `st.multiselect` per category, each has its own `max_selections` but the global total can exceed 5 if user selects from multiple groups.
**Why it happens:** Streamlit enforces `max_selections` per widget, not across widgets.
**How to avoid:** Enforce global max in app logic: recalculate `remaining = 5 - len(selected_kpis)` and pass to each group's `max_selections`. Re-render if total exceeds 5.
**Warning signs:** More than 5 KPI cards appearing in the main canvas.

---

## Code Examples

### Full Layout Configuration
```python
# Source: https://docs.streamlit.io/develop/api-reference/configuration/st.set_page_config
import streamlit as st
import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd

# Must be FIRST st call
st.set_page_config(
    page_title="S&P 500 KPI Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Set global Plotly template — applies to all figures
pio.templates.default = "plotly_white"
```

### Cached Data Loading
```python
# Source: https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data
@st.cache_data(ttl=3600)
def load_kpis(ticker: str) -> pd.DataFrame:
    """Load kpis.parquet for a ticker. Cached per ticker, refreshes hourly."""
    return pd.read_parquet(f"data/clean/{ticker}/kpis.parquet", engine="pyarrow")

@st.cache_data(ttl=3600)
def get_available_tickers() -> list[str]:
    """Return list of tickers with existing kpis.parquet files."""
    from pathlib import Path
    return sorted([p.parent.name for p in Path("data/clean").glob("*/kpis.parquet")])
```

### Plotly Figure Styling (Bloomberg-like)
```python
# Source: https://plotly.com/python/templates/ + https://plotly.com/python/line-charts/
def build_trend_figure(df: pd.DataFrame, kpi: str, title: str,
                       year_range: tuple, color: str = "#1f4e79") -> go.Figure:
    """Single-company trend line with Bloomberg-style minimal chrome."""
    filtered = df[(df.fiscal_year >= year_range[0]) & (df.fiscal_year <= year_range[1])]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=filtered["fiscal_year"],
        y=filtered[kpi],
        mode="lines+markers",
        line=dict(color=color, width=2.5),
        marker=dict(size=6),
        hovertemplate="%{x}: %{y:.2%}<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_white",
        title=dict(text=title, font=dict(size=14)),
        margin=dict(l=0, r=0, t=30, b=0),
        showlegend=False,
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False, tickformat="d", dtick=2)
    fig.update_yaxes(showgrid=True, gridcolor="#f5f5f5", zeroline=False)
    return fig
```

### Comparativo Overlay Figure
```python
# Source: https://plotly.com/python/creating-and-updating-figures/
def build_comparativo_figure(df_hd, df_pg, kpi, title, year_range) -> go.Figure:
    """Two-company overlay on same figure."""
    fig = go.Figure()
    for ticker, df, color in [("HD", df_hd, "#1f4e79"), ("PG", df_pg, "#2e7d32")]:
        d = df[(df.fiscal_year >= year_range[0]) & (df.fiscal_year <= year_range[1])]
        fig.add_trace(go.Scatter(
            x=d["fiscal_year"], y=d[kpi], name=ticker,
            mode="lines+markers",
            line=dict(color=color, width=2.5),
        ))
    fig.update_layout(
        template="plotly_white",
        title=title,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
        margin=dict(l=0, r=0, t=40, b=0),
    )
    fig.update_xaxes(showgrid=False, tickformat="d")
    fig.update_yaxes(showgrid=True, gridcolor="#f5f5f5")
    return fig
```

### Company Selector (Radio at Top)
```python
# Source: https://docs.streamlit.io/develop/api-reference/widgets/st.radio
company_mode = st.radio(
    label="Company",
    options=["HD", "PG", "Comparativo"],
    horizontal=True,    # renders as inline button row, not vertical list
    index=0,
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `st.plotly_chart(fig, use_container_width=True)` | `st.plotly_chart(fig, width="stretch")` | Streamlit ~1.40 | Breaking — old param logs DeprecationWarning, removed post Dec 2025 |
| `st.metric(label, value, delta)` (no charts) | `st.metric(..., chart_data=values, chart_type="line")` | Streamlit ~1.44 | Sparklines now built into metric widget |
| `st.cache` (removed) | `@st.cache_data` | Streamlit 1.18 | `st.cache` is removed; only `st.cache_data` and `st.cache_resource` exist |
| `st.plotly_chart(fig, **kwargs)` for config | `st.plotly_chart(fig, config={...})` | Streamlit ~1.40 | `**kwargs` deprecated; use explicit `config` dict |

**Deprecated/outdated:**
- `st.bokeh_chart`: Removed in Streamlit 1.52. Do not use.
- `st.cache`: Removed. Use `@st.cache_data` or `@st.cache_resource`.
- `use_container_width` in `st.plotly_chart`: Deprecated, will be removed. Use `width="stretch"`.

---

## Open Questions

1. **2+3 layout for 5 KPIs: two rows vs one row**
   - What we know: `st.columns(5)` creates one row of 5 equal columns. Two-row 2+3 requires two separate `st.columns` calls.
   - What's unclear: Whether Streamlit's reflow model allows two `st.columns` blocks to be placed in the same visual row, or if they always stack vertically.
   - Recommendation: Use two sequential `st.columns` blocks (row1=2 cols, row2=3 cols). Streamlit stacks them vertically by default, which creates the 2+3 layout as intended.

2. **st.metric sparkline vs dedicated Plotly chart for single-company mode**
   - What we know: `st.metric(chart_data=...)` sparklines are low-customization but built-in. Full Plotly figures give Bloomberg-style control.
   - What's unclear: Whether the sparkline quality is acceptable for a "CFO-ready" dashboard.
   - Recommendation: Use full Plotly charts per card (even in single-company mode) for consistent Bloomberg aesthetic. The `plotly_white` template with minimal chrome looks better than the default Streamlit sparkline.

3. **st.cache_data invalidation when a new ticker is added via DASH-03**
   - What we know: Calling `st.cache_data.clear()` invalidates ALL cached data in the session.
   - What's unclear: Whether selective invalidation per ticker is possible without cache keys tied to session state.
   - Recommendation: Call `st.cache_data.clear()` after a successful `FinancialAgent.run()` in the dynamic ticker flow. This is safe since reloading all KPI data is fast from Parquet (milliseconds per ticker).

---

## Validation Architecture

> `workflow.nyquist_validation` is not set in `.planning/config.json` — section skipped.

The config.json has `"workflow": {"research": true, "plan_check": true, "verifier": true}` — `nyquist_validation` key is absent. Skip this section per instructions.

---

## Sources

### Primary (HIGH confidence)
- https://docs.streamlit.io/develop/api-reference/layout/st.columns — `spec`, `gap`, `vertical_alignment`, `border`, `width` parameters verified
- https://docs.streamlit.io/develop/api-reference/widgets/st.multiselect — `max_selections`, `accept_new_options`, flat options (no grouping); confirmed via GitHub issue #12350
- https://docs.streamlit.io/develop/api-reference/data/st.metric — `chart_data`, `chart_type`, `border`, `delta_arrow`, `format` parameters verified
- https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data — `ttl`, `persist`, `scope`, `max_entries` parameters verified
- https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart — `width="stretch"` (replaces `use_container_width`), `config`, `selection_mode` verified
- https://docs.streamlit.io/develop/api-reference/configuration/st.set_page_config — `layout="wide"`, `initial_sidebar_state` verified
- https://plotly.com/python/templates/ — `plotly_white` template, `pio.templates.default` global setting verified
- https://plotly.com/python/line-charts/ — `go.Scatter`, `add_trace()`, multi-trace overlay pattern verified
- `pip index versions streamlit` — confirmed 1.54.0 is latest (Feb 2026)
- `pip index versions plotly` — confirmed 6.5.2 is latest (Feb 2026)
- Actual parquet inspection: `pandas 3.0.1`, `pyarrow 23.0.1` already installed; HD and PG kpis.parquet confirmed 19 rows × 22 cols, fiscal years 2007-2025

### Secondary (MEDIUM confidence)
- https://docs.streamlit.io/develop/quick-reference/release-notes/2025 — Streamlit 1.52.0 release notes; `st.metric` sparkline and `delta_arrow` confirmed
- Multiple community sources confirming `width="stretch"` replaces `use_container_width` with deprecation deadline

### Tertiary (LOW confidence)
- None — all critical claims verified through official docs or direct code inspection

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified via `pip index versions`, packages already installed confirmed via pip show
- Architecture: HIGH — all patterns verified against official Streamlit/Plotly docs
- KPI formatting: HIGH — verified against actual parquet data (HD/PG kpis.parquet inspected directly)
- Pitfalls: HIGH — deprecations confirmed via official changelog and GitHub issues

**Research date:** 2026-02-26
**Valid until:** 2026-03-28 (Streamlit releases frequently; verify `width="stretch"` still current if >30 days)
