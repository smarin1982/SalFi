# Features Research: SP500 Financial Dashboard

> Research type: Project Research — Features dimension
> Milestone: Greenfield
> Question: What features do professional financial analysis dashboards have? Table stakes vs differentiators for multi-company S&P 500 comparison using 10-K data.
> Date: 2026-02-24

---

## Table Stakes

Features users expect as baseline. Without these, they will not trust the tool or will abandon it quickly.

### Data Integrity and Sourcing

| Feature | Description | Complexity |
|---|---|---|
| Source attribution | Every number shows where it came from (e.g., "10-K FY2023, filed 2024-02-15") | Low |
| Filing date visibility | Users can see when data was filed, not just the fiscal year | Low |
| Clearly labeled fiscal year vs calendar year | Many S&P 500 companies have non-December fiscal year ends | Low |
| Restatement handling | When a company restates financials, old vs. new values must be distinguishable | Medium |
| GAAP-only labeling | For 10-K sourced data, be explicit that these are audited GAAP figures | Low |

**Why this is table stakes:** Financial professionals will immediately cross-check a few numbers against their known sources. One wrong number kills trust in the entire tool. SEC EDGAR is the authoritative source, so data provenance from EDGAR is itself a trust signal.

### Core Financial Statements (from 10-K)

| Feature | Description | Complexity |
|---|---|---|
| Income Statement | Revenue, gross profit, operating income, net income, EPS (basic + diluted) | Low |
| Balance Sheet | Assets, liabilities, equity, cash, debt | Low |
| Cash Flow Statement | Operating, investing, financing cash flows; free cash flow | Low |
| At least 5 years of history | Trend analysis requires multi-year context; 10 years is better | Low (data storage) |
| Per-share normalization | Revenue/share, earnings/share, book value/share | Low |

### Key Derived Metrics (calculated from 10-K data)

| Feature | Description | Complexity |
|---|---|---|
| Profitability ratios | Gross margin %, operating margin %, net margin %, ROE, ROA, ROIC | Low |
| Leverage ratios | Debt/equity, debt/EBITDA, interest coverage | Low |
| Liquidity ratios | Current ratio, quick ratio | Low |
| Growth rates | YoY and CAGR for revenue, earnings, free cash flow | Low |
| Valuation multiples | P/E, P/B, P/S, EV/EBITDA (requires market cap — see dependency note) | Medium |

### Multi-Company Comparison

| Feature | Description | Complexity |
|---|---|---|
| Side-by-side metric table | Select 2-10 companies, pick a metric, see values in columns | Low-Medium |
| Sector/industry filtering | Filter S&P 500 universe by GICS sector or industry | Low |
| Sortable tables | Sort companies by any metric (highest revenue, best margin, etc.) | Low |
| Company search | Find a company by ticker or name | Low |

### Visualization

| Feature | Description | Complexity |
|---|---|---|
| Time series line charts | Plot any metric over time for one or more companies | Low-Medium |
| Bar/column charts | Year-over-year comparison, single metric across companies | Low |
| Readable, clean defaults | Charts must be interpretable without customization | Low |
| Axis labels and units | Dollar amounts in $M or $B with clear labels; percentages labeled as % | Low |

---

## Differentiators

Features that elevate the tool from "fine" to "genuinely useful for professionals." These are where the tool can earn a reputation.

### Analytical Power

| Feature | Description | Complexity | Why it Differentiates |
|---|---|---|---|
| Normalized comparison (% of revenue) | Show all income statement items as % of revenue for true peer comparison | Low | Removes size distortion; essential for cross-company analysis |
| Indexed growth charts | Set any year as 100, show relative growth trajectories | Low-Medium | Reveals compounding differences Bloomberg shows this but buries it |
| Cohort comparison by metric range | "Show all S&P 500 companies with gross margin > 60% and revenue growth > 10% YoY" | Medium | Screener capability; this is what analysts actually want |
| Scatter plots (two-metric correlation) | Plot P/E vs. earnings growth, or margin vs. revenue growth, across the universe | Medium | Reveals valuation outliers and sector clusters |
| Waterfall charts for margin analysis | Show where margin is lost from gross to operating to net | Medium | Used in earnings analysis; rarely available in free tools |
| Segment-level data | Revenue/profit by business segment where disclosed in 10-K | High | Differentiates product lines; critical for conglomerates |

### Data Context and Intelligence

| Feature | Description | Complexity | Why it Differentiates |
|---|---|---|---|
| Anomaly flagging | Highlight when a metric is a statistical outlier vs. peer group or own history | Medium | Saves analyst time; draws attention to what matters |
| Trend direction indicators | Simple up/down/flat icons on key metrics, 3-year and 5-year view | Low | Scannable; reduces cognitive load |
| Peer group auto-suggestion | When viewing a company, suggest its closest peers by sector + size | Medium | Reduces setup friction significantly |
| Footnote / disclosure excerpts | Pull key disclosures from 10-K text (risk factors, accounting changes) | High | Raw EDGAR text is hard to navigate; surfacing it adds real value |

### Export and Integration

| Feature | Description | Complexity | Why it Differentiates |
|---|---|---|---|
| CSV / Excel export of any table or chart data | Professionals do their own modeling; they need the numbers | Low | Macrotrends does this; it's why analysts use it despite ugly UI |
| Reproducible data snapshots | Export with filing dates so the snapshot is auditable | Low | Critical for compliance and research documentation |
| Python API / Jupyter notebook integration | For a Python-based tool, expose data as a DataFrame or via a clean API | Medium | Koyfin lacks this; open-source tools like financedatabase provide it; huge differentiator for quant users |

### User Experience

| Feature | Description | Complexity | Why it Differentiates |
|---|---|---|---|
| Persistent custom comparison sets | Save "my FAANG comparison" and return to it | Low-Medium | Session state; Bloomberg does this; free tools do not |
| Keyboard shortcuts for navigation | Switch companies, metrics, time periods without mouse | Medium | Power-user adoption; differentiates for frequent use |
| URL-shareable views | A specific comparison (company set + metric + chart type) generates a shareable link | Low-Medium | Critical for team workflows; Koyfin added this late |
| Dark mode | Standard expectation for terminal-style finance tools | Low | Table stakes among technical users; differentiator vs. Macrotrends |

---

## Anti-Features

Things to deliberately NOT build. Each adds complexity, maintenance burden, or scope creep without meaningful value for the stated use case (S&P 500 comparison using 10-K data).

### Real-Time and Near-Real-Time Data

| Anti-Feature | Why to Avoid |
|---|---|
| Live stock price feeds | 10-K data is annual/quarterly; mixing real-time prices requires data licensing, API costs, and rate limiting. The tool's value is fundamental analysis, not trading. |
| Intraday charts or price history | This is Bloomberg/Refinitiv territory. It distracts from the 10-K fundamentals story. |
| Earnings call transcripts or NLP | High complexity, requires separate data source, scope creep. Not 10-K data. |
| Analyst consensus estimates | Forward-looking estimates are not in 10-K filings. Requires paid data (Bloomberg, FactSet). |

### Social and Community Features

| Anti-Feature | Why to Avoid |
|---|---|
| Comments or discussion threads | Moderation overhead; not how professionals consume financial data. |
| User ratings or crowdsourced data | Undermines the "authoritative EDGAR source" trust signal. |
| Watchlist notifications / alerts | Push infrastructure complexity; out of scope for a comparison dashboard. |

### Excessive Customization

| Anti-Feature | Why to Avoid |
|---|---|
| Custom formula builder (DIY metric creation) | High complexity, high support burden, low adoption. Professionals will use Excel for this. |
| Drag-and-drop dashboard layout | Looks impressive in demos; adds little analytical value; significant frontend complexity. |
| Custom color themes beyond light/dark | Engineering distraction with zero analytical payoff. |
| AI-generated narrative summaries ("Company X has shown...") | LLM output is not auditable; analysts will not trust AI prose for financial conclusions. |

### Data Scope Creep

| Anti-Feature | Why to Avoid |
|---|---|
| Non-S&P 500 companies (global equities, small caps) | EDGAR coverage for foreign filers is inconsistent; normalization becomes very hard. |
| 10-Q (quarterly) filings alongside 10-K | Quarterly XBRL tagging is less consistent; doubles data pipeline complexity. Start with 10-K only. |
| Non-GAAP / adjusted metrics | Companies define these differently; cross-company comparison on non-GAAP is misleading. |
| Macro economic overlays (GDP, rates) | Different data source, different cadence, different normalization. Scope creep. |
| ESG / sustainability metrics | 10-K ESG disclosures are inconsistent pre-2024; not XBRL tagged; requires text extraction. |

---

## Feature Dependencies

Understanding which features must be built before others become possible.

```
[1] EDGAR Data Pipeline (fetch + parse 10-K XBRL)
        |
        v
[2] Normalized Data Store (company + fiscal_year + metric_name + value + source_filing)
        |
        +---> [3a] Single-company time series view
        |
        +---> [3b] Multi-company comparison table (depends on 2+ companies in store)
        |
        +---> [3c] Derived metrics (margins, ratios, growth rates) — depends on [2]
                    |
                    +---> [4a] Sector screener / filter — depends on [3c] + sector taxonomy
                    |
                    +---> [4b] Scatter plot / correlation view — depends on [3c] cross-company
                    |
                    +---> [4c] Anomaly flagging — depends on [3c] statistical distribution
                    |
                    +---> [5] Cohort / peer comparison — depends on [4a] + [3c]
```

**Critical path insight:** Everything in the Differentiators section depends on [2] being designed correctly. If the data store normalizes metrics inconsistently (e.g., mixing fiscal year labels, storing revenue in dollars vs. thousands), downstream features will silently produce wrong answers. The data model is the highest-leverage design decision.

**Market cap / valuation multiples dependency:** P/E, EV/EBITDA, and P/B require a market cap data source that is NOT in 10-K filings. This is a significant data sourcing decision. Options: (a) pull from a free source like Yahoo Finance, (b) omit valuation multiples from v1, (c) let users input market cap manually. Recommendation: omit or make optional in v1 to avoid data licensing complexity.

---

## Key Findings

1. **Data provenance is the trust foundation.** For SEC EDGAR tools, showing the exact filing, filing date, and fiscal year for every data point is not optional — it is what separates a credible tool from a spreadsheet. Professional users will verify before they rely.

2. **The most valuable differentiator is the screener.** The ability to filter the entire S&P 500 universe by combinations of metrics ("high margin + high ROIC + accelerating revenue growth") is what Bloomberg and FactSet charge thousands per year for. This is achievable with EDGAR data and has very high professional value density per engineering effort.

3. **Export is underrated.** Macrotrends is objectively an ugly tool with mediocre charts, yet it has strong analyst usage specifically because it exports clean CSVs. For a Python-based tool targeting analysts, a first-class DataFrame/CSV export path is a higher-return investment than chart polish.

4. **Quarterly data (10-Q) and real-time prices are traps.** Both seem like natural extensions but each adds significant data pipeline complexity and undermines the tool's core strength (audited, annual, apples-to-apples comparison). Resist scope creep toward these until the 10-K annual story is solid.

5. **The data model design is the highest-leverage decision.** A normalized store with consistent metric naming, fiscal year conventions, and source attribution enables every downstream feature. A poorly designed store makes anomaly detection, peer comparison, and export unreliable — and retrofitting is expensive. Invest in schema design before building UI.

---

*Sources used: Domain knowledge of Bloomberg Terminal, Koyfin, Macrotrends, Wisesheets, SEC EDGAR XBRL API, open-source Python financial libraries (financedatabase, yfinance, OpenBB), and professional financial analysis workflows. Research conducted 2026-02-24.*
