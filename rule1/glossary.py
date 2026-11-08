"""Names and plain-language explanations of every metric shown in the app."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    label: str
    help: str
    frequency: str  # "Daily", "Quarterly", "Yearly"
    percent: bool = False

    @property
    def tooltip(self) -> str:
        return f"{self.help}\n\nUpdated: {self.frequency.lower()}."


DAILY = {
    "close": Metric("Price", "The share price at the close of each trading day.", "Daily"),
    "volume": Metric("Volume", "How many shares changed hands that day.", "Daily"),
    "trailing_pe": Metric(
        "Trailing P/E",
        "Price ÷ earnings per share of the last 12 months. Roughly: how many years of today's "
        "profit you pay for. Lower = cheaper.",
        "Daily (price changes daily, earnings every quarter)"),
    "forward_pe": Metric(
        "Forward P/E",
        "Price ÷ the earnings per share analysts expect over the next 12 months. "
        "Only available from Yahoo from the day tracking started.",
        "Daily"),
    "peg_5y": Metric(
        "PEG ratio (5yr expected)",
        "P/E ÷ expected yearly earnings growth over the next 5 years. Below 1 can mean the "
        "price is low for the growth expected. Yahoo only, from the day tracking started.",
        "Daily"),
    "price_sales": Metric(
        "Price/Sales",
        "Company value (price × shares) ÷ revenue of the last 12 months.",
        "Daily (price changes daily, revenue every quarter)"),
    "price_book": Metric(
        "Price/Book",
        "Price ÷ book value per share (what the company owns minus what it owes, per share).",
        "Daily (price changes daily, book value every quarter)"),
    "trailing_div_yield": Metric(
        "Trailing dividend yield",
        "Dividends paid over the last 12 months ÷ today's price. 2% means 2 a year for every 100 invested.",
        "Daily", percent=True),
    "forward_div_yield": Metric(
        "Forward dividend yield",
        "Dividends expected over the next 12 months ÷ today's price. Yahoo only.",
        "Daily", percent=True),
    "payout_ratio": Metric(
        "Payout ratio",
        "The share of profit paid out as dividends. 30% = 30 of every 100 earned.",
        "Daily (changes when new results are published)", percent=True),
    "market_cap": Metric("Market cap", "Total value of the company on the stock market: price × shares.", "Daily"),
    # Whole US market (S&P 500 page only)
    "cape": Metric(
        "CAPE (Shiller P/E)",
        "S&P 500 price ÷ the average of the last 10 years of earnings, adjusted for inflation. Smooths out "
        "booms and recessions; high values have been followed by low returns over the next 10 years. "
        "For buying: LOWER is better (below its long-term average of about 17 = cheap). "
        "Source: Robert Shiller (Yale) and multpl.com for recent months.", "Monthly"),
    "pe_shiller": Metric(
        "S&P 500 P/E (12 months)",
        "S&P 500 price ÷ reported earnings of the last 12 months, since 1871. Source: Robert Shiller (Yale) and multpl.com; "
        "earnings arrive a few months late. For buying: LOWER is better (below its long-term average of about 16 "
        "= cheap). Jumps up in recessions because earnings fall, so check it together with CAPE.", "Monthly"),
    "sp500_eps": Metric(
        "S&P 500 EPS (12 months)",
        "Earnings per share of the S&P 500 as a whole: the reported profit of all 500 companies over the last "
        "12 months, per unit of the index (in index points, so S&P 500 ÷ this = its P/E). Since 1871. For buying: "
        "steady growth is good; compare its growth with the price: price rising faster than EPS = getting more "
        "expensive. Source: Robert Shiller (Yale) and multpl.com.", "Monthly"),
    "sp500_sales": Metric(
        "S&P 500 sales per share (12 months)",
        "Revenue of all S&P 500 companies over the last 12 months, per unit of the index (index points). "
        "S&P 500 ÷ this = its price/sales. For buying: steady growth is good; price rising much faster than "
        "sales = getting more expensive. Source: multpl.com (S&P data).", "Quarterly"),
    "buffett": Metric(
        "Buffett indicator",
        "Market value of US non-financial companies ÷ US GDP (yearly economic output). Above its long-term average = "
        "stocks are expensive compared with the economy. For buying: LOWER is better. "
        "Source: FRED (US Federal Reserve).",
        "Quarterly, about 3 months late", percent=True),
    "earnings_yield_gap": Metric(
        "Earnings yield − 10y bond yield",
        "1 ÷ P/E (what the S&P 500 earns per 100 invested) minus the 10-year US Treasury yield. Low or "
        "negative = stocks pay little extra over safe bonds, i.e. expensive. For buying: HIGHER is better.",
        "Monthly", percent=True),
    "ten_year_yield": Metric(
        "10-year Treasury yield",
        "Interest on 10-year US government bonds. For buying stocks: LOWER is better, because high bond yields "
        "make safe bonds a strong alternative and usually weigh on stock prices. Source: FRED.", "Daily", percent=True),
}

QUARTERLY = {
    "revenue": Metric("Revenue (quarter)", "Total sales in that quarter.", "Quarterly"),
    "revenue_ttm": Metric("Revenue (TTM)", "Total sales over the last 4 quarters (TTM = trailing 12 months).", "Quarterly"),
    "eps_diluted": Metric("EPS (diluted, quarter)", "Profit per share in that quarter, diluted (counts shares from options and convertibles too).", "Quarterly"),
    "eps_diluted_ttm": Metric("EPS (diluted, TTM)", "Profit per share over the last 4 quarters, diluted.", "Quarterly"),
    "fcf": Metric(
        "Free cash flow (quarter)",
        "Cash from the business minus money spent on equipment and buildings (Operating Cash Flow − CapEx). "
        "The cash left over for the owners.",
        "Quarterly"),
    "fcf_ttm": Metric("Free cash flow (TTM)", "Free cash flow over the last 4 quarters.", "Quarterly"),
    "roic_ttm": Metric(
        "ROIC (TTM)",
        "Return on invested capital: after-tax operating profit of the last 12 months ÷ (debt + equity). "
        "How much profit each euro/dollar invested in the business makes. Rule #1 looks for 10% or more.",
        "Quarterly", percent=True),
    "bvps": Metric(
        "BVPS",
        "Book value per share: equity (what the company owns minus what it owes) ÷ shares. "
        "Rule #1 looks for it to grow 10% or more a year.",
        "Quarterly"),
    "total_debt": Metric("Debt", "Money the company has borrowed (short and long term).", "Quarterly"),
    "net_debt_fcf_ttm": Metric(
        "Net Debt / FCF (TTM)",
        "(Debt − cash) ÷ free cash flow of the last 12 months: how many years of free cash flow it "
        "would take to pay off the debt. Rule #1 looks for 3 or less. Negative = more cash than debt.",
        "Quarterly"),
    "dividends_ttm": Metric("Dividends (TTM)", "Total dividends paid over the last 4 quarters.", "Quarterly"),
    "shares_outstanding": Metric("Shares outstanding", "Number of shares that exist.", "Quarterly"),
}

DCF = {
    "dcf_low": Metric("DCF low end", "Most conservative estimate of what one share is worth (intrinsic value).", "Quarterly (entered by hand)"),
    "dcf_middle": Metric("DCF middle", "Middle estimate of what one share is worth (mean or median of the sites).", "Quarterly (entered by hand)"),
    "dcf_high": Metric("DCF high end", "Most optimistic estimate of what one share is worth.", "Quarterly (entered by hand)"),
}

YEARLY = {
    "roic": Metric("ROIC", "After-tax operating profit of the year ÷ (debt + equity). Rule #1 looks for 10% or more.", "Yearly", percent=True),
    "bvps": Metric("BVPS", "Book value per share at year end.", "Yearly"),
    "revenue": Metric("Revenue", "Total sales in the year.", "Yearly"),
    "eps_diluted": Metric("EPS (diluted)", "Profit per share in the year, diluted (counts shares from options and convertibles too).", "Yearly"),
    "fcf": Metric("Free Cash Flow", "Operating Cash Flow − CapEx for the year.", "Yearly"),
    "net_debt_fcf": Metric("Net Debt / FCF", "Years of free cash flow needed to pay off the debt. Rule #1 looks for 3 or less.", "Yearly"),
    "total_debt": Metric("Debt", "Borrowed money at year end.", "Yearly"),
    "dividends": Metric("Dividends", "Total dividends paid in the year.", "Yearly"),
    "payout_ratio": Metric("Payout ratio", "Share of the year's profit paid as dividends.", "Yearly", percent=True),
    "shares_outstanding": Metric("Shares outstanding", "Number of shares at year end.", "Yearly"),
}

CAGR_HELP = ("Growth per year, on average, over the number of years in the column (CAGR). "
             "Rule #1 looks for 10% or more a year for BVPS, Revenue, EPS and Free Cash Flow.")

GRAPH = {**DAILY, **QUARTERLY, **DCF}
