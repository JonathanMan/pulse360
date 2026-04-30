"""
components/stock_score_utils.py
================================
Shared constants, helpers, data-fetching, and scoring engines used by both
  pages/7_Stock_Score.py   — single-stock Buffett Score analysis
  pages/8_Screener.py      — Top-20 Buffett Stock Screener

Import pattern:
    from components.stock_score_utils import (
        fetch_stock_data, _compute_score, _fundamentals_trend,
        _price_trend, _get_sbc,
        _score_color, _score_color_sub, _score_label, _hex_rgba,
        _macro_adj_score, _macro_sens_cell, _owner_earnings_dcf,
        _sector_percentile, _percentile_badge, _is_special_sector,
        _SECTOR_GM_STD, _SECTOR_NM_STD, _SECTOR_ROE_MEDIAN, _SECTOR_ROE_STD,
        _MACRO_ADJ, _MACRO_DESCRIPTIONS, _REGIME_FOCUS,
        _FALLBACK_SCORES, _SCREENER_UNIVERSE,
        DISCLAIMER, _sf,
    )
"""

from __future__ import annotations

import math
import random
import time
from typing import Any

import numpy as np          # noqa: F401  (available to importers)
import pandas as pd
import streamlit as st
import yfinance as yf

# ── Disclaimer ────────────────────────────────────────────────────────────────
DISCLAIMER = (
    "*Educational analysis only — not personalised investment advice. "
    "Pulse360 is not a Registered Investment Advisor. "
    "Consult a licensed financial advisor before making investment decisions.*"
)

# ── Sector median benchmarks ──────────────────────────────────────────────────
# Source: Damodaran NYU sector averages (approximate)
_SECTOR_GROSS_MARGIN: dict[str, float] = {
    "Technology":             58.0, "Software—Application":  72.0,
    "Semiconductors":         55.0, "Software—Infrastructure":70.0,
    "Healthcare":             50.0, "Drug Manufacturers":     65.0,
    "Biotechnology":          70.0, "Medical Devices":        55.0,
    "Consumer Defensive":     34.0, "Food Distribution":      20.0,
    "Consumer Cyclical":      30.0, "Specialty Retail":       28.0,
    "Financial Services":     45.0, "Banks":                  35.0,
    "Insurance":              30.0, "Energy":                 32.0,
    "Oil & Gas E&P":          60.0, "Oil & Gas Integrated":   30.0,
    "Industrials":            30.0, "Aerospace & Defense":    22.0,
    "Real Estate":            38.0, "REIT":                   55.0,
    "Communication Services": 52.0, "Telecom Services":       55.0,
    "Utilities":              35.0, "Materials":              26.0,
}
_SECTOR_NET_MARGIN: dict[str, float] = {
    "Technology":             20.0, "Software—Application":  18.0,
    "Semiconductors":         18.0, "Healthcare":            12.0,
    "Drug Manufacturers":     18.0, "Biotechnology":          8.0,
    "Consumer Defensive":      8.0, "Consumer Cyclical":      5.0,
    "Financial Services":     22.0, "Banks":                 25.0,
    "Energy":                  8.0, "Industrials":            7.0,
    "Real Estate":            15.0, "REIT":                  18.0,
    "Communication Services": 12.0, "Utilities":             12.0,
    "Materials":               8.0,
}
_SECTOR_PE: dict[str, float] = {
    "Technology": 32.0, "Software—Application": 40.0,
    "Semiconductors": 30.0, "Healthcare": 22.0,
    "Consumer Defensive": 20.0, "Consumer Cyclical": 18.0,
    "Financial Services": 12.0, "Banks": 10.0,
    "Energy": 14.0, "Industrials": 18.0,
    "Real Estate": 25.0, "Communication Services": 22.0,
    "Utilities": 18.0, "Materials": 16.0,
}
_DEFAULT_GROSS_MARGIN = 38.0
_DEFAULT_NET_MARGIN   = 10.0
_DEFAULT_PE           = 20.0

# Approximate standard deviations for sector percentile ranking
# Source: Damodaran distribution data (rough estimates)
_SECTOR_GM_STD: dict[str, float] = {
    "Technology": 18.0, "Software—Application": 15.0, "Semiconductors": 16.0,
    "Healthcare": 14.0, "Drug Manufacturers": 16.0, "Biotechnology": 20.0,
    "Consumer Defensive": 9.0, "Consumer Staples": 9.0,
    "Consumer Cyclical": 10.0, "Specialty Retail": 10.0,
    "Financial Services": 12.0, "Banks": 8.0, "Energy": 12.0,
    "Industrials": 9.0, "Communication Services": 13.0, "Utilities": 8.0,
    "Real Estate": 12.0, "Materials": 9.0,
}
_SECTOR_NM_STD: dict[str, float] = {
    "Technology": 10.0, "Software—Application": 10.0, "Healthcare": 8.0,
    "Consumer Defensive": 4.0, "Consumer Staples": 4.0,
    "Consumer Cyclical": 4.0, "Financial Services": 8.0, "Banks": 8.0,
    "Energy": 7.0, "Industrials": 5.0, "Communication Services": 7.0,
    "Utilities": 5.0, "Real Estate": 8.0, "Materials": 5.0,
}
_SECTOR_ROE_MEDIAN: dict[str, float] = {
    "Technology": 28.0, "Software—Application": 35.0, "Healthcare": 18.0,
    "Consumer Defensive": 22.0, "Consumer Cyclical": 15.0,
    "Financial Services": 12.0, "Banks": 10.0, "Energy": 12.0,
    "Industrials": 16.0, "Communication Services": 20.0, "Utilities": 10.0,
    "Materials": 14.0,
}
_SECTOR_ROE_STD: dict[str, float] = {
    "Technology": 18.0, "Software—Application": 22.0, "Healthcare": 12.0,
    "Consumer Defensive": 10.0, "Consumer Cyclical": 10.0,
    "Financial Services": 8.0, "Banks": 7.0, "Energy": 12.0,
    "Industrials": 10.0, "Communication Services": 15.0, "Utilities": 6.0,
    "Materials": 10.0,
}

_SECTOR_SPECIAL = {
    "Financial Services", "Banks", "Insurance", "REIT",
    "Real Estate", "Mortgage Finance",
}

# ── Macro regime sector adjustments (±pts on base score, capped ±15) ──────────
_MACRO_ADJ: dict[str, dict[str, int]] = {
    "Normal": {},
    "High Inflation": {
        "Energy": 12, "Basic Materials": 10, "Materials": 10,
        "Consumer Defensive": 5, "Consumer Staples": 5,
        "Real Estate": -8, "Technology": -6, "Consumer Cyclical": -8,
        "Communication Services": -3, "Utilities": -4,
    },
    "Rising Rates": {
        "Financial Services": 8, "Banks": 10, "Insurance": 6,
        "Utilities": -10, "Real Estate": -9, "Technology": -5,
        "Consumer Defensive": -2, "Consumer Cyclical": -3,
    },
    "Recession Risk": {
        "Consumer Defensive": 8, "Consumer Staples": 8,
        "Healthcare": 7, "Utilities": 6,
        "Consumer Cyclical": -10, "Industrials": -8, "Energy": -5,
        "Financial Services": -4, "Technology": -3,
    },
    "Recovery / Expansion": {
        "Consumer Cyclical": 9, "Industrials": 8, "Energy": 6,
        "Technology": 5, "Financial Services": 4,
        "Consumer Defensive": -4, "Utilities": -5, "Healthcare": -2,
    },
}

_MACRO_DESCRIPTIONS: dict[str, str] = {
    "Normal":               "No macro adjustment — pure Buffett score",
    "High Inflation":       "CPI > 4%: Energy & Materials benefit; Tech & Real Estate hurt",
    "Rising Rates":         "Fed tightening: Banks & Insurance benefit; Utilities & REITs hurt",
    "Recession Risk":       "PMI < 50, yield curve inverted: Staples & Healthcare defensive",
    "Recovery / Expansion": "PMI > 55, credit expanding: Cyclicals & Industrials outperform",
}

# ── Fallback fundamental scores for key blue chips ───────────────────────────
# Used when yfinance is rate-limited so the screener stays complete.
_FALLBACK_SCORES: dict[str, dict] = {
    "KO":   {"Score":72,"Moat":30,"Fortress":18,"Valuation":12,"Momentum":7,"Shareholder":5,"Sector":"Consumer Defensive","Company":"Coca-Cola","FCF_Yield":3.8,"Fwd_PE":22.1,"Trend":"↑","TrendColor":"#2ecc71","TrendTip":"Improving","Price":63.0,"Mkt Cap $B":272.0},
    "PEP":  {"Score":70,"Moat":29,"Fortress":17,"Valuation":12,"Momentum":7,"Shareholder":5,"Sector":"Consumer Defensive","Company":"PepsiCo","FCF_Yield":3.5,"Fwd_PE":20.8,"Trend":"↑","TrendColor":"#2ecc71","TrendTip":"Improving","Price":168.0,"Mkt Cap $B":232.0},
    "JNJ":  {"Score":68,"Moat":28,"Fortress":19,"Valuation":11,"Momentum":6,"Shareholder":4,"Sector":"Healthcare","Company":"Johnson & Johnson","FCF_Yield":4.1,"Fwd_PE":15.2,"Trend":"→","TrendColor":"#f39c12","TrendTip":"Mixed","Price":158.0,"Mkt Cap $B":381.0},
    "MSFT": {"Score":79,"Moat":35,"Fortress":21,"Valuation":12,"Momentum":8,"Shareholder":3,"Sector":"Technology","Company":"Microsoft","FCF_Yield":2.4,"Fwd_PE":31.5,"Trend":"↑","TrendColor":"#2ecc71","TrendTip":"Improving","Price":415.0,"Mkt Cap $B":3090.0},
    "AAPL": {"Score":75,"Moat":33,"Fortress":20,"Valuation":12,"Momentum":7,"Shareholder":3,"Sector":"Technology","Company":"Apple","FCF_Yield":3.8,"Fwd_PE":28.2,"Trend":"↑","TrendColor":"#2ecc71","TrendTip":"Improving","Price":210.0,"Mkt Cap $B":3200.0},
    "GOOGL":{"Score":76,"Moat":34,"Fortress":21,"Valuation":13,"Momentum":6,"Shareholder":2,"Sector":"Communication Services","Company":"Alphabet","FCF_Yield":4.2,"Fwd_PE":20.1,"Trend":"↑","TrendColor":"#2ecc71","TrendTip":"Improving","Price":175.0,"Mkt Cap $B":2180.0},
    "V":    {"Score":78,"Moat":35,"Fortress":21,"Valuation":12,"Momentum":7,"Shareholder":3,"Sector":"Financial Services","Company":"Visa","FCF_Yield":2.9,"Fwd_PE":26.8,"Trend":"↑","TrendColor":"#2ecc71","TrendTip":"Improving","Price":280.0,"Mkt Cap $B":573.0},
    "MA":   {"Score":77,"Moat":35,"Fortress":20,"Valuation":11,"Momentum":8,"Shareholder":3,"Sector":"Financial Services","Company":"Mastercard","FCF_Yield":2.5,"Fwd_PE":29.4,"Trend":"↑","TrendColor":"#2ecc71","TrendTip":"Improving","Price":475.0,"Mkt Cap $B":444.0},
    "PG":   {"Score":71,"Moat":30,"Fortress":18,"Valuation":12,"Momentum":6,"Shareholder":5,"Sector":"Consumer Defensive","Company":"Procter & Gamble","FCF_Yield":3.6,"Fwd_PE":23.0,"Trend":"→","TrendColor":"#f39c12","TrendTip":"Mixed","Price":170.0,"Mkt Cap $B":401.0},
    "ANSS": {"Score":62,"Moat":28,"Fortress":17,"Valuation":10,"Momentum":5,"Shareholder":2,"Sector":"Technology","Company":"Ansys","FCF_Yield":2.1,"Fwd_PE":38.0,"Trend":"→","TrendColor":"#f39c12","TrendTip":"Mixed","Price":340.0,"Mkt Cap $B":29.0},
    "MCD":  {"Score":69,"Moat":29,"Fortress":15,"Valuation":13,"Momentum":7,"Shareholder":5,"Sector":"Consumer Cyclical","Company":"McDonald's","FCF_Yield":3.9,"Fwd_PE":22.5,"Trend":"↑","TrendColor":"#2ecc71","TrendTip":"Improving","Price":297.0,"Mkt Cap $B":213.0},
    "TMO":  {"Score":67,"Moat":28,"Fortress":18,"Valuation":11,"Momentum":6,"Shareholder":4,"Sector":"Healthcare","Company":"Thermo Fisher","FCF_Yield":3.1,"Fwd_PE":24.0,"Trend":"→","TrendColor":"#f39c12","TrendTip":"Mixed","Price":510.0,"Mkt Cap $B":196.0},
    "HON":  {"Score":64,"Moat":26,"Fortress":17,"Valuation":12,"Momentum":6,"Shareholder":3,"Sector":"Industrials","Company":"Honeywell","FCF_Yield":4.2,"Fwd_PE":19.5,"Trend":"→","TrendColor":"#f39c12","TrendTip":"Mixed","Price":218.0,"Mkt Cap $B":134.0},
    "XOM":  {"Score":60,"Moat":22,"Fortress":17,"Valuation":13,"Momentum":5,"Shareholder":3,"Sector":"Energy","Company":"ExxonMobil","FCF_Yield":5.8,"Fwd_PE":13.2,"Trend":"↓","TrendColor":"#e74c3c","TrendTip":"Deteriorating","Price":108.0,"Mkt Cap $B":462.0},
}

# ── Screener universe (~80 quality large-caps) ────────────────────────────────
_SCREENER_UNIVERSE: list[str] = [
    # Technology
    "AAPL", "MSFT", "GOOGL", "META", "NVDA", "AVGO", "TXN", "QCOM", "ORCL", "IBM",
    # Software
    "CRM", "ADBE", "NOW", "INTU", "ANSS",
    # Consumer Staples / Defensive (classic Buffett territory)
    "KO", "PEP", "PG", "CL", "KMB", "MKC", "GIS", "HSY", "SJM", "CHD",
    # Healthcare
    "JNJ", "ABT", "MDT", "TMO", "DHR", "EW", "SYK", "BDX", "ISRG", "ZBH",
    # Financials (flag with special-sector warning)
    "BRK-B", "JPM", "BAC", "WFC", "AXP", "V", "MA", "BLK", "MS", "GS",
    # Consumer Discretionary
    "MCD", "SBUX", "NKE", "TJX", "ROST", "YUM", "DPZ",
    # Industrials
    "HON", "MMM", "CAT", "DE", "EMR", "ITW", "GWW", "FAST",
    # Energy (quality names)
    "XOM", "CVX", "PSX",
    # Communication
    "DIS", "NFLX", "CMCSA",
    # Materials / Specialty
    "ECL", "SHW", "APD",
    # Real Estate / REITs (flagged)
    "AMT", "PLD",
    # Berkshire holdings / Buffett favourites
    "OXY", "ALLY", "USB",
]


# ── Percentile ranking ────────────────────────────────────────────────────────

def _sector_percentile(value: float, median: float, std: float) -> str:
    """Return a human-readable percentile label based on z-score approximation."""
    if std <= 0:
        return ""
    z = (value - median) / std
    if z >= 1.65:  return "Top 5%"
    if z >= 1.04:  return "Top 15%"
    if z >= 0.52:  return "Top 30%"
    if z >= 0.13:  return "Above median"
    if z >= -0.13: return "~Median"
    if z >= -0.52: return "Below median"
    if z >= -1.04: return "Bottom 30%"
    if z >= -1.65: return "Bottom 15%"
    return "Bottom 5%"


def _percentile_badge(label: str) -> str:
    """Return a styled HTML badge for a percentile label."""
    if "Top 5"    in label: bg, fg = "#0d2b1d", "#2ecc71"
    elif "Top 15" in label: bg, fg = "#0d2b1d", "#27ae60"
    elif "Top 30" in label: bg, fg = "#1a2b0d", "#a8d08d"
    elif "Above"  in label: bg, fg = "#1a2000", "#c8e06e"
    elif "Median" in label: bg, fg = "#1e1e1e", "#888888"
    elif "Below"  in label: bg, fg = "#2b1a0d", "#e67e22"
    elif "Bottom 30" in label: bg, fg = "#2b0d0d", "#e74c3c"
    else:                   bg, fg = "#2b0d0d", "#c0392b"
    return (
        f'<span style="background:{bg};color:{fg};border:1px solid {fg}55;'
        f'border-radius:4px;padding:1px 6px;font-size:0.68rem;font-weight:700;'
        f'margin-left:6px;white-space:nowrap;">{label}</span>'
    )


# ── Macro helpers ──────────────────────────────────────────────────────────────

# Callout text surfaced under the regime selector in the screener.
# Format: (focus_sectors, focus_section, rationale_one-liner)
_REGIME_FOCUS: dict[str, tuple[str, str, str] | None] = {
    "Normal":               None,
    "High Inflation":       ("Energy, Materials, Staples",
                             "Quality Moat",
                             "Pricing power moats dominate — high-margin franchises pass costs on"),
    "Rising Rates":         ("Banks, Insurance",
                             "Financial Fortress",
                             "Balance-sheet strength matters most; leverage kills in tightening cycles"),
    "Recession Risk":       ("Consumer Staples, Healthcare, Utilities",
                             "Quality Moat + Fortress",
                             "Defensive durability and low debt are the only reliable shelters"),
    "Recovery / Expansion": ("Cyclicals, Industrials, Energy",
                             "Momentum",
                             "Early-cycle leaders run on earnings acceleration, not just quality"),
}


def _macro_adj_score(base_score: int, sector: str | None, regime: str) -> int:
    """Apply macro regime sector adjustment. Capped at ±15, total 0–100."""
    adj_map = _MACRO_ADJ.get(regime, {})
    adj = 0
    for key, delta in adj_map.items():
        if sector and key.lower() in sector.lower():
            adj = max(adj, abs(delta)) * (1 if delta > 0 else -1)
            break
    adj = max(-15, min(15, adj))
    return max(0, min(100, base_score + adj))


def _macro_sens_cell(sector: str, regime: str) -> str:
    """Return coloured HTML showing this sector's macro sensitivity."""
    if regime == "Normal":
        return '<span style="color:#444;">—</span>'
    adj = _MACRO_ADJ.get(regime, {}).get(sector, 0)
    if adj == 0:
        return '<span style="color:#555;">0</span>'
    color = "#2ecc71" if adj > 0 else "#e74c3c"
    sign  = "+" if adj > 0 else ""
    return f'<span style="color:{color};font-weight:700;">{sign}{adj}</span>'


# ── Score colour helpers ───────────────────────────────────────────────────────

def _score_color_sub(value: int, max_value: int) -> str:
    """
    Colour for a sub-section score relative to its maximum.
    Used in screener table cells (Moat, Fortress, Valuation, Momentum).
    """
    if max_value == 0:
        return "#888"
    pct = value / max_value
    if pct >= 0.75: return "#2ecc71"
    if pct >= 0.50: return "#f39c12"
    return "#e74c3c"


def _score_color(score: int) -> str:
    """
    Colour for a total 0–100 Buffett score.
    Used in score cards and macro-adjusted screener totals.
    """
    if score >= 75: return "#2ecc71"
    if score >= 60: return "#27ae60"
    if score >= 45: return "#f1c40f"
    if score >= 30: return "#e67e22"
    return "#e74c3c"


def _score_label(score: int) -> tuple[str, str]:
    """Return (label, emoji) for a 0–100 Buffett score."""
    if score >= 80: return "Exceptional — Wide Moat",   "🟢"
    if score >= 65: return "Strong — Worth Deep Dive",   "🟢"
    if score >= 50: return "Decent — Some Weaknesses",  "🟡"
    if score >= 35: return "Weak — Multiple Red Flags", "🟠"
    return           "Poor — Fails Buffett Criteria",    "🔴"


def _hex_rgba(hx: str, a: float) -> str:
    """Convert hex colour + alpha to rgba() string."""
    h = hx.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


# ── Data helpers ──────────────────────────────────────────────────────────────

def _sf(v: Any, fallback: float | None = None) -> float | None:
    """Safely cast to float."""
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return fallback


def _row(df: pd.DataFrame | None, *aliases: str) -> pd.Series | None:
    """Return the first matching row from a yfinance DataFrame."""
    if df is None or df.empty:
        return None
    idx_lower = {str(i).lower(): i for i in df.index}
    for alias in aliases:
        key = str(alias).lower()
        if key in idx_lower:
            return df.loc[idx_lower[key]]
    return None


def _col0(s: pd.Series | None) -> float | None:
    """Most-recent value from a row series."""
    if s is None or s.empty:
        return None
    return _sf(s.iloc[0])


def _col1(s: pd.Series | None) -> float | None:
    """Prior-year value from a row series."""
    if s is None or len(s) < 2:
        return None
    return _sf(s.iloc[1])


def _pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old)


# ── Sector lookup helpers ─────────────────────────────────────────────────────

def _sector_gm(sector: str | None, industry: str | None) -> float:
    for key in [industry, sector]:
        if key and key in _SECTOR_GROSS_MARGIN:
            return _SECTOR_GROSS_MARGIN[key]
    return _DEFAULT_GROSS_MARGIN


def _sector_nm(sector: str | None, industry: str | None) -> float:
    for key in [industry, sector]:
        if key and key in _SECTOR_NET_MARGIN:
            return _SECTOR_NET_MARGIN[key]
    return _DEFAULT_NET_MARGIN


def _sector_pe(sector: str | None, industry: str | None) -> float:
    for key in [industry, sector]:
        if key and key in _SECTOR_PE:
            return _SECTOR_PE[key]
    return _DEFAULT_PE


def _is_special_sector(sector: str | None, industry: str | None) -> bool:
    for key in [industry, sector]:
        if key and any(s in key for s in ["Bank", "Insurance", "REIT", "Financial", "Mortgage"]):
            return True
    return False


# ── Price-momentum trend ──────────────────────────────────────────────────────

def _price_trend(info: dict) -> tuple[str, str, str]:
    """
    Price-momentum trend based on 200-day and 50-day moving averages.
    Returns (arrow, color, tooltip).

    Rules (matches the institutional benchmark):
      ↑ green  — price > 200MA by >3 %  (confirmed uptrend; extra ✓ if 50MA > 200MA)
      ↓ red    — price < 200MA by >3 %  (technical downtrend)
      → yellow — consolidating within ±3 % band of 200MA
    """
    cur   = _sf(info.get("currentPrice") or info.get("regularMarketPrice"))
    ma200 = _sf(info.get("twoHundredDayAverage"))
    ma50  = _sf(info.get("fiftyDayAverage"))

    if not cur or not ma200 or ma200 <= 0:
        return "—", "#444", "Price data unavailable"

    pct_vs_200 = (cur - ma200) / ma200

    if pct_vs_200 > 0.03:
        if ma50 and ma50 > ma200:
            tip = f"Uptrend confirmed: {pct_vs_200:+.1%} vs 200MA · 50MA above 200MA"
        else:
            tip = f"Above 200MA: {pct_vs_200:+.1%}"
        return "↑", "#2ecc71", tip

    if pct_vs_200 < -0.03:
        tip = f"Technical downtrend: {pct_vs_200:+.1%} below 200MA"
        return "↓", "#e74c3c", tip

    # Within ±3% band — consolidating
    if ma50:
        pct_vs_50 = (cur - ma50) / ma50
        tip = f"Consolidating: {pct_vs_200:+.1%} vs 200MA · {pct_vs_50:+.1%} vs 50MA"
    else:
        tip = f"Near 200MA: {pct_vs_200:+.1%}"
    return "→", "#f39c12", tip


# ── Fundamentals trend ────────────────────────────────────────────────────────

def _fundamentals_trend(raw_data: dict) -> tuple[str, str, str]:
    """
    Returns (arrow, color, tooltip) based on YoY direction of
    Revenue, Net Income, and Operating Cash Flow.
    ↑ = 2+ of 3 improving  |  ↓ = 2+ deteriorating  |  → = mixed
    """
    fin = raw_data.get("financials")
    cf  = raw_data.get("cashflow")

    improving = 0
    total     = 0
    for row in [
        _row(fin, "Total Revenue", "Revenue"),
        _row(fin, "Net Income"),
        _row(cf, "Operating Cash Flow", "Cash From Operations",
             "Net Cash From Operating Activities"),
    ]:
        if row is not None:
            vals = row.dropna()
            if len(vals) >= 2:
                total += 1
                if float(vals.iloc[0]) > float(vals.iloc[1]):
                    improving += 1

    if total == 0:
        return "—", "#444", "Trend: no data available"
    ratio = improving / total
    if ratio >= 0.67:
        return "↑", "#2ecc71", f"Improving: {improving}/{total} metrics up YoY"
    if ratio <= 0.33:
        return "↓", "#e74c3c", f"Deteriorating: {improving}/{total} metrics up YoY"
    return "→", "#f39c12", f"Mixed: {improving}/{total} metrics up YoY"


# ── Data fetching ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stock_data(ticker: str) -> dict:
    """
    Pull all fundamentals + price history from yfinance.
    Uses exponential-backoff retry to avoid Yahoo rate limits.
    Returns a normalised dict: info, financials, balance_sheet, cashflow, history, error.
    """
    result: dict = {
        "info": {}, "financials": None, "balance_sheet": None,
        "cashflow": None, "history": pd.DataFrame(), "error": None,
    }

    MAX_RETRIES = 4
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Do NOT pass a custom session — newer yfinance requires its own
            # curl_cffi session internally (installed via curl_cffi in requirements.txt).
            t = yf.Ticker(ticker.upper().strip())

            info = t.info or {}
            if not info or list(info.keys()) == ["trailingPegRatio"]:
                raise ValueError("Incomplete info response (likely rate-limited)")

            result["info"]          = info
            result["financials"]    = t.financials
            result["balance_sheet"] = t.balance_sheet
            result["cashflow"]      = t.cashflow
            result["history"]       = t.history(period="2y")
            result["error"]         = None
            return result

        except Exception as exc:
            if attempt < MAX_RETRIES:
                wait = (3 * (2 ** (attempt - 1))) + (random.random() * 2)
                time.sleep(wait)
            else:
                result["error"] = str(exc)

    return result


# ── Scoring engines ───────────────────────────────────────────────────────────

def _piotroski_score(
    bs: pd.DataFrame | None,
    fin: pd.DataFrame | None,
    cf: pd.DataFrame | None,
    info: dict,
) -> tuple[int, list[dict]]:
    """Compute Piotroski F-Score (0–9). Returns (score, signal list)."""
    signals: list[dict] = []

    def sig(name: str, passed: bool | None, detail: str = "") -> None:
        signals.append({"name": name, "pass": passed, "detail": detail,
                         "pts": 1 if passed else 0})

    # Profitability
    roa0 = _sf(info.get("returnOnAssets"))
    sig("ROA > 0", roa0 is not None and roa0 > 0,
        f"ROA = {roa0:.1%}" if roa0 is not None else "n/a")

    ocf_row = _row(cf, "Operating Cash Flow", "Cash From Operations",
                   "Net Cash From Operating Activities")
    ocf0    = _col0(ocf_row)
    sig("Operating CF > 0", ocf0 is not None and ocf0 > 0,
        f"OCF = ${ocf0/1e9:.2f}B" if ocf0 is not None else "n/a")

    ta_row  = _row(bs, "Total Assets")
    ta0 = _col0(ta_row); ta1 = _col1(ta_row)
    ni_row  = _row(fin, "Net Income")
    ni0 = _col0(ni_row); ni1 = _col1(ni_row)
    if ta0 and ta1 and ni0 and ni1 and ta0 > 0 and ta1 > 0:
        d_roa = (ni0 / ta0) - (ni1 / ta1)
        sig("ΔROA improving", d_roa > 0, f"ΔROA = {d_roa:+.2%}")
    else:
        sig("ΔROA improving", None, "insufficient data")

    if ocf0 is not None and ni0 is not None and ta0 is not None and ta0 > 0 and ni0 != 0:
        accrual = ocf0 / ta0 - ni0 / ta0
        sig("Cash earnings quality (OCF > NI)", accrual > 0,
            f"accrual ratio = {accrual:+.3f}")
    else:
        sig("Cash earnings quality (OCF > NI)", None, "insufficient data")

    # Leverage / Liquidity
    ltd_row = _row(bs, "Long Term Debt", "Long-Term Debt",
                   "Long Term Debt And Capital Lease Obligation")
    ltd0 = _col0(ltd_row); ltd1 = _col1(ltd_row)
    if ltd0 is not None and ltd1 is not None and ta0 and ta1 and ta0 > 0 and ta1 > 0:
        d_lev = (ltd0 / ta0) - (ltd1 / ta1)
        sig("ΔLeverage ≤ 0 (debt load falling)", d_lev <= 0, f"Δlev = {d_lev:+.3f}")
    else:
        d_lev_info = _sf(info.get("debtToEquity"))
        sig("ΔLeverage ≤ 0", None, f"D/E = {d_lev_info:.2f}" if d_lev_info else "n/a")

    cr  = _sf(info.get("currentRatio"))
    ca0 = _col0(_row(bs, "Current Assets")); ca1 = _col1(_row(bs, "Current Assets"))
    cl0 = _col0(_row(bs, "Current Liabilities")); cl1 = _col1(_row(bs, "Current Liabilities"))
    if ca0 and ca1 and cl0 and cl1 and cl0 > 0 and cl1 > 0:
        d_cr = (ca0 / cl0) - (ca1 / cl1)
        sig("ΔCurrent Ratio > 0 (liquidity rising)", d_cr > 0, f"Δcr = {d_cr:+.3f}")
    else:
        sig("ΔCurrent Ratio > 0", None, f"current = {cr:.2f}" if cr else "n/a")

    sh0    = _sf(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"))
    sh_row = _row(bs, "Ordinary Shares Number", "Common Stock Shares Outstanding", "Share Issued")
    sh1_bs = _col1(sh_row)
    if sh0 is not None and sh1_bs is not None and sh1_bs > 0:
        diluted = (sh0 - sh1_bs) / sh1_bs
        sig("No share dilution", diluted <= 0.01, f"YoY share Δ = {diluted:+.2%}")
    else:
        sig("No share dilution", None, "share count data unavailable")

    # Operating efficiency
    gp_row  = _row(fin, "Gross Profit")
    rev_row = _row(fin, "Total Revenue", "Revenue")
    gp0 = _col0(gp_row); gp1 = _col1(gp_row)
    rev0 = _col0(rev_row); rev1 = _col1(rev_row)
    if gp0 and gp1 and rev0 and rev1 and rev0 > 0 and rev1 > 0:
        d_gm = (gp0 / rev0) - (gp1 / rev1)
        sig("ΔGross Margin > 0", d_gm > 0, f"ΔGM = {d_gm:+.2%}")
    else:
        gm_info = _sf(info.get("grossMargins"))
        sig("ΔGross Margin > 0", None, f"GM = {gm_info:.1%}" if gm_info else "n/a")

    if rev0 and rev1 and ta0 and ta1 and ta0 > 0 and ta1 > 0:
        d_ato = (rev0 / ta0) - (rev1 / ta1)
        sig("ΔAsset Turnover > 0", d_ato > 0, f"Δato = {d_ato:+.3f}")
    else:
        sig("ΔAsset Turnover > 0", None, "insufficient data")

    total = sum(s["pts"] for s in signals if s["pass"] is not None)
    return total, signals


def _altman_z(
    bs: pd.DataFrame | None,
    fin: pd.DataFrame | None,
    info: dict,
) -> tuple[float | None, str]:
    """Compute Altman Z-Score. Returns (z_score, zone_label)."""
    try:
        ta = _col0(_row(bs, "Total Assets"))
        if not ta or ta <= 0:
            return None, "Insufficient data"

        wc_row = _row(bs, "Working Capital", "Net Working Capital")
        wc = _col0(wc_row)
        if wc is None:
            ca = _col0(_row(bs, "Current Assets"))
            cl = _col0(_row(bs, "Current Liabilities"))
            wc = (ca - cl) if ca is not None and cl is not None else None

        re   = _col0(_row(bs, "Retained Earnings", "Retained Earnings (Accumulated Deficit)"))
        ebit = _col0(_row(fin, "EBIT", "Operating Income", "Ebit"))
        if ebit is None:
            ni   = _col0(_row(fin, "Net Income"))
            tax  = _col0(_row(fin, "Tax Provision", "Income Tax Expense"))
            intr = _col0(_row(fin, "Interest Expense"))
            if ni is not None:
                ebit = ni + (tax or 0) + abs(intr or 0)

        mktcap = _sf(info.get("marketCap"))
        tl_row = _row(bs, "Total Liabilities Net Minority Interest",
                      "Total Liabilities", "Total Non Current Liabilities Net")
        tl = _col0(tl_row)
        if tl is None:
            te_val = _sf(info.get("totalStockholderEquity"))
            tl = (mktcap - te_val) if mktcap and te_val else None

        rev = _col0(_row(fin, "Total Revenue", "Revenue"))

        if sum(1 for p in [wc, re, ebit, mktcap, tl, rev, ta] if p is not None) < 5:
            return None, "Insufficient data"

        x1 = (wc   or 0) / ta
        x2 = (re   or 0) / ta
        x3 = (ebit or 0) / ta
        x4 = (mktcap or 0) / max(tl or 1, 1)
        x5 = (rev  or 0) / ta

        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5

        if z > 2.99:  zone = "Safe Zone (Z > 2.99)"
        elif z > 1.81: zone = "Grey Zone (1.81–2.99)"
        else:          zone = "Distress Zone (Z < 1.81)"

        return round(z, 2), zone

    except Exception:
        return None, "Calculation error"


def _owner_earnings_dcf(
    fin: pd.DataFrame | None,
    cf:  pd.DataFrame | None,
    info: dict,
    g_stage1: float = 0.08,
    g_terminal: float = 0.03,
    discount_rate: float = 0.10,
    maint_capex_pct: float = 1.0,
    deduct_sbc: bool = True,
) -> tuple[float | None, float | None]:
    """
    Estimate intrinsic value per share using Owner Earnings DCF.
    OE = Net Income + D&A − (CapEx × maint_capex_pct) [− SBC if deduct_sbc]

    maint_capex_pct: fraction of CapEx treated as maintenance (0–1).
    deduct_sbc: if True, subtract Stock-Based Compensation from OE.
      SBC is a real shareholder cost that does not appear in GAAP earnings —
      Buffett's original definition pre-dates heavy SBC, but modern institutional
      analysis treats it as a cash-equivalent dilution expense.

    Returns (owner_earnings_annual, intrinsic_value_per_share).
    Also returns sbc_amount embedded in the OE calculation (accessible via
    the raw value before returning, not surfaced here — callers needing SBC
    should call _get_sbc() separately).
    """
    try:
        ni    = _col0(_row(fin, "Net Income"))
        da    = _col0(_row(cf, "Depreciation And Amortization",
                             "Depreciation Depletion And Amortization",
                             "Depreciation Amortization Depletion"))
        capex = _col0(_row(cf, "Capital Expenditure", "Capital Expenditures",
                             "Purchase Of Ppe", "Capital Expenditure Reported"))
        sbc   = _col0(_row(cf, "Stock Based Compensation",
                             "Share Based Compensation",
                             "Stock-Based Compensation Expense",
                             "Share-Based Compensation"))

        if ni is None:
            return None, None

        capex_abs      = abs(capex) if capex is not None else 0
        da_abs         = abs(da)    if da    is not None else 0
        sbc_abs        = abs(sbc)   if sbc   is not None else 0
        maint_capex    = capex_abs * maint_capex_pct
        owner_earnings = ni + da_abs - maint_capex - (sbc_abs if deduct_sbc else 0)

        if owner_earnings <= 0:
            return owner_earnings, None

        shares = _sf(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"))
        if not shares or shares <= 0:
            return owner_earnings, None

        pv = 0.0
        for yr in range(1, 11):
            g     = g_stage1 if yr <= 5 else g_stage1 / 2
            oe_yr = owner_earnings * (1 + g) ** yr
            pv   += oe_yr / (1 + discount_rate) ** yr

        oe_term = owner_earnings * (1 + g_stage1 / 2) ** 10 * (1 + g_terminal)
        tv      = oe_term / (discount_rate - g_terminal)
        pv     += tv / (1 + discount_rate) ** 10

        return owner_earnings, pv / shares

    except Exception:
        return None, None


def _get_sbc(cf: pd.DataFrame | None) -> float | None:
    """Return Stock-Based Compensation (absolute value) from a yfinance cashflow DF."""
    sbc = _col0(_row(cf, "Stock Based Compensation",
                        "Share Based Compensation",
                        "Stock-Based Compensation Expense",
                        "Share-Based Compensation"))
    return abs(sbc) if sbc is not None else None


def _compute_score(data: dict) -> dict:
    """Run all scorecards and return a comprehensive results dict."""
    info = data.get("info", {})
    fin  = data.get("financials")
    bs   = data.get("balance_sheet")
    cf   = data.get("cashflow")
    hist = data.get("history", pd.DataFrame())

    sector   = info.get("sector")   or info.get("sectorDisp")
    industry = info.get("industry") or info.get("industryDisp")
    is_special = _is_special_sector(sector, industry)

    med_gm = _sector_gm(sector, industry)
    med_nm = _sector_nm(sector, industry)
    med_pe = _sector_pe(sector, industry)

    results: dict = {
        "sector": sector, "industry": industry, "is_special": is_special,
        "med_gm": med_gm, "med_nm": med_nm, "med_pe": med_pe,
        "sections": {}, "total": 0,
    }

    # ── Section 1: Quality Moat (40 pts) ──────────────────────────────────────
    s1 = {"max": 40, "items": [], "score": 0}

    def s1_item(name, pts, earned, detail, tip=""):
        s1["items"].append({"name": name, "pts": pts, "earned": earned,
                             "detail": detail, "tip": tip})
        s1["score"] += earned

    gm = _sf(info.get("grossMargins"))
    if gm is not None:
        gm_pct = gm * 100
        if gm_pct >= med_gm * 1.35: gm_pts = 10
        elif gm_pct >= med_gm * 1.15: gm_pts = 7
        elif gm_pct >= med_gm: gm_pts = 4
        else: gm_pts = 0
        s1_item("Gross Margin (vs sector)", 10, gm_pts,
                f"{gm_pct:.1f}% vs sector median {med_gm:.0f}%",
                "Pass if GM > 1.15× sector median (not flat 40% threshold)")
    else:
        s1_item("Gross Margin", 10, 0, "Data unavailable")

    nm = _sf(info.get("profitMargins"))
    if nm is not None:
        nm_pct = nm * 100
        if nm_pct >= med_nm * 1.3: nm_pts = 8
        elif nm_pct >= med_nm: nm_pts = 5
        elif nm_pct > 0: nm_pts = 2
        else: nm_pts = 0
        s1_item("Net Margin (vs sector)", 8, nm_pts,
                f"{nm_pct:.1f}% vs sector median {med_nm:.0f}%")
    else:
        s1_item("Net Margin", 8, 0, "Data unavailable")

    roe = _sf(info.get("returnOnEquity"))
    if roe is not None:
        roe_pct = roe * 100
        if roe_pct >= 20: roe_pts = 10
        elif roe_pct >= 15: roe_pts = 7
        elif roe_pct >= 10: roe_pts = 4
        else: roe_pts = 0
        s1_item("Return on Equity", 10, roe_pts,
                f"{roe_pct:.1f}% (targets: ≥20%=10, ≥15%=7, ≥10%=4)")
    else:
        s1_item("Return on Equity", 10, 0, "Data unavailable")

    rev_row = _row(fin, "Total Revenue", "Revenue")
    if rev_row is not None and len(rev_row.dropna()) >= 3:
        rev_vals = rev_row.dropna()[:4][::-1].values
        if len(rev_vals) >= 3 and rev_vals[0] > 0:
            yrs  = len(rev_vals) - 1
            cagr = (rev_vals[-1] / rev_vals[0]) ** (1 / yrs) - 1
            if cagr >= 0.15: rev_pts = 7
            elif cagr >= 0.08: rev_pts = 4
            elif cagr >= 0.03: rev_pts = 2
            else: rev_pts = 0
            s1_item("Revenue Growth CAGR", 7, rev_pts,
                    f"{cagr:.1%} p.a. over {yrs}Y",
                    "Consistent revenue growth signals durable competitive advantage")
        else:
            s1_item("Revenue Growth CAGR", 7, 0, "Insufficient history")
    else:
        s1_item("Revenue Growth CAGR", 7, 0, "Data unavailable")

    ocf_row = _row(cf, "Operating Cash Flow", "Cash From Operations")
    ocf  = _col0(ocf_row)
    ni0  = _col0(_row(fin, "Net Income"))
    if ocf is not None and ni0 is not None and ni0 > 0:
        oe_ratio = ocf / ni0
        if oe_ratio >= 1.2: oe_pts = 5
        elif oe_ratio >= 0.9: oe_pts = 3
        else: oe_pts = 0
        s1_item("Owner Earnings Quality (OCF/NI)", 5, oe_pts,
                f"OCF/NI = {oe_ratio:.2f}x (target ≥1.0)",
                "Buffett: real earnings show up as cash, not just accounting income")
    else:
        s1_item("Owner Earnings Quality", 5, 0, "Data unavailable")

    results["sections"]["moat"] = s1

    # ── Section 2: Financial Fortress (25 pts) ────────────────────────────────
    s2 = {"max": 25, "items": [], "score": 0}

    def s2_item(name, pts, earned, detail, tip=""):
        s2["items"].append({"name": name, "pts": pts, "earned": earned,
                             "detail": detail, "tip": tip})
        s2["score"] += earned

    f_score, f_signals = _piotroski_score(bs, fin, cf, info)
    f_pts = round(f_score / 9 * 13)
    s2["piotroski_score"]   = f_score
    s2["piotroski_signals"] = f_signals
    zone_f = "Strong (7–9)" if f_score >= 7 else "Neutral (4–6)" if f_score >= 4 else "Weak (0–3)"
    s2_item("Piotroski F-Score", 13, f_pts,
            f"{f_score}/9 — {zone_f}",
            "9-signal financial-strength trend. ≥7 = improving fundamentals")

    z_score, z_zone = _altman_z(bs, fin, info)
    if z_score is not None:
        z_pts = 7 if z_score > 2.99 else (4 if z_score > 1.81 else 0)
        s2_item("Altman Z-Score", 7, z_pts, f"Z = {z_score:.2f} — {z_zone}",
                ">2.99 = safe; 1.81–2.99 = grey zone; <1.81 = distress")
    else:
        s2_item("Altman Z-Score", 7, 4, f"{z_zone} (N/A — partial data)")
    s2["altman_z"]    = z_score
    s2["altman_zone"] = z_zone

    de = _sf(info.get("debtToEquity"))
    if de is not None:
        de_norm = de / 100 if de > 10 else de
        if de_norm <= 0.3: de_pts = 5
        elif de_norm <= 0.7: de_pts = 3
        elif de_norm <= 1.2: de_pts = 1
        else: de_pts = 0
        s2_item("Debt / Equity", 5, de_pts,
                f"D/E = {de_norm:.2f}x (target ≤0.5)",
                "Buffett prefers companies that don't need debt to prosper")
    else:
        s2_item("Debt / Equity", 5, 0, "Data unavailable")

    results["sections"]["fortress"] = s2

    # ── Section 3: Valuation (20 pts) ─────────────────────────────────────────
    s3 = {"max": 20, "items": [], "score": 0}

    def s3_item(name, pts, earned, detail, tip=""):
        s3["items"].append({"name": name, "pts": pts, "earned": earned,
                             "detail": detail, "tip": tip})
        s3["score"] += earned

    fcf  = _sf(info.get("freeCashflow"))
    mktc = _sf(info.get("marketCap"))
    if fcf is not None and mktc is not None and mktc > 0:
        fcf_yield = fcf / mktc * 100
        if fcf_yield >= 6: fcf_pts = 8
        elif fcf_yield >= 3: fcf_pts = 5
        elif fcf_yield > 0: fcf_pts = 2
        else: fcf_pts = 0
        s3_item("FCF Yield", 8, fcf_pts,
                f"{fcf_yield:.1f}% (target ≥5% for Buffett-style entry)",
                "FCF yield = free cash flow / market cap. More reliable than P/E.")
    else:
        s3_item("FCF Yield", 8, 0, "Data unavailable")

    pe = _sf(info.get("trailingPE")) or _sf(info.get("forwardPE"))
    if pe is not None and pe > 0:
        if pe <= med_pe * 0.75: pe_pts = 6
        elif pe <= med_pe: pe_pts = 4
        elif pe <= med_pe * 1.25: pe_pts = 2
        else: pe_pts = 0
        s3_item("P/E vs Sector Median", 6, pe_pts,
                f"P/E = {pe:.1f}x vs sector median {med_pe:.0f}x",
                "Sector-relative: avoids penalising quality growth sectors unfairly")
    else:
        s3_item("P/E vs Sector Median", 6, 0, "Data unavailable")

    pb = _sf(info.get("priceToBook"))
    if pb is not None and pb > 0:
        if pb <= 2.0: pb_pts = 4
        elif pb <= 4.0: pb_pts = 2
        elif pb <= 6.0: pb_pts = 1
        else: pb_pts = 0
        s3_item("Price / Book", 4, pb_pts, f"P/B = {pb:.2f}x (target ≤3)")
    else:
        s3_item("Price / Book", 4, 0, "Data unavailable")

    oe, iv = _owner_earnings_dcf(fin, cf, info)
    cur_price = _sf(info.get("currentPrice") or info.get("regularMarketPrice"))
    s3["owner_earnings"] = oe
    s3["iv_per_share"]   = iv
    s3["current_price"]  = cur_price
    if iv is not None and cur_price is not None and cur_price > 0:
        mos = (iv - cur_price) / iv * 100
        s3["margin_of_safety"] = mos
        if mos >= 20:
            s3["score"]    += 2
            s3["dcf_bonus"] = True
            s3["dcf_note"]  = f"DCF MOS = {mos:.0f}% — +2 bonus pts"
        else:
            s3["dcf_bonus"] = False
            s3["dcf_note"]  = f"DCF MOS = {mos:.0f}% (no bonus below 20%)"
    else:
        s3["margin_of_safety"] = None
        s3["dcf_bonus"] = False
        s3["dcf_note"]  = "IV estimate unavailable"

    results["sections"]["valuation"] = s3

    # ── Section 4: Momentum & Trend (10 pts) ──────────────────────────────────
    s4 = {"max": 10, "items": [], "score": 0}

    def s4_item(name, pts, earned, detail, tip=""):
        s4["items"].append({"name": name, "pts": pts, "earned": earned,
                             "detail": detail, "tip": tip})
        s4["score"] += earned

    ma200 = _sf(info.get("twoHundredDayAverage"))
    if cur_price and ma200 and ma200 > 0:
        above_ma = cur_price > ma200
        pct_vs   = (cur_price - ma200) / ma200 * 100
        s4_item("Price > 200-day MA", 5, 5 if above_ma else 0,
                f"Price ${cur_price:.2f} vs 200MA ${ma200:.2f} ({pct_vs:+.1f}%)",
                "Avoids catching falling knives.")
        if not hist.empty and len(hist) >= 200:
            ma200_series = hist["Close"].rolling(200).mean().dropna()
            if len(ma200_series) >= 20:
                slope = (ma200_series.iloc[-1] - ma200_series.iloc[-20]) / ma200_series.iloc[-20]
                s4_item("200-day MA slope rising", 3, 3 if slope > 0 else 0,
                        f"20-day slope = {slope:+.2%}",
                        "Rising 200MA = sustained uptrend; flat or falling = trend broken")
            else:
                s4_item("200-day MA slope", 3, 0, "Insufficient price history")
        else:
            s4_item("200-day MA slope", 3, 0, "Insufficient price history")
    else:
        s4_item("Price vs 200-day MA", 5, 0, "Price data unavailable")
        s4_item("200-day MA slope", 3, 0, "Price data unavailable")

    ni_row = _row(fin, "Net Income")
    if ni_row is not None and len(ni_row.dropna()) >= 2:
        ni_vals = ni_row.dropna()
        ni_improving = float(ni_vals.iloc[0]) > float(ni_vals.iloc[1])
        s4_item("EPS trend improving (YoY)", 2, 2 if ni_improving else 0,
                f"NI: ${ni_vals.iloc[0]/1e9:.2f}B → ${ni_vals.iloc[1]/1e9:.2f}B YoY",
                "Forward-looking: Buffett looks for durable earnings growth")
    else:
        s4_item("EPS trend", 2, 0, "Insufficient data")

    results["sections"]["momentum"] = s4

    # ── Section 5: Shareholder Alignment (5 pts) ──────────────────────────────
    s5 = {"max": 5, "items": [], "score": 0}

    def s5_item(name, pts, earned, detail, tip=""):
        s5["items"].append({"name": name, "pts": pts, "earned": earned,
                             "detail": detail, "tip": tip})
        s5["score"] += earned

    sh_cur  = _sf(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"))
    sh_row  = _row(bs, "Ordinary Shares Number", "Share Issued")
    sh_prev = _col1(sh_row)
    sh_chg_val: float | None = None
    if sh_cur and sh_prev and sh_prev > 0:
        sh_chg = (sh_cur - sh_prev) / sh_prev * 100
        sh_chg_val = round(sh_chg, 2)
        buyback = sh_chg < -1
        s5_item("Share count declining (buybacks)", 3, 3 if buyback else 0,
                f"YoY share change = {sh_chg:+.1f}%",
                "Buffett: buybacks at fair/cheap prices are the best capital allocation")
    else:
        s5_item("Share count declining", 3, 0, "Data unavailable")

    s5["sh_chg"] = sh_chg_val

    div_yield = _sf(info.get("dividendYield"))
    byback_yield_approx = (
        max(0.0, -(sh_chg_val or 0) / 100) * (_sf(info.get("priceToBook")) or 1)
        if sh_chg_val is not None else 0.0
    )
    total_yield = (div_yield or 0) * 100 + byback_yield_approx
    if total_yield >= 3: ty_pts = 2
    elif total_yield >= 1: ty_pts = 1
    else: ty_pts = 0
    s5_item("Total shareholder yield", 2, ty_pts,
            f"Dividend yield = {(div_yield or 0)*100:.1f}%",
            "Dividend + buyback yield. Capital returned to owners signals discipline.")

    results["sections"]["shareholder"] = s5

    # ── Grand total ────────────────────────────────────────────────────────────
    results["total"] = min(sum(sec["score"] for sec in results["sections"].values()), 100)
    return results
