import numpy as np
import pandas as pd
import pytest

from rule1 import fetch_sec, metrics, store
from rule1.periods import quarter_label


def test_quarter_label_handles_52_53_week_calendars():
    assert quarter_label("2026-03-31") == "2026Q1"
    assert quarter_label("2027-01-02") == "2026Q4"
    assert quarter_label("2026-09-27") == "2026Q3"


def test_statements_are_never_deleted(tmp_path):
    path = tmp_path / "quarterly.csv"
    row = lambda p, v: {"period": p, "period_end": "", "fiscal_label": "", "metric": "revenue",
                        "value": v, "source": "yahoo", "fetched_at": ""}
    store.merge_statements(path, pd.DataFrame([row("2021Q1", 1.0), row("2021Q2", 2.0)]))
    # A year later Yahoo no longer offers 2021Q1 and restates 2021Q2.
    merged = store.merge_statements(path, pd.DataFrame([row("2021Q2", 2.5), row("2021Q3", 3.0)]))
    assert dict(zip(merged["period"], merged["value"])) == {"2021Q1": 1.0, "2021Q2": 2.5, "2021Q3": 3.0}


def test_daily_merge_keeps_old_rows_and_snapshots(tmp_path):
    path = tmp_path / "daily.csv"
    first = pd.DataFrame({"close": [10.0, 11.0], "forward_pe_yahoo": [np.nan, 20.0]},
                         index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
    store.merge_daily(path, first)
    second = pd.DataFrame({"close": [11.0, 12.0], "forward_pe_yahoo": [np.nan, 21.0]},
                          index=pd.to_datetime(["2026-01-05", "2026-01-06"]))
    merged = store.merge_daily(path, second)
    assert list(merged["close"]) == [10.0, 11.0, 12.0]
    assert list(merged["forward_pe_yahoo"].fillna(0)) == [0, 20.0, 21.0]


def _fact(start, end, val, filed, fy=2023, fp="Q1", form="10-Q"):
    f = {"end": end, "val": val, "filed": filed, "fy": fy, "fp": fp, "form": form, "accn": "x"}
    if start:
        f["start"] = start
    return f


def test_sec_derives_quarters_from_year_to_date_values():
    ocf = [
        _fact("2023-01-01", "2023-03-31", 10, "2023-04-30", fp="Q1"),
        _fact("2023-01-01", "2023-06-30", 25, "2023-07-30", fp="Q2"),
        _fact("2023-01-01", "2023-09-30", 45, "2023-10-30", fp="Q3"),
        _fact("2023-01-01", "2023-12-31", 70, "2024-02-01", fp="FY", form="10-K"),
    ]
    revenue = [
        _fact("2023-01-01", "2023-03-31", 100, "2023-04-30"),
        _fact("2023-04-01", "2023-06-30", 110, "2023-07-30"),
        _fact("2023-01-01", "2023-12-31", 460, "2024-02-01", fp="FY", form="10-K"),
        # Restated later: the newest filing wins.
        _fact("2023-04-01", "2023-06-30", 111, "2024-07-30", fy=2024, fp="Q2"),
    ]
    debt = [_fact(None, "2023-12-31", 500, "2024-02-01", fp="FY", form="10-K")]
    data = {"facts": {"us-gaap": {
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": revenue}},
        "LongTermDebt": {"units": {"USD": debt}},
    }}}
    q, a = fetch_sec.parse_companyfacts(data)
    q_ocf = q[q.metric == "operating_cash_flow"].set_index("period")["value"].to_dict()
    assert q_ocf == {"2023Q1": 10, "2023Q2": 15, "2023Q3": 20, "2023Q4": 25}
    q_rev = q[q.metric == "revenue"].set_index("period")["value"].to_dict()
    assert q_rev == {"2023Q1": 100, "2023Q2": 111}
    assert q[(q.metric == "revenue") & (q.period == "2023Q2")]["fiscal_label"].item() == "FY2023 Q1"
    a_vals = a.set_index(["period", "metric"])["value"].to_dict()
    assert a_vals[("2023", "revenue")] == 460
    assert a_vals[("2023", "total_debt")] == 500


def _statements(quarters, **metrics_by_name):
    rows = []
    for metric, values in metrics_by_name.items():
        for p, v in zip(quarters, values):
            rows.append({"period": p, "metric": metric, "value": v, "source": "yahoo"})
    return pd.DataFrame(rows)


QUARTERS = ["2024Q1", "2024Q2", "2024Q3", "2024Q4", "2025Q1"]
BASE = dict(
    revenue=[100] * 5, eps_diluted=[1.0] * 5, net_income=[10] * 5,
    operating_income=[20] * 5, pretax_income=[20] * 5, tax_provision=[5] * 5,
    operating_cash_flow=[30] * 5, capex=[10] * 5, dividends_paid=[2] * 5,
    total_debt=[100] * 5, cash=[40] * 5, equity=[300] * 5, shares_outstanding=[10] * 5,
)


def test_quarterly_rule1_metrics():
    q = metrics.quarterly(_statements(QUARTERS, **BASE), pd.DataFrame(columns=["period", "metric", "value", "source"]))
    last = q.loc["2025Q1"]
    assert last["fcf"] == 20                      # OCF - CapEx
    assert last["fcf_ttm"] == 80
    assert last["roic_ttm"] == pytest.approx(4 * 20 * 0.75 / (100 + 300))  # NOPAT / (Debt + Equity)
    assert last["bvps"] == 30
    assert last["net_debt_fcf_ttm"] == pytest.approx(60 / 80)
    assert np.isnan(q.loc["2024Q3", "fcf_ttm"])  # fewer than 4 quarters


def test_manual_values_win():
    man = pd.DataFrame([{"period": "2025Q1", "metric": "equity", "value": 600.0, "source": "manual"},
                        {"period": "2025Q1", "metric": "roic_ttm", "value": 0.5, "source": "manual"}])
    q = metrics.quarterly(_statements(QUARTERS, **BASE), man)
    assert q.loc["2025Q1", "bvps"] == 60
    assert q.loc["2025Q1", "roic_ttm"] == 0.5


def test_annual_cagr_and_fill_from_quarters():
    years = [str(y) for y in range(2015, 2026)]
    annual = pd.DataFrame([{"period": y, "metric": "revenue", "value": 100 * 1.1 ** i, "source": "sec"}
                           for i, y in enumerate(years)])
    a = metrics.annual(_statements(QUARTERS, **BASE), annual, pd.DataFrame(columns=["period", "metric", "value", "source"]))
    assert a.loc["2025", "revenue_cagr_10y"] == pytest.approx(0.10)
    assert a.loc["2025", "revenue_cagr_1y"] == pytest.approx(0.10)
    assert a.loc["2024", "fcf"] == 80  # from 4 quarters, no annual report
    g = metrics.growth_table(a)
    assert g.loc["revenue", "10y"] == pytest.approx(0.10)


def test_dcf_summary():
    man = pd.DataFrame([{"ticker": "AMZN", "quarter": "2026Q1", "valueinvesting": 100, "alphaspread": 120,
                         "simplywallstreet": 140, "gurufocus_eps": 160, "gurufocus_fcf": 180,
                         "financecharts_fcf": 200, "financecharts_eps": 400, "middle": "median"}])
    d = metrics.dcf(man, "AMZN").loc["2026Q1"]
    assert (d["low"], d["high"], d["median"], d["middle"]) == (120, 260, 160, 160)
    assert d["mean"] == pytest.approx(1300 / 7)


def test_daily_back_calculates_pe_until_snapshot():
    q = metrics.quarterly(_statements(QUARTERS, **BASE), pd.DataFrame(columns=["period", "metric", "value", "source"]))
    dates = pd.to_datetime(["2025-06-02", "2025-06-03"])
    prices = pd.DataFrame({"close": [80.0, 84.0], "trailing_pe_yahoo": [np.nan, 22.0]},
                          index=pd.DatetimeIndex(dates, name="date"))
    d = metrics.daily(prices, q, pd.DataFrame(columns=["ticker", "date", "metric", "value"]))
    assert d["trailing_pe"].tolist() == [20.0, 22.0]  # 80 / TTM EPS 4, then Yahoo's value
    assert d["price_book"].iloc[0] == pytest.approx(80 / 30)
