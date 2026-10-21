"""Checks config/ticker_reference.csv against Yahoo: fills in missing names and flags
symbols Yahoo doesn't know or whose currency differs.

    python -m rule1.check_symbols
"""

from pathlib import Path

import pandas as pd
import yfinance as yf

REFERENCE = Path(__file__).resolve().parent.parent / "config" / "ticker_reference.csv"


def check(row) -> dict:
    try:
        info = yf.Ticker(row.yahoo_symbol).info or {}
    except Exception as exc:
        return {"yahoo_check": f"error: {exc}"[:80]}
    if not info.get("quoteType"):
        return {"yahoo_check": "not found on Yahoo"}
    out = {"name": row.name or info.get("longName") or info.get("shortName") or ""}
    notes = []
    if info.get("currency") and info["currency"] != row.currency:
        notes.append(f"price currency is {info['currency']}")
    fin = info.get("financialCurrency")
    if fin and fin != (info.get("currency") or row.currency):
        notes.append(f"reports in {fin}")
    out["yahoo_check"] = "; ".join(notes) or "ok"
    return out


def main():
    ref = pd.read_csv(REFERENCE, dtype=str).fillna("")
    for i, row in enumerate(ref.itertuples()):
        for key, value in check(row).items():
            ref.loc[i, key] = value
        print(f"{row.ticker}: {ref.loc[i, 'yahoo_check']}")
    ref.to_csv(REFERENCE, index=False)


if __name__ == "__main__":
    main()
