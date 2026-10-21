"""Manual entries from the Google Sheet (or a local Excel copy). Manual values
always win over fetched ones. The sheet is never written to."""

import os
from pathlib import Path
from urllib.parse import quote

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LOCAL_XLSX = ROOT / "manual" / "manual_entries.xlsx"
BACKUP_DIR = ROOT / "data" / "_manual_backup"

TABS = {
    "statements": ["ticker", "period", "metric", "value", "note"],
    "daily": ["ticker", "date", "metric", "value", "note"],
    "dcf": ["ticker", "quarter", "valueinvesting", "alphaspread", "simplywallstreet",
            "gurufocus_eps", "gurufocus_fcf", "financecharts_fcf", "financecharts_eps", "middle",
            "dcf_low", "dcf_average", "dcf_high", "note"],
}
DCF_SOURCES = TABS["dcf"][2:9]
DCF_OVERRIDES = ["dcf_low", "dcf_average", "dcf_high"]  # typed-in range; wins over the calculated one


def _sheet_url(sheet_id: str, tab: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={quote(tab)}"


def _clean(df: pd.DataFrame, tab: str) -> pd.DataFrame:
    df = df.rename(columns=lambda c: str(c).strip().lower())
    df = df.reindex(columns=TABS[tab]).dropna(how="all")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    if tab == "statements":
        df["period"] = df["period"].astype(str).str.strip().str.upper().str.replace(r"\.0$", "", regex=True)
        df["metric"] = df["metric"].astype(str).str.strip()
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"])
    elif tab == "daily":
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["metric"] = df["metric"].astype(str).str.strip()
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["date", "value"])
    else:
        df["quarter"] = df["quarter"].astype(str).str.strip().str.upper()
        for col in DCF_SOURCES + DCF_OVERRIDES:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["middle"] = df["middle"].fillna("median").astype(str).str.strip().str.lower()
    return df.reset_index(drop=True)


def load(sheet_id: str | None = None) -> dict[str, pd.DataFrame]:
    """Google Sheet if an id is set, else the local Excel file, else the last backup."""
    sheet_id = sheet_id or os.environ.get("MANUAL_SHEET_ID")
    out = {}
    for tab, cols in TABS.items():
        df = None
        try:
            if sheet_id:
                df = pd.read_csv(_sheet_url(sheet_id, tab))
            elif LOCAL_XLSX.exists():
                df = pd.read_excel(LOCAL_XLSX, sheet_name=tab)
        except Exception as exc:  # a missing tab or no network falls back to the backup
            print(f"manual: could not read tab '{tab}': {exc}")
        if df is None and (BACKUP_DIR / f"{tab}.csv").exists():
            df = pd.read_csv(BACKUP_DIR / f"{tab}.csv")
        out[tab] = _clean(df, tab) if df is not None else pd.DataFrame(columns=cols)
    return out


def backup(manual: dict[str, pd.DataFrame]) -> None:
    """Keep a copy in the repository, so manual data survives even if the sheet is lost."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for tab, df in manual.items():
        if not df.empty:
            df.to_csv(BACKUP_DIR / f"{tab}.csv", index=False, date_format="%Y-%m-%d")


def statements_for(manual: dict, ticker: str) -> pd.DataFrame:
    df = manual["statements"]
    df = df[df["ticker"] == ticker]
    return df.assign(source="manual")[["period", "metric", "value", "source"]]
