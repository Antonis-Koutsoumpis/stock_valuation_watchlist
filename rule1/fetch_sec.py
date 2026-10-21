"""SEC EDGAR XBRL company facts (US companies only): 10+ years of quarterly and
annual statement data, free. The SEC requires a contact email in the User-Agent."""

import os
from datetime import datetime, timezone

import pandas as pd
import requests

from .periods import quarter_label, year_label
from .store import STATEMENT_COLUMNS

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_cik_cache: dict[str, str] = {}

# Our metric -> us-gaap concepts in priority order. Companies switch concepts over
# the years (e.g. SalesRevenueNet before 2018), so lower-priority concepts fill gaps.
DURATION_CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "tax_provision": ["IncomeTaxExpenseBenefit"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
}
INSTANT_CONCEPTS = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "equity": ["StockholdersEquity"],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
    "debt_total_long_term": ["LongTermDebt"],
    "debt_long_term_noncurrent": ["LongTermDebtNoncurrent"],
    "debt_long_term_current": ["LongTermDebtCurrent"],
    "debt_short_term": ["ShortTermBorrowings", "CommercialPaper"],
}
# Not additive across quarters, so never derived by subtracting year-to-date values.
NON_ADDITIVE = {"eps_diluted", "diluted_shares"}
# Restated to today's share count after a stock split (e.g. Amazon's 20-for-1 in 2022).
PER_SHARE = {"eps_diluted"}
SHARE_COUNTS = {"diluted_shares", "shares_outstanding"}


def _split_adjust(df: pd.DataFrame, metric: str, splits: pd.Series | None) -> pd.DataFrame:
    """A value filed before a split is in old shares; values filed after it are already restated."""
    if splits is None or splits.empty or (metric not in PER_SHARE and metric not in SHARE_COUNTS):
        return df
    factor = df["filed"].map(lambda filed: float(splits[splits.index > filed].prod()))
    df = df.copy()
    df["val"] = df["val"] / factor if metric in PER_SHARE else df["val"] * factor
    return df


def _headers() -> dict:
    contact = os.environ.get("SEC_CONTACT_EMAIL")
    if not contact:
        raise RuntimeError("Set SEC_CONTACT_EMAIL; the SEC requires a contact email.")
    return {"User-Agent": f"rule1-watchlist {contact}"}


def lookup_cik(ticker: str) -> str | None:
    """The SEC's company number for a US ticker (e.g. AMZN -> 0001018724), or None."""
    if not _cik_cache:
        resp = requests.get(TICKERS_URL, headers=_headers(), timeout=60)
        resp.raise_for_status()
        _cik_cache.update({r["ticker"].upper(): str(r["cik_str"]).zfill(10) for r in resp.json().values()})
    return _cik_cache.get(ticker.upper())


def fetch_companyfacts(cik: str) -> dict:
    resp = requests.get(URL.format(cik=cik.zfill(10)), headers=_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json()


def _facts(data: dict, concept: str) -> pd.DataFrame:
    node = data.get("facts", {}).get("us-gaap", {}).get(concept)
    if not node:
        return pd.DataFrame()
    units = node["units"]
    unit = next((u for u in ("USD", "USD/shares", "shares") if u in units), next(iter(units)))
    df = pd.DataFrame(units[unit])
    df = df[df["form"].isin(["10-K", "10-Q", "10-K/A", "10-Q/A"])]
    if df.empty:
        return df
    df["end"] = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    if "start" in df:
        df["start"] = pd.to_datetime(df["start"])
    return df


def _fiscal_labels(df: pd.DataFrame) -> dict:
    """The earliest filing that contains a period end is the one reporting it as
    its own period, so its fy/fp is that period's fiscal label."""
    first = df.sort_values("filed").drop_duplicates("end", keep="first")
    return {r.end: f"FY{r.fy} {r.fp}" for r in first.itertuples() if pd.notna(r.fy)}


def _duration_series(df: pd.DataFrame, additive: bool) -> tuple[dict, dict]:
    """Returns ({quarter_end: value}, {year_end: value}) from duration facts.
    10-Q cash flows are year-to-date; quarters are derived by differencing."""
    df = df.sort_values("filed").drop_duplicates(["start", "end"], keep="last")
    days = (df["end"] - df["start"]).dt.days
    quarterly = {r.end: r.val for r in df[(days >= 80) & (days <= 100)].itertuples()}
    is_10k = df["form"].str.startswith("10-K") & (df["fp"] == "FY")
    annual = {r.end: r.val for r in df[(days >= 350) & (days <= 380) & is_10k].itertuples()}
    if additive:
        for _, chain in df.groupby("start"):
            chain = chain.sort_values("end")
            ends, vals = list(chain["end"]), list(chain["val"])
            for i in range(1, len(ends)):
                step = (ends[i] - ends[i - 1]).days
                if 80 <= step <= 100 and ends[i] not in quarterly:
                    quarterly[ends[i]] = vals[i] - vals[i - 1]
    return quarterly, annual


def _rows(values: dict, labeller, metric, fiscal, fetched_at) -> list[dict]:
    return [{
        "period": labeller(end),
        "period_end": end.strftime("%Y-%m-%d"),
        "fiscal_label": fiscal.get(end, ""),
        "metric": metric,
        "value": float(val),
        "source": "sec",
        "fetched_at": fetched_at,
    } for end, val in values.items()]


def parse_companyfacts(data: dict, splits: pd.Series | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`splits`: split ratios indexed by date (e.g. 20.0 on 2022-06-06)."""
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q_rows, a_rows, fiscal, year_ends = [], [], {}, set()

    for metric, concepts in DURATION_CONCEPTS.items():
        q_vals, a_vals = {}, {}
        for concept in concepts:
            df = _facts(data, concept)
            if df.empty or "start" not in df:
                continue
            df = _split_adjust(df, metric, splits)
            fiscal.update({k: v for k, v in _fiscal_labels(df).items() if k not in fiscal})
            q, a = _duration_series(df, metric not in NON_ADDITIVE)
            for end, v in q.items():
                q_vals.setdefault(end, v)
            for end, v in a.items():
                a_vals.setdefault(end, v)
        year_ends.update(a_vals)
        q_rows += _rows(q_vals, quarter_label, metric, fiscal, fetched_at)
        a_rows += _rows(a_vals, year_label, metric, fiscal, fetched_at)

    instants = {}
    for metric, concepts in INSTANT_CONCEPTS.items():
        vals = {}
        for concept in concepts:
            df = _facts(data, concept)
            if df.empty:
                continue
            df = _split_adjust(df, metric, splits)
            fiscal.update({k: v for k, v in _fiscal_labels(df).items() if k not in fiscal})
            df = df.sort_values("filed").drop_duplicates("end", keep="last")
            for r in df.itertuples():
                vals.setdefault(r.end, r.val)
        instants[metric] = vals

    # Total debt = long-term debt (incl. current portion) + short-term borrowings.
    total_debt = {}
    ends = set().union(*(instants[m] for m in instants if m.startswith("debt_")))
    for end in ends:
        lt = instants["debt_total_long_term"].get(end)
        if lt is None:
            parts = [instants["debt_long_term_noncurrent"].get(end), instants["debt_long_term_current"].get(end)]
            lt = sum(p for p in parts if p is not None) if any(p is not None for p in parts) else None
        st = instants["debt_short_term"].get(end, 0.0)
        if lt is not None or st:
            total_debt[end] = (lt or 0.0) + st
    instants = {m: v for m, v in instants.items() if not m.startswith("debt_")}
    instants["total_debt"] = total_debt

    for metric, vals in instants.items():
        q_rows += _rows(vals, quarter_label, metric, fiscal, fetched_at)
        a_rows += _rows({e: v for e, v in vals.items() if e in year_ends}, year_label, metric, fiscal, fetched_at)

    return pd.DataFrame(q_rows, columns=STATEMENT_COLUMNS), pd.DataFrame(a_rows, columns=STATEMENT_COLUMNS)


def fetch_statements(cik: str, splits: pd.Series | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    return parse_companyfacts(fetch_companyfacts(cik), splits)
