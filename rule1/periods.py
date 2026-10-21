"""Quarter labels such as 2026Q1, based on the calendar quarter of a period end date."""

import pandas as pd

# Companies on 52/53-week calendars end quarters a few days into the next
# calendar quarter (e.g. 2 Jan). Shifting back keeps them in the right quarter.
_SHIFT = pd.Timedelta(days=14)


def quarter_label(period_end) -> str:
    d = pd.Timestamp(period_end) - _SHIFT
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def year_label(period_end) -> str:
    return str((pd.Timestamp(period_end) - _SHIFT).year)


def quarter_start(label: str) -> pd.Timestamp:
    year, q = int(label[:4]), int(label[-1])
    return pd.Timestamp(year=year, month=3 * (q - 1) + 1, day=1)


def quarter_end(label: str) -> pd.Timestamp:
    return quarter_start(label) + pd.offsets.QuarterEnd(0)


def date_to_quarter(dates: pd.Series) -> pd.Series:
    dates = pd.to_datetime(dates)
    return dates.dt.year.astype(str) + "Q" + dates.dt.quarter.astype(str)
