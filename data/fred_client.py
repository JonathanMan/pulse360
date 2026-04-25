"""
FRED data layer for Pulse360.

All series are fetched via fredapi with Streamlit caching.
Each fetch returns a result dict with data, staleness metadata, and error info —
never raises, never returns None silently.
"""

import logging
from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st
from fredapi import Fred

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Series registry
# (series_id) -> (human description, frequency, stale_threshold_days)
# ---------------------------------------------------------------------------
SERIES_META: dict[str, tuple[str, str, int]] = {
    # ── Recession model inputs ───────────────────────────────────────────────
    "T10Y3M":           ("10Y–3M Treasury Spread",                "daily",     5),
    "SAHMREALTIME":     ("Sahm Rule Recession Indicator",          "monthly",  45),
    "CFNAI":            ("Chicago Fed National Activity Index",      "monthly",  65),
    "NFCI":             ("Chicago Fed NFCI",                       "weekly",   14),
    "ICSA":             ("Initial Jobless Claims (weekly)",        "weekly",   14),
    "BAMLH0A0HYM2":     ("HY OAS (bps)",                          "daily",     5),
    "NAPM":             ("ISM Manufacturing PMI",                  "monthly",  45),
    # ── Tab 1 – Macro Overview ───────────────────────────────────────────────
    "A191RL1Q225SBEA":  ("Real GDP Growth QoQ Ann.",               "quarterly",220),
    "GDPC1":            ("Real GDP Level",                         "quarterly",220),
    "USREC":            ("NBER Recession Indicator",               "monthly",   60),
    # ── Tab 2 – Growth & Business Activity ──────────────────────────────────
    "INDPRO":           ("Industrial Production",                  "monthly",  45),
    "TCU":              ("Capacity Utilization",                   "monthly",  45),
    "NMFCI":            ("ISM Services PMI",                       "monthly",  45),
    "ADXTNO":           ("Durable Goods ex-def ex-aircraft",       "monthly",  45),
    # ── Tab 3 – Labor Market ─────────────────────────────────────────────────
    "UNRATE":           ("Unemployment Rate (U-3)",                "monthly",  45),
    "U6RATE":           ("U-6 Underemployment",                    "monthly",  45),
    "PAYEMS":           ("Nonfarm Payrolls",                       "monthly",  45),
    "IC4WSA":           ("Initial Claims 4-Week Avg",              "weekly",   14),
    "CCSA":             ("Continuing Claims",                      "weekly",   14),
    "JTSJOL":           ("JOLTS Job Openings",                     "monthly",  60),
    "CES0500000003":    ("Avg Hourly Earnings",                    "monthly",  45),
    # ── Tab 4 – Inflation & Prices ───────────────────────────────────────────
    "CPIAUCSL":         ("CPI All Items",                          "monthly",  45),
    "CPILFESL":         ("Core CPI",                               "monthly",  45),
    "PCEPI":            ("PCE",                                    "monthly",  45),
    "PCEPILFE":         ("Core PCE",                               "monthly",  45),
    "PPIFIS":           ("PPI Final Demand",                       "monthly",  45),
    "T5YIE":            ("5Y Breakeven Inflation",                 "daily",     5),
    "T10YIE":           ("10Y Breakeven Inflation",                "daily",     5),
    "DCOILWTICO":       ("WTI Crude Oil ($/bbl)",                  "daily",     5),
    "PCETRIM12M159SFRBDAL": ("Trimmed Mean PCE",                   "monthly",  45),
    # ── Tab 5 – Monetary Policy & Financial Conditions ───────────────────────
    "FEDFUNDS":         ("Effective Fed Funds Rate",               "monthly",  45),
    "DGS1MO":           ("1M Treasury Yield",                      "daily",     5),
    "DGS3MO":           ("3M Treasury Yield",                      "daily",     5),
    "DGS6MO":           ("6M Treasury Yield",                      "daily",     5),
    "DGS1":             ("1Y Treasury Yield",                      "daily",     5),
    "DGS2":             ("2Y Treasury Yield",                      "daily",     5),
    "DGS5":             ("5Y Treasury Yield",                      "daily",     5),
    "DGS10":            ("10Y Treasury Yield",                     "daily",     5),
    "DGS30":            ("30Y Treasury Yield",                     "daily",     5),
    "T10Y2Y":           ("10Y–2Y Treasury Spread",                 "daily",     5),
    "BAMLC0A0CM":       ("IG OAS (bps)",                          "daily",     5),
    "DFII10":           ("10Y TIPS Real Yield",                    "daily",     5),
    "MORTGAGE30US":     ("30Y Mortgage Rate",                      "weekly",   14),
    # ── Phase Returns — asset class total return indices ────────────────────
    "BAMLUT0008TRIV":       ("1-10Y Treasury Total Return Index",   "daily",     5),
    "BAMLHYH0A0HYM2TRIV":  ("HY Corporate Bond Total Return Index","daily",     5),
    "GOLDAMGBD228NLBM":    ("Gold Price USD (London AM Fix)",       "daily",     5),
    # ── Tab 6 – Markets (FRED-sourced; sector ETFs via yfinance) ────────────
    "SP500":            ("S&P 500",                                "daily",     5),
    "NASDAQCOM":        ("NASDAQ Composite",                       "daily",     5),
    "WILL5000INDFC":    ("Wilshire 5000",                          "daily",     5),
    "VIXCLS":           ("VIX",                                    "daily",     5),
    # ── Tab 7 – Housing, Consumer & Sentiment ───────────────────────────────
    "HOUST":            ("Housing Starts (000s)",                  "monthly",  45),
    "PERMIT":           ("Building Permits (000s)",                "monthly",  45),
    "CSUSHPISA":        ("Case-Shiller National HPI",              "monthly",  60),
    "RSXFS":            ("Retail Sales ex-Food Services",          "monthly",  45),
    "RSFSXMV":          ("Retail Sales ex-Autos & Gas",            "monthly",  45),
    "UMCSENT":          ("U of Michigan Consumer Sentiment",       "monthly",  45),
    "PSAVERT":          ("Personal Savings Rate",                  "monthly",  45),
    # ── Tab 8 – Global & External ────────────────────────────────────────────
    "DTWEXBGS":         ("Trade-Weighted USD (Broad)",             "daily",     5),
    "DEXUSEU":          ("USD/EUR",                                "daily",     5),
    "DEXJPUS":          ("USD/JPY",                                "daily",     5),
    "DCOILBRENTEU":     ("Brent Crude ($/bbl)",                    "daily",     5),
    "PALLFNFINDEXQ":    ("Global Commodity Index",                 "quarterly",100),
}

# ---------------------------------------------------------------------------
# FRED client (cached as a resource — one connection, shared across sessions)
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _get_fred() -> Fred:
    return Fred(api_key=st.secrets["FRED_API_KEY"])


# ---------------------------------------------------------------------------
# Core fetch function
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_series(
    series_id: str,
    start_date: str = "2000-01-01",
    end_date: Optional[str] = None,
) -> dict:
    """
    Fetch a FRED series and return a result dict.

    Return shape:
        {
            series_id:   str,
            description: str,
            data:        pd.Series (DatetimeIndex → float),  empty on failure
            last_date:   date | None,
            last_value:  float | None,
            is_stale:    bool,
            stale_message: str | None,   e.g. "Last valid: 2026-03-01 (54d ago)"
            error:       str | None,
        }
    Never raises. Always returns the dict.
    """
    desc, _freq, stale_threshold = SERIES_META.get(series_id, (series_id, "daily", 30))

    result: dict = {
        "series_id":     series_id,
        "description":   desc,
        "data":          pd.Series(dtype=float),
        "last_date":     None,
        "last_value":    None,
        "is_stale":      False,
        "stale_message": None,
        "error":         None,
    }

    try:
        fred = _get_fred()
        kwargs: dict = {"observation_start": start_date}
        if end_date:
            kwargs["observation_end"] = end_date

        raw = fred.get_series(series_id, **kwargs)
        raw = raw.dropna()

        if raw.empty:
            result["error"] = f"No data returned for {series_id}"
            return result

        result["data"]       = raw
        result["last_date"]  = raw.index[-1].date()
        result["last_value"] = float(raw.iloc[-1])

        days_old = (date.today() - result["last_date"]).days
        if days_old > stale_threshold:
            result["is_stale"]      = True
            result["stale_message"] = (
                f"Last valid: {result['last_date'].strftime('%Y-%m-%d')} ({days_old}d ago)"
            )

    except Exception as exc:
        result["error"] = str(exc)
        logger.error("fetch_series(%s): %s", series_id, exc)

    return result


# ---------------------------------------------------------------------------
# Derived calculations used by the recession model
# ---------------------------------------------------------------------------

def compute_lei_growth(usslind_data: pd.Series, months: int = 6) -> Optional[float]:
    """
    Annualised LEI growth over the past `months` months.
    Returns a percentage (e.g. -4.2 means −4.2 % annualised) or None.
    """
    if usslind_data is None or usslind_data.empty:
        return None

    monthly = usslind_data.resample("MS").last().dropna()
    if len(monthly) < months + 1:
        return None

    current = monthly.iloc[-1]
    past    = monthly.iloc[-(months + 1)]

    if past == 0:
        return None

    six_mo_return = (current / past) - 1
    annualised    = ((1 + six_mo_return) ** 2 - 1) * 100
    return round(annualised, 2)


def compute_cfnai_signal(cfnai_data: pd.Series, months: int = 3) -> Optional[float]:
    """
    Return the trailing `months`-month average of the CFNAI.
    CFNAI semantics: >0 = above-trend growth, <-0.7 = recession signal.
    Returns the average value or None if insufficient data.
    """
    if cfnai_data is None or cfnai_data.empty:
        return None
    monthly = cfnai_data.resample("MS").last().dropna()
    if len(monthly) < months:
        return None
    return round(float(monthly.iloc[-months:].mean()), 3)


def compute_icsa_yoy(icsa_data: pd.Series) -> Optional[float]:
    """
    Year-over-year % change in the 4-week average of initial claims.
    Returns a percentage or None.
    """
    if icsa_data is None or icsa_data.empty or len(icsa_data) < 56:
        return None

    current_avg  = icsa_data.iloc[-4:].mean()
    year_ago_avg = icsa_data.iloc[-56:-52].mean()

    if year_ago_avg == 0 or pd.isna(year_ago_avg):
        return None

    return round((current_avg / year_ago_avg - 1) * 100, 2)


# ---------------------------------------------------------------------------
# Convenience: fetch all 7 recession model inputs in one call
# ---------------------------------------------------------------------------

def fetch_model_inputs() -> dict:
    """
    Returns a dict of series_id → fetch_series() result for all 7 model inputs.
    Uses start_date="1990-01-01" for longer history on model calculations.
    """
    model_ids = ["T10Y3M", "SAHMREALTIME", "CFNAI", "NFCI", "ICSA", "BAMLH0A0HYM2", "NAPM"]
    return {sid: fetch_series(sid, start_date="1990-01-01") for sid in model_ids}
