"""Daily update: fetch every watchlist stock and add the new data to its CSV files.

    python -m rule1.update            # all stocks
    python -m rule1.update AMZN       # one stock
"""

import sys
import time
import traceback
from pathlib import Path

import pandas as pd

from . import fetch_sec, fetch_yahoo, manual
from .store import DATA_DIR, merge_daily, merge_statements, stock_dir

WATCHLIST = Path(__file__).resolve().parent.parent / "config" / "watchlist.csv"
FX_DIR = DATA_DIR / "_fx"
PAUSE_SECONDS = 1.0  # between stocks, to stay polite with Yahoo


def retry(fn, *args, attempts=3, wait=10):
    """Yahoo sometimes refuses bursts of requests; wait and try again."""
    for i in range(attempts):
        try:
            return fn(*args)
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(wait * (i + 1))


def load_watchlist() -> pd.DataFrame:
    return pd.read_csv(WATCHLIST, dtype=str).fillna("")


def update_stock(row) -> None:
    folder = stock_dir(row.ticker)
    daily_path = folder / "daily.csv"

    prices = retry(fetch_yahoo.fetch_prices, row.yahoo_symbol, not daily_path.exists())
    if prices.empty:
        raise RuntimeError(f"no prices from Yahoo for {row.yahoo_symbol}")
    snapshot = retry(fetch_yahoo.fetch_snapshot, row.yahoo_symbol, prices.index.max())
    merge_daily(daily_path, prices.join(snapshot, how="left"))
    print(f"{row.ticker}: {len(prices)} price rows, snapshot for {prices.index.max():%Y-%m-%d}")

    if getattr(row, "type", "stock") == "index":
        return  # an index has prices only, no financial statements

    quarterly, annual = retry(fetch_yahoo.fetch_statements, row.yahoo_symbol)
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
    n_q = q["period"].nunique() if not q.empty else 0
    n_a = a["period"].nunique() if not a.empty else 0
    print(f"{row.ticker}: {n_q} quarters, {n_a} years stored")


def fx_pair(row) -> str | None:
    """e.g. TWDUSD when a stock trades in USD but reports in TWD."""
    fin = getattr(row, "financial_currency", "") or row.currency
    return f"{fin}{row.currency}" if fin != row.currency else None


def update_fx(pairs: set[str]) -> None:
    FX_DIR.mkdir(parents=True, exist_ok=True)
    for pair in sorted(pairs):
        path = FX_DIR / f"{pair}.csv"
        rates = retry(fetch_yahoo.fetch_prices, f"{pair}=X", not path.exists())
        merge_daily(path, rates[["close"]])
        print(f"FX {pair}: {len(rates)} rows")


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
        time.sleep(PAUSE_SECONDS)
    try:
        update_fx({p for p in map(fx_pair, watchlist.itertuples()) if p})
    except Exception:
        traceback.print_exc()
    manual.backup(manual.load())
    if failed:
        print(f"Failed: {', '.join(failed)}")
    return 1 if failed and len(failed) == len(watchlist) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
