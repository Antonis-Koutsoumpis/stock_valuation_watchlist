"""S&P 500 bear markets: declines of 20% or more from a closing high to the
following low (peak and trough dates of the daily close).

Source of the dates and declines: Yardeni Research, "S&P 500 Bull & Bear
Market Tables" (Standard & Poor's, Haver Analytics). The causes are short
summaries of what is generally seen as having driven each decline.

The list is kept by hand: add a row when a new bear market has ended
(the trough is only known afterwards). rule1/export_web.py copies it to
docs/data/bear_markets.json for the web app.
"""
import textwrap

import pandas as pd

BEAR_MARKETS = [
    # peak, trough, decline (%), short label, what drove it
    ("1929-09-07", "1929-11-13", -44.7, "1929 Crash",
     "Wall Street Crash: a speculative bubble built on borrowed money burst "
     "(Black Thursday and Black Tuesday, October 1929)."),
    ("1930-04-10", "1932-06-01", -83.0, "Great Depression",
     "Bank failures, deflation, tight money and the Smoot-Hawley tariffs "
     "turned the crash into a worldwide depression."),
    ("1932-09-07", "1933-02-27", -40.6, "1933 banking panic",
     "A new wave of bank runs, ending in the national bank holiday of "
     "March 1933."),
    ("1933-07-18", "1933-10-21", -29.8, "1933 rally unwinds",
     "The speculative rally after the dollar left the gold standard "
     "collapsed, amid doubts about the New Deal's recovery programme."),
    ("1934-02-06", "1935-03-14", -31.8, "Stalled recovery",
     "An uneven recovery from the Depression and uncertainty about New Deal "
     "policies and new market regulation."),
    ("1937-03-06", "1938-03-31", -54.5, "1937–38 recession",
     "The Fed doubled banks' reserve requirements and the government cut "
     "spending, pushing the economy back into recession."),
    ("1938-11-09", "1939-04-08", -26.2, "War fears in Europe",
     "The growing threat of war in Europe; Germany occupied Czechoslovakia "
     "in March 1939."),
    ("1939-10-25", "1940-06-10", -31.9, "WWII: fall of France",
     "World War II: Germany's invasion of Western Europe and the fall of "
     "France (May–June 1940)."),
    ("1940-11-09", "1942-04-28", -34.5, "WWII: Pearl Harbor",
     "World War II: the attack on Pearl Harbor (December 1941) brought the "
     "US into the war, followed by early Allied defeats."),
    ("1946-05-29", "1946-10-09", -26.6, "Post-war inflation",
     "The end of wartime price controls: an inflation surge, strikes and "
     "fears of a post-war slump."),
    ("1948-06-15", "1949-06-13", -20.6, "1948–49 recession",
     "Tighter money against post-war inflation, followed by the 1948–49 "
     "recession."),
    ("1957-07-15", "1957-10-22", -20.7, "1957 recession",
     "Fed rate rises, the 1957–58 recession and the Sputnik shock "
     "(October 1957)."),
    ("1961-12-12", "1962-06-26", -28.0, "Kennedy Slide",
     "High valuations unwound; President Kennedy's clash with the steel "
     "industry and the flash crash of May 1962."),
    ("1966-02-09", "1966-10-07", -22.2, "1966 credit crunch",
     "Inflation rose with Vietnam War and Great Society spending, and the "
     "Fed tightened credit sharply."),
    ("1968-11-29", "1970-05-26", -36.1, "1969–70 recession",
     "Rising inflation and interest rates, the Vietnam War and the 1969–70 "
     "recession (Penn Central's collapse in 1970)."),
    ("1973-01-11", "1974-10-03", -48.2, "Oil crisis & stagflation",
     "The OPEC oil embargo (1973), stagflation, the end of the Bretton Woods "
     "system, Watergate and the end of the 'Nifty Fifty' boom."),
    ("1980-11-28", "1982-08-12", -27.1, "Volcker rate shock",
     "The Fed (Paul Volcker) raised interest rates to about 20% to break "
     "inflation, causing the 1981–82 recession."),
    ("1987-08-25", "1987-12-04", -33.5, "Black Monday",
     "The S&P 500 fell 20.5% on 19 October 1987 alone: high valuations, "
     "rising rates and automated 'portfolio insurance' selling."),
    ("2000-03-24", "2002-10-09", -49.1, "Dot-com bubble",
     "The internet/tech bubble burst, followed by the 2001 recession, the "
     "9/11 attacks and accounting scandals (Enron, WorldCom)."),
    ("2007-10-09", "2009-03-09", -56.8, "Global financial crisis",
     "The US housing and subprime-mortgage bubble burst; Lehman Brothers' "
     "collapse (September 2008) set off a global banking crisis."),
    ("2020-02-19", "2020-03-23", -33.9, "COVID-19 pandemic",
     "The COVID-19 pandemic and lockdowns: the fastest fall into a bear "
     "market on record."),
    ("2022-01-03", "2022-10-12", -25.4, "Inflation & rate hikes",
     "High inflation and the fastest Fed rate rises since the 1980s; "
     "Russia's invasion of Ukraine (February 2022) added an energy shock."),
]

BEAR_FILL = "rgba(128, 128, 128, 0.18)"
BEAR_HELP = (
    "**What is a bear market?** A fall of **20% or more** in a stock market "
    "index from its last closing high (the *peak*) to the lowest close that "
    "follows (the *trough*), after which prices rise again. It is measured on "
    "daily closing prices.\n\n"
    "**What is shaded:** the period from the peak to the trough, in light "
    "grey. Smaller falls of 10–20% are called *corrections* and are not "
    "shaded.\n\n"
    "**Good to know:** the 20% line is a convention, not a law of nature: "
    "falls that stopped just short of it (1990, 1998, 2011, 2018 and April "
    "2025) are not counted. A bear market is only known once its low is "
    "behind us, so a new one is added afterwards.\n\n"
    "**Which market:** the S&P 500 (the US market) — 22 bear markets since "
    "1928, dates from Yardeni Research — also when another stock or index is shown, as a "
    "reference for the market as a whole."
)


def bear_table() -> pd.DataFrame:
    df = pd.DataFrame(BEAR_MARKETS, columns=["peak", "trough", "decline", "label", "cause"])
    df["peak"] = pd.to_datetime(df["peak"])
    df["trough"] = pd.to_datetime(df["trough"])
    return df


def bears_in_range(start, end) -> pd.DataFrame:
    df = bear_table()
    return df[(df["trough"] >= pd.Timestamp(start)) & (df["peak"] <= pd.Timestamp(end))]


def hover_text(r) -> str:
    return (f"<b>{r.label}</b><br>{r.peak:%d %b %Y} – {r.trough:%d %b %Y}: "
            f"{r.decline:.1f}%<br>" + "<br>".join(textwrap.wrap(r.cause, 60)))


def add_bear_markets(fig, start, end, causes: bool = False, font_size: int = 10):
    """Shade the bear markets between start and end in light grey; with
    `causes`, label each with what drove it (hover the label for more)."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    for r in bears_in_range(start, end).itertuples():
        fig.add_vrect(x0=r.peak, x1=r.trough, fillcolor=BEAR_FILL, line_width=0, layer="below")
        if causes:
            a, b = max(r.peak, start), min(r.trough, end)
            fig.add_annotation(
                x=a + (b - a) / 2, xref="x", y=1, yref="paper", yanchor="top",
                text=r.label, textangle=-90, showarrow=False,
                font=dict(size=font_size, color="rgba(90, 90, 90, 0.95)"),
                hovertext=hover_text(r),
            )
    return fig
