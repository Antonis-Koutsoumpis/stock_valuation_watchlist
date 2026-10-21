"""Rule #1 stock valuation watchlist (Streamlit)."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rule1 import build, charts, manual, metrics, screener, valuation
from rule1.glossary import CAGR_HELP, DAILY, DCF, GRAPH, QUARTERLY, YEARLY, Metric
from rule1.periods import quarter_end, quarter_start
from rule1.store import DATA_DIR, read_csv
from rule1.update import load_watchlist

st.set_page_config(page_title="Rule #1 Watchlist", layout="wide")

COLORS = ["#1f77b4", "#d62728", "#9467bd", "#ff7f0e"]
DCF_FILL = "rgba(46, 139, 87, 0.22)"
DCF_LINE = "rgba(46, 139, 87, 0.9)"
COMPARE_COLORS = ["#2ca02c", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
CALC_FILL = "rgba(255, 140, 0, 0.18)"
CALC_LINE = "rgba(230, 120, 0, 0.95)"
QUARTER_BAR_WIDTH = 75 * 24 * 3600 * 1000  # ms


def secret(name: str):
    try:
        return st.secrets.get(name)
    except Exception:  # no secrets file when run locally
        return None


@st.cache_data(ttl=600)
def load_manual():
    return manual.load(secret("MANUAL_SHEET_ID"))


@st.cache_data(ttl=600)
def load_close(ticker: str) -> pd.Series:
    prices = read_csv(DATA_DIR / ticker / "daily.csv", index_col="date", parse_dates=["date"])
    return prices["close"].dropna() if not prices.empty else pd.Series(dtype=float)


@st.cache_data(ttl=600)
def load_stock(ticker: str):
    return build.load_stock(load_watchlist().set_index("ticker").loc[ticker], load_manual())


@st.cache_data(show_spinner="Calculating the value…")
def load_valuation(ticker: str, horizon: int, discount: float, growth: float | None):
    daily_df, q_df, a_df, _ = load_stock(ticker)
    a = valuation.Assumptions(horizon=horizon, discount=discount, growth=growth)
    return valuation.value(daily_df, q_df, a_df, a), valuation.history(daily_df, q_df, a_df, a)


def add_boxes(fig, ranges: pd.DataFrame, axis: str, start, end, name: str, fill: str, line: str):
    """One box per quarter from low to high, with the middle as a line."""
    box_x, box_y, mid_x, mid_y, mid_text = [], [], [], [], []
    for q, r in ranges.iterrows():
        q0, q1 = quarter_start(q), quarter_end(q)
        if q1 < start or q0 > end or pd.isna(r["low"]) or pd.isna(r["high"]):
            continue
        box_x += [q0, q1, q1, q0, q0, None]
        box_y += [r["low"], r["low"], r["high"], r["high"], r["low"], None]
        if pd.notna(r["middle"]):
            text = f"{name} {q}: {fmt(r['low'])} to {fmt(r['high'])}, middle {fmt(r['middle'])}"
            mid_x += [q0, q1, None]
            mid_y += [r["middle"], r["middle"], None]
            mid_text += [text, text, None]
    fig.add_trace(go.Scatter(x=box_x, y=box_y, yaxis=axis, fill="toself", fillcolor=fill,
                             line=dict(color=line, width=0.5), mode="lines", name=f"{name} (low to high)",
                             hoverinfo="skip", legendgroup=name))
    fig.add_trace(go.Scatter(x=mid_x, y=mid_y, yaxis=axis, mode="lines", name=f"{name} middle",
                             line=dict(color=line, width=2), text=mid_text, hovertemplate="%{text}<extra></extra>",
                             legendgroup=name))


def fmt(value, percent=False):
    if value is None or pd.isna(value):
        return ""
    if percent:
        return f"{value:.1%}"
    if abs(value) >= 1e9:
        return f"{value / 1e9:,.2f} B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:,.1f} M"
    return f"{value:,.2f}"


def quarter_mid(label: str) -> pd.Timestamp:
    start = quarter_start(label)
    return start + (quarter_end(label) - start) / 2


GREEN = "background-color: rgba(76, 175, 80, 0.25)"
ROW_LABELS = {"roic": "ROIC (average)", "net_debt_fcf": "Net Debt / FCF (average)", "bvps": "BVPS growth",
              "revenue": "Revenue growth", "eps_diluted": "EPS growth", "fcf": "Free Cash Flow growth"}


def rule1_ok(metric: str, v) -> bool:
    if pd.isna(v):
        return False
    return v <= 3 if metric == "net_debt_fcf" else v >= 0.10


def rule1_styler(growth: pd.DataFrame):
    """Rule #1 table with cells that meet the rule in green."""
    green = pd.DataFrame([[GREEN if rule1_ok(m, v) else "" for v in row] for m, row in growth.iterrows()],
                         index=growth.index, columns=growth.columns)
    text = pd.DataFrame([[fmt(v, percent=m != "net_debt_fcf") for v in row] for m, row in growth.iterrows()],
                        index=growth.index, columns=growth.columns)
    text.index = green.index = [ROW_LABELS.get(m, m) for m in growth.index]
    return text.style.apply(lambda _: green, axis=None)


def show_table(df: pd.DataFrame, glossary: dict):
    """Formatted table; hovering a column header shows what the metric means."""
    cols = [c for c in glossary if c in df]
    t = df[cols].sort_index(ascending=False)
    t = t.apply(lambda col: col.map(lambda v: fmt(v, glossary[col.name].percent)))
    t.columns = [glossary[c].label for c in cols]
    config = {glossary[c].label: st.column_config.Column(help=glossary[c].tooltip) for c in cols}
    st.dataframe(t, use_container_width=True, column_config=config)


# ---------------------------------------------------------------- stock page
def stock_page():
    watchlist = load_watchlist()
    options = [f"{r.ticker} · {r.name}" for r in watchlist.itertuples()]
    choice = st.sidebar.selectbox("Find a stock", options, index=0, placeholder="Type a name or ticker")
    ticker = choice.split(" · ")[0]
    stock = watchlist.set_index("ticker").loc[ticker]
    daily_df, q_df, a_df, dcf_df = load_stock(ticker)

    st.title(f"{stock['name']} ({ticker})")
    if daily_df.empty:
        st.warning("No data stored for this stock yet. It appears after the next daily update.")
        return

    # ---- Sidebar: graph options ----
    st.sidebar.markdown("### Graph")
    available = [m for m in GRAPH
                 if (m in daily_df and daily_df[m].notna().any())
                 or (m in q_df and q_df[m].notna().any())
                 or (m in DCF and "close" in daily_df)]
    selected = st.sidebar.multiselect(
        "Variables", available, default=["close"], format_func=lambda m: GRAPH[m].label, max_selections=4,
        help="Up to 4, each with its own axis. Hover the ? next to each name under the graph to see what it means.")

    first, last_day = daily_df.index.min().date(), daily_df.index.max().date()
    default_start = max(first, (pd.Timestamp(last_day) - pd.DateOffset(years=5)).date())
    picked = st.sidebar.date_input("Time range", value=(default_start, last_day), min_value=first, max_value=last_day,
                                   help="Or drag across the graph to zoom in, and double-click it to zoom back out.")
    start, end = (pd.Timestamp(picked[0]), pd.Timestamp(picked[1])) if len(picked) == 2 else (pd.Timestamp(first), pd.Timestamp(last_day))

    log_scale = st.sidebar.radio("Scale", ["Raw", "Logarithmic"], horizontal=True) == "Logarithmic"
    needs_quarterly = any(m in QUARTERLY or m in DCF for m in selected)
    freq = st.sidebar.radio("Frequency", ["Daily", "Quarterly"], horizontal=True,
                            index=1 if needs_quarterly else 0, disabled=needs_quarterly,
                            help="Quarterly averages the daily values of each quarter and shows the price as bars. "
                                 "Graphs with quarterly metrics are always quarterly.")
    quarterly_mode = needs_quarterly or freq == "Quarterly"
    bar_values = st.sidebar.toggle("Show values on bars", value=False, disabled=not quarterly_mode)

    trends = st.sidebar.multiselect(
        "Trend lines", charts.TRENDS,
        help="Linear: straight line. Polynomial: a curve that can bend. "
             "Log: constant growth per year (a straight line on a log scale); the legend shows the yearly growth.")
    degree = st.sidebar.slider("Polynomial degree", 2, 5, 2) if "Polynomial" in trends else 2
    averages = st.sidebar.multiselect(
        "Average lines", [5, 10], format_func=lambda y: f"{y}-year average",
        help="Dotted line at the average of each variable over the last 5 or 10 years of the time range.")
    show_dcf = st.sidebar.checkbox(
        "Show DCF range boxes (from the sites)", value=False, disabled=dcf_df.empty or "close" not in selected,
        help="One box per quarter from the DCF low end to the high end, with the middle as a line. "
             "Shown with the Price variable.")

    st.sidebar.markdown("### Compare")
    indices = watchlist[watchlist["type"] == "index"]["ticker"].tolist()
    others = [t for t in indices + watchlist[watchlist["type"] != "index"]["ticker"].tolist() if t != ticker]
    names = watchlist.set_index("ticker")["name"]
    compare = st.sidebar.multiselect(
        "Compare with (stocks or indices)", others, format_func=lambda t: f"{t} · {names[t]}",
        help="Adds the stocks or indices you pick (e.g. the S&P 500 and Nasdaq 100) to the price graph as dashed "
             "lines, scaled to start at this stock's price, so you see which grew more. A second graph below "
             "shows the change in %.")

    st.sidebar.markdown("### Calculated value", help=valuation.HELP)
    horizon = st.sidebar.slider("Growth years (before the terminal value)", 5, 10, 10,
                                help="How many years the company keeps growing at the growth rate. After that it "
                                     "grows 3% a year forever: that later part is the terminal value.")
    discount = st.sidebar.slider("Discount rate (%)", 6.0, 15.0, 10.0, 0.5,
                                 help="The yearly return you want. Middle scenario; conservative uses 2% more and "
                                      "optimistic 2% less. A higher rate gives a lower value.") / 100
    own_growth = st.sidebar.number_input(
        "Your growth rate (%)", min_value=0.0, max_value=30.0, value=None, step=1.0, placeholder="From the data",
        help="Empty: the median of the stock's 5- and 10-year growth (EPS, FCF, book value, revenue) and the "
             "analysts' 5-year estimate, between 0% and 20% (see the 'Calculated value' tab). If you type a rate, "
             "it is the middle scenario (conservative 3% lower, optimistic 3% higher).")
    calc, calc_hist = load_valuation(ticker, horizon, discount, None if own_growth is None else own_growth / 100)
    show_calc = st.sidebar.checkbox(
        "Show calculated value boxes", value=False, disabled=calc_hist.empty or "close" not in selected,
        help="One box per quarter from the conservative to the optimistic value, with the middle as a line, "
             "calculated with the data published by then. Shown with the Price variable.")

    # ---- Header ----
    last = daily_df.dropna(subset=["close"]).iloc[-1]
    roic = q_df["roic_ttm"].dropna().iloc[-1] if "roic_ttm" in q_df and q_df["roic_ttm"].notna().any() else None
    cols = st.columns(6)
    cols[0].metric(f"Price ({stock['currency']})", fmt(last["close"]),
                   help=f"{DAILY['close'].tooltip}\n\nClose on {last.name:%d %b %Y}.")
    cols[1].metric("Trailing P/E", fmt(last.get("trailing_pe")), help=DAILY["trailing_pe"].tooltip)
    cols[2].metric("Forward P/E", fmt(last.get("forward_pe")), help=DAILY["forward_pe"].tooltip)
    cols[3].metric("ROIC (TTM)", fmt(roic, percent=True), help=QUARTERLY["roic_ttm"].tooltip)
    if not dcf_df.empty:
        latest = dcf_df.iloc[-1]
        cols[4].metric(f"DCF middle ({dcf_df.index[-1]})", fmt(latest["middle"]),
                       help=f"{DCF['dcf_middle'].tooltip}\n\nRange {fmt(latest['low'])} to {fmt(latest['high'])}.")
    else:
        cols[4].metric("Margin of Safety price", fmt(calc["mos"]),
                       help="Rule #1: half the Sticker Price (middle scenario). Phil Town buys at or below it.")
    rng = calc["range"]
    cols[5].metric("Calculated value", fmt(rng["middle"]),
                   help=f"Median of all methods, middle scenario (see the 'Calculated value' tab). Range {fmt(rng['low'])} "
                        f"to {fmt(rng['high'])}; Rule #1 Margin of Safety price {fmt(calc['mos'])}.")

    # ---- Graph ----
    def series_for(metric: str) -> pd.Series:
        if metric in DCF:
            src = dcf_df if not dcf_df.empty else calc_hist  # calculated estimates until some are typed in
            s = src[metric.removeprefix("dcf_")].dropna()
            s.index = pd.DatetimeIndex([quarter_mid(p) for p in s.index])
        elif metric in QUARTERLY:
            s = q_df[metric].dropna()
            s.index = pd.DatetimeIndex([quarter_mid(p) for p in s.index])
        else:
            s = daily_df[metric].dropna()
            if quarterly_mode:
                s = s.groupby(s.index.to_period("Q")).mean()
                s.index = pd.DatetimeIndex([quarter_mid(str(p)) for p in s.index])
        return s[(s.index >= start) & (s.index <= end + pd.Timedelta(days=1))]

    fig = go.Figure()
    axis_slots = [("left", 0.0), ("right", 1.0), ("left", 0.06), ("right", 0.94)]
    price_axis = None
    first_dates = []
    for i, metric in enumerate(selected):
        meta, color = GRAPH[metric], COLORS[i]
        s = series_for(metric)
        if not s.empty:
            first_dates.append(s.index.min())
        axis = "y" if i == 0 else f"y{i + 1}"
        if metric == "close":
            price_axis = axis
        if metric == "close" and quarterly_mode:
            fig.add_trace(go.Bar(
                x=s.index, y=s.values, name=f"{meta.label} (quarter average)", yaxis=axis, width=QUARTER_BAR_WIDTH,
                marker_color=color, opacity=0.65,
                text=[fmt(v) for v in s.values] if bar_values else None, textposition="outside"))
        else:
            fig.add_trace(go.Scatter(x=s.index, y=s.values, name=meta.label, yaxis=axis,
                                     mode="lines+markers" if quarterly_mode or len(s) < 30 else "lines",
                                     line=dict(color=color),
                                     text=[fmt(v) for v in s.values] if bar_values and quarterly_mode else None,
                                     textposition="top center"))
            if bar_values and quarterly_mode:
                fig.data[-1].mode = "lines+markers+text"
        for kind in trends:
            fitted, label = charts.trend(s, kind, degree)
            if not fitted.empty:
                fig.add_trace(go.Scatter(x=fitted.index, y=fitted.values, name=f"{meta.label}: {label}", yaxis=axis,
                                         mode="lines", line=dict(color=color, dash="dash", width=1.5)))
        for years in averages:
            avg = charts.trailing_average(s, years)
            if avg:
                a_start, a_end, value = avg
                fig.add_trace(go.Scatter(
                    x=[a_start, a_end], y=[value, value], yaxis=axis, mode="lines",
                    name=f"{meta.label}: {years}-yr average ({fmt(value, meta.percent)})",
                    line=dict(color=color, dash="dot", width=2)))
        side, pos = axis_slots[i]
        spec = dict(title=meta.label, side=side, type="log" if log_scale else "linear",
                    tickformat=".0%" if meta.percent else None, showgrid=i == 0)
        if i:
            spec.update(overlaying="y", anchor="free", position=pos, autoshift=True)
        fig.update_layout({"yaxis" if i == 0 else f"yaxis{i + 1}": spec})

    if show_dcf and not dcf_df.empty and price_axis:
        add_boxes(fig, dcf_df, price_axis, start, end, "DCF sites", DCF_FILL, DCF_LINE)
    if show_calc and not calc_hist.empty and price_axis:
        add_boxes(fig, calc_hist, price_axis, start, end, "Calculated value", CALC_FILL, CALC_LINE)

    if compare and price_axis:
        # Compared stocks and indices on the price axis, scaled to start at this stock's price.
        own = daily_df["close"].dropna()
        own = own[(own.index >= start) & (own.index <= end + pd.Timedelta(days=1))]
        for j, t in enumerate(compare):
            other = load_close(t)
            other = other[(other.index >= start) & (other.index <= end + pd.Timedelta(days=1))]
            common = own.index.intersection(other.index)
            if common.empty:
                continue
            first_day = common.min()
            scaled = other[other.index >= first_day] * own[first_day] / other[first_day]
            change = scaled.iloc[-1] / scaled.iloc[0] - 1
            if quarterly_mode:
                scaled = scaled.groupby(scaled.index.to_period("Q")).mean()
                scaled.index = pd.DatetimeIndex([quarter_mid(str(p)) for p in scaled.index])
            fig.add_trace(go.Scatter(
                x=scaled.index, y=scaled.values, yaxis=price_axis, mode="lines",
                name=f"{t} · {names[t]} (scaled, {change:+.0%})",
                line=dict(color=COMPARE_COLORS[j % len(COMPARE_COLORS)], width=1.5, dash="dash")))

    # The graph starts at the first date with data for the selected variables.
    x_start = max(start, min(first_dates) - pd.Timedelta(days=45)) if first_dates else start
    fig.update_layout(
        height=580, hovermode="x unified", margin=dict(l=60, r=60, t=40, b=30), bargap=0,
        legend=dict(orientation="h", y=-0.28),
        xaxis=dict(domain=[0.08, 0.92], range=[x_start, end + pd.Timedelta(days=1)],
                   rangeslider=dict(visible=True, thickness=0.06),
                   rangeselector=dict(buttons=[
                       dict(count=1, label="1y", step="year", stepmode="backward"),
                       dict(count=3, label="3y", step="year", stepmode="backward"),
                       dict(count=5, label="5y", step="year", stepmode="backward"),
                       dict(count=10, label="10y", step="year", stepmode="backward"),
                       dict(step="all", label="All")])))
    st.plotly_chart(fig, use_container_width=True)

    if compare:
        perf_chart(ticker, compare, names, start, end)

    if selected:
        legend_cols = st.columns(len(selected))
        for col, metric in zip(legend_cols, selected):
            col.markdown(f"**{GRAPH[metric].label}**", help=GRAPH[metric].tooltip)

    # ---- Rule #1 tables ----
    st.subheader("Rule #1 numbers (latest year)", help=CAGR_HELP)
    growth = metrics.growth_table(a_df)
    if growth.empty:
        st.info("Not enough yearly data yet.")
    else:
        st.dataframe(rule1_styler(growth), use_container_width=True, column_config={
            c: st.column_config.Column(help=f"Over the last {c[:-1]} year(s).") for c in growth.columns})
        st.caption("Green = meets Rule #1: ROIC and growth 10% or more a year; debt payable from 3 years of free "
                   "cash flow or less (Net Debt / FCF ≤ 3, negative = more cash than debt). ROIC and Net Debt / FCF "
                   "are averages over the period; the others are growth per year (CAGR). Empty cells: not enough "
                   "history yet, or a start/end value that is zero or negative.")

    tab_y, tab_q, tab_calc, tab_dcf = st.tabs(["Yearly", "Quarterly", "Calculated value", "DCF estimates"])
    with tab_y:
        if not a_df.empty:
            show_table(a_df, YEARLY)
    with tab_q:
        if not q_df.empty:
            show_table(q_df, {**QUARTERLY, "cash": Metric("Cash", "Cash and cash equivalents at quarter end.", "Quarterly")})
    with tab_calc:
        calculated_value_tab(calc, stock["currency"], horizon, discount)
    with tab_dcf:
        if dcf_df.empty:
            st.info("No DCF estimates typed in yet, so this shows the calculated estimates of every method "
                    "(middle scenario) at the end of each quarter, with the data published by then. "
                    "Typed-in estimates (manual-entry sheet, tab 'dcf') will replace them.")
            hist = calc_hist.sort_index(ascending=False)
            hist = hist[["low", "middle", "high", "mos", *[m for m in valuation.METHODS if m in hist]]]
            st.dataframe(hist.map(fmt), use_container_width=True, column_config={
                "low": st.column_config.Column("Low (conservative)", help="Median of all methods, conservative scenario."),
                "middle": st.column_config.Column("Middle", help="Median of all methods, middle scenario."),
                "high": st.column_config.Column("High (optimistic)", help="Median of all methods, optimistic scenario."),
                "mos": st.column_config.Column("Margin of Safety", help="Half the Rule #1 Sticker Price."),
                **{m: st.column_config.Column(m, help=h) for m, h in valuation.METHOD_HELP.items()}})
        else:
            st.dataframe(dcf_df.sort_index(ascending=False), use_container_width=True)

    fin = stock.get("financial_currency") or stock["currency"]
    currency_note = (f"Prices in {stock['currency']}; financial statements in {fin} "
                     f"(converted to {stock['currency']} for P/E and similar ratios)."
                     if fin != stock["currency"] else f"All values in {stock['currency']}.")
    st.caption(f"{currency_note} Sources: SEC EDGAR (US), Yahoo Finance, and manual entries "
               "(manual values always win). TTM = trailing 12 months. Quarters are calendar quarters.")


def calculated_value_tab(calc: dict, currency: str, horizon: int, discount: float):
    st.markdown(valuation.HELP)
    with st.expander("How each method works"):
        st.markdown("\n".join(f"- **{m}**: {h}" for m, h in valuation.METHOD_HELP.items()))
    if not calc["growth"]:
        st.info("No value: the stock has no positive growth history or analyst estimate yet.")
        return
    inp = calc["inputs"]
    table = calc["table"].copy()
    table.loc["Median of all methods"] = table.median()
    table["Price / middle"] = inp["price"] / table["Middle"]
    st.dataframe(table.map(lambda v: fmt(v)), use_container_width=True, column_config={
        "Conservative": st.column_config.Column(help="Lowest growth rates, discount rate + 2%, final growth 2%."),
        "Middle": st.column_config.Column(help="Middle growth rate, your discount rate, final growth 3%."),
        "Optimistic": st.column_config.Column(help="Highest growth rates, discount rate − 2%, final growth 3%."),
        "Price / middle": st.column_config.Column(help="Below 1: the price is below the calculated value."),
    })
    st.caption(f"Values per share in {currency}. Rule #1 Margin of Safety price (half the middle Sticker Price): "
               f"{fmt(calc['mos'])}. Empty cells: the starting value (EPS or FCF) is zero or negative.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Growth rate used**", help="Conservative = 25th percentile of the rates on the right, "
                    "middle = median, optimistic = 75th percentile; between 0% and 20% a year.")
        st.dataframe(pd.Series({s: fmt(g, percent=True) for s, g in calc["growth"].items()}, name="per year"),
                     use_container_width=True)
        st.markdown("**Starting values**")
        st.dataframe(pd.Series({
            "Price": fmt(inp["price"]), "EPS (last 12 months)": fmt(inp["eps"]),
            "FCF per share (last 12 months)": fmt(inp["fcf_per_share"]),
            "Average P/E (10 years)": fmt(inp["avg_pe"]),
            "Growth years": str(horizon), "Discount rate": fmt(discount, percent=True)}, name="value"),
            use_container_width=True)
    with c2:
        st.markdown("**Growth rates found**", help="Yearly growth (CAGR) over 5 and 10 years from the statements, "
                    "and the analysts' 5-year estimate (Yahoo's P/E ÷ PEG).")
        st.dataframe(pd.Series({k: fmt(v, percent=True) for k, v in calc["candidates"].items()}, name="per year"),
                     use_container_width=True)


def perf_chart(ticker, compare, names, start, end):
    """Price change in % since the first date all chosen series have in common."""
    log_scale = st.radio("Comparison scale", ["Logarithmic", "Raw"], horizontal=True,
                         help="Logarithmic: the same % growth looks the same at any time, which makes long "
                              "periods comparable. Raw: change in %.") == "Logarithmic"
    series = {t: load_close(t) for t in [ticker, *compare]}
    series = {t: s[(s.index >= start) & (s.index <= end + pd.Timedelta(days=1))] for t, s in series.items()}
    series = {t: s for t, s in series.items() if not s.empty}
    if len(series) < 2:
        st.info("Not enough overlapping price history to compare.")
        return
    common_start = max(s.index.min() for s in series.values())
    fig = go.Figure()
    for i, (t, s) in enumerate(series.items()):
        s = s[s.index >= common_start]
        change = s / s.iloc[0] - 1
        years = (s.index[-1] - s.index[0]).days / 365.25
        per_year = (1 + change.iloc[-1]) ** (1 / years) - 1 if years >= 1 and change.iloc[-1] > -1 else None
        per_year_text = f", {per_year:+.1%}/yr" if per_year is not None else ""
        fig.add_trace(go.Scatter(
            x=change.index, y=(1 + change) if log_scale else change, mode="lines",
            name=f"{t} · {names[t]} ({change.iloc[-1]:+.0%}{per_year_text})",
            line=dict(width=2.5 if t == ticker else 1.5, color=COLORS[i % len(COLORS)] if t == ticker else None),
            hovertemplate="%{y:.1%}<extra>" + t + "</extra>" if not log_scale else "%{y:.2f}×<extra>" + t + "</extra>"))
    fig.update_layout(
        title=f"Performance since {common_start:%d %b %Y}", height=420, hovermode="x unified",
        margin=dict(l=60, r=30, t=50, b=30), legend=dict(orientation="h", y=-0.15),
        yaxis=dict(title="Growth of 1 (×)" if log_scale else "Change since start",
                   type="log" if log_scale else "linear", tickformat=None if log_scale else ".0%"))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Price change only, without dividends. Starts on the first date all chosen series have data, "
               "within the time range.")


# ---------------------------------------------------------------- screener page
@st.cache_data(ttl=600)
def load_screener_table() -> pd.DataFrame:
    if screener.SUMMARY_PATH.exists():
        return pd.read_csv(screener.SUMMARY_PATH, index_col="ticker")
    # Not built yet (before the first daily update): calculate it now, once.
    return screener.build_summary(load_watchlist(), lambda row: build.load_stock(row, load_manual()))


def screener_page():
    st.title("Screener")
    st.write("Find watchlist stocks that meet all your conditions. The default conditions are Phil Town's "
             "Big 5: ROIC, and growth of BVPS, EPS, Revenue and Free Cash Flow, each 10% or more a year. "
             "Change the period (1 to 10 years), remove a row, or add your own. Percent metrics take "
             "percent values (type 10 for 10%).")
    table = load_screener_table()

    conditions = st.data_editor(
        screener.DEFAULT_CONDITIONS, num_rows="dynamic", use_container_width=True, key="conditions",
        column_config={
            "metric": st.column_config.SelectboxColumn("Metric", options=list(screener.FILTERS), required=True,
                                                       help="Hover the column headers of the results for what each means."),
            "period": st.column_config.SelectboxColumn(
                "Period", options=screener.PERIODS,
                help="Latest = today's value or the last 12 months. Ny = over the last N years: the yearly "
                     "growth (CAGR) for growth metrics, the average for ROIC."),
            "operator": st.column_config.SelectboxColumn("Condition", options=list(screener.OPERATORS), required=True),
            "value": st.column_config.NumberColumn("Value", help="For percent metrics, 10 means 10%.", required=True),
        })
    resolved = [screener.resolve(c.metric, c.period) for c in conditions.dropna(subset=["metric"]).itertuples()]
    for c, r in zip(conditions.dropna(subset=["metric"]).itertuples(), resolved):
        if r is None:
            st.warning(f"'{c.metric}' needs one of these periods: {', '.join(screener.FILTERS[c.metric].periods)}"
                       if c.metric in screener.FILTERS else f"Unknown metric '{c.metric}'.")
    result = screener.apply_filters(table, conditions)
    st.caption(f"{len(result)} of {len(table)} stocks meet all conditions. Stocks without enough history "
               "for a condition don't pass it (most non-US stocks have 4 years until older data is added).")

    columns = {"close": ("Price", screener.FILTERS["Price"]), "trailing_pe": ("Trailing P/E", screener.FILTERS["Trailing P/E"]),
               "calc_middle": ("Calculated value", screener.Filter(valuation.HELP, {})),
               "price_to_calc": ("Price / calculated value", screener.FILTERS["Price / calculated value"])}
    for r in resolved:
        if r:
            columns[r[0]] = (r[1], r[2])
    shown = result[["name", "currency", *[c for c in columns if c in result]]].copy()
    config = {"name": st.column_config.Column("Name"), "currency": st.column_config.Column("Currency")}
    for col, (label, f) in columns.items():
        if col not in shown:
            continue
        if f.percent:
            shown[col] = shown[col] * 100
        config[col] = st.column_config.NumberColumn(label, help=f.help, format="%.1f%%" if f.percent else "%.2f")
    st.dataframe(shown, use_container_width=True, column_config=config)
    st.caption("Values are recalculated with every daily update.")


st.navigation([
    st.Page(stock_page, title="Stock", icon=":material/show_chart:", default=True),
    st.Page(screener_page, title="Screener", icon=":material/filter_alt:", url_path="screener"),
]).run()
