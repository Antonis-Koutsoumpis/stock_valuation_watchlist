"""Rule #1 stock valuation watchlist (Streamlit)."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rule1 import charts, manual, metrics, screener
from rule1.glossary import CAGR_HELP, DAILY, DCF, GRAPH, QUARTERLY, YEARLY, Metric
from rule1.periods import quarter_end, quarter_start
from rule1.store import DATA_DIR, read_csv
from rule1.update import load_watchlist

st.set_page_config(page_title="Rule #1 Watchlist", layout="wide")

COLORS = ["#1f77b4", "#d62728", "#9467bd", "#ff7f0e"]
DCF_FILL = "rgba(46, 139, 87, 0.22)"
DCF_LINE = "rgba(46, 139, 87, 0.9)"
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
    folder = DATA_DIR / ticker
    prices = read_csv(folder / "daily.csv", index_col="date", parse_dates=["date"])
    sq = read_csv(folder / "quarterly.csv", dtype={"period": str})
    sa = read_csv(folder / "annual.csv", dtype={"period": str})
    m = load_manual()
    man = manual.statements_for(m, ticker)
    q = metrics.quarterly(sq, man) if not (sq.empty and man.empty) else pd.DataFrame()
    a = metrics.annual(sq, sa, man) if not (sq.empty and sa.empty and man.empty) else pd.DataFrame()
    md = m["daily"][m["daily"]["ticker"] == ticker]
    row = load_watchlist().set_index("ticker").loc[ticker]
    fx = None
    if row.get("financial_currency") and row["financial_currency"] != row["currency"]:
        rates = read_csv(DATA_DIR / "_fx" / f"{row['financial_currency']}{row['currency']}.csv",
                         index_col="date", parse_dates=["date"])
        fx = rates["close"] if not rates.empty else None
    d = metrics.daily(prices, q, md, a, fx, float(row.get("adr_ratio") or 1))
    return d, q, a, metrics.dcf(m["dcf"], ticker)


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
                 or (m in DCF and not dcf_df.empty)]
    selected = st.sidebar.multiselect(
        "Variables", available, default=["close"], format_func=lambda m: GRAPH[m].label, max_selections=4,
        help="Up to 4, each with its own axis. Hover the ? next to each name under the graph to see what it means.")

    first, last_day = daily_df.index.min().date(), daily_df.index.max().date()
    picked = st.sidebar.date_input("Time range", value=(first, last_day), min_value=first, max_value=last_day,
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
        "Show DCF range boxes", value=not dcf_df.empty, disabled=dcf_df.empty or "close" not in selected,
        help="One box per quarter from the DCF low end to the high end, with the middle as a line. "
             "Shown with the Price variable.")

    st.sidebar.markdown("### Compare")
    indices = watchlist[watchlist["type"] == "index"]["ticker"].tolist()
    others = [t for t in indices + watchlist[watchlist["type"] != "index"]["ticker"].tolist() if t != ticker]
    names = watchlist.set_index("ticker")["name"]
    compare = st.sidebar.multiselect(
        "Compare performance with", others, format_func=lambda t: f"{t} · {names[t]}",
        help="Shows how much the price rose or fell (in %) since the start of the time range, "
             "for this stock and the ones you pick, e.g. the S&P 500 and Nasdaq 100.")

    # ---- Header ----
    last = daily_df.dropna(subset=["close"]).iloc[-1]
    roic = q_df["roic_ttm"].dropna().iloc[-1] if "roic_ttm" in q_df and q_df["roic_ttm"].notna().any() else None
    cols = st.columns(5)
    cols[0].metric(f"Price ({stock['currency']})", fmt(last["close"]),
                   help=f"{DAILY['close'].tooltip}\n\nClose on {last.name:%d %b %Y}.")
    cols[1].metric("Trailing P/E", fmt(last.get("trailing_pe")), help=DAILY["trailing_pe"].tooltip)
    cols[2].metric("Forward P/E", fmt(last.get("forward_pe")), help=DAILY["forward_pe"].tooltip)
    cols[3].metric("ROIC (TTM)", fmt(roic, percent=True), help=QUARTERLY["roic_ttm"].tooltip)
    if not dcf_df.empty:
        latest = dcf_df.iloc[-1]
        cols[4].metric(f"DCF middle ({dcf_df.index[-1]})", fmt(latest["middle"]),
                       help=f"{DCF['dcf_middle'].tooltip}\n\nRange {fmt(latest['low'])} to {fmt(latest['high'])}.")

    # ---- Graph ----
    def series_for(metric: str) -> pd.Series:
        if metric in DCF:
            s = dcf_df[metric.removeprefix("dcf_")].dropna()
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
        box_x, box_y, mid_x, mid_y, mid_text = [], [], [], [], []
        for q, r in dcf_df.iterrows():
            q0, q1 = quarter_start(q), quarter_end(q)
            if q1 < start or q0 > end or pd.isna(r["low"]) or pd.isna(r["high"]):
                continue
            box_x += [q0, q1, q1, q0, q0, None]
            box_y += [r["low"], r["low"], r["high"], r["high"], r["low"], None]
            if pd.notna(r["middle"]):
                text = f"DCF {q}: {fmt(r['low'])} to {fmt(r['high'])}, middle {fmt(r['middle'])}"
                mid_x += [q0, q1, None]
                mid_y += [r["middle"], r["middle"], None]
                mid_text += [text, text, None]
        fig.add_trace(go.Scatter(x=box_x, y=box_y, yaxis=price_axis, fill="toself", fillcolor=DCF_FILL,
                                 line=dict(color=DCF_LINE, width=0.5), mode="lines", name="DCF range (low to high)",
                                 hoverinfo="skip", legendgroup="dcf"))
        fig.add_trace(go.Scatter(x=mid_x, y=mid_y, yaxis=price_axis, mode="lines", name="DCF middle",
                                 line=dict(color=DCF_LINE, width=2), text=mid_text, hovertemplate="%{text}<extra></extra>",
                                 legendgroup="dcf"))

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
    st.subheader("Rule #1 growth (CAGR, latest year)", help=CAGR_HELP)
    growth = metrics.growth_table(a_df)
    if growth.empty:
        st.info("Not enough yearly data yet.")
    else:
        growth.index = [YEARLY[m].label for m in growth.index]
        config = {c: st.column_config.Column(help=f"Average growth per year over the last {c[:-1]} year(s).")
                  for c in growth.columns}
        st.dataframe(growth.map(lambda v: "" if pd.isna(v) else f"{v:.1%}"), use_container_width=True,
                     column_config=config)
        st.caption("Empty cells: not enough history yet, or a start/end value that is zero or negative.")

    tab_y, tab_q, tab_dcf = st.tabs(["Yearly", "Quarterly", "DCF estimates"])
    with tab_y:
        if not a_df.empty:
            show_table(a_df, YEARLY)
    with tab_q:
        if not q_df.empty:
            show_table(q_df, {**QUARTERLY, "cash": Metric("Cash", "Cash and cash equivalents at quarter end.", "Quarterly")})
    with tab_dcf:
        if dcf_df.empty:
            st.info("No DCF estimates entered yet. Add them in the manual-entry sheet, tab 'dcf'.")
        else:
            st.dataframe(dcf_df.sort_index(ascending=False), use_container_width=True)

    fin = stock.get("financial_currency") or stock["currency"]
    currency_note = (f"Prices in {stock['currency']}; financial statements in {fin} "
                     f"(converted to {stock['currency']} for P/E and similar ratios)."
                     if fin != stock["currency"] else f"All values in {stock['currency']}.")
    st.caption(f"{currency_note} Sources: SEC EDGAR (US), Yahoo Finance, and manual entries "
               "(manual values always win). TTM = trailing 12 months. Quarters are calendar quarters.")


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
def screener_page():
    st.title("Screener")
    st.write("Find watchlist stocks that meet all your conditions. Percent metrics take percent values "
             "(type 10 for 10%).")
    watchlist = load_watchlist()
    rows = {}
    for r in watchlist.itertuples():
        d, q, a, dcf = load_stock(r.ticker)
        rows[r.ticker] = {"name": r.name, "currency": r.currency, **screener.summary_row(d, q, a, dcf)}
    table = pd.DataFrame.from_dict(rows, orient="index")

    labels = [m.label for m in screener.COLUMNS.values()]
    default = pd.DataFrame([{"metric": "ROIC (TTM)", "operator": ">", "value": 10.0}])
    conditions = st.data_editor(
        default, num_rows="dynamic", use_container_width=True, key="conditions",
        column_config={
            "metric": st.column_config.SelectboxColumn("Metric", options=labels, required=True),
            "operator": st.column_config.SelectboxColumn("Condition", options=list(screener.OPERATORS), required=True),
            "value": st.column_config.NumberColumn("Value", help="For percent metrics, 10 means 10%.", required=True),
        })
    result = screener.apply_filters(table, conditions)
    st.caption(f"{len(result)} of {len(table)} stocks meet all conditions.")

    shown = result.copy()
    config = {"name": st.column_config.Column("Name"), "currency": st.column_config.Column("Currency")}
    for key, meta in screener.COLUMNS.items():
        if meta.percent:
            shown[key] = shown[key] * 100
        config[key] = st.column_config.NumberColumn(meta.label, help=meta.tooltip,
                                                    format="%.1f%%" if meta.percent else "%.2f")
    st.dataframe(shown[["name", "currency", *screener.COLUMNS]], use_container_width=True, column_config=config)


st.navigation([
    st.Page(stock_page, title="Stock", icon=":material/show_chart:", default=True),
    st.Page(screener_page, title="Screener", icon=":material/filter_alt:", url_path="screener"),
]).run()
