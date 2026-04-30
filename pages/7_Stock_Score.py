"""
Pulse360 — Buffett Stock Score
================================
A comprehensive stock-level quality + valuation screener implementing the
Buffett / Munger investment framework, incorporating every improvement
surfaced by quantitative finance research:

  1. Sector-relative benchmarking  — margins judged vs industry median, not
     flat thresholds (avoids punishing high-quality tech or healthcare)
  2. Piotroski F-Score             — 9-point financial-strength trend signal
  3. Altman Z-Score                — bankruptcy / distress risk
  4. Owner Earnings DCF            — intrinsic value per share estimate
  5. Share count trend             — buyback detection
  6. 200-day MA momentum filter    — avoids "falling knives"
  7. FCF yield & valuation context — a great company ≠ a great investment
  8. Sector warnings               — Financials / REITs flagged for adjusted rules

Score: 0 – 100 across five dimensions.
Data : yfinance (fundamentals + price history). Cached 1 hour.
"""

from __future__ import annotations

import math
import time
import random
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

from components.chart_utils import dark_layout


def _make_yf_session() -> requests.Session:
    """Return a requests.Session that mimics a real browser to avoid Yahoo rate limits."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    return session

# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .main .block-container { padding-top: 1rem; max-width: 1200px; }
    div[data-testid="metric-container"] {
        background: #1a1a2e; border-radius: 8px;
        padding: 12px 16px; border: 1px solid #333;
    }
    .stTabs [data-baseweb="tab"] { background-color: #1a1a2e;
                                   border-radius: 6px 6px 0 0; padding: 8px 14px; }
    .stTabs [aria-selected="true"] { background-color: #2a2a4a; }
</style>
""", unsafe_allow_html=True)

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

_SECTOR_SPECIAL = {
    "Financial Services", "Banks", "Insurance", "REIT",
    "Real Estate", "Mortgage Finance",
}

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


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stock_data(ticker: str) -> dict:
    """
    Pull all fundamentals + price history from yfinance.
    Uses a browser-like session + exponential-backoff retry to avoid Yahoo rate limits.
    Returns a normalised dict with sub-keys:
        info, financials, balance_sheet, cashflow, history, error
    """
    result: dict = {
        "info": {}, "financials": None, "balance_sheet": None,
        "cashflow": None, "history": pd.DataFrame(), "error": None,
    }

    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            session = _make_yf_session()
            t = yf.Ticker(ticker.upper().strip(), session=session)

            info = t.info or {}
            # yfinance sometimes returns a minimal dict on rate-limit; detect it
            if not info or list(info.keys()) == ["trailingPegRatio"]:
                raise ValueError("Incomplete info response (likely rate-limited)")

            result["info"]          = info
            result["financials"]    = t.financials
            result["balance_sheet"] = t.balance_sheet
            result["cashflow"]      = t.cashflow
            result["history"]       = t.history(period="2y")
            result["error"]         = None
            return result  # success — exit immediately

        except Exception as exc:
            err_str = str(exc)
            if attempt < MAX_RETRIES:
                # Exponential back-off with jitter: 2s, 4s, …  ± 0–1s
                wait = (2 ** attempt) + random.random()
                time.sleep(wait)
            else:
                result["error"] = err_str

    return result


# ── Scoring engines ───────────────────────────────────────────────────────────

def _piotroski_score(
    bs: pd.DataFrame | None,
    fin: pd.DataFrame | None,
    cf: pd.DataFrame | None,
    info: dict,
) -> tuple[int, list[dict]]:
    """
    Compute Piotroski F-Score (0–9) from yfinance DataFrames.
    Returns (score, list of signal dicts for display).
    """
    signals: list[dict] = []

    def sig(name: str, passed: bool | None, detail: str = "") -> None:
        signals.append({
            "name": name,
            "pass": passed,
            "detail": detail,
            "pts": 1 if passed else 0,
        })

    # ── Profitability signals ──────────────────────────────────────────────────
    roa0 = _sf(info.get("returnOnAssets"))
    roa_ok = (roa0 is not None and roa0 > 0)
    sig("ROA > 0", roa_ok, f"ROA = {roa0:.1%}" if roa0 is not None else "n/a")

    ocf_row = _row(cf, "Operating Cash Flow", "Cash From Operations",
                   "Net Cash From Operating Activities")
    ocf0    = _col0(ocf_row)
    sig("Operating CF > 0", ocf0 is not None and ocf0 > 0,
        f"OCF = ${ocf0/1e9:.2f}B" if ocf0 is not None else "n/a")

    ta_row = _row(bs, "Total Assets")
    ta0 = _col0(ta_row); ta1 = _col1(ta_row)
    ni_row = _row(fin, "Net Income")
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

    # ── Leverage / Liquidity signals ───────────────────────────────────────────
    ltd_row = _row(bs, "Long Term Debt", "Long-Term Debt",
                   "Long Term Debt And Capital Lease Obligation")
    ltd0 = _col0(ltd_row); ltd1 = _col1(ltd_row)
    if ltd0 is not None and ltd1 is not None and ta0 is not None and ta1 is not None and ta0 > 0 and ta1 > 0:
        d_lev = (ltd0 / ta0) - (ltd1 / ta1)
        sig("ΔLeverage ≤ 0 (debt load falling)", d_lev <= 0, f"Δlev = {d_lev:+.3f}")
    else:
        d_lev_info = _sf(info.get("debtToEquity"))
        sig("ΔLeverage ≤ 0", None, f"D/E = {d_lev_info:.2f}" if d_lev_info else "n/a")

    cr = _sf(info.get("currentRatio"))
    # Can only compute delta if we have balance sheet current assets/liabilities
    ca0 = _col0(_row(bs, "Current Assets")); ca1 = _col1(_row(bs, "Current Assets"))
    cl0 = _col0(_row(bs, "Current Liabilities")); cl1 = _col1(_row(bs, "Current Liabilities"))
    if ca0 and ca1 and cl0 and cl1 and cl0 > 0 and cl1 > 0:
        d_cr = (ca0 / cl0) - (ca1 / cl1)
        sig("ΔCurrent Ratio > 0 (liquidity rising)", d_cr > 0, f"Δcr = {d_cr:+.3f}")
    else:
        sig("ΔCurrent Ratio > 0", None, f"current = {cr:.2f}" if cr else "n/a")

    sh0 = _sf(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"))
    sh_row = _row(bs, "Ordinary Shares Number", "Common Stock Shares Outstanding",
                  "Share Issued")
    sh1_bs = _col1(sh_row)
    if sh0 is not None and sh1_bs is not None and sh1_bs > 0:
        diluted = (sh0 - sh1_bs) / sh1_bs
        sig("No share dilution", diluted <= 0.01,
            f"YoY share Δ = {diluted:+.2%}")
    else:
        sig("No share dilution", None, "share count data unavailable")

    # ── Operating efficiency signals ───────────────────────────────────────────
    gp_row = _row(fin, "Gross Profit")
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
    """
    Compute Altman Z-Score for public non-financial companies.
    Returns (z_score, zone_label).
    """
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

        re  = _col0(_row(bs, "Retained Earnings", "Retained Earnings (Accumulated Deficit)"))
        ebit_row = _row(fin, "EBIT", "Operating Income", "Ebit")
        ebit = _col0(ebit_row)
        if ebit is None:
            ni   = _col0(_row(fin, "Net Income"))
            tax  = _col0(_row(fin, "Tax Provision", "Income Tax Expense"))
            intr = _col0(_row(fin, "Interest Expense"))
            if ni is not None:
                ebit = ni + (tax or 0) + abs(intr or 0)

        mktcap = _sf(info.get("marketCap"))
        tl_row  = _row(bs, "Total Liabilities Net Minority Interest",
                        "Total Liabilities", "Total Non Current Liabilities Net")
        tl = _col0(tl_row)
        if tl is None:
            tl_val = _sf(info.get("totalDebt"))
            te_val = _sf(info.get("totalStockholderEquity"))
            tl = (mktcap - te_val) if mktcap and te_val else None

        rev = _col0(_row(fin, "Total Revenue", "Revenue"))

        # Require at least 4 / 5 components
        parts = [wc, re, ebit, mktcap, tl, rev, ta]
        if sum(1 for p in parts if p is not None) < 5:
            return None, "Insufficient data"

        x1 = (wc   or 0) / ta
        x2 = (re   or 0) / ta
        x3 = (ebit or 0) / ta
        x4 = (mktcap or 0) / max(tl or 1, 1)
        x5 = (rev  or 0) / ta

        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5

        if z > 2.99:
            zone = "Safe Zone (Z > 2.99)"
        elif z > 1.81:
            zone = "Grey Zone (1.81–2.99)"
        else:
            zone = "Distress Zone (Z < 1.81)"

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
) -> tuple[float | None, float | None]:
    """
    Estimate intrinsic value per share using Owner Earnings DCF.
    OE = Net Income + D&A − CapEx ± ΔWorking Capital

    Returns (owner_earnings_annual, intrinsic_value_per_share).
    """
    try:
        ni  = _col0(_row(fin, "Net Income"))
        da  = _col0(_row(cf,  "Depreciation And Amortization",
                              "Depreciation Depletion And Amortization",
                              "Depreciation Amortization Depletion"))
        capex = _col0(_row(cf, "Capital Expenditure",
                             "Capital Expenditures",
                             "Purchase Of Ppe",
                             "Capital Expenditure Reported"))

        if ni is None:
            return None, None

        # CapEx is typically negative in yfinance — take absolute value
        capex_abs = abs(capex) if capex is not None else 0
        da_abs    = abs(da)    if da    is not None else 0

        owner_earnings = ni + da_abs - capex_abs  # simplified; ignore ΔWC

        if owner_earnings <= 0:
            return owner_earnings, None

        shares = _sf(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"))
        if not shares or shares <= 0:
            return owner_earnings, None

        # Two-stage DCF: 10-year horizon
        pv = 0.0
        for yr in range(1, 11):
            g = g_stage1 if yr <= 5 else g_stage1 / 2
            oe_yr = owner_earnings * (1 + g) ** yr
            pv   += oe_yr / (1 + discount_rate) ** yr

        # Terminal value (perpetuity)
        oe_term = owner_earnings * (1 + g_stage1 / 2) ** 10 * (1 + g_terminal)
        tv      = oe_term / (discount_rate - g_terminal)
        pv     += tv / (1 + discount_rate) ** 10

        iv_per_share = pv / shares
        return owner_earnings, iv_per_share

    except Exception:
        return None, None


def _compute_score(data: dict) -> dict:
    """
    Run all scorecards and return a comprehensive results dict.
    """
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

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — Quality Moat (40 pts)
    # ══════════════════════════════════════════════════════════════════════════
    s1 = {"max": 40, "items": [], "score": 0}

    def s1_item(name, pts, earned, detail, tip=""):
        s1["items"].append({"name": name, "pts": pts, "earned": earned,
                             "detail": detail, "tip": tip})
        s1["score"] += earned

    gm = _sf(info.get("grossMargins"))
    if gm is not None:
        gm_pct = gm * 100
        if gm_pct >= med_gm * 1.35:
            gm_pts = 10
        elif gm_pct >= med_gm * 1.15:
            gm_pts = 7
        elif gm_pct >= med_gm:
            gm_pts = 4
        else:
            gm_pts = 0
        s1_item(
            "Gross Margin (vs sector)",
            10, gm_pts,
            f"{gm_pct:.1f}% vs sector median {med_gm:.0f}%",
            "Pass if GM > 1.15× sector median (not flat 40% threshold)",
        )
    else:
        s1_item("Gross Margin", 10, 0, "Data unavailable")

    nm = _sf(info.get("profitMargins"))
    if nm is not None:
        nm_pct = nm * 100
        if nm_pct >= med_nm * 1.3:
            nm_pts = 8
        elif nm_pct >= med_nm:
            nm_pts = 5
        elif nm_pct > 0:
            nm_pts = 2
        else:
            nm_pts = 0
        s1_item(
            "Net Margin (vs sector)",
            8, nm_pts,
            f"{nm_pct:.1f}% vs sector median {med_nm:.0f}%",
        )
    else:
        s1_item("Net Margin", 8, 0, "Data unavailable")

    roe = _sf(info.get("returnOnEquity"))
    if roe is not None:
        roe_pct = roe * 100
        if roe_pct >= 20:
            roe_pts = 10
        elif roe_pct >= 15:
            roe_pts = 7
        elif roe_pct >= 10:
            roe_pts = 4
        else:
            roe_pts = 0
        s1_item(
            "Return on Equity",
            10, roe_pts,
            f"{roe_pct:.1f}% (targets: ≥20%=10, ≥15%=7, ≥10%=4)",
        )
    else:
        s1_item("Return on Equity", 10, 0, "Data unavailable")

    rev_row = _row(fin, "Total Revenue", "Revenue")
    if rev_row is not None and len(rev_row.dropna()) >= 3:
        rev_vals = rev_row.dropna()[:4][::-1].values
        if len(rev_vals) >= 3 and rev_vals[0] > 0:
            yrs   = len(rev_vals) - 1
            cagr  = (rev_vals[-1] / rev_vals[0]) ** (1 / yrs) - 1
            if cagr >= 0.15:
                rev_pts = 7
            elif cagr >= 0.08:
                rev_pts = 4
            elif cagr >= 0.03:
                rev_pts = 2
            else:
                rev_pts = 0
            s1_item("Revenue Growth CAGR", 7, rev_pts, f"{cagr:.1%} p.a. over {yrs}Y",
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
        if oe_ratio >= 1.2:
            oe_pts = 5
        elif oe_ratio >= 0.9:
            oe_pts = 3
        else:
            oe_pts = 0
        s1_item("Owner Earnings Quality (OCF/NI)", 5, oe_pts,
                f"OCF/NI = {oe_ratio:.2f}x (target ≥1.0)",
                "Buffett: real earnings show up as cash, not just accounting income")
    else:
        s1_item("Owner Earnings Quality", 5, 0, "Data unavailable")

    results["sections"]["moat"] = s1

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — Financial Fortress (25 pts)
    # ══════════════════════════════════════════════════════════════════════════
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
        if z_score > 2.99:
            z_pts = 7
        elif z_score > 1.81:
            z_pts = 4
        else:
            z_pts = 0
        s2_item("Altman Z-Score", 7, z_pts, f"Z = {z_score:.2f} — {z_zone}",
                ">2.99 = safe; 1.81–2.99 = grey zone; <1.81 = distress")
    else:
        s2_item("Altman Z-Score", 7, 4, f"{z_zone} (N/A — partial data)")
    s2["altman_z"] = z_score
    s2["altman_zone"] = z_zone

    de = _sf(info.get("debtToEquity"))
    if de is not None:
        de_norm = de / 100 if de > 10 else de
        if de_norm <= 0.3:
            de_pts = 5
        elif de_norm <= 0.7:
            de_pts = 3
        elif de_norm <= 1.2:
            de_pts = 1
        else:
            de_pts = 0
        s2_item("Debt / Equity", 5, de_pts,
                f"D/E = {de_norm:.2f}x (target ≤0.5)",
                "Buffett prefers companies that don't need debt to prosper")
    else:
        s2_item("Debt / Equity", 5, 0, "Data unavailable")

    results["sections"]["fortress"] = s2

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — Valuation (20 pts)
    # ══════════════════════════════════════════════════════════════════════════
    s3 = {"max": 20, "items": [], "score": 0}

    def s3_item(name, pts, earned, detail, tip=""):
        s3["items"].append({"name": name, "pts": pts, "earned": earned,
                             "detail": detail, "tip": tip})
        s3["score"] += earned

    fcf  = _sf(info.get("freeCashflow"))
    mktc = _sf(info.get("marketCap"))
    if fcf is not None and mktc is not None and mktc > 0:
        fcf_yield = fcf / mktc * 100
        if fcf_yield >= 6:
            fcf_pts = 8
        elif fcf_yield >= 3:
            fcf_pts = 5
        elif fcf_yield > 0:
            fcf_pts = 2
        else:
            fcf_pts = 0
        s3_item("FCF Yield", 8, fcf_pts,
                f"{fcf_yield:.1f}% (target ≥5% for Buffett-style entry)",
                "FCF yield = free cash flow / market cap. More reliable than P/E.")
    else:
        s3_item("FCF Yield", 8, 0, "Data unavailable")

    pe = _sf(info.get("trailingPE")) or _sf(info.get("forwardPE"))
    if pe is not None and pe > 0:
        if pe <= med_pe * 0.75:
            pe_pts = 6
        elif pe <= med_pe:
            pe_pts = 4
        elif pe <= med_pe * 1.25:
            pe_pts = 2
        else:
            pe_pts = 0
        s3_item("P/E vs Sector Median", 6, pe_pts,
                f"P/E = {pe:.1f}x vs sector median {med_pe:.0f}x",
                "Sector-relative: avoids penalising quality growth sectors unfairly")
    else:
        s3_item("P/E vs Sector Median", 6, 0, "Data unavailable")

    pb = _sf(info.get("priceToBook"))
    if pb is not None and pb > 0:
        if pb <= 2.0:
            pb_pts = 4
        elif pb <= 4.0:
            pb_pts = 2
        elif pb <= 6.0:
            pb_pts = 1
        else:
            pb_pts = 0
        s3_item("Price / Book", 4, pb_pts, f"P/B = {pb:.2f}x (target ≤3)")
    else:
        s3_item("Price / Book", 4, 0, "Data unavailable")

    # DCF intrinsic value
    oe, iv = _owner_earnings_dcf(fin, cf, info)
    cur_price = _sf(info.get("currentPrice") or info.get("regularMarketPrice"))
    s3["owner_earnings"] = oe
    s3["iv_per_share"]   = iv
    s3["current_price"]  = cur_price
    if iv is not None and cur_price is not None and cur_price > 0:
        mos = (iv - cur_price) / iv * 100
        s3["margin_of_safety"] = mos
        if mos >= 20:
            s3["score"] += 2
            s3["dcf_bonus"] = True
            s3["dcf_note"] = f"DCF MOS = {mos:.0f}% — +2 bonus pts"
        else:
            s3["dcf_bonus"] = False
            s3["dcf_note"] = f"DCF MOS = {mos:.0f}% (no bonus below 20%)"
    else:
        s3["margin_of_safety"] = None
        s3["dcf_bonus"] = False
        s3["dcf_note"] = "IV estimate unavailable"

    results["sections"]["valuation"] = s3

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4 — Momentum & Trend (10 pts)
    # ══════════════════════════════════════════════════════════════════════════
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
                "Avoids catching falling knives. Gemini: 'value stocks can stay cheap for years.'")
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

    # EPS trend
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

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 5 — Shareholder Alignment (5 pts)
    # ══════════════════════════════════════════════════════════════════════════
    s5 = {"max": 5, "items": [], "score": 0}

    def s5_item(name, pts, earned, detail, tip=""):
        s5["items"].append({"name": name, "pts": pts, "earned": earned,
                             "detail": detail, "tip": tip})
        s5["score"] += earned

    sh_cur = _sf(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"))
    sh_row = _row(bs, "Ordinary Shares Number", "Share Issued")
    sh_prev = _col1(sh_row)
    if sh_cur and sh_prev and sh_prev > 0:
        sh_chg = (sh_cur - sh_prev) / sh_prev * 100
        buyback = sh_chg < -1
        s5_item("Share count declining (buybacks)", 3, 3 if buyback else 0,
                f"YoY share change = {sh_chg:+.1f}%",
                "Buffett: buybacks at fair/cheap prices are the best capital allocation")
    else:
        s5_item("Share count declining", 3, 0, "Data unavailable")

    div_yield = _sf(info.get("dividendYield"))
    if mktc and fcf:
        byback_yield_approx = (
            max(0.0, -(sh_chg if sh_cur and sh_prev else 0) / 100) * (_sf(info.get("priceToBook")) or 1)
        )
    else:
        byback_yield_approx = 0.0
    total_yield = (div_yield or 0) * 100 + byback_yield_approx
    if total_yield >= 3:
        ty_pts = 2
    elif total_yield >= 1:
        ty_pts = 1
    else:
        ty_pts = 0
    s5_item("Total shareholder yield", 2, ty_pts,
            f"Dividend yield = {(div_yield or 0)*100:.1f}%",
            "Dividend + buyback yield. Capital returned to owners signals discipline.")

    results["sections"]["shareholder"] = s5

    # ── Grand total ────────────────────────────────────────────────────────────
    total = sum(sec["score"] for sec in results["sections"].values())
    results["total"] = min(total, 100)

    return results


# ── Page helpers ──────────────────────────────────────────────────────────────

def _hex_rgba(hx: str, a: float) -> str:
    h = hx.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"

def _score_color(score: int) -> str:
    if score >= 75: return "#2ecc71"
    if score >= 60: return "#27ae60"
    if score >= 45: return "#f1c40f"
    if score >= 30: return "#e67e22"
    return "#e74c3c"

def _score_label(score: int) -> tuple[str, str]:
    if score >= 80: return "Exceptional — Wide Moat",     "🟢"
    if score >= 65: return "Strong — Worth Deep Dive",     "🟢"
    if score >= 50: return "Decent — Some Weaknesses",    "🟡"
    if score >= 35: return "Weak — Multiple Red Flags",   "🟠"
    return           "Poor — Fails Buffett Criteria",      "🔴"

def _render_section_items(items: list[dict]) -> None:
    for item in items:
        earned = item["earned"]
        pts    = item["pts"]
        pct    = earned / pts if pts > 0 else 0
        if pct >= 0.8:
            icon, color = "✅", "#2ecc71"
        elif pct >= 0.4:
            icon, color = "🟡", "#f39c12"
        elif item.get("pass") is None:
            icon, color = "⬜", "#555"
        else:
            icon, color = "❌", "#e74c3c"

        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
            f'padding:6px 10px;border-bottom:1px solid #1e1e2e;">'
            f'<span style="color:#ccc;font-size:0.85rem;">{icon} {item["name"]}'
            f'{"<span style=\'font-size:0.72rem;color:#888;margin-left:8px;\'>ℹ " + item.get("tip", "") + "</span>" if item.get("tip") else ""}'
            f'</span>'
            f'<span style="font-size:0.8rem;">'
            f'<span style="color:#888;">{item["detail"]}&nbsp;&nbsp;</span>'
            f'<span style="color:{color};font-weight:700;">{earned}/{pts}</span>'
            f'</span></div>',
            unsafe_allow_html=True,
        )


# ── Main page ──────────────────────────────────────────────────────────────────

st.markdown("# 🔍 Buffett Stock Score")
st.caption(
    "A 100-point stock screen implementing the Buffett / Munger quality framework. "
    "Addresses all five weaknesses surfaced by quantitative research: sector-relative "
    "benchmarks · Piotroski F-Score · Altman Z-Score · Owner Earnings DCF · "
    "200-day MA momentum · Share buyback detection."
)

col_inp, col_tip = st.columns([2, 3])
with col_inp:
    ticker_input = st.text_input(
        "Enter stock ticker",
        placeholder="e.g. AAPL, MSFT, KO, BRK-B",
        key="stock_score_ticker",
        help="Any ticker listed on US exchanges (yfinance). "
             "International tickers: append exchange suffix (e.g. SHEL.L)",
    ).strip().upper()

with col_tip:
    st.info(
        "**How scoring works:** 100pts across five dimensions — "
        "Quality Moat (40) · Financial Fortress (25) · Valuation (20) · "
        "Momentum (10) · Shareholder Alignment (5). "
        "Margins are benchmarked vs sector medians, not flat thresholds.",
        icon="📐",
    )

if not ticker_input:
    st.markdown("""
---
<div style="text-align:center; color:#555; padding:32px 0; font-size:0.95rem;">
    Enter a ticker above to run the full Buffett Score analysis
</div>
""", unsafe_allow_html=True)
    st.caption(DISCLAIMER)
    st.stop()

# ── Load data ─────────────────────────────────────────────────────────────────
with st.spinner(f"Loading fundamentals for {ticker_input}…"):
    raw = fetch_stock_data(ticker_input)

if raw.get("error") or not raw.get("info"):
    st.error(
        f"Could not load data for **{ticker_input}**. "
        f"Error: {raw.get('error', 'No data returned')}. "
        "Check the ticker is correct and try again."
    )
    st.stop()

info     = raw["info"]
long_name = info.get("longName") or info.get("shortName") or ticker_input
sector    = info.get("sector")   or info.get("sectorDisp") or "Unknown"
industry  = info.get("industry") or info.get("industryDisp") or "Unknown"
cur_price = _sf(info.get("currentPrice") or info.get("regularMarketPrice"))
mktcap    = _sf(info.get("marketCap"))

# ── Company header ────────────────────────────────────────────────────────────
st.markdown("---")
hc1, hc2, hc3, hc4 = st.columns([3, 1, 1, 1])
with hc1:
    st.markdown(f"## {long_name}")
    st.caption(f"{ticker_input} · {sector} · {industry}")
with hc2:
    if cur_price:
        st.metric("Price", f"${cur_price:,.2f}")
with hc3:
    if mktcap:
        st.metric("Market Cap", f"${mktcap/1e9:.1f}B")
with hc4:
    ma200 = _sf(info.get("twoHundredDayAverage"))
    if cur_price and ma200:
        pct = (cur_price - ma200) / ma200 * 100
        st.metric("vs 200-day MA", f"{pct:+.1f}%",
                  delta_color="normal" if pct > 0 else "inverse")

# Special sector warning
if _is_special_sector(sector, industry):
    st.warning(
        f"⚠️ **{sector} / {industry}** — This is a financial or REIT sector company. "
        "Standard Buffett rules (D/E, Gross Margin) are **not directly applicable** due to "
        "the capital structure of financial firms. Treat the score directionally, not literally. "
        "Piotroski F-Score and ROE remain meaningful.",
        icon="🏦",
    )

# ── Compute score ─────────────────────────────────────────────────────────────
with st.spinner("Computing scores…"):
    score_data = _compute_score(raw)

total        = score_data["total"]
s_color      = _score_color(total)
s_label, s_emoji = _score_label(total)
secs         = score_data["sections"]
moat         = secs["moat"]
fortress     = secs["fortress"]
valuation    = secs["valuation"]
momentum     = secs["momentum"]
shareholder  = secs["shareholder"]

# ── Composite score card ───────────────────────────────────────────────────────
st.markdown(
    f"""
    <div style="background:#1a1a2e;border:2px solid {_hex_rgba(s_color, 0.6)};
                border-radius:12px;padding:20px 24px;margin:12px 0;">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;
                  flex-wrap:wrap;gap:16px;margin-bottom:14px;">
        <div>
          <div style="color:#888;font-size:0.7rem;font-weight:700;letter-spacing:.08em;
                      text-transform:uppercase;margin-bottom:6px;">
            Buffett Score — {long_name}
          </div>
          <div style="color:{s_color};font-size:3rem;font-weight:900;line-height:1;">
            {total}
            <span style="font-size:1rem;color:#555;font-weight:400;"> / 100</span>
          </div>
          <div style="color:{s_color};font-size:1rem;font-weight:700;margin-top:6px;">
            {s_emoji} {s_label}
          </div>
        </div>
        <div style="font-size:0.8rem;line-height:2.1;padding-top:4px;">
    """,
    unsafe_allow_html=True,
)

# Section breakdown rows
for sec_key, sec_name, sec_color in [
    ("moat",        "⚔️  Quality Moat",        "#3498db"),
    ("fortress",    "🏰  Financial Fortress",   "#9b59b6"),
    ("valuation",   "💰  Valuation",            "#2ecc71"),
    ("momentum",    "📈  Momentum",             "#f39c12"),
    ("shareholder", "🤝  Shareholder Alignment","#1abc9c"),
]:
    sec   = secs[sec_key]
    pct   = sec["score"] / sec["max"] * 100
    sc    = _score_color(int(pct))
    st.markdown(
        f'<div style="font-size:0.8rem;line-height:2.0;">'
        f'<span style="color:#888;">{sec_name}</span>'
        f'&nbsp;<span style="color:{sc};font-weight:700;">{sec["score"]}/{sec["max"]}</span>'
        f'&nbsp;<span style="color:#555;font-size:0.72rem;">'
        f'{"▓" * int(pct // 10)}{"░" * (10 - int(pct // 10))}'
        f'</span></div>',
        unsafe_allow_html=True,
    )

st.markdown("</div></div>", unsafe_allow_html=True)

# ── Five section tabs ──────────────────────────────────────────────────────────
t1, t2, t3, t4, t5 = st.tabs([
    "⚔️ Quality Moat",
    "🏰 Financial Fortress",
    "💰 Valuation & DCF",
    "📈 Momentum",
    "🤝 Shareholder Alignment",
])

# ── TAB 1: Quality Moat ────────────────────────────────────────────────────────
with t1:
    st.markdown(f"#### Quality Moat — {moat['score']}/{moat['max']} pts")
    st.caption(
        "Gross Margin and Net Margin are benchmarked against the **sector median**, "
        "not a flat 40% threshold. This avoids unfairly penalising high-quality tech "
        "or healthcare companies and unfairly rewarding low-margin commodity businesses."
    )
    med_gm = score_data["med_gm"]
    med_nm = score_data["med_nm"]
    st.info(
        f"**Sector benchmarks for {sector}:** "
        f"Gross Margin median = {med_gm:.0f}% · "
        f"Net Margin median = {med_nm:.0f}%",
        icon="📊",
    )
    _render_section_items(moat["items"])

# ── TAB 2: Financial Fortress ──────────────────────────────────────────────────
with t2:
    st.markdown(f"#### Financial Fortress — {fortress['score']}/{fortress['max']} pts")

    col_f, col_z = st.columns(2)

    with col_f:
        f_score = fortress.get("piotroski_score", 0)
        f_color = "#2ecc71" if f_score >= 7 else "#f39c12" if f_score >= 4 else "#e74c3c"
        st.markdown(
            f'<div style="background:#1a1a2e;border:1px solid {_hex_rgba(f_color,0.4)};'
            f'border-radius:8px;padding:14px;text-align:center;margin-bottom:12px;">'
            f'<div style="color:#888;font-size:0.7rem;font-weight:700;letter-spacing:.06em;'
            f'text-transform:uppercase;">Piotroski F-Score</div>'
            f'<div style="color:{f_color};font-size:2.5rem;font-weight:800;">{f_score}<span style="font-size:1rem;color:#555;">/9</span></div>'
            f'<div style="color:{f_color};font-size:0.8rem;">{"Strong 🟢" if f_score >= 7 else "Neutral 🟡" if f_score >= 4 else "Weak 🔴"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.caption("9 binary signals across profitability, leverage, and operating efficiency. "
                   "F ≥ 7 = strengthening fundamentals; F ≤ 3 = deteriorating.")
        for sig in fortress.get("piotroski_signals", []):
            icon = "✅" if sig["pass"] is True else ("❌" if sig["pass"] is False else "⬜")
            st.markdown(
                f'<div style="padding:4px 8px;border-bottom:1px solid #1e1e2e;font-size:0.82rem;">'
                f'{icon} <span style="color:#ccc;">{sig["name"]}</span>'
                f'<span style="color:#666;font-size:0.75rem;float:right;">{sig["detail"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with col_z:
        z_val  = fortress.get("altman_z")
        z_zone = fortress.get("altman_zone", "N/A")
        z_color = "#2ecc71" if (z_val and z_val > 2.99) else "#f39c12" if (z_val and z_val > 1.81) else "#e74c3c"
        st.markdown(
            f'<div style="background:#1a1a2e;border:1px solid {_hex_rgba(z_color,0.4)};'
            f'border-radius:8px;padding:14px;text-align:center;margin-bottom:12px;">'
            f'<div style="color:#888;font-size:0.7rem;font-weight:700;letter-spacing:.06em;'
            f'text-transform:uppercase;">Altman Z-Score</div>'
            f'<div style="color:{z_color};font-size:2.5rem;font-weight:800;">'
            f'{f"{z_val:.2f}" if z_val else "N/A"}</div>'
            f'<div style="color:{z_color};font-size:0.8rem;">{z_zone}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Bankruptcy risk indicator. "
            "> 2.99: Safe zone. "
            "1.81–2.99: Grey zone — monitor. "
            "< 1.81: Distress — high financial risk. "
            "Note: less reliable for financial/REIT sectors."
        )
        for item in fortress["items"]:
            if "Altman" not in item["name"] and "Piotroski" not in item["name"]:
                _render_section_items([item])

# ── TAB 3: Valuation & DCF ─────────────────────────────────────────────────────
with t3:
    st.markdown(f"#### Valuation & DCF — {valuation['score']}/{valuation['max']} pts")
    st.caption(
        "A great company is only a great investment if you pay the right price. "
        "P/E is benchmarked against the sector median. FCF Yield is Buffett's "
        "preferred valuation metric. The Owner Earnings DCF estimates intrinsic value "
        "per share and calculates margin of safety."
    )

    _render_section_items(valuation["items"])

    # DCF detail card
    oe  = valuation.get("owner_earnings")
    iv  = valuation.get("iv_per_share")
    cp  = valuation.get("current_price")
    mos = valuation.get("margin_of_safety")

    st.markdown("---")
    st.markdown("##### 📐 Owner Earnings DCF — Intrinsic Value Estimate")
    st.caption(
        "Buffett's 1986 definition: Owner Earnings = Net Income + D&A − CapEx. "
        "Projected over 10 years (8% growth years 1–5, 4% years 6–10), discounted at 10%. "
        "Terminal value at 3% perpetuity growth. "
        "⚠️ Highly sensitive to growth assumptions — use as a sanity check, not a precise target."
    )

    dcf_c1, dcf_c2, dcf_c3 = st.columns(3)
    with dcf_c1:
        if oe is not None:
            st.metric("Owner Earnings (TTM)", f"${oe/1e9:.2f}B" if abs(oe) > 1e8 else f"${oe/1e6:.0f}M")
        else:
            st.metric("Owner Earnings", "N/A")
    with dcf_c2:
        if iv is not None:
            st.metric("DCF Intrinsic Value / Share", f"${iv:.2f}")
        else:
            st.metric("DCF IV / Share", "N/A")
    with dcf_c3:
        if mos is not None:
            mos_color = "normal" if mos > 0 else "inverse"
            st.metric("Margin of Safety", f"{mos:.0f}%",
                      delta=f"{'Undervalued' if mos > 0 else 'Overvalued'}",
                      delta_color=mos_color)
        else:
            st.metric("Margin of Safety", "N/A")

    if iv and cp:
        st.caption(valuation.get("dcf_note", ""))
    else:
        st.info("Insufficient data to compute DCF intrinsic value. "
                "Check that the company has positive net income and CapEx data on yfinance.", icon="ℹ️")

# ── TAB 4: Momentum ────────────────────────────────────────────────────────────
with t4:
    st.markdown(f"#### Momentum & Trend — {momentum['score']}/{momentum['max']} pts")
    st.caption(
        "Addresses the 'value trap' problem: a fundamentally strong company whose stock "
        "is in a sustained downtrend may be experiencing structural deterioration that "
        "backward-looking ratios haven't yet captured. The 200-day MA is Buffett's "
        "least-favourite indicator — but it's a useful filter for avoiding falling knives."
    )
    _render_section_items(momentum["items"])

    # Price vs 200-day MA chart
    hist = raw.get("history", pd.DataFrame())
    if not hist.empty and len(hist) >= 60:
        close = hist["Close"]
        ma200_series = close.rolling(200).mean()
        ma50_series  = close.rolling(50).mean()

        fig_p = go.Figure()
        fig_p.add_trace(go.Scatter(
            x=close.index, y=close.values,
            name="Price", line={"color": "#3498db", "width": 1.5},
            hovertemplate="%{x|%b %Y}: $%{y:.2f}<extra></extra>",
        ))
        fig_p.add_trace(go.Scatter(
            x=ma200_series.index, y=ma200_series.values,
            name="200-day MA", line={"color": "#e74c3c", "width": 2, "dash": "dot"},
            hovertemplate="200MA: $%{y:.2f}<extra></extra>",
        ))
        fig_p.add_trace(go.Scatter(
            x=ma50_series.index, y=ma50_series.values,
            name="50-day MA", line={"color": "#f39c12", "width": 1.5, "dash": "dash"},
            hovertemplate="50MA: $%{y:.2f}<extra></extra>",
        ))
        fig_p = dark_layout(fig_p, yaxis_title="Price (USD)")
        fig_p.update_layout(
            height=360,
            title=dict(text=f"{ticker_input} — Price vs Moving Averages (2Y)",
                       font=dict(size=13, color="#ccc")),
            legend={"orientation": "h", "y": -0.2},
        )
        st.plotly_chart(fig_p, use_container_width=True, key="stock_score_price_chart")

# ── TAB 5: Shareholder Alignment ───────────────────────────────────────────────
with t5:
    st.markdown(f"#### Shareholder Alignment — {shareholder['score']}/{shareholder['max']} pts")
    st.caption(
        "Buffett's view: management quality is revealed by capital allocation decisions. "
        "Share buybacks at fair prices are the single best use of excess capital. "
        "A declining share count over 5 years is one of the strongest signals of "
        "a shareholder-friendly management team."
    )
    _render_section_items(shareholder["items"])

    # Share count trend chart from balance sheet
    bs = raw.get("balance_sheet")
    sh_row = _row(bs, "Ordinary Shares Number", "Share Issued",
                  "Common Stock Shares Outstanding")
    if sh_row is not None:
        sh_data = sh_row.dropna()
        if len(sh_data) >= 2:
            sh_df = pd.DataFrame({
                "Year": [str(d.year) for d in sh_data.index[::-1]],
                "Shares (B)": [float(v) / 1e9 for v in sh_data.values[::-1]],
            })
            fig_sh = go.Figure()
            fig_sh.add_trace(go.Bar(
                x=sh_df["Year"], y=sh_df["Shares (B)"],
                marker_color=[
                    "#2ecc71" if i == 0 or sh_df["Shares (B)"].iloc[i] <= sh_df["Shares (B)"].iloc[i - 1]
                    else "#e74c3c"
                    for i in range(len(sh_df))
                ],
                hovertemplate="<b>%{x}</b>: %{y:.3f}B shares<extra></extra>",
                name="Shares Outstanding",
            ))
            fig_sh = dark_layout(fig_sh, yaxis_title="Shares Outstanding (B)")
            fig_sh.update_layout(
                height=280,
                title=dict(text="Shares Outstanding — Annual Trend",
                           font=dict(size=13, color="#ccc")),
            )
            st.plotly_chart(fig_sh, use_container_width=True, key="stock_score_shares_chart")
            st.caption("Green bars = share count fell or held flat (buybacks/neutral). "
                       "Red bars = share count rose (dilution).")

# ── Bottom Line verdict ────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### ⚡ Bottom Line")

if total >= 75:
    verdict_title = "STRONG BUY CANDIDATE"
    verdict_color = "#2ecc71"
    verdict_body  = (
        f"{long_name} scores {total}/100 — clearing the bar for exceptional quality. "
        f"Wide moat fundamentals, strong financial health, and reasonable valuation "
        f"all align. Buffett would likely be interested. Conduct deeper qualitative "
        f"research on the durability of the competitive advantage before sizing a position."
    )
elif total >= 60:
    verdict_title = "WORTH DEEPER ANALYSIS"
    verdict_color = "#27ae60"
    verdict_body  = (
        f"{long_name} scores {total}/100. Strong across most dimensions with some "
        f"weaknesses. Review the failing checks above — are they structural or cyclical? "
        f"If the moat is intact and the failures are temporary, this may still be a "
        f"Buffett-grade business at the right price."
    )
elif total >= 45:
    verdict_title = "PROCEED WITH CAUTION"
    verdict_color = "#f1c40f"
    verdict_body  = (
        f"{long_name} scores {total}/100. Passes some key tests but shows meaningful "
        f"weaknesses. Focus on understanding the failing sections before committing capital. "
        f"Consider whether a lower entry price (higher margin of safety) would compensate "
        f"for the quality shortfalls."
    )
elif total >= 30:
    verdict_title = "SIGNIFICANT RED FLAGS"
    verdict_color = "#e67e22"
    verdict_body  = (
        f"{long_name} scores {total}/100. Multiple fundamental weaknesses present. "
        f"This stock does not meet Buffett's quality threshold as currently measured. "
        f"Review whether it belongs in a value vs. quality framework, or avoid until "
        f"fundamentals improve materially."
    )
else:
    verdict_title = "DOES NOT PASS SCREEN"
    verdict_color = "#e74c3c"
    verdict_body  = (
        f"{long_name} scores {total}/100 — failing across most Buffett criteria. "
        f"The combination of weak moat, questionable financial health, and poor "
        f"valuation context makes this a high-risk, low-conviction candidate. "
        f"Buffett's advice: 'It's far better to buy a wonderful company at a fair price "
        f"than a fair company at a wonderful price.'"
    )

st.markdown(
    f"""
    <div style="background:{_hex_rgba(verdict_color, 0.10)};
                border:2px solid {_hex_rgba(verdict_color, 0.65)};
                border-left:6px solid {verdict_color};
                border-radius:10px;padding:20px 24px;margin:8px 0 20px;">
      <div style="color:#888;font-size:0.7rem;font-weight:700;letter-spacing:.09em;
                  text-transform:uppercase;margin-bottom:8px;">
        Buffett Score Verdict — {long_name}
      </div>
      <div style="color:{verdict_color};font-size:1.55rem;font-weight:800;
                  margin-bottom:10px;line-height:1.1;">
        {verdict_title}
      </div>
      <div style="color:#e0e0e0;font-size:0.9rem;line-height:1.65;max-width:820px;">
        {verdict_body}
      </div>
      <div style="margin-top:12px;padding-top:10px;border-top:1px solid {_hex_rgba(verdict_color, 0.25)};
                  display:flex;gap:24px;font-size:0.75rem;color:#888;flex-wrap:wrap;">
        <span>Score <strong style="color:{verdict_color};">{total}/100</strong></span>
        <span>Moat <strong style="color:{_score_color(int(moat['score']/moat['max']*100))};">{moat['score']}/{moat['max']}</strong></span>
        <span>Fortress <strong style="color:{_score_color(int(fortress['score']/fortress['max']*100))};">{fortress['score']}/{fortress['max']}</strong></span>
        <span>Valuation <strong style="color:{_score_color(int(valuation['score']/valuation['max']*100))};">{valuation['score']}/{valuation['max']}</strong></span>
        <span>Momentum <strong style="color:{_score_color(int(momentum['score']/momentum['max']*100))};">{momentum['score']}/{momentum['max']}</strong></span>
        <span>Shareholder <strong style="color:{_score_color(int(shareholder['score']/shareholder['max']*100))};">{shareholder['score']}/{shareholder['max']}</strong></span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("---")
st.caption(DISCLAIMER)
