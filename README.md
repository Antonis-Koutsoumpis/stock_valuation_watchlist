The repository is linked to two versions of the app, with the same data and calculations:

- **Web app (works on phones and desktop):** [Stock valuation watchlist (GitHub Pages)](https://antonis-koutsoumpis.github.io/stock_valuation_watchlist/). It can be installed on a phone's home screen (iPhone: *Share → Add to Home Screen*; Android: menu ⋮ → *Install app*) and works offline with the stocks you opened before.
- **Streamlit app:** [Stock valuation watchlist](https://stock-valuation-watchlist.streamlit.app).

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
  conservative/middle/optimistic; `rule1/valuation.py`). Optionally shades the S&P 500's bear markets
  (falls of 20% or more, peak to low) in light grey and labels what drove each one
  (`rule1/bear_markets.py`; add a row when a new one has ended).

- **Web app** (`docs/`): the same Stock and Screener pages in plain HTML, CSS and JavaScript (Plotly charts).
  After every daily update, `.github/workflows/pages.yml` builds its data with `python -m rule1.export_web`
  (the same code as the Streamlit app) and publishes it on GitHub Pages. The calculated value is worked out in
  the browser (a JavaScript copy of `rule1/valuation.py`), so its sliders work without a server.

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
| `docs/` | Web app for GitHub Pages; `docs/data/` is built by the Pages workflow and not stored in the repository |
| `rule1/export_web.py` | Builds the web app's data files (one JSON file per stock, the screener table, the glossary) |

## Definitions

- ROIC = NOPAT / (Debt + Equity), NOPAT = operating income × (1 − tax rate)
- FCF = Operating Cash Flow − CapEx
- Quarters are calendar quarters of the period end date (2026Q1 = Jan–Mar)
- Back-calculated daily ratios use the latest quarter already published (period end + 45 days)

## Settings (repository secrets)

- `SEC_CONTACT_EMAIL`: required by the SEC for its free data
- `MANUAL_SHEET_ID`: the Google Sheet with manual entries (shared as "anyone with the link can view")

## Web app on GitHub Pages (one-time setup)

In the repository on GitHub go to **Settings → Pages → Build and deployment** and set **Source** to
**GitHub Actions**. Then run the workflow **Publish web app** once from the **Actions** tab (or wait for the next
daily update). The app is then live at https://antonis-koutsoumpis.github.io/stock_valuation_watchlist/.

## Run locally

```
pip install -r requirements.txt
python -m rule1.update      # fetch data
streamlit run app.py        # open the app
python -m rule1.export_web  # build the web app's data, then: cd docs && python -m http.server
python -m pytest            # tests
```

## License

Free for personal and other noncommercial use under the [PolyForm Noncommercial License 1.0.0](LICENSE). Commercial use is not allowed without permission. Market data comes from Yahoo Finance, FRED, multpl.com and Robert Shiller and remains under their own terms.
