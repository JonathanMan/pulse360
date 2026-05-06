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
        _macro_adj_score, _macro_sens_cell, _macro_sensitivity, _macro_beta_cell,
        _owner_earnings_dcf,
        _sector_percentile, _percentile_badge, _is_special_sector,
        _SECTOR_GM_STD, _SECTOR_NM_STD, _SECTOR_ROE_MEDIAN, _SECTOR_ROE_STD,
        _MACRO_ADJ, _MACRO_DESCRIPTIONS, _REGIME_FOCUS,
        _REGIME_RATIONALE, _COMPLEXITY,
        _FALLBACK_SCORES, _SCREENER_UNIVERSE,
        _earnings_date_cached,
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
    "Pie360 is not a Registered Investment Advisor. "
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

# ── Macro Score Transparency — per-sector rationale strings ──────────────────
# Surfaced as tooltip text on the Macro Sens. cell in the Screener so investors
# understand *why* a sector score is adjusted, not just by how much.
_REGIME_RATIONALE: dict[str, dict[str, str]] = {
    "High Inflation": {
        "Energy":                "Commodity producers pass through price increases → revenue surge & margin expansion",
        "Basic Materials":       "Raw-material producers benefit directly from commodity price inflation",
        "Materials":             "Hard-asset businesses preserve margins via cost pass-through to customers",
        "Consumer Defensive":    "Essential-goods franchises with pricing power offset input cost inflation",
        "Consumer Staples":      "Essential-goods franchises with pricing power offset input cost inflation",
        "Real Estate":           "Rising cap rates compress REIT valuations; floating-rate debt squeezes margins",
        "Technology":            "Long-duration earnings repriced lower as real discount rates rise",
        "Consumer Cyclical":     "Discretionary spending contracts as consumers feel purchasing-power erosion",
        "Communication Services":"Ad budgets cut in inflationary slowdowns; subscription growth moderates",
        "Utilities":             "Regulated utilities cannot raise prices fast enough to match input cost inflation",
    },
    "Rising Rates": {
        "Financial Services":    "Widening net interest margins flow directly to fee income and EPS",
        "Banks":                 "Loan repricing boosts NIM; deposit funding remains sticky at lower rates",
        "Insurance":             "Fixed-income float income resets higher → significant investment yield uplift",
        "Utilities":             "Bond-proxy de-rates as sovereign yields offer risk-free competition for yield",
        "Real Estate":           "Financing costs rise and cap rates expand → property valuations compress",
        "Technology":            "Growth multiples contract as DCF discount rates rise across the board",
        "Consumer Defensive":    "Defensive premium narrows as higher yields offer safer yield alternatives",
        "Consumer Cyclical":     "Mortgage and consumer credit costs rise → discretionary spending cools",
    },
    "Recession Risk": {
        "Consumer Defensive":    "Inelastic demand for essentials → stable revenues and cash flows through downturns",
        "Consumer Staples":      "Strong brands sustain revenues when consumers cut discretionary spending",
        "Healthcare":            "Medical spending is non-discretionary → revenues hold even in contractions",
        "Utilities":             "Regulated, monopoly-like revenues provide recession-proof cash flow visibility",
        "Consumer Cyclical":     "Discretionary spending is the first casualty in recessions — volumes fall sharply",
        "Industrials":           "Capex cycles dry up; industrial order books crater quickly in downturns",
        "Energy":                "Demand destruction and commodity price collapse compound earnings pressure",
        "Financial Services":    "Credit losses surge; loan-loss provisions hammer net income",
        "Technology":            "Enterprise IT budgets cut and consumer hardware upgrades deferred in recessions",
    },
    "Recovery / Expansion": {
        "Consumer Cyclical":     "Pent-up demand releases and rising consumer confidence lifts discretionary spending",
        "Industrials":           "Capex restarts, supply chains rebuild — industrial order books fill fast",
        "Energy":                "Rising demand with restrained supply pushes commodity prices and margins higher",
        "Technology":            "Enterprise spending restarts and consumer upgrades accelerate in expansions",
        "Financial Services":    "Loan growth accelerates and credit quality improves as economy expands",
        "Consumer Defensive":    "Defensive premium erodes as capital rotates into higher-beta cyclicals",
        "Utilities":             "Low-beta utilities underperform as investors reach for higher-growth sectors",
        "Healthcare":            "Defensive premium compresses as risk appetite shifts to cyclical growth",
    },
}

# ── Fallback fundamental scores for key blue chips ───────────────────────────
# Used when yfinance is rate-limited so the screener stays complete.
_FALLBACK_SCORES: dict[str, dict] = {
    "KO":   {"Score":72,"Moat":30,"Fortress":18,"Valuation":12,"Momentum":7,"Shareholder":5,"Sector":"Consumer Defensive","Company":"Coca-Cola","FCF_Yield":3.8,"Fwd_PE":22.1,"Trend":"↑","TrendColor":"#00a35a","TrendTip":"Improving","Price":63.0,"Mkt Cap $B":272.0},
    "PEP":  {"Score":70,"Moat":29,"Fortress":17,"Valuation":12,"Momentum":7,"Shareholder":5,"Sector":"Consumer Defensive","Company":"PepsiCo","FCF_Yield":3.5,"Fwd_PE":20.8,"Trend":"↑","TrendColor":"#00a35a","TrendTip":"Improving","Price":168.0,"Mkt Cap $B":232.0},
    "JNJ":  {"Score":68,"Moat":28,"Fortress":19,"Valuation":11,"Momentum":6,"Shareholder":4,"Sector":"Healthcare","Company":"Johnson & Johnson","FCF_Yield":4.1,"Fwd_PE":15.2,"Trend":"→","TrendColor":"#c98800","TrendTip":"Mixed","Price":158.0,"Mkt Cap $B":381.0},
    "MSFT": {"Score":79,"Moat":35,"Fortress":21,"Valuation":12,"Momentum":8,"Shareholder":3,"Sector":"Technology","Company":"Microsoft","FCF_Yield":2.4,"Fwd_PE":31.5,"Trend":"↑","TrendColor":"#00a35a","TrendTip":"Improving","Price":415.0,"Mkt Cap $B":3090.0},
    "AAPL": {"Score":75,"Moat":33,"Fortress":20,"Valuation":12,"Momentum":7,"Shareholder":3,"Sector":"Technology","Company":"Apple","FCF_Yield":3.8,"Fwd_PE":28.2,"Trend":"↑","TrendColor":"#00a35a","TrendTip":"Improving","Price":210.0,"Mkt Cap $B":3200.0},
    "GOOGL":{"Score":76,"Moat":34,"Fortress":21,"Valuation":13,"Momentum":6,"Shareholder":2,"Sector":"Communication Services","Company":"Alphabet","FCF_Yield":4.2,"Fwd_PE":20.1,"Trend":"↑","TrendColor":"#00a35a","TrendTip":"Improving","Price":175.0,"Mkt Cap $B":2180.0},
    "V":    {"Score":78,"Moat":35,"Fortress":21,"Valuation":12,"Momentum":7,"Shareholder":3,"Sector":"Financial Services","Company":"Visa","FCF_Yield":2.9,"Fwd_PE":26.8,"Trend":"↑","TrendColor":"#00a35a","TrendTip":"Improving","Price":280.0,"Mkt Cap $B":573.0},
    "MA":   {"Score":77,"Moat":35,"Fortress":20,"Valuation":11,"Momentum":8,"Shareholder":3,"Sector":"Financial Services","Company":"Mastercard","FCF_Yield":2.5,"Fwd_PE":29.4,"Trend":"↑","TrendColor":"#00a35a","TrendTip":"Improving","Price":475.0,"Mkt Cap $B":444.0},
    "PG":   {"Score":71,"Moat":30,"Fortress":18,"Valuation":12,"Momentum":6,"Shareholder":5,"Sector":"Consumer Defensive","Company":"Procter & Gamble","FCF_Yield":3.6,"Fwd_PE":23.0,"Trend":"→","TrendColor":"#c98800","TrendTip":"Mixed","Price":170.0,"Mkt Cap $B":401.0},
    "ANSS": {"Score":62,"Moat":28,"Fortress":17,"Valuation":10,"Momentum":5,"Shareholder":2,"Sector":"Technology","Company":"Ansys","FCF_Yield":2.1,"Fwd_PE":38.0,"Trend":"→","TrendColor":"#c98800","TrendTip":"Mixed","Price":340.0,"Mkt Cap $B":29.0},
    "MCD":  {"Score":69,"Moat":29,"Fortress":15,"Valuation":13,"Momentum":7,"Shareholder":5,"Sector":"Consumer Cyclical","Company":"McDonald's","FCF_Yield":3.9,"Fwd_PE":22.5,"Trend":"↑","TrendColor":"#00a35a","TrendTip":"Improving","Price":297.0,"Mkt Cap $B":213.0},
    "TMO":  {"Score":67,"Moat":28,"Fortress":18,"Valuation":11,"Momentum":6,"Shareholder":4,"Sector":"Healthcare","Company":"Thermo Fisher","FCF_Yield":3.1,"Fwd_PE":24.0,"Trend":"→","TrendColor":"#c98800","TrendTip":"Mixed","Price":510.0,"Mkt Cap $B":196.0},
    "HON":  {"Score":64,"Moat":26,"Fortress":17,"Valuation":12,"Momentum":6,"Shareholder":3,"Sector":"Industrials","Company":"Honeywell","FCF_Yield":4.2,"Fwd_PE":19.5,"Trend":"→","TrendColor":"#c98800","TrendTip":"Mixed","Price":218.0,"Mkt Cap $B":134.0},
    "XOM":  {"Score":60,"Moat":22,"Fortress":17,"Valuation":13,"Momentum":5,"Shareholder":3,"Sector":"Energy","Company":"ExxonMobil","FCF_Yield":5.8,"Fwd_PE":13.2,"Trend":"↓","TrendColor":"#d92626","TrendTip":"Deteriorating","Price":108.0,"Mkt Cap $B":462.0},
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

# ── Circle of Competence — complexity tiers ───────────────────────────────────
# Rates each screener ticker by how much domain knowledge is needed to analyse
# it reliably.  Three tiers:
#   "straightforward" — simple, predictable business model; ideal for all profiles
#   "moderate"        — understandable with research; suits most investors
#   "specialist"      — complex balance sheet, leverage, derivatives, or opaque
#                       revenue mix; warrants extra caution for beginners
#
# Shown as a pill badge in the Screener ticker cell and as a banner on the
# Buffett Score page (warning-level callout for Beginner profiles on specialist
# companies; informational for Analyst/Pro).
_COMPLEXITY: dict[str, str] = {
    # ── Straightforward ──────────────────────────────────────────────────────
    "KO":    "straightforward",   # Sell branded beverages, collect royalties
    "PEP":   "straightforward",   # Beverages + snacks; predictable cash flows
    "PG":    "straightforward",   # Consumer staples brand portfolio
    "CL":    "straightforward",   # Toothpaste + household products
    "KMB":   "straightforward",   # Tissue & personal care essentials
    "MKC":   "straightforward",   # Spices & seasoning; niche pricing-power moat
    "GIS":   "straightforward",   # Packaged food brands
    "HSY":   "straightforward",   # Chocolate brand with durable pricing power
    "SJM":   "straightforward",   # Jams, pet food — simple branded goods
    "CHD":   "straightforward",   # Arm & Hammer; steady CPG franchise
    "MCD":   "straightforward",   # Franchise model; real estate + royalties
    "SBUX":  "straightforward",   # Retail coffee with global brand loyalty
    "NKE":   "straightforward",   # Branded athletic wear; asset-light model
    "YUM":   "straightforward",   # Franchise operator (KFC, Taco Bell, Pizza Hut)
    "DPZ":   "straightforward",   # Pizza franchise with digital ordering moat
    "V":     "straightforward",   # Pure payment rail; zero credit risk on its own books
    "MA":    "straightforward",   # Same payment-rail model as Visa
    "ECL":   "straightforward",   # Water treatment & hygiene chemicals
    "SHW":   "straightforward",   # Paint & coatings; simple pricing model
    "APD":   "straightforward",   # Industrial gas with long-term supply contracts
    "OXY":   "straightforward",   # E&P with clear asset base (simpler than integrated)
    # ── Moderate ────────────────────────────────────────────────────────────
    "AAPL":  "moderate",          # Hardware + services ecosystem; supply chain complexity
    "MSFT":  "moderate",          # Cloud + enterprise software; multi-segment P&L
    "GOOGL": "moderate",          # Ad + cloud + moonshots; conglomerate risk
    "META":  "moderate",          # Ad platform + heavy metaverse capex overhang
    "NVDA":  "moderate",          # Semiconductor cycles + AI platform transition
    "AVGO":  "moderate",          # Chip + software (VMware); M&A integration risk
    "TXN":   "moderate",          # Analog chips; cyclical but asset-heavy fab model
    "QCOM":  "moderate",          # Chipmaker + licensing; royalty-dispute history
    "ORCL":  "moderate",          # Legacy DB + cloud transition; complex licensing tiers
    "IBM":   "moderate",          # IT services + consulting; multi-decade transformation
    "CRM":   "moderate",          # SaaS with aggressive M&A (Slack, Tableau)
    "ADBE":  "moderate",          # Creative cloud with AI disruption risk to model
    "NOW":   "moderate",          # Enterprise workflow SaaS; high growth but rich valuation
    "INTU":  "moderate",          # Tax + SMB finance software ecosystem
    "ANSS":  "moderate",          # Simulation software; niche but deep technical moat
    "JNJ":   "moderate",          # Pharma + MedTech (post-Kenvue spin)
    "ABT":   "moderate",          # Diagnostics + devices + nutrition segments
    "MDT":   "moderate",          # Large-cap medical devices; reimbursement complexity
    "TMO":   "moderate",          # Life science tools + CRO services mix
    "DHR":   "moderate",          # Industrial sciences conglomerate via M&A rollup
    "EW":    "moderate",          # Heart valve specialist; regulatory + clinical risk
    "SYK":   "moderate",          # Orthopaedic & surgical devices
    "BDX":   "moderate",          # Medical supplies + diagnostics
    "ISRG":  "moderate",          # Robotic surgery; capital equipment + consumables model
    "ZBH":   "moderate",          # Orthopaedic implants; hospital budget sensitivity
    "TJX":   "moderate",          # Off-price retail; opportunistic inventory model
    "ROST":  "moderate",          # Similar to TJX; off-price buying model
    "HON":   "moderate",          # Diversified industrial + aerospace conglomerate
    "MMM":   "moderate",          # Science conglomerate + significant legal liability overhang
    "CAT":   "moderate",          # Heavy equipment; mining + construction cycle exposure
    "DE":    "moderate",          # Agricultural & construction equipment cycles
    "EMR":   "moderate",          # Process automation; B2B industrial
    "ITW":   "moderate",          # 80/20 simplification model; diversified industrial
    "GWW":   "moderate",          # Industrial distribution; thin-margin but reliable
    "FAST":  "moderate",          # Industrial fasteners distribution
    "XOM":   "moderate",          # Integrated oil; refining + chemicals + E&P
    "CVX":   "moderate",          # Integrated oil; complex asset base
    "PSX":   "moderate",          # Refining + chemicals + midstream
    "DIS":   "moderate",          # Media + parks + streaming; high capex + restructuring
    "NFLX":  "moderate",          # Streaming with significant content cost complexity
    "CMCSA": "moderate",          # Cable + NBCUniversal + streaming
    "PLD":   "moderate",          # Industrial REIT; real estate valuation model needed
    "AMT":   "moderate",          # Cell tower REIT; long-term lease structure analysis
    "USB":   "moderate",          # Regional bank; simpler than money-center SIFIs
    # ── Specialist ──────────────────────────────────────────────────────────
    "BRK-B": "specialist",        # Conglomerate of 60+ businesses + insurance float; requires deep reading
    "JPM":   "specialist",        # SIFI bank; trading book, derivatives, Basel III capital
    "BAC":   "specialist",        # Complex SIFI with legacy mortgage exposure + derivatives desk
    "WFC":   "specialist",        # SIFI bank post-scandal; regulatory asset cap adds complexity
    "AXP":   "specialist",        # Credit card issuer that takes credit risk — unlike V/MA
    "BLK":   "specialist",        # Asset management; AUM sensitivity + fee compression + product mix
    "MS":    "specialist",        # Investment bank + wealth management; trading VAR exposure
    "GS":    "specialist",        # Bulge-bracket investment bank; principal trading + complex revenue streams
    "ALLY":  "specialist",        # Auto finance bank; consumer credit + asset-liability management
}


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
    if "Top 5"    in label: bg, fg = "#0d2b1d", "#00a35a"
    elif "Top 15" in label: bg, fg = "#0d2b1d", "#27ae60"
    elif "Top 30" in label: bg, fg = "#1a2b0d", "#a8d08d"
    elif "Above"  in label: bg, fg = "#1a2000", "#c8e06e"
    elif "Median" in label: bg, fg = "#1e1e1e", "#888888"
    elif "Below"  in label: bg, fg = "#2b1a0d", "#e67e22"
    elif "Bottom 30" in label: bg, fg = "#2b0d0d", "#d92626"
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


def _macro_sensitivity(base_score: int, sector: str | None) -> dict:
    """
    Compute Buffett score under every macro regime for a given base score + sector.
    Returns a dict with:
      range      — max_adj_score − min_adj_score (how sensitive this stock is to regime shifts)
      best       — regime that gives the highest score
      worst      — regime that gives the lowest score
      best_score — score in best regime
      worst_score— score in worst regime
      scores     — {regime: adjusted_score} for all regimes
    """
    scores = {r: _macro_adj_score(base_score, sector, r) for r in _MACRO_ADJ}
    best   = max(scores, key=scores.get)
    worst  = min(scores, key=scores.get)
    return {
        "range":       scores[best] - scores[worst],
        "best":        best,
        "worst":       worst,
        "best_score":  scores[best],
        "worst_score": scores[worst],
        "scores":      scores,
    }


def _macro_beta_cell(macro_range: int) -> str:
    """Return coloured HTML for the Macro Beta (sensitivity range) cell."""
    if macro_range <= 0:
        return '<span style="color:#444;">—</span>'
    if macro_range <= 8:
        color, label = "#00a35a", "stable"
    elif macro_range <= 14:
        color, label = "#c98800", "moderate"
    else:
        color, label = "#d92626", "high"
    return (
        f'<span style="color:{color};font-weight:700;">{macro_range}</span>'
        f'<span style="color:#555;font-size:0.65rem;margin-left:3px;">{label}</span>'
    )


def _macro_sens_cell(sector: str, regime: str) -> str:
    """Return coloured HTML showing this sector's macro sensitivity.

    The tooltip (title attribute) explains *why* the adjustment is applied,
    pulled from _REGIME_RATIONALE.  Investors can hover to understand the
    economic logic behind any score change.
    """
    if regime == "Normal":
        return '<span style="color:#444;">—</span>'
    adj = _MACRO_ADJ.get(regime, {}).get(sector, 0)
    # Look up rationale; fall back gracefully if sector isn't mapped
    rationale = _REGIME_RATIONALE.get(regime, {}).get(sector, "")
    title_attr = f' title="{rationale}"' if rationale else ""
    if adj == 0:
        neutral = "No adjustment for this sector in the current regime"
        return f'<span style="color:#555;" title="{neutral}">0</span>'
    color = "#00a35a" if adj > 0 else "#d92626"
    sign  = "+" if adj > 0 else ""
    return (
        f'<span style="color:{color};font-weight:700;cursor:help;"{title_attr}>'
        f'{sign}{adj}</span>'
    )


# ── Score colour helpers ───────────────────────────────────────────────────────

def _score_color_sub(value: int, max_value: int) -> str:
    """
    Colour for a sub-section score relative to its maximum.
    Used in screener table cells (Moat, Fortress, Valuation, Momentum).
    """
    if max_value == 0:
        return "#888"
    pct = value / max_value
    if pct >= 0.75: return "#00a35a"
    if pct >= 0.50: return "#c98800"
    return "#d92626"


def _score_color(score: int) -> str:
    """
    Colour for a total 0–100 Buffett score.
    Used in score cards and macro-adjusted screener totals.
    """
    if score >= 75: return "#00a35a"
    if score >= 60: return "#27ae60"
    if score >= 45: return "#f1c40f"
    if score >= 30: return "#e67e22"
    return "#d92626"


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
        return "↑", "#00a35a", tip

    if pct_vs_200 < -0.03:
        tip = f"Technical downtrend: {pct_vs_200:+.1%} below 200MA"
        return "↓", "#d92626", tip

    # Within ±3% band — consolidating
    if ma50:
        pct_vs_50 = (cur - ma50) / ma50
        tip = f"Consolidating: {pct_vs_200:+.1%} vs 200MA · {pct_vs_50:+.1%} vs 50MA"
    else:
        tip = f"Near 200MA: {pct_vs_200:+.1%}"
    return "→", "#c98800", tip


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
        return "↑", "#00a35a", f"Improving: {improving}/{total} metrics up YoY"
    if ratio <= 0.33:
        return "↓", "#d92626", f"Deteriorating: {improving}/{total} metrics up YoY"
    return "→", "#c98800", f"Mixed: {improving}/{total} metrics up YoY"


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


# ══════════════════════════════════════════════════════════════════════════════
# Disk-based score cache
# ══════════════════════════════════════════════════════════════════════════════
"""
Cache-first scoring layer.

When a live yfinance fetch succeeds, the flat scores dict is persisted to a
JSON file in .ticker_cache/.  On subsequent failures (rate-limits, outages)
the cached scores are returned with _stale=True and _cached_at set to the
write timestamp, so the UI can display "data as of <date>" instead of an error.

Cache location: <app_root>/.ticker_cache/<TICKER>.json
  The app root is derived from this file's own path so it works both locally
  and on Streamlit Cloud.
"""

import json
import os
from datetime import datetime, timezone

# Resolve cache dir relative to this file so it works anywhere
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".ticker_cache")


def _cache_path(ticker: str) -> str:
    return os.path.join(_CACHE_DIR, f"{ticker.upper()}.json")


def _cache_write(ticker: str, scored: dict) -> None:
    """
    Persist a scored-ticker dict to disk.
    Only serialisable scalar fields are kept (drops DataFrames, nested sections).
    Silently swallows errors — a cache miss is never fatal.
    """
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        payload = {
            k: v for k, v in scored.items()
            if isinstance(v, (str, int, float, bool, type(None)))
        }
        payload["_cached_at"] = datetime.now(timezone.utc).isoformat()
        payload["_stale"]     = False
        with open(_cache_path(ticker), "w") as fh:
            json.dump(payload, fh)
    except Exception:
        pass


def _cache_read(ticker: str) -> dict | None:
    """
    Read a cached scored-ticker dict.
    Returns the dict with _stale=True and a human-readable _cached_at string,
    or None if no cache file exists.
    """
    try:
        path = _cache_path(ticker)
        if not os.path.exists(path):
            return None
        with open(path) as fh:
            data = json.load(fh)
        # Parse timestamp → friendly label, e.g. "May 1"
        raw_ts = data.get("_cached_at", "")
        try:
            dt = datetime.fromisoformat(raw_ts).astimezone()
            data["_cached_at"] = dt.strftime("%-d %b")   # "1 May"
        except Exception:
            data["_cached_at"] = "recent"
        data["_stale"] = True
        return data
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def score_ticker_cached(ticker: str) -> dict:
    """
    Score a ticker with automatic cache-first fallback.

    Priority:
      1. Live yfinance fetch + _compute_score  →  _stale=False, writes disk cache
      2. Disk cache (any age)                  →  _stale=True,  _cached_at="1 May"
      3. _FALLBACK_SCORES static dict          →  _stale=True,  _cached_at="built-in"
      4. Empty dict {}                         →  caller should treat as failure

    The returned dict always contains at minimum:
        Ticker, Company, Sector, Score (=total), Moat, Fortress, Valuation,
        Momentum, Price, FCF_Yield, Fwd_PE, Trend, TrendColor, TrendTip,
        ShareChg, _stale, _cached_at
    """
    ticker = ticker.upper().strip()

    # ── 1. Try live fetch ──────────────────────────────────────────────────────
    data = fetch_stock_data(ticker)
    if data and not data.get("error") and data.get("info"):
        try:
            scores   = _compute_score(data)
            info     = data["info"]
            total    = scores["total"]
            secs     = scores["sections"]
            trend, t_color, t_tip = _price_trend(data)

            sh_chg_val = None
            for sec in secs.values():
                if "sh_chg" in sec:
                    sh_chg_val = sec["sh_chg"]
                    break

            result = {
                "Ticker":    ticker,
                "Company":   info.get("shortName") or info.get("longName") or ticker,
                "Sector":    info.get("sector") or info.get("sectorDisp") or "Unknown",
                "Score":     total,
                "Moat":      secs.get("moat",        {}).get("score", 0),
                "Fortress":  secs.get("fortress",    {}).get("score", 0),
                "Valuation": secs.get("valuation",   {}).get("score", 0),
                "Momentum":  secs.get("momentum",    {}).get("score", 0),
                "Price":     _sf(info.get("currentPrice") or info.get("regularMarketPrice")),
                "FCF_Yield": data.get("fcf_yield"),
                "Fwd_PE":    _sf(info.get("forwardPE")),
                "Trend":     trend,
                "TrendColor": t_color,
                "TrendTip":  t_tip,
                "ShareChg":  sh_chg_val,
                "_stale":    False,
                "_cached_at": None,
            }
            _cache_write(ticker, result)
            return result
        except Exception:
            pass  # fall through to cache

    # ── 2. Disk cache ──────────────────────────────────────────────────────────
    cached = _cache_read(ticker)
    if cached:
        return cached

    # ── 3. Static fallback ────────────────────────────────────────────────────
    fb = _FALLBACK_SCORES.get(ticker)
    if fb:
        result = fb.copy()
        result.setdefault("_stale",     True)
        result.setdefault("_cached_at", "built-in")
        return result

    # ── 4. Total failure ──────────────────────────────────────────────────────
    return {}


# ── Earnings Calendar ─────────────────────────────────────────────────────────

@st.cache_data(ttl=21_600)   # cache 6 hours — dates rarely change intraday
def _earnings_date_cached(ticker: str) -> str | None:
    """Return the next earnings date as 'YYYY-MM-DD', or None if unavailable.

    Tries yfinance .calendar dict first (yfinance >= 0.2.x), then falls back
    to .info['earningsDate'] (UNIX timestamp list).
    """
    from datetime import datetime, timezone

    t = yf.Ticker(ticker.upper().strip())

    # ── Strategy 1: .calendar dict (yfinance >= 0.2.x) ───────────────────────
    try:
        cal = t.calendar
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date") or cal.get("earningsDate") or []
            if dates:
                d = dates[0]
                if hasattr(d, "date"):           # pandas Timestamp / datetime
                    return d.date().isoformat()
                return str(d)[:10]
        elif hasattr(cal, "columns"):            # old DataFrame-style response
            cols = list(cal.columns)
            if cols:
                return str(cols[0])[:10]
    except Exception:
        pass

    # ── Strategy 2: .info earningsDate / earningsTimestamp ────────────────────
    try:
        info = t.info
        raw = info.get("earningsDate") or info.get("earningsTimestamp")
        if raw:
            ts = raw[0] if isinstance(raw, list) else raw
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            return str(ts)[:10]
    except Exception:
        pass

    return None
