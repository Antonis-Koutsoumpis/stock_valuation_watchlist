"""Turns a stock's stored CSV files into the metric tables the app and screener use."""

import pandas as pd

from . import manual, metrics
from .store import DATA_DIR, read_csv


def load_stock(row: pd.Series, man: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(daily, quarterly, yearly, dcf) for one watchlist row; `man` from manual.load()."""
    ticker = row.name
    folder = DATA_DIR / ticker
    prices = read_csv(folder / "daily.csv", index_col="date", parse_dates=["date"])
    sq = read_csv(folder / "quarterly.csv", dtype={"period": str})
    sa = read_csv(folder / "annual.csv", dtype={"period": str})
    entries = manual.statements_for(man, ticker)
    q = metrics.quarterly(sq, entries) if not (sq.empty and entries.empty) else pd.DataFrame()
    a = metrics.annual(sq, sa, entries) if not (sq.empty and sa.empty and entries.empty) else pd.DataFrame()
    md = man["daily"][man["daily"]["ticker"] == ticker]
    fx = None
    if row.get("financial_currency") and row["financial_currency"] != row["currency"]:
        rates = read_csv(DATA_DIR / "_fx" / f"{row['financial_currency']}{row['currency']}.csv",
                         index_col="date", parse_dates=["date"])
        fx = rates["close"] if not rates.empty else None
    d = metrics.daily(prices, q, md, a, fx, float(row.get("adr_ratio") or 1))
    return d, q, a, metrics.dcf(man["dcf"], ticker)
