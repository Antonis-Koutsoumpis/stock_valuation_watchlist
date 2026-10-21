"""Rule #1 stock valuation watchlist (Streamlit)."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rule1 import manual, metrics
from rule1.periods import quarter_end, quarter_start
from rule1.store import DATA_DIR, read_csv
from rule1.update import load_watchlist

st.set_page_config(page_title="Rule #1 Watchlist", layout="wide")

DAILY_METRICS = {
    "close": "Price",
    "volume": "Volume",
    "trailing_pe": "Trailing P/E",
    "forward_pe": "Forward P/E",
    "peg_5y": "PEG ratio (5yr expected)",
    "price_sales": "Price/Sales",
    "price_book": "Price/Book",
    "trailing_div_yield": "Trailing annual dividend yield",
    "forward_div_yield": "Forward annual dividend yield",
    "payout_ratio": "Payout ratio",
    "market_cap": "Market cap",
}
QUARTERLY_METRICS = {
    "revenue": "Revenue (quarter)",
    "revenue_ttm": "Revenue (TTM)",
    "eps_diluted": "EPS (quarter)",
    "eps_diluted_ttm": "EPS (TTM)",
    "fcf": "Free cash flow (quarter)",
    "fcf_ttm": "Free cash flow (TTM)",
    "roic_ttm": "ROIC (TTM)",
    "bvps": "BVPS",
    "total_debt": "Debt",
    "net_debt_fcf_ttm": "Net Debt / FCF (TTM)",
    "dividends_ttm": "Dividends (TTM)",
    "shares_outstanding": "Shares outstanding",
}
DCF_METRICS = {"dcf_low": "DCF low end", "dcf_middle": "DCF middle", "dcf_high": "DCF high end"}
ALL_METRICS = {**DAILY_METRICS, **QUARTERLY_METRICS, **DCF_METRICS}
PERCENT = {"roic_ttm", "roic", "trailing_div_yield", "forward_div_yield", "payout_ratio"}
YEARLY_LABELS = {"roic": "ROIC", "bvps": "BVPS", "revenue": "Revenue", "eps_diluted": "EPS",
                 "fcf": "Free Cash Flow", "net_debt_fcf": "Net Debt / FCF", "total_debt": "Debt",
                 "dividends": "Dividends", "payout_ratio": "Payout ratio",
                 "shares_outstanding": "Shares outstanding"}
RULE1_LABELS = {"roic": "ROIC", "bvps": "BVPS", "revenue": "Revenue", "eps_diluted": "EPS",
                "fcf": "Free Cash Flow", "net_debt_fcf": "Net Debt / FCF"}


def secret(name: str):
    try:
        return st.secrets.get(name)
    except Exception:  # no secrets file when run locally
        return None


@st.cache_data(ttl=600)
def load_manual():
    return manual.load(secret("MANUAL_SHEET_ID"))


@st.cache_data(ttl=600)
def load_stock(ticker: str):
    folder = DATA_DIR / ticker
    prices = read_csv(folder / "daily.csv", index_col="date", parse_dates=["date"])
    sq = read_csv(folder / "quarterly.csv", dtype={"period": str})
    sa = read_csv(folder / "annual.csv", dtype={"period": str})
    m = load_manual()
    man = manual.statements_for(m, ticker)
    q = metrics.quarterly(sq, man) if not (sq.empty and man.empty) else pd.DataFrame()
    a = metrics.annual(sq, sa, man) if not (sq.empty and sa.empty and man.empty) else pd.DataFrame()
    md = m["daily"][m["daily"]["ticker"] == ticker]
    d = metrics.daily(prices, q, md)
    return d, q, a, metrics.dcf(m["dcf"], ticker)


def fmt(value, metric=""):
    if pd.isna(value):
        return ""
    if metric in PERCENT:
        return f"{value:.1%}"
    if abs(value) >= 1e9:
        return f"{value / 1e9:,.2f} B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:,.1f} M"
    return f"{value:,.2f}"


# ---- Sidebar: search and chart options ----
watchlist = load_watchlist()
options = [f"{r.ticker} · {r.name}" for r in watchlist.itertuples()]
choice = st.sidebar.selectbox("Find a stock", options, index=0, placeholder="Type a name or ticker")
ticker = choice.split(" · ")[0]
stock = watchlist.set_index("ticker").loc[ticker]

daily_df, q_df, a_df, dcf_df = load_stock(ticker)

st.sidebar.markdown("### Graph")
available = [m for m in ALL_METRICS
             if (m in daily_df and daily_df[m].notna().any())
             or (m in q_df and q_df[m].notna().any())
             or (m in DCF_METRICS and not dcf_df.empty)]
selected = st.sidebar.multiselect("Variables", available, default=["close"],
                                  format_func=lambda m: ALL_METRICS[m], max_selections=4)
log_scale = st.sidebar.radio("Scale", ["Raw", "Logarithmic"], horizontal=True) == "Logarithmic"
needs_quarterly = any(m in QUARTERLY_METRICS for m in selected)
freq = st.sidebar.radio("Frequency", ["Daily", "Quarterly (daily values averaged)"],
                        index=1 if needs_quarterly else 0, disabled=needs_quarterly,
                        help="Graphs with quarterly metrics always average daily values per quarter.")
quarterly_mode = needs_quarterly or freq.startswith("Quarterly")
show_dcf = st.sidebar.checkbox("Show DCF range behind the price", value=not dcf_df.empty,
                               disabled=dcf_df.empty)

# ---- Header ----
st.title(f"{stock['name']} ({ticker})")
if daily_df.empty:
    st.warning("No data stored for this stock yet. It appears after the next daily update.")
    st.stop()
last = daily_df.dropna(subset=["close"]).iloc[-1]
cols = st.columns(5)
cols[0].metric(f"Price ({stock['currency']})", fmt(last["close"]), help=f"Close on {last.name:%d %b %Y}")
cols[1].metric("Trailing P/E", fmt(last.get("trailing_pe")))
cols[2].metric("Forward P/E", fmt(last.get("forward_pe")))
cols[3].metric("ROIC (TTM)", fmt(q_df["roic_ttm"].dropna().iloc[-1] if "roic_ttm" in q_df and q_df["roic_ttm"].notna().any() else None, "roic"))
if not dcf_df.empty:
    latest = dcf_df.iloc[-1]
    cols[4].metric(f"DCF middle ({dcf_df.index[-1]})", fmt(latest["middle"]),
                   help=f"Range {fmt(latest['low'])} to {fmt(latest['high'])}")

# ---- Graph ----
def series_for(metric: str) -> pd.Series:
    if metric in DCF_METRICS:
        s = dcf_df[metric.removeprefix("dcf_")] if not dcf_df.empty else pd.Series(dtype=float)
        s.index = [quarter_end(p) for p in s.index]
        return s
    if metric in QUARTERLY_METRICS:
        s = q_df[metric].dropna()
        s.index = [quarter_end(p) for p in s.index]
        return s
    s = daily_df[metric].dropna()
    if quarterly_mode:
        s = s.groupby(s.index.to_period("Q")).mean()
        s.index = s.index.to_timestamp(how="end").normalize()
    return s


fig = go.Figure()
axis_slots = [("left", 0.0), ("right", 1.0), ("left", 0.06), ("right", 0.94)]
price_axis = None
for i, metric in enumerate(selected):
    s = series_for(metric)
    axis = "y" if i == 0 else f"y{i + 1}"
    if metric == "close":
        price_axis = axis
    shape = "hv" if (metric in DCF_METRICS and not quarterly_mode) else "linear"
    fig.add_trace(go.Scatter(x=s.index, y=s.values, name=ALL_METRICS[metric], yaxis=axis,
                             mode="lines+markers" if quarterly_mode else "lines", line_shape=shape))
    side, pos = axis_slots[i]
    layout_key = "yaxis" if i == 0 else f"yaxis{i + 1}"
    spec = dict(title=ALL_METRICS[metric], side=side, type="log" if log_scale else "linear",
                tickformat=".0%" if metric in PERCENT else None, showgrid=i == 0)
    if i:
        spec.update(overlaying="y", anchor="free", position=pos, autoshift=True)
    fig.update_layout({layout_key: spec})

if show_dcf and not dcf_df.empty and price_axis:
    band = dcf_df[["low", "middle", "high"]]
    if quarterly_mode:
        x, shape = [quarter_end(p) for p in band.index], "linear"
    else:  # each quarter's range holds from the start of that quarter
        x = [quarter_start(p) for p in band.index] + [quarter_end(band.index[-1])]
        band, shape = pd.concat([band, band.iloc[[-1]]]), "hv"
    grey = "rgba(120, 120, 120, 0.8)"
    fig.add_trace(go.Scatter(x=x, y=band["low"], yaxis=price_axis, name="DCF low end", mode="lines",
                             line=dict(width=1, color=grey), line_shape=shape))
    fig.add_trace(go.Scatter(x=x, y=band["high"], yaxis=price_axis, name="DCF high end", mode="lines",
                             line=dict(width=1, color=grey), line_shape=shape,
                             fill="tonexty", fillcolor="rgba(120, 120, 120, 0.15)"))
    fig.add_trace(go.Scatter(x=x, y=band["middle"], yaxis=price_axis, name="DCF middle", mode="lines",
                             line=dict(width=1.5, dash="dash", color="rgba(60, 60, 60, 1)"), line_shape=shape))

fig.update_layout(height=520, hovermode="x unified", margin=dict(l=60, r=60, t=30, b=30),
                  legend=dict(orientation="h", y=-0.12), xaxis=dict(domain=[0.08, 0.92]))
st.plotly_chart(fig, use_container_width=True)

# ---- Rule #1 tables ----
st.subheader("Rule #1 growth (CAGR, latest year)")
growth = metrics.growth_table(a_df)
if growth.empty:
    st.info("Not enough yearly data yet.")
else:
    growth.index = [RULE1_LABELS[m] for m in growth.index]
    st.dataframe(growth.map(lambda v: "" if pd.isna(v) else f"{v:.1%}"), use_container_width=True)
    st.caption("Empty cells: not enough history yet, or a start/end value that is zero or negative.")

tab_y, tab_q, tab_dcf = st.tabs(["Yearly", "Quarterly", "DCF estimates"])
with tab_y:
    if not a_df.empty:
        cols = ["roic", "bvps", "revenue", "eps_diluted", "fcf", "net_debt_fcf", "total_debt",
                "dividends", "payout_ratio", "shares_outstanding"]
        t = a_df[[c for c in cols if c in a_df]].sort_index(ascending=False)
        t = t.apply(lambda col: col.map(lambda v: fmt(v, col.name)))
        t.columns = [YEARLY_LABELS.get(c, c) for c in t.columns]
        st.dataframe(t, use_container_width=True)
with tab_q:
    if not q_df.empty:
        cols = ["revenue", "revenue_ttm", "eps_diluted", "eps_diluted_ttm", "fcf", "fcf_ttm", "roic_ttm",
                "bvps", "total_debt", "cash", "net_debt_fcf_ttm", "dividends_ttm", "shares_outstanding"]
        t = q_df[[c for c in cols if c in q_df]].sort_index(ascending=False)
        t = t.apply(lambda col: col.map(lambda v: fmt(v, col.name)))
        t.columns = [QUARTERLY_METRICS.get(c, c.replace("_", " ")) for c in t.columns]
        st.dataframe(t, use_container_width=True)
with tab_dcf:
    if dcf_df.empty:
        st.info("No DCF estimates entered yet. Add them in the manual-entry sheet, tab 'dcf'.")
    else:
        st.dataframe(dcf_df.sort_index(ascending=False), use_container_width=True)

st.caption(f"All values in {stock['currency']}. Sources: SEC EDGAR (US), Yahoo Finance, and manual entries "
           "(manual values always win). TTM = trailing 12 months. Quarters are calendar quarters.")
