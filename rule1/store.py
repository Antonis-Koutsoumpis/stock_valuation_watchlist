"""CSV storage. Rows are added or updated, never deleted, so history accumulates
even after a source stops offering older periods."""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Long format for statement data: one row per (period, metric, source).
STATEMENT_COLUMNS = ["period", "period_end", "fiscal_label", "metric", "value", "source", "fetched_at"]
STATEMENT_KEYS = ["period", "metric", "source"]


def stock_dir(ticker: str) -> Path:
    path = DATA_DIR / ticker
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, **kwargs)


def merge_daily(path: Path, new: pd.DataFrame) -> pd.DataFrame:
    """Merge wide daily rows indexed by date. New non-empty values win; old rows stay."""
    old = read_csv(path, index_col="date", parse_dates=["date"])
    if new.empty:
        return old
    new = new.copy()
    new.index = pd.to_datetime(new.index).normalize()
    new.index.name = "date"
    merged = new if old.empty else new.combine_first(old)
    merged = merged.sort_index()
    merged.to_csv(path, date_format="%Y-%m-%d", float_format="%.6g")
    return merged


def merge_statements(path: Path, new: pd.DataFrame, replace_sources: set[str] = frozenset()) -> pd.DataFrame:
    """Merge long statement rows. A newer fetch of the same key replaces the value
    (restatements); keys missing from the new fetch are kept, except for sources in
    `replace_sources` that always deliver their full history (the SEC), whose old rows
    are replaced by the new fetch."""
    old = read_csv(path, dtype={"period": str, "fiscal_label": str})
    if new.empty:
        return old
    new = new.reindex(columns=STATEMENT_COLUMNS)
    replaced = set(replace_sources) & set(new["source"])
    if replaced and not old.empty:
        old = old[~old["source"].isin(replaced)]
    merged = new if old.empty else pd.concat([old, new], ignore_index=True)
    merged = merged.dropna(subset=["value"])
    merged = merged.drop_duplicates(subset=STATEMENT_KEYS, keep="last")
    merged = merged.sort_values(["period", "metric", "source"]).reset_index(drop=True)
    merged.to_csv(path, index=False, float_format="%.10g")
    return merged
