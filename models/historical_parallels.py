"""
Pulse360 — Historical Parallels Engine
========================================
Finds the 3 historical months (1997-present) whose macro stress profile most
closely resembles the current environment, then reports the forward asset-class
returns that actually followed each parallel.

Algorithm
---------
1.  Load the pre-computed backtest DataFrame (cached 24h via run_historical_backtest).
2.  Extract the 6 stress columns — one per recession-model feature.
3.  Build a current feature vector from RecessionModelOutput.features.
4.  Compute Euclidean distance between the current vector and every historical
    month.  Optionally weight by feature model-weights.
5.  Return top-N closest months (default 3) with their forward returns.

Forward returns (6M and 12M)
----------------------------
Fetched from FRED at monthly frequency for five asset classes:
    SP500           → S&P 500 Index (price return)
    BAMLCC0A0CMTRIV → US Investment-Grade Corps total return index
    BAMLHYH0A0HYM2TRIV → US High-Yield total return index
    GOLDAMGBD228NLBM   → Gold (London PM fix, USD/troy oz)
    DCOILWTICO         → WTI Crude Oil (USD/bbl)

All are resampled to month-end before return calculation.

Public API
----------
    find_historical_parallels(model_output, n=3) → list[ParallelResult]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from data.fred_client import fetch_series
from models.backtest import run_historical_backtest
from models.recession_model import RecessionModelOutput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapping: series_id → backtest stress column name
# Mirrors the naming logic in backtest.py:
#   col = "stress_" + name.lower().replace(" ","_").replace("–","")
#                                 .replace("(","").replace(")","")
# ---------------------------------------------------------------------------

_SERIES_TO_STRESS_COL: dict[str, str] = {
    "T10Y3M":       "stress_10y3m_treasury_spread",
    "SAHMREALTIME": "stress_sahm_rule",
    "CFNAI":        "stress_cfnai_activity_index",
    "NFCI":         "stress_chicago_fed_nfci",
    "ICSA":         "stress_initial_claims_yoy",
    "BAMLH0A0HYM2": "stress_high-yield_oas",
}

# Feature weights (mirror recession_model._FEATURES)
_WEIGHTS: dict[str, float] = {
    "T10Y3M":       0.30,
    "SAHMREALTIME": 0.20,
    "CFNAI":        0.20,
    "NFCI":         0.10,
    "ICSA":         0.10,
    "BAMLH0A0HYM2": 0.10,
}

# ---------------------------------------------------------------------------
# Asset-class forward-return series
# ---------------------------------------------------------------------------

_ASSET_SERIES: dict[str, str] = {
    "S&P 500":    "SP500",
    "IG Bonds":   "BAMLCC0A0CMTRIV",
    "HY Credit":  "BAMLHYH0A0HYM2TRIV",
    "Gold":       "GOLDAMGBD228NLBM",
    "WTI Oil":    "DCOILWTICO",
}

_ASSET_EMOJI: dict[str, str] = {
    "S&P 500":   "📈",
    "IG Bonds":  "🏦",
    "HY Credit": "⚡",
    "Gold":      "🥇",
    "WTI Oil":   "🛢️",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ForwardReturn:
    asset:      str
    emoji:      str
    ret_6m:     Optional[float]   # percentage, e.g. 12.4 means +12.4%
    ret_12m:    Optional[float]


@dataclass
class ParallelResult:
    rank:              int           # 1 = closest
    date:              pd.Timestamp
    distance:          float         # weighted Euclidean distance (0 = identical)
    similarity_pct:    float         # 100 − distance*100 capped 0-100
    recession_prob:    float         # model probability at that date
    traffic_light:     str
    feature_vector:    dict[str, float]   # series_id → stress_score
    forward_returns:   list[ForwardReturn] = field(default_factory=list)
    outcome_note:      str = ""      # "Recession followed", "Soft landing", etc.


# ---------------------------------------------------------------------------
# Caching helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86_400, show_spinner=False)
def _load_asset_prices() -> dict[str, pd.Series]:
    """
    Fetch all five asset-class series from FRED and resample to month-end.
    Returns dict: asset_label → monthly price Series with DatetimeIndex.
    Cached 24h.
    """
    out: dict[str, pd.Series] = {}
    for label, sid in _ASSET_SERIES.items():
        try:
            result = fetch_series(sid, start_date="1996-01-01")
            raw = result.get("data")
            if raw is None or raw.empty:
                continue
            raw = raw.dropna()
            raw.index = pd.DatetimeIndex(raw.index)
            monthly = raw.resample("ME").last().dropna()
            out[label] = monthly.astype(float)
        except Exception as exc:
            logger.warning("historical_parallels: could not fetch %s (%s): %s", sid, label, exc)
    return out


def _forward_return(
    series: pd.Series,
    match_date: pd.Timestamp,
    months: int,
) -> Optional[float]:
    """
    Return the percentage price change from match_date forward `months` months.
    Returns None if insufficient data.
    """
    try:
        available = series[series.index >= match_date]
        if available.empty:
            return None
        start_price = float(available.iloc[0])
        if start_price == 0:
            return None
        # Find the value closest to (match_date + months)
        target = match_date + pd.DateOffset(months=months)
        future = series[series.index >= target]
        if future.empty:
            return None
        end_price = float(future.iloc[0])
        return round((end_price / start_price - 1) * 100, 1)
    except Exception:
        return None


def _outcome_note(
    bt: pd.DataFrame,
    match_date: pd.Timestamp,
    lookahead_months: int = 12,
) -> str:
    """
    Describe what actually happened after the match date using the backtest
    probability trajectory and the USREC series (if available in bt).
    """
    try:
        future = bt[bt.index > match_date].head(lookahead_months)
        if future.empty:
            return ""
        max_prob = future["probability"].max()
        if "usrec" in bt.columns:
            rec_months = (future["usrec"] == 1).sum() if "usrec" in future.columns else 0
            if rec_months >= 2:
                return "⚠️ Recession followed within 12 months"
        if max_prob >= 60:
            return "⚠️ Recession probability surged (≥60%) within 12 months"
        if max_prob >= 40:
            return "⚡ Elevated risk period followed — no official recession"
        return "✅ Soft landing — recession probability stayed contained"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def find_historical_parallels(
    model_output: RecessionModelOutput,
    n: int = 3,
    weighted: bool = True,
) -> list[ParallelResult]:
    """
    Find the N closest historical months to the current macro stress profile.

    Parameters
    ----------
    model_output : RecessionModelOutput
        The current model output (contains per-feature stress_scores).
    n : int
        Number of top matches to return (default 3).
    weighted : bool
        If True, weight each feature dimension by its model weight before
        computing distance (rewards accuracy on higher-weight features).

    Returns
    -------
    list[ParallelResult], sorted closest-first.  Empty list on failure.
    """
    # ── 1. Load backtest ───────────────────────────────────────────────────
    try:
        bt = run_historical_backtest()
    except Exception as exc:
        logger.error("historical_parallels: backtest load failed: %s", exc)
        return []

    if bt.empty:
        return []

    # ── 2. Identify usable stress columns ─────────────────────────────────
    col_order: list[str] = []    # backtest column names
    sid_order: list[str] = []    # corresponding series_ids
    weights:   list[float] = []  # model weights for those features

    for sid, col in _SERIES_TO_STRESS_COL.items():
        if col in bt.columns:
            col_order.append(col)
            sid_order.append(sid)
            weights.append(_WEIGHTS.get(sid, 1.0 / len(_SERIES_TO_STRESS_COL)))

    if not col_order:
        logger.error("historical_parallels: no stress columns found in backtest")
        return []

    weights_arr = np.array(weights)
    if weighted:
        weights_arr = weights_arr / weights_arr.sum()  # normalise
    else:
        weights_arr = np.ones(len(col_order)) / len(col_order)

    # ── 3. Build current feature vector ───────────────────────────────────
    feat_map = {f.series_id: f.stress_score for f in model_output.features}
    current_vec = np.array([feat_map.get(sid, 0.5) for sid in sid_order])

    # ── 4. Build historical matrix and compute distances ──────────────────
    hist_matrix = bt[col_order].dropna().values   # shape (T, D)
    hist_dates  = bt[col_order].dropna().index

    # Weighted Euclidean distance
    diff    = hist_matrix - current_vec           # (T, D)
    w_diff  = diff * weights_arr                  # broadcast weights
    dists   = np.sqrt((w_diff ** 2).sum(axis=1))  # (T,)

    # Exclude the most recent 12 months to avoid self-matching
    today = pd.Timestamp.now(tz="UTC").tz_localize(None)
    cutoff = today - pd.DateOffset(months=12)
    mask = hist_dates < cutoff
    if mask.sum() < n:
        mask = np.ones(len(hist_dates), dtype=bool)  # fallback: include all

    masked_dists = np.where(mask, dists, np.inf)
    top_idx      = np.argsort(masked_dists)[:n]

    # ── 5. Load asset prices for forward returns ───────────────────────────
    asset_prices = _load_asset_prices()

    # ── 6. Build ParallelResult for each match ─────────────────────────────
    results: list[ParallelResult] = []
    for rank, idx in enumerate(top_idx, start=1):
        match_date = hist_dates[idx]
        dist       = float(dists[idx])
        sim_pct    = max(0.0, round(100 - dist * 100, 1))

        row = bt.loc[match_date]

        fvec = {sid: round(float(row.get(col, 0.5)), 3)
                for sid, col in zip(sid_order, col_order)}

        # Forward returns
        fwd_returns: list[ForwardReturn] = []
        for label, series in asset_prices.items():
            fr = ForwardReturn(
                asset   = label,
                emoji   = _ASSET_EMOJI.get(label, ""),
                ret_6m  = _forward_return(series, match_date, 6),
                ret_12m = _forward_return(series, match_date, 12),
            )
            fwd_returns.append(fr)

        result = ParallelResult(
            rank           = rank,
            date           = match_date,
            distance       = round(dist, 4),
            similarity_pct = sim_pct,
            recession_prob = float(row.get("probability", 0)),
            traffic_light  = str(row.get("traffic_light", "green")),
            feature_vector = fvec,
            forward_returns= fwd_returns,
            outcome_note   = _outcome_note(bt, match_date),
        )
        results.append(result)

    return results
