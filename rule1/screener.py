"""One row of latest values per stock, and AND-filters on them."""

import operator

import numpy as np
import pandas as pd

from .glossary import CAGR_HELP, DAILY, QUARTERLY, YEARLY, Metric

COLUMNS = {
    "close": DAILY["close"],
    "trailing_pe": DAILY["trailing_pe"],
    "forward_pe": DAILY["forward_pe"],
    "price_book": DAILY["price_book"],
    "trailing_div_yield": DAILY["trailing_div_yield"],
    "roic_ttm": QUARTERLY["roic_ttm"],
    "roic": YEARLY["roic"],
    "bvps": QUARTERLY["bvps"],
    "eps_diluted_ttm": QUARTERLY["eps_diluted_ttm"],
    "net_debt_fcf_ttm": QUARTERLY["net_debt_fcf_ttm"],
    **{f"{m}_cagr_5y": Metric(f"{YEARLY[m].label} growth 5y", CAGR_HELP, "Yearly", percent=True)
       for m in ["roic", "bvps", "revenue", "eps_diluted", "fcf"]},
    **{f"{m}_cagr_1y": Metric(f"{YEARLY[m].label} growth 1y", CAGR_HELP, "Yearly", percent=True)
       for m in ["bvps", "revenue", "eps_diluted", "fcf"]},
    "dcf_middle": Metric("DCF middle", "Latest middle estimate of what one share is worth.", "Quarterly (entered by hand)"),
    "price_to_dcf": Metric("Price / DCF middle",
                           "Price ÷ DCF middle. Below 1 = the share trades below its estimated value.",
                           "Daily"),
}
OPERATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "=": operator.eq}


def _last(df: pd.DataFrame, col: str):
    if df.empty or col not in df or df[col].notna().sum() == 0:
        return np.nan
    return df[col].dropna().iloc[-1]


def summary_row(daily: pd.DataFrame, quarterly: pd.DataFrame, annual: pd.DataFrame, dcf: pd.DataFrame) -> dict:
    row = {c: _last(daily, c) for c in ["close", "trailing_pe", "forward_pe", "price_book", "trailing_div_yield"]}
    row.update({c: _last(quarterly, c) for c in ["roic_ttm", "bvps", "eps_diluted_ttm", "net_debt_fcf_ttm"]})
    row["roic"] = _last(annual, "roic")
    for col in COLUMNS:
        if "_cagr_" in col:
            row[col] = _last(annual, col)
    row["dcf_middle"] = _last(dcf, "middle")
    row["price_to_dcf"] = row["close"] / row["dcf_middle"] if row["dcf_middle"] else np.nan
    return row


def apply_filters(table: pd.DataFrame, conditions: pd.DataFrame) -> pd.DataFrame:
    """conditions: rows of (metric label, operator, value). Percent metrics take values in %
    (10 means 10%). All conditions must hold (AND). A stock with no value fails the condition."""
    by_label = {m.label: (key, m) for key, m in COLUMNS.items()}
    mask = pd.Series(True, index=table.index)
    for c in conditions.dropna(subset=["metric", "operator", "value"]).itertuples():
        if c.metric not in by_label or c.operator not in OPERATORS:
            continue
        key, meta = by_label[c.metric]
        value = float(c.value) / 100 if meta.percent else float(c.value)
        mask &= OPERATORS[c.operator](table[key], value).fillna(False)
    return table[mask]
