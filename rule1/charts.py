"""Trend lines and averages drawn on top of a metric."""

import numpy as np
import pandas as pd

TRENDS = ["Linear", "Polynomial", "Logarithmic", "Exponential"]


def _years(index: pd.DatetimeIndex) -> np.ndarray:
    return (index - index[0]).days.to_numpy() / 365.25


def trend(series: pd.Series, kind: str, degree: int = 2) -> tuple[pd.Series, str]:
    """Fitted values and a legend label.
    Linear: straight line. Polynomial: curve of the given degree.
    Logarithmic: rises quickly at first, then flattens out (y = a + b·ln(t + 1/12)).
    Exponential: a constant growth rate per year (a straight line on a log scale)."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    if kind == "Exponential":
        s = s[s > 0]
    if len(s) < max(3, degree + 1):
        return pd.Series(dtype=float), ""
    x = _years(pd.DatetimeIndex(s.index))
    if kind == "Linear":
        coef = np.polyfit(x, s.values, 1)
        return pd.Series(np.polyval(coef, x), index=s.index), f"linear trend ({coef[0]:+,.2f}/yr)"
    if kind == "Polynomial":
        coef = np.polyfit(x, s.values, degree)
        return pd.Series(np.polyval(coef, x), index=s.index), f"polynomial trend (degree {degree})"
    if kind == "Logarithmic":
        lx = np.log(x + 1 / 12)  # t starts one month in, so ln(t) exists at the first point
        coef = np.polyfit(lx, s.values, 1)
        return pd.Series(np.polyval(coef, lx), index=s.index), "logarithmic trend"
    coef = np.polyfit(x, np.log(s.values), 1)
    growth = np.exp(coef[0]) - 1
    return pd.Series(np.exp(np.polyval(coef, x)), index=s.index), f"exponential trend ({growth:+.1%}/yr)"


def trailing_average(series: pd.Series, years: int) -> tuple[pd.Timestamp, pd.Timestamp, float] | None:
    """Average over the last `years` years of the series: (start, end, value)."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    end = pd.Timestamp(s.index.max())
    start = end - pd.DateOffset(years=years)
    window = s[s.index >= start]
    if pd.Timestamp(s.index.min()) > start + pd.DateOffset(months=6):
        return None  # not enough history for this average
    return start, end, float(window.mean())
