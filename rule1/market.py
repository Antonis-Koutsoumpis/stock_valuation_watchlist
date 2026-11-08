"""Valuation of the whole US market, for the index pages (free sources only).

- Robert Shiller's monthly S&P 500 data (Yale): price, 12-month earnings, CAPE since 1871.
  His file is updated rarely, so multpl.com's monthly tables (same method) fill the recent months.
- FRED: market value of US corporate equities, GDP (Buffett indicator) and the 10-year
  Treasury yield.
- Yahoo: the P/E of an ETF that tracks the index (SPY, QQQ), stored daily by the update.
"""

import io

import numpy as np
import pandas as pd
import requests

from .store import DATA_DIR

MARKET_DIR = DATA_DIR / "_market"
SHILLER_URL = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
MULTPL_URL = "https://www.multpl.com/{}/table/{}"
MULTPL_TABLES = {"cape": ("shiller-pe", "by-month"), "pe": ("s-p-500-pe-ratio", "by-month"),
                 "eps": ("s-p-500-earnings", "by-month"), "sales": ("s-p-500-sales", "by-quarter")}
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
FRED_SERIES = {
    "NCBEILQ027S": "US corporate equities, market value ($ millions, quarterly)",
    "GDP": "US GDP ($ billions, annual rate, quarterly)",
    "DGS10": "10-year Treasury yield (%, daily)",
}
# Yahoo has no P/E for an index itself, but has one for an ETF that tracks it.
VALUATION_PROXY = {"^GSPC": "SPY", "^NDX": "QQQ"}
# Index pages that get the whole-market metrics. They describe the S&P 500 / US market; there is no free
# Nasdaq-100 CAPE or P/E history, so the Nasdaq-100 page shows the US-market ones next to its own QQQ P/E.
MARKET_TICKERS = {"SPX", "NDX"}
ETF_NAMES = {"SPX": "SPY fund (tracks the S&P 500)", "NDX": "QQQ fund (tracks the Nasdaq-100)"}
COLUMNS = ["cape", "pe_shiller", "sp500_eps", "sp500_sales", "buffett", "earnings_yield_gap", "ten_year_yield"]


def fetch_fred(series: str) -> pd.Series:
    resp = requests.get(FRED_URL.format(series), timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = ["date", "value"]  # FRED names the date column DATE or observation_date
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().set_index("date")["value"].rename(series)


def parse_multpl(html: str) -> pd.Series:
    """multpl.com 'by month' table: Date ('Nov 1, 2026') and Value ('39.93', sometimes with a note)."""
    table = pd.read_html(io.StringIO(html))[0]
    table.columns = ["date", "value"]
    values = pd.to_numeric(table["value"].astype(str).str.replace(",", "").str.extract(r"(-?\d+(?:\.\d+)?)")[0], errors="coerce")
    dates = pd.to_datetime(table["date"], errors="coerce")
    s = pd.Series(values.values, index=pd.DatetimeIndex(dates, name="date")).dropna().sort_index()
    # The current month appears twice (today's value and the 1st of the month): keep the latest.
    s.index = s.index.to_period("M").to_timestamp()
    return s[~s.index.duplicated(keep="last")]


def fetch_multpl(page: str, period: str = "by-month") -> pd.Series:
    resp = requests.get(MULTPL_URL.format(page, period), timeout=60,
                        headers={"User-Agent": "Mozilla/5.0 (stock-valuation-watchlist; monthly table)"})
    resp.raise_for_status()
    return parse_multpl(resp.text)


def parse_shiller(raw: pd.DataFrame) -> pd.DataFrame:
    """Shiller's 'Data' sheet (read without header) -> monthly price, earnings, dividends, cape.
    Dates are written as 2023.01 (January) ... 2023.1 (October)."""
    header_row = next(i for i, v in raw.iloc[:, 0].items() if str(v).strip() == "Date")
    df = raw.iloc[header_row + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[header_row]]
    date = pd.to_numeric(df["Date"], errors="coerce")
    df = df[date.notna()]
    date = date[date.notna()]
    year = np.floor(date).astype(int)
    month = np.round((date - year) * 100).astype(int)
    out = pd.DataFrame({
        "price": pd.to_numeric(df["P"], errors="coerce").values,
        "earnings": pd.to_numeric(df["E"], errors="coerce").values,
        "dividends": pd.to_numeric(df["D"], errors="coerce").values,
        "cape": pd.to_numeric(df["CAPE"], errors="coerce").values,
    }, index=pd.DatetimeIndex(pd.to_datetime(dict(year=year, month=month, day=1)).values, name="date"))
    return out.dropna(how="all")


def fetch_shiller() -> pd.DataFrame:
    resp = requests.get(SHILLER_URL, timeout=120)
    resp.raise_for_status()
    raw = pd.read_excel(io.BytesIO(resp.content), sheet_name="Data", header=None)
    return parse_shiller(raw)


def update_market() -> None:
    """Each source on its own, so one that is down does not stop the others."""
    MARKET_DIR.mkdir(parents=True, exist_ok=True)
    for series in FRED_SERIES:
        try:
            s = fetch_fred(series)
            s.to_csv(MARKET_DIR / f"fred_{series}.csv")
            print(f"FRED {series}: {len(s)} rows, last {s.index[-1]:%Y-%m-%d}")
        except Exception as exc:
            print(f"FRED {series} failed: {exc}")
    for name, (page, period) in MULTPL_TABLES.items():
        try:
            s = fetch_multpl(page, period)
            s.rename("value").to_csv(MARKET_DIR / f"multpl_{name}.csv")
            print(f"multpl {name}: {len(s)} months, last {s.index[-1]:%Y-%m}")
        except Exception as exc:
            print(f"multpl {name} failed: {exc}")
    try:
        shiller = fetch_shiller()
        shiller.to_csv(MARKET_DIR / "shiller.csv")
        last = shiller["earnings"].last_valid_index()
        print(f"Shiller: {len(shiller)} months, earnings to {last:%Y-%m}")
    except Exception as exc:
        print(f"Shiller failed: {exc}")


def _read(name: str) -> pd.DataFrame:
    path = MARKET_DIR / name
    return pd.read_csv(path, index_col="date", parse_dates=["date"]) if path.exists() else pd.DataFrame()


def valuation(shiller: pd.DataFrame, equities: pd.Series, gdp: pd.Series, ten_year: pd.Series,
              recent_cape: pd.Series | None = None, recent_pe: pd.Series | None = None,
              recent_eps: pd.Series | None = None, sales: pd.Series | None = None) -> pd.DataFrame:
    """Monthly/quarterly/daily market metrics on one date index (not filled forward).
    recent_* (multpl.com) win over Shiller's file where both have a month."""
    parts = []
    eps = shiller["earnings"].dropna() if not shiller.empty else pd.Series(dtype=float)
    if recent_eps is not None and not recent_eps.empty:
        eps = recent_eps.combine_first(eps)
    if not eps.empty:
        parts.append(eps.rename("sp500_eps"))
    if sales is not None and not sales.empty:
        parts.append(sales.rename("sp500_sales"))
    cape, pe = pd.Series(dtype=float), pd.Series(dtype=float)
    if not shiller.empty:
        cape = shiller["cape"].dropna()
        pe = (shiller["price"] / shiller["earnings"]).where(shiller["earnings"] > 0).dropna()
    if recent_cape is not None and not recent_cape.empty:
        cape = recent_cape.combine_first(cape)
    if recent_pe is not None and not recent_pe.empty:
        pe = recent_pe.combine_first(pe)
    if not cape.empty:
        parts.append(cape.rename("cape"))
    if not pe.empty:
        parts.append(pe.rename("pe_shiller"))
        if not ten_year.empty:
            # Earnings yield minus the 10-year yield, monthly (10-year yield = month average).
            monthly_10y = ten_year.resample("MS").mean() / 100
            parts.append((1 / pe - monthly_10y.reindex(pe.index)).dropna().rename("earnings_yield_gap"))
    if not equities.empty and not gdp.empty:
        parts.append((equities / 1000 / gdp).dropna().rename("buffett"))
    if not ten_year.empty:
        parts.append((ten_year / 100).rename("ten_year_yield"))
    return pd.concat(parts, axis=1).sort_index() if parts else pd.DataFrame(columns=COLUMNS)


def load_valuation() -> pd.DataFrame:
    def series(name):
        df = _read(f"fred_{name}.csv")
        return df.iloc[:, 0] if not df.empty else pd.Series(dtype=float)  # column named after the series
    def multpl(name):
        df = _read(f"multpl_{name}.csv")
        s = df.iloc[:, 0] if not df.empty else pd.Series(dtype=float)
        return s[~s.index.duplicated(keep="first")]  # files saved before duplicates were removed
    return valuation(_read("shiller.csv"), series("NCBEILQ027S"), series("GDP"), series("DGS10"),
                     multpl("cape"), multpl("pe"), multpl("eps"), multpl("sales"))


def for_days(values: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Each day gets the latest value known on that day (monthly and quarterly values held flat)."""
    if values.empty:
        return pd.DataFrame(index=days)
    out = {}
    for col in values:
        s = values[col].dropna()
        if s.empty:
            continue
        held = s.reindex(s.index.union(days)).ffill().reindex(days)
        # stop holding a value more than ~2 quarters after the last observation
        out[col] = held.where(days <= s.index[-1] + pd.Timedelta(days=200))
    return pd.DataFrame(out, index=days)
