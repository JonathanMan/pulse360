"""
Pulse360 — Historical Backtest Engine
=======================================
Runs the recession probability model at every month from 1997-01 to present,
using only data that would have been available at each point in time
(proper point-in-time backtesting — no look-ahead bias).

Covers three NBER recessions with full feature data:
  • 2001 dot-com recession (Mar–Nov 2001)
  • 2007–09 Great Recession (Dec 2007 – Jun 2009)
  • 2020 COVID recession (Feb–Apr 2020)

HY OAS (BAMLH0A0HYM2) starts 1996-12-31, so full backtest begins 1997-01.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st

from data.fred_client import fetch_series
from models.recession_model import (
    _stress_t10y3m,
    _stress_sahm,
    _stress_cfnai,
    _stress_nfci,
    _stress_claims_yoy,
    _stress_hy_oas,
)

logger = logging.getLogger(__name__)

# Feature config for backtest — mirrors _FEATURES in recession_model.py
# weights MUST match recession_model._FEATURES exactly
_BT_FEATURES = [
    {"name": "10Y–3M Treasury Spread", "series_id": "T10Y3M",        "weight": 0.30, "stress_fn": _stress_t10y3m,    "derived": None},
    {"name": "Sahm Rule",              "series_id": "SAHMREALTIME",   "weight": 0.20, "stress_fn": _stress_sahm,      "derived": None},
    {"name": "CFNAI (Activity Index)", "series_id": "CFNAI",          "weight": 0.20, "stress_fn": _stress_cfnai,     "derived": "cfnai"},  # 0.15→0.20, absorbed NAPM
    {"name": "Chicago Fed NFCI",       "series_id": "NFCI",           "weight": 0.10, "stress_fn": _stress_nfci,      "derived": None},
    {"name": "Initial Claims YoY",     "series_id": "ICSA",           "weight": 0.10, "stress_fn": _stress_claims_yoy,"derived": "icsa_yoy"},
    {"name": "High-Yield OAS",         "series_id": "BAMLH0A0HYM2",  "weight": 0.10, "stress_fn": _stress_hy_oas,    "derived": None},
    # NAPM (ISM Manufacturing PMI) removed from FRED ~2024 due to ISM licensing.
    # Its 5% weight was redistributed to CFNAI above.
]

assert abs(sum(f["weight"] for f in _BT_FEATURES) - 1.0) < 1e-9, "BT weights must sum to 1.0"


# ---------------------------------------------------------------------------
# Point-in-time helper functions
# ---------------------------------------------------------------------------

def _value_at(series: pd.Series, as_of: pd.Timestamp) -> Optional[float]:
    """Last available value on or before as_of."""
    if series.empty or not isinstance(series.index, pd.DatetimeIndex):
        return None
    available = series[series.index <= as_of].dropna()
    return float(available.iloc[-1]) if not available.empty else None


def _cfnai_at(series: pd.Series, as_of: pd.Timestamp, months: int = 3) -> Optional[float]:
    """3-month trailing average of CFNAI up to as_of."""
    if series.empty or not isinstance(series.index, pd.DatetimeIndex):
        return None
    available = series[series.index <= as_of].resample("MS").last().dropna()
    if len(available) < months:
        return None
    return round(float(available.iloc[-months:].mean()), 3)


def _icsa_yoy_at(series: pd.Series, as_of: pd.Timestamp) -> Optional[float]:
    """4-week average YoY % change in initial claims up to as_of."""
    if series.empty or not isinstance(series.index, pd.DatetimeIndex):
        return None
    available = series[series.index <= as_of].dropna()
    if len(available) < 56:
        return None
    current_avg  = available.iloc[-4:].mean()
    year_ago_avg = available.iloc[-56:-52].mean()
    if year_ago_avg == 0 or pd.isna(year_ago_avg):
        return None
    return round((current_avg / year_ago_avg - 1) * 100, 2)


# ---------------------------------------------------------------------------
# Main backtest runner
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)   # cache 24 hours
def run_historical_backtest(start_date: str = "1997-01-01") -> pd.DataFrame:
    """
    Run the recession model at every calendar month from start_date to today.

    Returns:
        DataFrame indexed by month-start date with columns:
            probability       — model output 0–100
            traffic_light     — "green" | "yellow" | "red"
            stress_<name>     — per-feature stress score 0–1
        Empty DataFrame on failure.
    """
    long_start = "1990-01-01"   # extra buffer for YoY and MA calculations

    # Fetch all series with full history
    raw: dict[str, pd.Series] = {}
    for cfg in _BT_FEATURES:
        result = fetch_series(cfg["series_id"], start_date=long_start)
        if result["error"]:
            logger.warning("backtest: fetch failed for %s: %s", cfg["series_id"], result["error"])
        raw[cfg["series_id"]] = result["data"]

    # Monthly date range: first of each month from start_date to today
    dates = pd.date_range(
        start = start_date,
        end   = pd.Timestamp.today().normalize(),
        freq  = "MS",
    )

    records = []
    for ts in dates:
        row: dict = {"date": ts}
        weighted_stress = 0.0

        for cfg in _BT_FEATURES:
            sid    = cfg["series_id"]
            data   = raw[sid]
            derive = cfg["derived"]

            # Get point-in-time value
            if derive == "cfnai":
                value = _cfnai_at(data, ts)
            elif derive == "icsa_yoy":
                value = _icsa_yoy_at(data, ts)
            else:
                value = _value_at(data, ts)

            if value is None:
                stress = 0.5   # neutral assumption when data unavailable
            else:
                stress, _ = cfg["stress_fn"](float(value))

            weighted_stress += cfg["weight"] * stress
            col = "stress_" + cfg["name"].lower().replace(" ", "_").replace("–", "").replace("(", "").replace(")", "")
            row[col] = round(stress, 3)
            row[f"value_{sid.lower()}"] = value

        prob = round(weighted_stress * 100, 1)
        row["probability"]   = prob
        row["traffic_light"] = "green" if prob < 25 else "yellow" if prob < 50 else "red"
        records.append(row)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).set_index("date")
    df.index = pd.DatetimeIndex(df.index)
    return df


# ---------------------------------------------------------------------------
# Recession performance analysis
# ---------------------------------------------------------------------------

def compute_recession_stats(
    backtest_df: pd.DataFrame,
    usrec_series: pd.Series,
) -> list[dict]:
    """
    For each NBER recession, compute:
      - recession start and end
      - date model first crossed 25% (yellow threshold) — lead/lag in months
      - date model first crossed 50% (red threshold) — lead/lag in months
      - peak probability during recession window
      - whether the model gave a true signal or missed

    Args:
        backtest_df:  output of run_historical_backtest()
        usrec_series: USREC series from FRED (1 = recession month)

    Returns:
        List of dicts, one per recession.
    """
    if backtest_df.empty or usrec_series.empty:
        return []

    # Identify recession periods (runs of consecutive 1s)
    usrec = usrec_series.resample("MS").last().dropna()
    usrec = usrec[usrec.index >= pd.Timestamp("1997-01-01")]

    recessions = []
    in_rec = False
    rec_start = None

    for ts, val in usrec.items():
        if val == 1 and not in_rec:
            in_rec    = True
            rec_start = ts
        elif val == 0 and in_rec:
            in_rec = False
            recessions.append((rec_start, ts - pd.DateOffset(months=1)))

    if in_rec and rec_start is not None:
        recessions.append((rec_start, usrec.index[-1]))

    stats = []
    for rec_start, rec_end in recessions:
        prob = backtest_df["probability"]

        # First crossing of 25% (yellow) before or during recession
        window_pre = prob[prob.index <= rec_end]
        yellow_dates = window_pre[window_pre >= 25].index
        first_yellow = yellow_dates[0] if len(yellow_dates) > 0 else None

        red_dates = window_pre[window_pre >= 50].index
        first_red = red_dates[0] if len(red_dates) > 0 else None

        # Peak during recession window
        rec_window = prob[(prob.index >= rec_start) & (prob.index <= rec_end)]
        peak_prob  = float(rec_window.max()) if not rec_window.empty else None
        peak_date  = rec_window.idxmax()     if not rec_window.empty else None

        # Lead time: months before rec_start that 25% was first crossed
        def _lead(signal_date):
            if signal_date is None:
                return None
            delta = (rec_start.year - signal_date.year) * 12 + (rec_start.month - signal_date.month)
            return delta   # positive = months early; negative = months late

        stats.append({
            "recession_start":  rec_start.strftime("%b %Y"),
            "recession_end":    rec_end.strftime("%b %Y"),
            "first_yellow":     first_yellow.strftime("%b %Y") if first_yellow is not None else "Never",
            "yellow_lead_months": _lead(first_yellow),
            "first_red":        first_red.strftime("%b %Y") if first_red is not None else "Never",
            "red_lead_months":  _lead(first_red),
            "peak_probability": peak_prob,
            "peak_date":        peak_date.strftime("%b %Y") if peak_date is not None else "—",
        })

    return stats


# ---------------------------------------------------------------------------
# False positive analysis
# ---------------------------------------------------------------------------

def compute_false_positive_periods(
    backtest_df: pd.DataFrame,
    usrec_series: pd.Series,
    threshold: float = 25.0,
) -> list[dict]:
    """
    Find periods where the model was above `threshold` but no recession occurred
    within the following 12 months.

    Returns list of {start, end, peak_prob} dicts.
    """
    if backtest_df.empty or usrec_series.empty:
        return []

    usrec = usrec_series.resample("MS").last().dropna()
    prob  = backtest_df["probability"]

    false_positives = []
    in_signal = False
    signal_start = None
    signal_peak  = 0.0

    for ts, p in prob.items():
        # Check if any recession in next 12 months
        future_12m  = usrec[(usrec.index > ts) & (usrec.index <= ts + pd.DateOffset(months=12))]
        recession_ahead = bool((future_12m == 1).any())

        # Also check if currently in recession
        current_rec = bool(usrec.get(ts, 0) == 1)

        elevated = p >= threshold

        if elevated and not in_signal:
            in_signal    = True
            signal_start = ts
            signal_peak  = p
        elif elevated and in_signal:
            signal_peak = max(signal_peak, p)
        elif not elevated and in_signal:
            # Signal ended — was it a false positive?
            if not recession_ahead and not current_rec:
                false_positives.append({
                    "start":     signal_start.strftime("%b %Y"),
                    "end":       ts.strftime("%b %Y"),
                    "peak_prob": round(signal_peak, 1),
                })
            in_signal    = False
            signal_start = None
            signal_peak  = 0.0

    return false_positives
