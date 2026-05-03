"""
Pulse360 — Historical Phase Returns Engine
============================================
Computes asset-class return statistics (annualised return, win rate, volatility)
broken down by economic cycle phase.

Phase labels are derived from the backtest probability model + NBER dates:
  • Contraction — NBER recession active
  • Recovery    — first 6 months after recession end
  • Late Cycle  — prob ≥ 25%, not contraction/recovery
  • Expansion   — prob < 25%, not contraction/recovery

Asset classes (all FRED total-return series):
  • US Equities  — SP500 (S&P 500, 1950–)
  • Bonds (IG)   — BAMLCC0A0CMTRIV (ICE BofA IG Corp total return, 1996–)
  • High-Yield   — BAMLHYH0A0HYM2TRIV (HY corp total return, 1996–)
  • Oil          — DCOILWTICO (WTI crude spot, 1986–)

Caveat: phase labels are derived from the same model used to define the analysis
window, so this is an in-sample calibration check, not out-of-sample validation.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from data.fred_client import fetch_series

logger = logging.getLogger(__name__)

ASSET_CLASSES = {
    "US Equities":  "SP500",
    "Bonds (IG)":   "BAMLCC0A0CMTRIV",
    "High-Yield":   "BAMLHYH0A0HYM2TRIV",
    "Oil (WTI)":    "DCOILWTICO",
}

PHASES = ["Expansion", "Late Cycle", "Contraction", "Recovery"]

PHASE_COLORS = {
    "Expansion":  "#2ecc71",
    "Late Cycle": "#f39c12",
    "Contraction":"#e74c3c",
    "Recovery":   "#3498db",
}


# ---------------------------------------------------------------------------
# Phase labelling
# ---------------------------------------------------------------------------

def label_phases(
    backtest_df: pd.DataFrame,
    usrec_series: pd.Series,
    recovery_window: int = 6,
) -> pd.Series:
    """
    Assign a cycle phase to every month in backtest_df.

    Priority order (first match wins):
      1. Contraction — NBER marks the month as recession
      2. Recovery    — within `recovery_window` months of recession end
      3. Late Cycle  — model probability ≥ 25%
      4. Expansion   — model probability < 25%

    Args:
        backtest_df:      output of run_historical_backtest()
        usrec_series:     USREC monthly series from FRED
        recovery_window:  months after recession end to label as Recovery

    Returns:
        pd.Series indexed like backtest_df with string phase labels.
    """
    usrec = usrec_series.resample("MS").last().dropna()

    # Identify the first non-recession month after each recession (rec_end)
    rec_ends: list[pd.Timestamp] = []
    prev_val = 0
    for ts, val in usrec.items():
        if int(val) == 0 and prev_val == 1:
            rec_ends.append(ts)
        prev_val = int(val)

    # Build the recovery window set (normalised to month-start)
    recovery_set: set[pd.Timestamp] = set()
    for end in rec_ends:
        for i in range(recovery_window):
            recovery_set.add(end + pd.DateOffset(months=i))
    recovery_set = {pd.Timestamp(ts.year, ts.month, 1) for ts in recovery_set}

    prob = backtest_df["probability"]
    labels: dict[pd.Timestamp, str] = {}

    for ts in prob.index:
        ts_norm = pd.Timestamp(ts.year, ts.month, 1)
        nber_val = int(usrec.get(ts_norm, 0))
        p = float(prob[ts])

        if nber_val == 1:
            labels[ts] = "Contraction"
        elif ts_norm in recovery_set:
            labels[ts] = "Recovery"
        elif p >= 25:
            labels[ts] = "Late Cycle"
        else:
            labels[ts] = "Expansion"

    return pd.Series(labels, name="phase")


# ---------------------------------------------------------------------------
# Asset return helpers
# ---------------------------------------------------------------------------

def _monthly_returns(series: pd.Series) -> pd.Series:
    """Convert a price/index series to monthly simple returns."""
    monthly = series.resample("MS").last().dropna()
    return monthly.pct_change().dropna()


def _phase_stats(returns: pd.Series, phase_label: str, phase_series: pd.Series) -> dict:
    """
    Compute statistics for `returns` during months labelled `phase_label`.

    Returns dict with: ann_return, win_rate, ann_vol, n_months, best_month, worst_month.
    """
    mask = phase_series == phase_label
    aligned = returns[returns.index.isin(phase_series[mask].index)].dropna()

    if len(aligned) < 3:
        return {
            "ann_return":  None,
            "win_rate":    None,
            "ann_vol":     None,
            "n_months":    len(aligned),
            "best_month":  None,
            "worst_month": None,
        }

    mean_monthly = aligned.mean()
    ann_return   = ((1 + mean_monthly) ** 12 - 1) * 100
    win_rate     = (aligned > 0).mean() * 100
    ann_vol      = aligned.std() * np.sqrt(12) * 100

    return {
        "ann_return":  round(ann_return, 1),
        "win_rate":    round(win_rate, 1),
        "ann_vol":     round(ann_vol, 1),
        "n_months":    len(aligned),
        "best_month":  round(aligned.max() * 100, 1),
        "worst_month": round(aligned.min() * 100, 1),
    }


# ---------------------------------------------------------------------------
# Main computation entry point
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)   # cache 24 hours
def compute_phase_returns(
    backtest_prob_json: str,     # JSON string of backtest_df["probability"] for cache key
    phase_labels_json:  str,     # JSON string of phase_series for cache key
    start_date: str = "1997-01-01",
) -> dict:
    """
    Fetch asset class data and compute return statistics by cycle phase.

    Args:
        backtest_prob_json: JSON of probability series (used only for cache keying)
        phase_labels_json:  JSON of phase labels series (used only for cache keying)
        start_date:         Backtest start date

    Returns:
        {
          "asset_returns":  dict[asset_name -> pd.Series of monthly returns],
          "phase_stats":    dict[asset_name -> dict[phase -> stats_dict]],
          "returns_table":  pd.DataFrame (phases as index, assets as columns, ann_return values),
          "winrate_table":  pd.DataFrame (same shape, win rate values),
          "vol_table":      pd.DataFrame (same shape, volatility values),
          "coverage":       dict[asset_name -> {"start": str, "n_months": int}],
        }
    """
    # Re-deserialise phase labels from JSON.
    # Use json.loads + pd.Series to avoid pd.read_json treating the string as
    # a file path in newer pandas versions (FileNotFoundError on Streamlit Cloud).
    _raw = json.loads(phase_labels_json)
    phase_series = pd.Series(_raw)
    phase_series.index = pd.to_datetime(phase_series.index)  # handles ISO strings

    long_start = "1990-01-01"
    asset_returns: dict[str, pd.Series] = {}
    coverage:      dict[str, dict]      = {}

    for asset_name, series_id in ASSET_CLASSES.items():
        result = fetch_series(series_id, start_date=long_start)
        if result["error"] or result["data"].empty:
            logger.warning("phase_returns: fetch failed for %s (%s)", asset_name, result.get("error"))
            continue
        rets = _monthly_returns(result["data"])
        rets = rets[rets.index >= pd.Timestamp(start_date)]
        if rets.empty:
            continue
        asset_returns[asset_name] = rets
        coverage[asset_name] = {
            "start":    rets.index[0].strftime("%b %Y"),
            "n_months": len(rets),
        }

    if not asset_returns:
        return {}

    # Compute stats per asset per phase
    phase_stats: dict[str, dict[str, dict]] = {}
    for asset_name, rets in asset_returns.items():
        phase_stats[asset_name] = {
            phase: _phase_stats(rets, phase, phase_series)
            for phase in PHASES
        }

    # Build summary tables
    def _table(metric: str) -> pd.DataFrame:
        data = {
            asset: {phase: (phase_stats[asset][phase][metric]) for phase in PHASES}
            for asset in asset_returns
        }
        return pd.DataFrame(data, index=PHASES)

    return {
        "asset_returns": asset_returns,
        "phase_stats":   phase_stats,
        "returns_table": _table("ann_return"),
        "winrate_table": _table("win_rate"),
        "vol_table":     _table("ann_vol"),
        "coverage":      coverage,
    }
