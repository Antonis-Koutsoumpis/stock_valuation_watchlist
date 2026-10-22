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


def test_typed_in_dcf_range_wins():
    man = pd.DataFrame([{"ticker": "FTK", "quarter": "2026Q1", "valueinvesting": 10, "alphaspread": 20,
                         "simplywallstreet": 30, "gurufocus_eps": np.nan, "gurufocus_fcf": np.nan,
                         "financecharts_fcf": np.nan, "financecharts_eps": np.nan, "middle": "median",
                         "dcf_low": np.nan, "dcf_average": 25.0, "dcf_high": 40.0},
                        {"ticker": "FTK", "quarter": "2026Q2", "valueinvesting": np.nan, "alphaspread": np.nan,
                         "simplywallstreet": np.nan, "gurufocus_eps": np.nan, "gurufocus_fcf": np.nan,
                         "financecharts_fcf": np.nan, "financecharts_eps": np.nan, "middle": "median",
                         "dcf_low": 5.0, "dcf_average": 6.0, "dcf_high": 7.0}])
    d = metrics.dcf(man, "FTK")
    assert (d.loc["2026Q1", "low"], d.loc["2026Q1", "middle"], d.loc["2026Q1", "high"]) == (20, 25, 40)
    assert (d.loc["2026Q2", "low"], d.loc["2026Q2", "middle"], d.loc["2026Q2", "high"]) == (5, 6, 7)


def test_trend_lines():
    from rule1 import charts
    idx = pd.date_range("2016-01-01", periods=11, freq="YS")
    grow = pd.Series(100 * 1.1 ** np.arange(11), index=idx)
    fitted, label = charts.trend(grow, "Log")
    assert fitted.iloc[-1] == pytest.approx(grow.iloc[-1], rel=1e-3)
    assert "+10.0%/yr" in label
    line = pd.Series(np.arange(11) * 2.0 + 1, index=idx)
    fitted, _ = charts.trend(line, "Linear")
    assert fitted.values == pytest.approx(line.values, abs=0.05)
    fitted, label = charts.trend(grow, "Polynomial", 3)
    assert len(fitted) == 11 and "degree 3" in label


def test_trailing_average():
    from rule1 import charts
    idx = pd.date_range("2010-01-01", "2025-12-31", freq="QS")
    s = pd.Series(np.where(idx.year >= 2021, 20.0, 10.0), index=idx)
    _, _, five = charts.trailing_average(s, 5)
    assert five == pytest.approx(20.0, abs=1.0)
    assert charts.trailing_average(s[s.index.year >= 2022], 10) is None  # not enough history


def test_screener_and_filters():
    from rule1 import screener
    table = pd.DataFrame({"roic_avg_10y": [0.15, 0.05, np.nan], "bvps_cagr_5y": [0.12, 0.20, 0.30],
                          "trailing_pe": [15.0, 30.0, 10.0]}, index=["A", "B", "C"])
    cond = pd.DataFrame([{"metric": "ROIC", "period": "10y", "operator": ">=", "value": 10},
                         {"metric": "BVPS growth", "period": "5y", "operator": ">", "value": 10},
                         {"metric": "Trailing P/E", "period": None, "operator": "<", "value": 20}])
    assert list(screener.apply_filters(table, cond).index) == ["A"]
    # A growth metric without a period is ignored rather than guessed.
    only = pd.DataFrame([{"metric": "BVPS growth", "period": None, "operator": ">", "value": 10}])
    assert len(screener.apply_filters(table, only)) == 3


def test_screener_summary_roic_average():
    from rule1 import screener
    annual = pd.DataFrame({"roic": [0.05, 0.10, 0.20]}, index=["2023", "2024", "2025"])
    row = screener.summary_row(pd.DataFrame(), pd.DataFrame(), annual, pd.DataFrame())
    assert row["roic_avg_2y"] == pytest.approx(0.15)
    assert np.isnan(row["roic_avg_5y"])


def test_sec_split_adjustment():
    eps = [
        _fact("2019-01-01", "2019-12-31", 23.0, "2020-01-31", fy=2019, fp="FY", form="10-K"),
        # Filed after the 20-for-1 split: already restated.
        _fact("2021-01-01", "2021-12-31", 3.24, "2023-02-03", fy=2022, fp="FY", form="10-K"),
    ]
    shares = [_fact(None, "2019-12-31", 500, "2020-01-31", fp="FY", form="10-K")]
    data = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": eps}},
                                  "CommonStockSharesOutstanding": {"units": {"shares": shares}}}}}
    splits = pd.Series([20.0], index=pd.to_datetime(["2022-06-06"]))
    _, a = fetch_sec.parse_companyfacts(data, splits)
    vals = a.set_index(["period", "metric"])["value"].to_dict()
    assert vals[("2019", "eps_diluted")] == pytest.approx(1.15)
    assert vals[("2021", "eps_diluted")] == pytest.approx(3.24)
    assert vals[("2019", "shares_outstanding")] == 10000


def test_sec_rows_are_replaced_by_a_new_full_fetch(tmp_path):
    path = tmp_path / "annual.csv"
    row = lambda p, v, src: {"period": p, "period_end": "", "fiscal_label": "", "metric": "fcf",
                             "value": v, "source": src, "fetched_at": ""}
    store.merge_statements(path, pd.DataFrame([row("2026", -1.0, "sec"), row("2020", 5.0, "yahoo")]))
    merged = store.merge_statements(path, pd.DataFrame([row("2025", 2.0, "sec")]), replace_sources={"sec"})
    assert sorted(zip(merged["period"], merged["source"])) == [("2020", "yahoo"), ("2025", "sec")]


def test_daily_falls_back_to_yearly_figures():
    years = pd.DataFrame([{"period": y, "metric": m, "value": v, "source": "yahoo"}
                          for y, eps in [("2023", 2.0), ("2024", 3.0)]
                          for m, v in [("eps_diluted", eps), ("equity", 100.0), ("shares_outstanding", 10.0),
                                       ("revenue", 50.0)]])
    empty = pd.DataFrame(columns=["period", "metric", "value", "source"])
    a = metrics.annual(empty, years, empty)
    dates = pd.to_datetime(["2024-02-01", "2024-04-02", "2025-04-01"])
    prices = pd.DataFrame({"close": [20.0, 20.0, 30.0]}, index=pd.DatetimeIndex(dates, name="date"))
    d = metrics.daily(prices, pd.DataFrame(), pd.DataFrame(columns=["ticker", "date", "metric", "value"]), a)
    # 2023's report counts from the end of March 2024, 2024's from the end of March 2025.
    assert np.isnan(d["trailing_pe"].iloc[0])
    assert d["trailing_pe"].iloc[1:].tolist() == [10.0, 10.0]
    assert d["price_book"].iloc[1:].tolist() == [2.0, 3.0]


def test_daily_converts_reporting_currency_and_adr_ratio():
    q = metrics.quarterly(_statements(QUARTERS, **BASE), pd.DataFrame(columns=["period", "metric", "value", "source"]))
    dates = pd.DatetimeIndex(pd.to_datetime(["2025-06-02"]), name="date")
    prices = pd.DataFrame({"close": [100.0]}, index=dates)
    fx = pd.Series([0.5], index=pd.to_datetime(["2025-06-01"]))  # 1 unit of reporting currency = 0.5 USD
    d = metrics.daily(prices, q, pd.DataFrame(columns=["ticker", "date", "metric", "value"]), None, fx, 5)
    # TTM EPS 4 -> 2 USD per share -> 10 USD per ADR (5 shares)
    assert d["trailing_pe"].iloc[0] == pytest.approx(10.0)
    assert d["price_book"].iloc[0] == pytest.approx(100 / (30 * 0.5 * 5))


def test_sec_q4_eps_from_full_year():
    eps = [
        _fact("2023-01-01", "2023-03-31", 1.0, "2023-04-30", fp="Q1"),
        _fact("2023-04-01", "2023-06-30", 1.1, "2023-07-30", fp="Q2"),
        _fact("2023-07-01", "2023-09-30", 1.2, "2023-10-30", fp="Q3"),
        _fact("2023-01-01", "2023-12-31", 4.6, "2024-02-01", fp="FY", form="10-K"),
    ]
    data = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": eps}}}}}
    q, _ = fetch_sec.parse_companyfacts(data)
    vals = q.set_index("period")["value"].to_dict()
    assert vals["2023Q4"] == pytest.approx(1.3)


def test_dcf_per_share_matches_hand_calculation():
    from rule1 import valuation
    # 2 years at 10% growth, 10% discount: each year is worth 1.0 today; terminal 3%
    v = valuation.dcf_per_share(1.0, 0.10, 0.10, 0.03, 2)
    terminal = 1.21 * 1.03 / 0.07 / 1.21
    assert abs(v - (2 + terminal)) < 1e-9
    assert np.isnan(valuation.dcf_per_share(-1.0, 0.1, 0.1, 0.03, 5))


def test_sticker_price_uses_lower_pe_and_half_for_mos():
    from rule1 import valuation
    a = valuation.Assumptions(horizon=10)
    sticker, mos = valuation.sticker_price(2.0, 0.10, 15.0, a)  # future P/E = min(20, 15)
    assert abs(sticker - 2.0 * 1.1 ** 10 * 15 / 1.15 ** 10) < 1e-9
    assert mos == sticker / 2


def test_valuation_scenarios_and_history():
    from rule1 import valuation
    days = pd.bdate_range("2015-01-01", "2020-12-31")
    daily = pd.DataFrame({"close": 100.0, "trailing_pe": 20.0, "trailing_pe_yahoo": 20.0, "peg_5y_yahoo": 2.0},
                         index=days)
    years = [str(y) for y in range(2010, 2020)]
    annual = pd.DataFrame({"eps_diluted_cagr_5y": 0.08, "fcf_cagr_5y": 0.12, "net_income": 1.0, "fcf": 1.0},
                          index=pd.Index(years, name="period"))
    quarterly = pd.DataFrame({"period_end": pd.to_datetime(["2019-12-31"]), "fcf_ttm": [2.0], "net_income_ttm": [4.0]},
                             index=["2019Q4"])
    v = valuation.value(daily, quarterly, annual)
    assert v["candidates"] == {"EPS (diluted) 5y": 0.08, "FCF 5y": 0.12, "Analysts 5y": 0.10}
    assert v["growth"]["Conservative"] < v["growth"]["Middle"] < v["growth"]["Optimistic"]
    assert v["inputs"]["eps"] == 5.0 and v["inputs"]["fcf_per_share"] == 2.5
    assert v["range"]["low"] < v["range"]["middle"] < v["range"]["high"]
    own = valuation.value(daily, quarterly, annual, valuation.Assumptions(growth=0.05))
    assert own["growth"]["Middle"] == 0.05
    h = valuation.history(daily, quarterly, annual)
    assert h.index[0] == "2015Q1" and h.index[-1] == "2020Q4"
    assert h["middle"].notna().all()


def test_more_methods():
    from rule1 import valuation
    assert valuation.graham_formula(2.0, 0.10, 0.044) == pytest.approx(2.0 * 28.5)
    assert valuation.lynch(2.0, 0.40) == 50.0  # growth capped at 25
    assert valuation.graham_number(2.0, 10.0) == pytest.approx(np.sqrt(450))
    assert valuation.exit_multiple(1.0, 0.0, 0.0, 10, 2) == pytest.approx(12.0)


def test_inflation_adjusted_prices():
    from rule1 import inflation
    cpi = pd.Series([100.0, 110.0], index=pd.to_datetime(["2020-01-01", "2020-02-01"]))
    prices = pd.Series([10.0, 10.0, 10.0], index=pd.to_datetime(["2020-01-15", "2020-02-15", "2020-03-15"]))
    real = inflation.real(prices, cpi)
    assert real.tolist() == pytest.approx([11.0, 10.0, 10.0])
