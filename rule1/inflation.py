"""US consumer prices (CPI-U, monthly, from FRED) to show prices in today's money."""

import io

import pandas as pd
import requests

from .store import DATA_DIR

CPI_PATH = DATA_DIR / "_macro" / "us_cpi.csv"
CPI_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"


def fetch_cpi() -> pd.Series:
    resp = requests.get(CPI_URL, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = ["date", "cpi"]  # FRED names the date column DATE or observation_date
    df["date"] = pd.to_datetime(df["date"])
    df["cpi"] = pd.to_numeric(df["cpi"], errors="coerce")
    return df.dropna().set_index("date")["cpi"]


def update_cpi() -> None:
    cpi = fetch_cpi()
    CPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    cpi.to_csv(CPI_PATH)
    print(f"CPI: {len(cpi)} months, last {cpi.index[-1]:%Y-%m}")


def load_cpi() -> pd.Series:
    if not CPI_PATH.exists():
        return pd.Series(dtype=float)
    return pd.read_csv(CPI_PATH, index_col="date", parse_dates=["date"])["cpi"]


def real(prices: pd.Series, cpi: pd.Series) -> pd.Series:
    """Prices in money of the latest CPI month: price × CPI(latest) ÷ CPI(month of the price).
    Days after the latest CPI month use the latest CPI. Days before the first CPI month are dropped."""
    if cpi.empty or prices.empty:
        return pd.Series(dtype=float)
    monthly = cpi.copy()
    monthly.index = monthly.index.to_period("M")
    months = prices.index.to_period("M")
    factor = pd.Series(monthly.reindex(months).values, index=prices.index)
    factor = factor.where(months <= monthly.index.max(), monthly.iloc[-1])
    return (prices * monthly.iloc[-1] / factor).dropna()
