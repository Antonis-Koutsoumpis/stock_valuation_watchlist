"""Daily update: fetch every watchlist stock and add the new data to its CSV files.

    python -m rule1.update            # all stocks
    python -m rule1.update AMZN       # one stock
"""

import sys
import traceback
from pathlib import Path

import pandas as pd

from . import fetch_sec, fetch_yahoo, manual
from .store import merge_daily, merge_statements, stock_dir

WATCHLIST = Path(__file__).resolve().parent.parent / "config" / "watchlist.csv"


def load_watchlist() -> pd.DataFrame:
    return pd.read_csv(WATCHLIST, dtype=str).fillna("")


def update_stock(row) -> None:
    folder = stock_dir(row.ticker)
    daily_path = folder / "daily.csv"

    prices = fetch_yahoo.fetch_prices(row.yahoo_symbol, full_history=not daily_path.exists())
    if prices.empty:
        raise RuntimeError(f"no prices from Yahoo for {row.yahoo_symbol}")
    snapshot = fetch_yahoo.fetch_snapshot(row.yahoo_symbol, prices.index.max())
    merge_daily(daily_path, prices.join(snapshot, how="left"))
    print(f"{row.ticker}: {len(prices)} price rows, snapshot for {prices.index.max():%Y-%m-%d}")

    if getattr(row, "type", "stock") == "index":
        return  # an index has prices only, no financial statements

    quarterly, annual = fetch_yahoo.fetch_statements(row.yahoo_symbol)
    cik = row.sec_cik
    if not cik and row.currency == "USD":
        try:
            cik = fetch_sec.lookup_cik(row.ticker) or ""
        except Exception as exc:
            print(f"{row.ticker}: SEC lookup failed: {exc}")
    if cik:
        try:
            splits = fetch_yahoo.fetch_splits(row.yahoo_symbol)
            sec_q, sec_a = fetch_sec.fetch_statements(cik, splits)
            quarterly, annual = pd.concat([quarterly, sec_q]), pd.concat([annual, sec_a])
        except Exception as exc:  # Yahoo data is still saved if the SEC is down
            print(f"{row.ticker}: SEC fetch failed: {exc}")
    q = merge_statements(folder / "quarterly.csv", quarterly, replace_sources={"sec"})
    a = merge_statements(folder / "annual.csv", annual, replace_sources={"sec"})
    print(f"{row.ticker}: {q['period'].nunique()} quarters, {a['period'].nunique()} years stored")


def main(tickers: list[str]) -> int:
    watchlist = load_watchlist()
    if tickers:
        watchlist = watchlist[watchlist["ticker"].isin(tickers)]
    failed = []
    for row in watchlist.itertuples():
        try:
            update_stock(row)
        except Exception:
            traceback.print_exc()
            failed.append(row.ticker)
    manual.backup(manual.load())
    if failed:
        print(f"Failed: {', '.join(failed)}")
    return 1 if failed and len(failed) == len(watchlist) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
