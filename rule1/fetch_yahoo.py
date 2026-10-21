"""Yahoo Finance via yfinance: daily prices, today's valuation snapshot, and the
quarterly/annual statements Yahoo currently offers (about 5 quarters, 4 years)."""

from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from .periods import quarter_label, year_label
from .store import STATEMENT_COLUMNS

# Our metric name -> candidate Yahoo row labels, first match wins.
STATEMENT_ROWS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "net_income": ["Net Income Common Stockholders", "Net Income"],
    "eps_diluted": ["Diluted EPS"],
    "operating_income": ["Operating Income", "EBIT"],
    "pretax_income": ["Pretax Income"],
    "tax_provision": ["Tax Provision"],
    "diluted_shares": ["Diluted Average Shares"],
    "total_debt": ["Total Debt"],
    "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
    "equity": ["Stockholders Equity", "Common Stock Equity"],
    "shares_outstanding": ["Ordinary Shares Number", "Share Issued"],
    "operating_cash_flow": ["Operating Cash Flow"],
    "capex": ["Capital Expenditure"],
    "dividends_paid": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
}

# Daily snapshot columns -> Yahoo `info` keys. Yahoo only gives today's value.
SNAPSHOT_KEYS = {
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "peg_5y": "trailingPegRatio",
    "price_sales": "priceToSalesTrailing12Months",
    "price_book": "priceToBook",
    "trailing_div_yield": "trailingAnnualDividendYield",
    "payout_ratio": "payoutRatio",
}


def fetch_prices(symbol: str, full_history: bool) -> pd.DataFrame:
    hist = yf.Ticker(symbol).history(period="max" if full_history else "1mo", auto_adjust=False)
    if hist.empty:
        return pd.DataFrame()
    hist.index = hist.index.tz_localize(None).normalize()
    out = pd.DataFrame({"close": hist["Close"], "adj_close": hist["Adj Close"], "volume": hist["Volume"]})
    out.index.name = "date"
    return out


def fetch_splits(symbol: str) -> pd.Series:
    splits = yf.Ticker(symbol).splits
    if splits is None or splits.empty:
        return pd.Series(dtype=float)
    splits.index = splits.index.tz_localize(None).normalize()
    return splits[splits > 0]


def fetch_snapshot(symbol: str, last_trading_day) -> pd.DataFrame:
    info = yf.Ticker(symbol).info or {}
    row = {col: info.get(key) for col, key in SNAPSHOT_KEYS.items()}
    # Yahoo's `dividendYield` switched to percent in 2025; rate / price is unambiguous.
    rate, price = info.get("dividendRate"), info.get("currentPrice") or info.get("regularMarketPrice")
    row["forward_div_yield"] = rate / price if rate and price else None
    row = {f"{k}_yahoo": v for k, v in row.items()}
    return pd.DataFrame([row], index=pd.DatetimeIndex([last_trading_day], name="date"))


def _statement_rows(frames, labeller, source, fetched_at) -> pd.DataFrame:
    rows = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for metric, labels in STATEMENT_ROWS.items():
            label = next((l for l in labels if l in frame.index), None)
            if label is None:
                continue
            for period_end, value in frame.loc[label].items():
                if pd.isna(value):
                    continue
                if metric == "capex":
                    value = abs(value)
                if metric == "dividends_paid":
                    value = abs(value)
                rows.append({
                    "period": labeller(period_end),
                    "period_end": pd.Timestamp(period_end).strftime("%Y-%m-%d"),
                    "fiscal_label": "",
                    "metric": metric,
                    "value": float(value),
                    "source": source,
                    "fetched_at": fetched_at,
                })
    return pd.DataFrame(rows, columns=STATEMENT_COLUMNS)


def fetch_statements(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (quarterly, annual) long-format rows."""
    t = yf.Ticker(symbol)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    quarterly = _statement_rows(
        [t.quarterly_income_stmt, t.quarterly_balance_sheet, t.quarterly_cashflow],
        quarter_label, "yahoo", fetched_at)
    annual = _statement_rows(
        [t.income_stmt, t.balance_sheet, t.cashflow],
        year_label, "yahoo", fetched_at)
    return quarterly, annual
