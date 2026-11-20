"""Build the data files for the web app (GitHub Pages).

    python -m rule1.export_web [output folder]      # default: docs/data

Writes one JSON file per watchlist entry (stocks/<TICKER>.json) plus watchlist.json,
glossary.json, screener.json and cpi.json. The GitHub Action .github/workflows/pages.yml
runs this after every daily update and publishes docs/ with these files, so the web app
shows the same numbers as the Streamlit app.

Everything is computed here with the same code as the Streamlit app (rule1/*), except the
calculated value: its inputs (price, EPS, FCF per share, growth rates found, ...) are
exported, and the web app does the valuation itself so the sliders (growth years,
discount rate, your growth rate) work without a server.
"""

import json
import math
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import build, inflation, manual, market, metrics, screener, valuation
from .glossary import CAGR_HELP, DAILY, DCF, QUARTERLY, YEARLY
from .metrics import ANNUAL_REPORTING_LAG, REPORTING_LAG
from .update import load_watchlist

ROOT = Path(__file__).resolve().parent.parent
EPOCH = pd.Timestamp("1970-01-01")


def clean(v):
    """JSON-safe number: NaN/inf -> None, 6 significant digits."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if math.isnan(f) or math.isinf(f):
        return None
    return float(f"{f:.6g}")


def days(index) -> list[int]:
    return [int((pd.Timestamp(d) - EPOCH).days) for d in index]


def columns(df: pd.DataFrame, cols) -> dict:
    return {c: [clean(v) for v in df[c].tolist()] for c in cols if c in df and df[c].notna().any()}


def valuation_inputs(daily_df, q_df, a_df) -> dict:
    return {"inp": {k: clean(v) for k, v in valuation.inputs(daily_df, q_df, a_df).items()},
            "cands": {k: clean(v) for k, v in valuation.growth_candidates(daily_df, a_df).items()}}


def valuation_history(daily_df, q_df, a_df) -> list[dict]:
    """Like valuation.history(): at the end of every quarter, with the data published by then.
    Only the inputs are stored; the web app calculates the values."""
    if daily_df is None or daily_df.empty or "close" not in daily_df:
        return []
    closes = daily_df["close"].dropna()
    out = []
    for day in closes.groupby(closes.index.to_period("Q")).apply(lambda s: s.index.max()):
        d = daily_df[daily_df.index <= day]
        q = q_df[q_df["period_end"] + REPORTING_LAG <= day] if "period_end" in q_df else q_df
        y = a_df[[pd.Timestamp(f"{p}-12-31") + ANNUAL_REPORTING_LAG <= day for p in a_df.index]] \
            if not a_df.empty else a_df
        out.append({"q": f"{day.year}Q{day.quarter}", **valuation_inputs(d, q, y)})
    return out


def export_stock(row: pd.Series, man: dict) -> dict:
    daily_df, q_df, a_df, dcf_df = build.load_stock(row, man)
    daily_cols = [c for c in DAILY if c in daily_df]
    q_cols = [*QUARTERLY, "cash"]
    growth = metrics.growth_table(a_df)
    out = {
        "ticker": row.name, "name": row["name"], "currency": row["currency"],
        "financial_currency": row.get("financial_currency") or row["currency"], "type": row.get("type", "stock"),
        "daily": {"d": days(daily_df.index), "cols": columns(daily_df, daily_cols)} if not daily_df.empty else None,
        "quarterly": ({"p": [str(p) for p in q_df.index], "cols": columns(q_df, q_cols)} if not q_df.empty else None),
        "annual": ({"p": [str(p) for p in a_df.index], "cols": columns(a_df, list(YEARLY))} if not a_df.empty else None),
        "growth": ({"rows": list(growth.index), "cols": list(growth.columns),
                    "values": [[clean(v) for v in r] for r in growth.to_numpy()]} if not growth.empty else None),
        "dcf": ({"q": list(dcf_df.index), **{c: [clean(v) if c != "middle_choice" else v for v in dcf_df[c]]
                                             for c in dcf_df.columns}} if not dcf_df.empty else None),
        "valuation": {"now": valuation_inputs(daily_df, q_df, a_df) if not daily_df.empty else None,
                      "history": valuation_history(daily_df, q_df, a_df)},
    }
    return out


def glossary() -> dict:
    def table(d):
        return {k: {"label": m.label, "help": m.help, "frequency": m.frequency, "percent": m.percent}
                for k, m in d.items()}
    return {
        "daily": table(DAILY), "quarterly": table(QUARTERLY), "dcf": table(DCF), "yearly": table(YEARLY),
        "cagr_help": CAGR_HELP, "valuation_help": valuation.HELP, "method_help": valuation.METHOD_HELP,
        "methods": valuation.METHODS, "assumptions": asdict(valuation.Assumptions()),
        "market_tickers": sorted(market.MARKET_TICKERS), "market_columns": market.COLUMNS,
        "etf_names": market.ETF_NAMES,
        "screener": {"filters": {k: {"help": f.help, "periods": f.periods, "percent": f.percent}
                                 for k, f in screener.FILTERS.items()},
                     "periods": screener.PERIODS, "operators": list(screener.OPERATORS),
                     "default_conditions": screener.DEFAULT_CONDITIONS.to_dict("records")},
    }


def main(out_dir: Path):
    (out_dir / "stocks").mkdir(parents=True, exist_ok=True)
    watchlist = load_watchlist()
    man = manual.load()
    rows = []
    for ticker, row in watchlist.set_index("ticker").iterrows():
        try:
            data = export_stock(row, man)
        except Exception as exc:  # one broken stock must not stop the others
            print(f"web export: {ticker} skipped: {exc}")
            continue
        (out_dir / "stocks" / f"{ticker}.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        rows.append({"ticker": ticker, "name": row["name"], "currency": row["currency"],
                     "type": row.get("type", "stock"), "has_data": data["daily"] is not None})
    (out_dir / "watchlist.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    (out_dir / "glossary.json").write_text(json.dumps(glossary(), ensure_ascii=False), encoding="utf-8")

    table = (pd.read_csv(screener.SUMMARY_PATH, index_col="ticker") if screener.SUMMARY_PATH.exists()
             else screener.build_summary(watchlist, lambda r: build.load_stock(r, man)))
    (out_dir / "screener.json").write_text(json.dumps(
        {"columns": ["ticker", *table.columns],
         "rows": [[t, *[clean(v) if not isinstance(v, str) else v for v in r]] for t, r in zip(table.index, table.to_numpy())]},
        ensure_ascii=False), encoding="utf-8")

    cpi = inflation.load_cpi()
    (out_dir / "cpi.json").write_text(json.dumps(
        {d.strftime("%Y-%m"): clean(v) for d, v in cpi.items()}), encoding="utf-8")
    print(f"web export: {len(rows)} entries written to {out_dir}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "data")
