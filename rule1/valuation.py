"""Intrinsic value per share, calculated from the stored data with several methods and three
scenarios (conservative, middle, optimistic). See METHOD_HELP for each method.

All per-share inputs are taken in the price currency (EPS = price ÷ trailing P/E, FCF per share =
EPS × FCF ÷ net income, BVPS = price ÷ price/book), so stocks that report in another currency or
trade as ADRs need no extra step.
"""

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .metrics import ANNUAL_REPORTING_LAG, REPORTING_LAG

SCENARIOS = ["Conservative", "Middle", "Optimistic"]
METHOD_HELP = {
    "FCF DCF": "Free cash flow per share grows at the growth rate for the growth years, then at 3% a year "
               "forever (the terminal value). Every year is discounted back to today at the discount rate.",
    "EPS DCF": "The same as FCF DCF, with diluted earnings per share.",
    "FCF exit multiple": "Free cash flow per share grows for the growth years; the share is then sold at the "
                         "10-year average P/E (between 8 and 25). Cash flows and sale are discounted to today.",
    "EPS exit multiple": "The same as FCF exit multiple, with diluted earnings per share.",
    "Rule #1 Sticker Price": "Phil Town: EPS after the growth years × a future P/E (2 × the growth rate, at most the "
                             "10-year average P/E), discounted at 15% a year. The Margin of Safety price is half.",
    "Graham formula": "Benjamin Graham: EPS × (8.5 + 2 × growth rate in %), using a 4.4% bond yield.",
    "Peter Lynch fair value": "A fair P/E equals the growth rate in % (PEG of 1): EPS × growth rate, "
                              "with the growth rate between 5 and 25.",
    "Earnings power value": "No growth at all: EPS ÷ discount rate. A floor for profitable companies.",
    "Graham number": "Asset-based: √(22.5 × EPS × book value per share). Low for companies with "
                     "few assets, such as software.",
}
METHODS = list(METHOD_HELP)

HELP = ("A value per share calculated from the stored data with several methods (hover each method in the "
        "table). Growth rate: by default the median of the stock's 5- and 10-year growth of EPS, FCF, book value "
        "and revenue and the analysts' 5-year estimate, between 0% and 20% (conservative uses the 25th "
        "percentile, optimistic the 75th). After the growth years the business grows 3% a year (the terminal "
        "value). The low, middle and high values are the median of all methods in each scenario. "
        "It is a rough guide, not advice.")


@dataclass(frozen=True)
class Assumptions:
    horizon: int = 10            # growth years before the terminal value
    discount: float = 0.10       # middle scenario; conservative +spread, optimistic -spread
    spread: float = 0.02
    terminal: float = 0.03       # growth after the horizon (conservative: 1% lower)
    growth: float | None = None  # your own growth rate; None = from the data
    growth_cap: float = 0.20     # no company grows faster than this for long
    marr: float = 0.15           # Rule #1 minimum acceptable rate of return
    max_pe: float = 50.0
    bond_yield: float = 0.044    # Graham's AAA yield (his formula is calibrated to 4.4%)


def _last(df: pd.DataFrame, col: str):
    if df is None or df.empty or col not in df or df[col].notna().sum() == 0:
        return np.nan
    return float(df[col].dropna().iloc[-1])


def growth_candidates(daily: pd.DataFrame, annual: pd.DataFrame) -> dict:
    """Growth rates the scenarios choose from: historical yearly growth (CAGR) and the
    analysts' 5-year estimate (Yahoo's P/E ÷ PEG)."""
    out = {}
    for key, label in [("eps_diluted", "EPS (diluted)"), ("fcf", "FCF"), ("bvps", "BVPS"), ("revenue", "Revenue")]:
        found = {n: _last(annual, f"{key}_cagr_{n}y") for n in range(10, 0, -1)}
        found = {n: v for n, v in found.items() if not np.isnan(v)}
        # 5 and 10 years; a young listing uses its longest history instead
        for n in [n for n in (5, 10) if n in found] or list(found)[:1]:
            out[f"{label} {n}y"] = found[n]
    pe, peg = _last(daily, "trailing_pe_yahoo"), _last(daily, "peg_5y_yahoo")
    if pe > 0 and peg > 0:
        out["Analysts 5y"] = pe / peg / 100
    return out


def inputs(daily: pd.DataFrame, quarterly: pd.DataFrame, annual: pd.DataFrame) -> dict:
    close = _last(daily, "close")
    pe = _last(daily, "trailing_pe")
    eps = close / pe if pe > 0 else np.nan
    pb = _last(daily, "price_book")
    fcf, ni = _last(quarterly, "fcf_ttm"), _last(quarterly, "net_income_ttm")
    if np.isnan(fcf) or np.isnan(ni):
        fcf, ni = _last(annual, "fcf"), _last(annual, "net_income")
    pe_hist = daily["trailing_pe"].dropna() if daily is not None and "trailing_pe" in daily else pd.Series(dtype=float)
    if not pe_hist.empty:
        pe_hist = pe_hist[pe_hist.index >= pe_hist.index.max() - pd.DateOffset(years=10)]
    return {
        "price": close,
        "eps": eps,
        "fcf_per_share": eps * fcf / ni if ni > 0 else np.nan,
        "bvps": close / pb if pb > 0 else np.nan,
        "avg_pe": float(pe_hist[(pe_hist > 0) & (pe_hist < 200)].mean()) if not pe_hist.empty else np.nan,
    }


def scenario_growth(candidates: dict, a: Assumptions) -> dict:
    """Conservative = 25th percentile of the candidates, middle = median, optimistic = 75th
    percentile; never below 0 or above growth_cap. Your own growth rate sets the middle
    (conservative 3% lower, optimistic 3% higher)."""
    vals = list(candidates.values())
    if a.growth is not None:
        low, mid, high = a.growth - 0.03, a.growth, a.growth + 0.03
    elif vals:
        low, mid, high = np.percentile(vals, [25, 50, 75])
    else:
        return {}
    return {s: float(np.clip(g, 0, a.growth_cap)) for s, g in zip(SCENARIOS, [low, mid, high])}


def dcf_per_share(start: float, growth: float, discount: float, terminal: float, years: int) -> float:
    if not start > 0 or discount <= terminal:
        return np.nan
    t = np.arange(1, years + 1)
    flows = start * (1 + growth) ** t
    pv = (flows / (1 + discount) ** t).sum()
    terminal_value = flows[-1] * (1 + terminal) / (discount - terminal)
    return float(pv + terminal_value / (1 + discount) ** years)


def exit_multiple(start: float, growth: float, discount: float, multiple: float, years: int) -> float:
    if not start > 0 or not multiple > 0:
        return np.nan
    t = np.arange(1, years + 1)
    flows = start * (1 + growth) ** t
    pv = (flows / (1 + discount) ** t).sum()
    return float(pv + flows[-1] * multiple / (1 + discount) ** years)


def sticker_price(eps: float, growth: float, avg_pe: float, a: Assumptions) -> tuple[float, float]:
    if not eps > 0:
        return np.nan, np.nan
    future_pe = 2 * growth * 100
    if avg_pe > 0:
        future_pe = min(future_pe, avg_pe)
    future_pe = min(future_pe, a.max_pe)
    sticker = eps * (1 + growth) ** a.horizon * future_pe / (1 + a.marr) ** a.horizon
    return float(sticker), float(sticker / 2)


def graham_formula(eps: float, growth: float, bond_yield: float) -> float:
    return float(eps * (8.5 + 2 * growth * 100) * 0.044 / bond_yield) if eps > 0 else np.nan


def lynch(eps: float, growth: float) -> float:
    return float(eps * np.clip(growth * 100, 5, 25)) if eps > 0 else np.nan


def graham_number(eps: float, bvps: float) -> float:
    return float(np.sqrt(22.5 * eps * bvps)) if eps > 0 and bvps > 0 else np.nan


def value(daily: pd.DataFrame, quarterly: pd.DataFrame, annual: pd.DataFrame,
          a: Assumptions = Assumptions()) -> dict:
    """{"table": methods × scenarios, "range": {low, middle, high}, "growth": {...},
    "candidates": {...}, "inputs": {...}, "mos": Margin of Safety price (middle)}."""
    inp = inputs(daily, quarterly, annual)
    cands = growth_candidates(daily, annual)
    growth = scenario_growth(cands, a)
    table = pd.DataFrame(index=METHODS, columns=SCENARIOS, dtype=float)
    mos = np.nan
    eps, fcf = inp["eps"], inp["fcf_per_share"]
    multiple = float(np.clip(inp["avg_pe"], 8, 25)) if inp["avg_pe"] > 0 else 15.0
    if growth:
        rates = {"Conservative": (a.discount + a.spread, a.terminal - 0.01),
                 "Middle": (a.discount, a.terminal),
                 "Optimistic": (a.discount - a.spread, a.terminal)}
        for s in SCENARIOS:
            r, tg, g = *rates[s], growth[s]
            sticker, m = sticker_price(eps, g, inp["avg_pe"], a)
            table[s] = pd.Series({
                "FCF DCF": dcf_per_share(fcf, g, r, tg, a.horizon),
                "EPS DCF": dcf_per_share(eps, g, r, tg, a.horizon),
                "FCF exit multiple": exit_multiple(fcf, g, r, multiple, a.horizon),
                "EPS exit multiple": exit_multiple(eps, g, r, multiple, a.horizon),
                "Rule #1 Sticker Price": sticker,
                "Graham formula": graham_formula(eps, g, a.bond_yield),
                "Peter Lynch fair value": lynch(eps, g),
                "Earnings power value": eps / r if eps > 0 else np.nan,
                "Graham number": graham_number(eps, inp["bvps"]),
            })
            if s == "Middle":
                mos = m
    rng = {"low": table["Conservative"].median(), "middle": table["Middle"].median(),
           "high": table["Optimistic"].median()}
    return {"table": table, "range": rng, "growth": growth, "candidates": cands, "inputs": inp, "mos": mos}


def history(daily: pd.DataFrame, quarterly: pd.DataFrame, annual: pd.DataFrame,
            a: Assumptions = Assumptions(), since: pd.Timestamp | None = None) -> pd.DataFrame:
    """At the end of every quarter, using only the data published by then (quarters 45 days and
    years 90 days after they end): low, middle, high, mos and each method's middle value.
    Index = quarter."""
    if daily is None or daily.empty or "close" not in daily:
        return pd.DataFrame(columns=["low", "middle", "high", "mos"])
    closes = daily["close"].dropna()
    if since is not None:
        closes = closes[closes.index >= since]
    rows = {}
    # last trading day of every quarter, and today for the running quarter
    for day in closes.groupby(closes.index.to_period("Q")).apply(lambda s: s.index.max()):
        d = daily[daily.index <= day]
        q = quarterly[quarterly["period_end"] + REPORTING_LAG <= day] if "period_end" in quarterly else quarterly
        y = annual[[pd.Timestamp(f"{p}-12-31") + ANNUAL_REPORTING_LAG <= day for p in annual.index]] \
            if not annual.empty else annual
        v = value(d, q, y, a)
        rows[f"{day.year}Q{day.quarter}"] = {**v["range"], "mos": v["mos"], **v["table"]["Middle"].to_dict()}
    return pd.DataFrame.from_dict(rows, orient="index").dropna(subset=["low", "middle", "high"], how="all")
