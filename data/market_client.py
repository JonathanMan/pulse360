"""
Market data layer for Pulse360 — yfinance-backed.

Covers equity indices, VIX, sector ETF heatmap, and Shiller CAPE.
FRED handles all macro series; yfinance handles market data not on FRED.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pandas as pd
import streamlit as st
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sector ETF universe for the Tab 6 heatmap
# ---------------------------------------------------------------------------
SECTOR_ETFS: dict[str, str] = {
    "XLK":  "Technology",
    "XLF":  "Financials",
    "XLV":  "Health Care",
    "XLE":  "Energy",
    "XLI":  "Industrials",
    "XLP":  "Consumer Staples",
    "XLY":  "Consumer Disc.",
    "XLU":  "Utilities",
    "XLB":  "Materials",
    "XLRE": "Real Estate",
    "XLC":  "Comm. Services",
}


# ---------------------------------------------------------------------------
# Core ticker fetch
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ticker(ticker: str, period: str = "5y", interval: str = "1d") -> dict:
    """
    Fetch OHLCV data for a ticker via yfinance.

    Return shape:
        {
            ticker:         str,
            close:          pd.Series (DatetimeIndex → float),
            last_price:     float | None,
            last_date:      date | None,
            pct_1d:         float | None,   (%)
            pct_ytd:        float | None,   (%)
            error:          str | None,
        }
    """
    result: dict = {
        "ticker":     ticker,
        "close":      pd.Series(dtype=float),
        "last_price": None,
        "last_date":  None,
        "pct_1d":     None,
        "pct_ytd":    None,
        "error":      None,
    }

    try:
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        if hist.empty:
            result["error"] = f"No data for {ticker}"
            return result

        close = hist["Close"]
        result["close"]      = close
        result["last_price"] = float(close.iloc[-1])
        result["last_date"]  = close.index[-1].date()

        if len(close) >= 2:
            result["pct_1d"] = round((close.iloc[-1] / close.iloc[-2] - 1) * 100, 2)

        ytd = close[close.index.year == close.index[-1].year]
        if len(ytd) >= 2:
            result["pct_ytd"] = round((ytd.iloc[-1] / ytd.iloc[0] - 1) * 100, 2)

    except Exception as exc:
        result["error"] = str(exc)
        logger.error("fetch_ticker(%s): %s", ticker, exc)

    return result


# ---------------------------------------------------------------------------
# Sector ETF heatmap
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_sector_returns(period_days: int = 22) -> pd.DataFrame:
    """
    Returns a DataFrame of sector ETF returns over the last `period_days` trading days.

    Columns: Sector, Ticker, Return (%)
    Sorted by Return descending.
    Fetches all sector ETFs in parallel via ThreadPoolExecutor.
    """

    def _fetch_one(ticker: str) -> tuple[str, dict]:
        return ticker, fetch_ticker(ticker, period="6mo")

    rows = []
    with ThreadPoolExecutor(max_workers=len(SECTOR_ETFS)) as executor:
        futures = {executor.submit(_fetch_one, tkr): tkr for tkr in SECTOR_ETFS}
        for future in as_completed(futures):
            ticker, r = future.result()
            sector = SECTOR_ETFS[ticker]
            if r["close"].empty or r["error"]:
                continue
            close = r["close"]
            if len(close) < period_days + 1:
                continue
            ret = (close.iloc[-1] / close.iloc[-(period_days + 1)] - 1) * 100
            rows.append({"Sector": sector, "Ticker": ticker, "Return (%)": round(ret, 2)})

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Return (%)", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Shiller CAPE
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)   # cache for 24h — monthly data
def fetch_shiller_cape() -> dict:
    """
    Fetch Shiller CAPE from the public Yale Excel file.

    Return shape:
        {
            data:           pd.Series (DatetimeIndex → float),
            last_value:     float | None,
            last_date:      date | None,
            historical_avg: float,   long-run avg pre-2000
            error:          str | None,
        }
    """
    result: dict = {
        "data":           pd.Series(dtype=float),
        "last_value":     None,
        "last_date":      None,
        "historical_avg": 17.0,
        "error":          None,
    }

    try:
        url = "https://shiller.yale.edu/data/ie_data.xls"
        df = pd.read_excel(url, sheet_name="Data", skiprows=7, header=0)

        # Locate CAPE column (P/E10 or CAPE)
        cape_col = next(
            (c for c in df.columns if "cape" in str(c).lower() or "p/e10" in str(c).lower()),
            None,
        )
        if cape_col is None:
            result["error"] = "CAPE column not found in Shiller spreadsheet"
            return result

        date_col = df.columns[0]
        df = df[[date_col, cape_col]].copy()
        df[cape_col] = pd.to_numeric(df[cape_col], errors="coerce")
        df = df.dropna()

        # Dates are stored as e.g. "1881.01" — convert to Timestamps
        df[date_col] = (
            df[date_col]
            .astype(str)
            .str[:7]
            .apply(lambda s: pd.Timestamp(s.replace(".", "-") + "-01"))
        )
        df = df.dropna(subset=[date_col])
        series = df.set_index(date_col)[cape_col].sort_index()
        series = series[series.index >= pd.Timestamp("1990-01-01")]

        result["data"]           = series
        result["last_value"]     = float(series.iloc[-1])
        result["last_date"]      = series.index[-1].date()
        result["historical_avg"] = round(
            float(series[series.index < pd.Timestamp("1990-01-01")].mean()), 1
        )

    except Exception as exc:
        result["error"] = str(exc)
        logger.error("fetch_shiller_cape: %s", exc)

    return result
