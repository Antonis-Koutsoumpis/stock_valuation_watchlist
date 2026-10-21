The repository is linked to the Streamlit app [Stock valuation watchlist](https://stock-valuation-watchlist.streamlit.app).

# Stock valuation watchlist

An online tool that values stocks using Phil Town's Rule #1 criteria. It runs for free: this
GitHub repository stores the data, a daily GitHub Actions job updates it, and a Streamlit app
shows it.

## How it works

- **Daily update** (`.github/workflows/daily-update.yml`, after the US close on weekdays):
  fetches prices, Yahoo's valuation snapshot and the latest statements for every stock in
  `config/watchlist.csv`, and adds them to `data/<TICKER>/`. Nothing is ever deleted, so history
  keeps growing after Yahoo drops older periods.
- **Sources**: SEC EDGAR for US companies (10+ years of quarterly statements), Yahoo Finance for
  all stocks, and manual entries from the Google Sheet. Manual values always win.
- **App** (`app.py`): search the watchlist, plot any metrics (raw or log scale, daily or
  averaged per quarter), see Rule #1 growth (CAGR over 1 to 10 years), the DCF range from the
  sites you entered, and a calculated value (FCF DCF, EPS DCF and Rule #1 Sticker Price, each
  conservative/middle/optimistic; `rule1/valuation.py`).

## Files

| Path | What it holds |
| --- | --- |
| `config/watchlist.csv` | The stocks on the watchlist. Add a row to add a stock (US stocks find their SEC data automatically) |
| `config/ticker_reference.csv` | All planned stocks and indices. Use the `ticker` column in the manual-entry sheet; `yahoo_check` shows whether Yahoo knows the symbol |
| `data/<TICKER>/daily.csv` | Daily close, volume, and Yahoo's daily snapshot (`*_yahoo` columns) |
| `data/<TICKER>/quarterly.csv` | Quarterly statement values, one row per period, metric and source |
| `data/<TICKER>/annual.csv` | Fiscal-year statement values |
| `data/_manual_backup/` | Daily copy of the manual-entry sheet |
| `templates/manual_entries_template.xlsx` | Fixed layout for manual entries |

## Definitions

- ROIC = NOPAT / (Debt + Equity), NOPAT = operating income × (1 − tax rate)
- FCF = Operating Cash Flow − CapEx
- Quarters are calendar quarters of the period end date (2026Q1 = Jan–Mar)
- Back-calculated daily ratios use the latest quarter already published (period end + 45 days)

## Settings (repository secrets)

- `SEC_CONTACT_EMAIL`: required by the SEC for its free data
- `MANUAL_SHEET_ID`: the Google Sheet with manual entries (shared as "anyone with the link can view")

## Run locally

```
pip install -r requirements.txt
python -m rule1.update      # fetch data
streamlit run app.py        # open the app
python -m pytest            # tests
```
