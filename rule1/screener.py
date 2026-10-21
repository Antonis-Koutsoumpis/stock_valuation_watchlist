"""One row of values per stock (precomputed by the daily update), and AND-filters on them."""

import operator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import valuation
from .glossary import CAGR_HELP, DAILY, QUARTERLY

SUMMARY_PATH = Path(__file__).resolve().parent.parent / "data" / "_summary" / "screener.csv"
YEARS = range(1, 11)
GROWTH = {"bvps": "BVPS", "eps_diluted": "EPS", "revenue": "Revenue", "fcf": "Free Cash Flow"}
OPERATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "=": operator.eq}


@dataclass(frozen=True)
class Filter:
    help: str
    periods: dict  # period label -> summary column
    percent: bool = False


def _years(fmt: str) -> dict:
    return {f"{n}y": fmt.format(n=n) for n in YEARS}


FILTERS = {
    "ROIC": Filter("Return on invested capital. Latest = last 12 months; Ny = average of the last N years. "
                   "Rule #1 looks for 10% or more.",
                   {"Latest": "roic_ttm", **_years("roic_avg_{n}y")}, percent=True),
    **{f"{label} growth": Filter(f"{label} growth per year over the last N years (CAGR). {CAGR_HELP}",
                                 _years(f"{key}_cagr_{{n}}y"), percent=True)
       for key, label in GROWTH.items()},
    "Trailing P/E": Filter(DAILY["trailing_pe"].help, {"Latest": "trailing_pe"}),
    "Forward P/E": Filter(DAILY["forward_pe"].help, {"Latest": "forward_pe"}),
    "Price/Book": Filter(DAILY["price_book"].help, {"Latest": "price_book"}),
    "Dividend yield": Filter(DAILY["trailing_div_yield"].help, {"Latest": "trailing_div_yield"}, percent=True),
    "Net Debt / FCF": Filter(QUARTERLY["net_debt_fcf_ttm"].help, {"Latest": "net_debt_fcf_ttm"}),
    "BVPS": Filter(QUARTERLY["bvps"].help, {"Latest": "bvps"}),
    "Price": Filter(DAILY["close"].help, {"Latest": "close"}),
    "Price / DCF middle": Filter("Price ÷ DCF middle from the sites you entered. "
                                 "Below 1 = the share trades below its estimated value.",
                                 {"Latest": "price_to_dcf"}),
    "Price / calculated value": Filter("Price ÷ the middle calculated value (default assumptions: 10 growth years, "
                                       "10% discount rate). Below 1 = the share trades below it.",
                                       {"Latest": "price_to_calc"}),
    "Price / Margin of Safety": Filter("Price ÷ the Rule #1 Margin of Safety price. At or below 1 = Phil Town's "
                                       "buy zone.", {"Latest": "price_to_mos"}),
}
PERIODS = ["Latest", *[f"{n}y" for n in YEARS]]

# Phil Town's Big 5: each should be 10% or more a year, over 10, 5 and 1 years.
DEFAULT_CONDITIONS = pd.DataFrame([
    {"metric": "ROIC", "period": "10y", "operator": ">=", "value": 10.0},
    {"metric": "BVPS growth", "period": "10y", "operator": ">=", "value": 10.0},
    {"metric": "EPS growth", "period": "10y", "operator": ">=", "value": 10.0},
    {"metric": "Revenue growth", "period": "10y", "operator": ">=", "value": 10.0},
    {"metric": "Free Cash Flow growth", "period": "10y", "operator": ">=", "value": 10.0},
])


def _last(df: pd.DataFrame, col: str):
    if df.empty or col not in df or df[col].notna().sum() == 0:
        return np.nan
    return df[col].dropna().iloc[-1]


def summary_row(daily: pd.DataFrame, quarterly: pd.DataFrame, annual: pd.DataFrame, dcf: pd.DataFrame) -> dict:
    row = {c: _last(daily, c) for c in ["close", "trailing_pe", "forward_pe", "price_book", "trailing_div_yield"]}
    row.update({c: _last(quarterly, c) for c in ["roic_ttm", "bvps", "net_debt_fcf_ttm"]})
    roic = annual["roic"].dropna() if "roic" in annual else pd.Series(dtype=float)
    for n in YEARS:
        row[f"roic_avg_{n}y"] = roic.iloc[-n:].mean() if len(roic) >= n else np.nan
        for key in GROWTH:
            row[f"{key}_cagr_{n}y"] = _last(annual, f"{key}_cagr_{n}y")
    row["dcf_middle"] = _last(dcf, "middle")
    row["price_to_dcf"] = row["close"] / row["dcf_middle"] if row["dcf_middle"] else np.nan
    calc = valuation.value(daily, quarterly, annual)
    row.update(calc_low=calc["range"]["low"], calc_middle=calc["range"]["middle"], calc_high=calc["range"]["high"],
               calc_mos=calc["mos"])
    row["price_to_calc"] = row["close"] / row["calc_middle"] if row["calc_middle"] > 0 else np.nan
    row["price_to_mos"] = row["close"] / row["calc_mos"] if row["calc_mos"] > 0 else np.nan
    return row


def build_summary(watchlist: pd.DataFrame, load) -> pd.DataFrame:
    """`load(row)` -> (daily, quarterly, yearly, dcf). Indices are left out."""
    rows = {}
    for ticker, r in watchlist.set_index("ticker").iterrows():
        if r.get("type") == "index":
            continue
        try:
            rows[ticker] = {"name": r["name"], "currency": r["currency"], **summary_row(*load(r))}
        except Exception as exc:  # one broken stock must not hide the others
            print(f"screener: {ticker} skipped: {exc}")
    table = pd.DataFrame.from_dict(rows, orient="index")
    table.index.name = "ticker"
    return table


def resolve(metric, period) -> tuple[str, str, Filter] | None:
    """(summary column, display label, filter) for a condition, or None if it doesn't apply."""
    f = FILTERS.get(metric)
    if f is None:
        return None
    if not isinstance(period, str) or period not in f.periods:
        period = next(iter(f.periods)) if len(f.periods) == 1 else None
    return (f.periods[period], f"{metric} ({period})", f) if period else None


def apply_filters(table: pd.DataFrame, conditions: pd.DataFrame) -> pd.DataFrame:
    """All conditions must hold (AND). Percent metrics take values in % (10 means 10%).
    A stock with no value for a condition fails it."""
    mask = pd.Series(True, index=table.index)
    for c in conditions.dropna(subset=["metric", "operator", "value"]).itertuples():
        resolved = resolve(c.metric, getattr(c, "period", None))
        if resolved is None or c.operator not in OPERATORS or resolved[0] not in table:
            continue
        column, _, f = resolved
        value = float(c.value) / 100 if f.percent else float(c.value)
        mask &= OPERATORS[c.operator](table[column], value).fillna(False)
    return table[mask]
