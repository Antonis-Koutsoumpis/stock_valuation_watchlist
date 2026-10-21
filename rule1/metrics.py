"""Rule #1 metrics from stored statements, prices and manual entries.

Priority for each (period, metric): manual > sec > yahoo.
ROIC = NOPAT / (Debt + Equity); FCF = Operating Cash Flow - CapEx.
"""

import numpy as np
import pandas as pd

from .manual import DCF_OVERRIDES, DCF_SOURCES
from .periods import quarter_end

SOURCE_PRIORITY = {"manual": 0, "sec": 1, "yahoo": 2}
FLOW_METRICS = ["revenue", "net_income", "eps_diluted", "operating_income", "pretax_income",
                "tax_provision", "operating_cash_flow", "capex", "dividends_paid", "nopat", "fcf"]
RULE1_METRICS = ["roic", "bvps", "revenue", "eps_diluted", "fcf", "net_debt_fcf"]
DEFAULT_TAX_RATE = 0.25
REPORTING_LAG = pd.Timedelta(days=45)  # results are public ~6 weeks after quarter end
ANNUAL_REPORTING_LAG = pd.Timedelta(days=90)  # annual reports come out later


def pick_values(statements: pd.DataFrame) -> pd.DataFrame:
    """Long rows from all sources -> wide table (period x metric) of the winning values."""
    if statements.empty:
        return pd.DataFrame()
    df = statements.assign(rank=statements["source"].map(SOURCE_PRIORITY).fillna(9))
    df = df.sort_values("rank").drop_duplicates(["period", "metric"], keep="first")
    wide = df.pivot(index="period", columns="metric", values="value").apply(pd.to_numeric, errors="coerce")
    return wide.sort_index()


def _col(df, name):
    return df[name] if name in df else pd.Series(np.nan, index=df.index)


def _derive(w: pd.DataFrame, flows: pd.DataFrame) -> pd.DataFrame:
    """Shared formulas. `flows` holds the 12-month flow values (TTM or fiscal year)."""
    out = pd.DataFrame(index=w.index)
    w, flows = w.astype(float), flows.astype(float)
    debt = _col(w, "total_debt").fillna(0.0)  # no debt reported -> no debt
    equity = _col(w, "equity")
    shares = _col(w, "shares_outstanding").fillna(_col(w, "diluted_shares"))
    out["revenue"] = flows["revenue"]
    out["eps_diluted"] = flows["eps_diluted"]
    out["net_income"] = flows["net_income"]
    out["nopat"] = flows["nopat"]
    out["fcf"] = flows["fcf"]
    out["roic"] = flows["nopat"] / (debt + equity)
    out["bvps"] = equity / shares
    out["equity"] = equity
    out["total_debt"] = _col(w, "total_debt")
    out["cash"] = _col(w, "cash")
    out["net_debt"] = debt - _col(w, "cash")
    out["net_debt_fcf"] = out["net_debt"] / flows["fcf"].where(flows["fcf"] > 0)
    out["shares_outstanding"] = shares
    out["dividends"] = flows["dividends_paid"]
    out["dividends_per_share"] = flows["dividends_paid"] / shares
    out["payout_ratio"] = flows["dividends_paid"] / flows["net_income"].where(flows["net_income"] > 0)
    return out.replace([np.inf, -np.inf], np.nan)


def _add_nopat_fcf(w: pd.DataFrame) -> pd.DataFrame:
    w = w.copy()
    pretax, tax = _col(w, "pretax_income"), _col(w, "tax_provision")
    rate = (tax / pretax.where(pretax > 0)).clip(0, 0.5)
    rate = rate.fillna(rate.median() if rate.notna().any() else DEFAULT_TAX_RATE)
    w["tax_rate"] = rate
    w["nopat"] = _col(w, "operating_income").fillna(pretax) * (1 - rate)
    w["fcf"] = _col(w, "operating_cash_flow") - _col(w, "capex")
    return w


def _apply_manual(df: pd.DataFrame, manual: pd.DataFrame, periods_like) -> pd.DataFrame:
    """Manual values for derived metrics (e.g. roic) also win."""
    df = df.copy()
    for r in manual[manual["period"].map(periods_like)].itertuples():
        if r.metric in df.columns:
            df.loc[r.period, r.metric] = r.value
    return df


def _is_quarter(p):
    return isinstance(p, str) and len(p) == 6 and p[4] == "Q"


def _is_year(p):
    return isinstance(p, str) and len(p) == 4 and p.isdigit()


def quarterly(statements: pd.DataFrame, manual: pd.DataFrame) -> pd.DataFrame:
    """Per quarter: reported quarter values plus trailing-12-month (TTM) Rule #1 metrics."""
    rows = pd.concat([statements, manual], ignore_index=True)
    w = pick_values(rows[rows["period"].map(_is_quarter)])
    if w.empty:
        return w
    full = pd.period_range(w.index.min(), w.index.max(), freq="Q").strftime("%YQ%q")
    w = _add_nopat_fcf(w.reindex(full))
    ttm = pd.DataFrame({m: _col(w, m).rolling(4, min_periods=4).sum() for m in FLOW_METRICS})
    out = _derive(w, ttm).add_suffix("_ttm")
    for m in ["revenue", "eps_diluted", "net_income", "fcf", "nopat", "operating_cash_flow", "capex", "dividends_paid"]:
        out[m] = _col(w, m)  # the quarter's own value
    for m in ["total_debt", "cash", "equity", "shares_outstanding"]:
        out[m] = _col(w, m)
        out = out.drop(columns=f"{m}_ttm", errors="ignore")
    out["bvps"] = out.pop("bvps_ttm")
    out["net_debt"] = out.pop("net_debt_ttm")
    out["period_end"] = [quarter_end(p) for p in out.index]
    out = _apply_manual(out, manual, _is_quarter)
    return out.dropna(how="all", subset=[c for c in out.columns if c != "period_end"])


def annual(statements_q: pd.DataFrame, statements_a: pd.DataFrame, manual: pd.DataFrame) -> pd.DataFrame:
    """Per year: reported fiscal-year values, filled from 4 quarters where missing,
    plus growth (CAGR) over 1 to 10 years."""
    rows = pd.concat([statements_a, manual], ignore_index=True)
    w = pick_values(rows[rows["period"].map(_is_year)])

    # Fill years missing from annual reports with sums of 4 calendar quarters.
    qrows = pd.concat([statements_q, manual], ignore_index=True)
    q = pick_values(qrows[qrows["period"].map(_is_quarter)])
    if not q.empty:
        q = q.assign(year=[p[:4] for p in q.index])
        counts = q.groupby("year").size()
        flow_cols = [c for c in q.columns if c in FLOW_METRICS]
        summed = q[q["year"].isin(counts[counts == 4].index)].groupby("year")[flow_cols].sum(min_count=4)
        last = q[[p.endswith("Q4") for p in q.index]].set_index("year").drop(columns=flow_cols, errors="ignore")
        from_q = summed.join(last, how="outer")
        w = from_q if w.empty else w.combine_first(from_q)
    if w.empty:
        return w
    full = [str(y) for y in range(int(w.index.min()), int(w.index.max()) + 1)]
    w = _add_nopat_fcf(w.reindex(full))
    flows = pd.DataFrame({m: _col(w, m) for m in FLOW_METRICS})
    out = _apply_manual(_derive(w, flows), manual, _is_year)
    for m in RULE1_METRICS:
        for n in range(1, 11):
            out[f"{m}_cagr_{n}y"] = cagr(out[m], n)
    return out.dropna(how="all")


def cagr(series: pd.Series, years: int) -> pd.Series:
    """(end / start)^(1/n) - 1, only when both ends are positive."""
    start = series.shift(years)
    ok = (series > 0) & (start > 0)
    return ((series / start) ** (1 / years) - 1).where(ok)


def growth_table(annual_df: pd.DataFrame) -> pd.DataFrame:
    """Latest year's CAGR per Rule #1 metric, 1 to 10 years."""
    if annual_df.empty:
        return pd.DataFrame()
    rows = {}
    for m in RULE1_METRICS:
        rows[m] = {f"{n}y": annual_df[f"{m}_cagr_{n}y"].dropna().iloc[-1]
                   if annual_df[f"{m}_cagr_{n}y"].notna().any() else np.nan for n in range(1, 11)}
    return pd.DataFrame(rows).T


def _as_of(dates: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """For each date, the values of the latest row already published (`available`)."""
    table = table.dropna(subset=["available"]).sort_values("available")
    return pd.merge_asof(dates, table, left_on="date", right_on="available").set_index("date")


def daily(prices: pd.DataFrame, quarterly_df: pd.DataFrame, manual_daily: pd.DataFrame,
          annual_df: pd.DataFrame | None = None, fx: pd.Series | None = None,
          adr_ratio: float = 1.0) -> pd.DataFrame:
    """Daily metrics: Yahoo's snapshot where captured, otherwise back-calculated from the
    close and the latest published figures: the last 4 quarters (period end + 45 days),
    or, where quarters are missing, the last yearly report (year end + 90 days).

    `fx`: daily rate from the reporting currency to the price currency, for stocks that
    report in another currency (e.g. TSMC: TWD -> USD). `adr_ratio`: ordinary shares per
    traded share (TSMC: 1 ADR = 5 shares)."""
    if prices.empty:
        return prices
    d = prices.sort_index().copy()
    cols = ["eps_diluted_ttm", "revenue_ttm", "bvps", "shares_outstanding",
            "dividends_per_share_ttm", "payout_ratio_ttm"]
    dates = d.reset_index()[["date"]]
    basis = pd.DataFrame(index=d.index, columns=cols, dtype=float)
    if not quarterly_df.empty:
        q = quarterly_df.assign(available=quarterly_df["period_end"] + REPORTING_LAG)
        basis = _as_of(dates, q[["available"] + [c for c in cols if c in q]]).reindex(columns=cols)
    if annual_df is not None and not annual_df.empty:
        a = annual_df.rename(columns={"eps_diluted": "eps_diluted_ttm", "revenue": "revenue_ttm",
                                      "dividends_per_share": "dividends_per_share_ttm",
                                      "payout_ratio": "payout_ratio_ttm"})
        a = a.assign(available=[pd.Timestamp(f"{y}-12-31") + ANNUAL_REPORTING_LAG for y in a.index])
        yearly = _as_of(dates, a[["available"] + [c for c in cols if c in a]]).reindex(columns=cols)
        basis = basis.combine_first(yearly)
    basis = basis.apply(pd.to_numeric, errors="coerce")
    if fx is not None and not fx.empty:
        rate = fx.sort_index().reindex(d.index, method="ffill")
        for col in ["eps_diluted_ttm", "revenue_ttm", "bvps", "dividends_per_share_ttm"]:
            basis[col] = basis[col] * rate
    if adr_ratio and adr_ratio != 1:
        for col in ["eps_diluted_ttm", "bvps", "dividends_per_share_ttm"]:
            basis[col] = basis[col] * adr_ratio
        basis["shares_outstanding"] = basis["shares_outstanding"] / adr_ratio
    close = d["close"]
    calc = {
        "trailing_pe": close / basis["eps_diluted_ttm"].where(basis["eps_diluted_ttm"] > 0),
        "price_sales": close * basis["shares_outstanding"] / basis["revenue_ttm"],
        "price_book": close / basis["bvps"].where(basis["bvps"] > 0),
        "trailing_div_yield": basis["dividends_per_share_ttm"] / close,
        "payout_ratio": basis["payout_ratio_ttm"],
    }
    for name, values in calc.items():
        d[f"{name}_calc"] = values
    d["market_cap"] = close * basis["shares_outstanding"]
    for name in ["trailing_pe", "forward_pe", "peg_5y", "price_sales", "price_book",
                 "trailing_div_yield", "forward_div_yield", "payout_ratio"]:
        yahoo, calc_col = _col(d, f"{name}_yahoo"), _col(d, f"{name}_calc")
        d[name] = yahoo.combine_first(calc_col)
    for r in manual_daily.itertuples():
        d.loc[pd.Timestamp(r.date), r.metric] = r.value
    return d.sort_index()


def dcf(manual_dcf: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Per quarter: low end (avg of 3 lowest), mean, median, high end (avg of 3 highest),
    and the chosen middle (mean or median). Values typed into dcf_low / dcf_average /
    dcf_high win over the calculated ones."""
    df = manual_dcf[manual_dcf["ticker"] == ticker]
    rows = []
    for r in df.itertuples():
        vals = sorted(v for v in (getattr(r, s) for s in DCF_SOURCES) if pd.notna(v))
        typed = {c: getattr(r, c, np.nan) for c in DCF_OVERRIDES}
        if not vals and all(pd.isna(v) for v in typed.values()):
            continue
        mean = float(np.mean(vals)) if vals else np.nan
        median = float(np.median(vals)) if vals else np.nan
        row = {
            "quarter": r.quarter, "n_estimates": len(vals),
            "low": float(np.mean(vals[:3])) if vals else np.nan, "mean": mean, "median": median,
            "high": float(np.mean(vals[-3:])) if vals else np.nan,
            "middle": median if r.middle != "mean" else mean, "middle_choice": r.middle,
        }
        for col, key in [("dcf_low", "low"), ("dcf_average", "middle"), ("dcf_high", "high")]:
            if pd.notna(typed[col]):
                row[key] = float(typed[col])
                if key == "middle":
                    row["middle_choice"] = "typed in"
        rows.append(row)
    return pd.DataFrame(rows).set_index("quarter").sort_index() if rows else pd.DataFrame()
