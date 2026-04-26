"""
Pulse360 — Weekly Diff Component
===================================
Renders a collapsible "What changed" panel on the Dashboard showing:

  • Recession probability delta (vs previous month, from backtest history)
  • 7-day delta for every model indicator (daily/weekly series only)
  • Last available value + date for monthly series (flags if stale)
  • Cycle phase — current vs prior period

All FRED data is already cached by Streamlit, so this component adds
zero extra API calls on re-renders.

Usage (in 0_Dashboard.py):
    from components.weekly_diff import render_weekly_diff
    render_weekly_diff(model_output, phase_output, prev_month_prob)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd
import streamlit as st

from data.fred_client import fetch_series

# ── Frequency labels ──────────────────────────────────────────────────────────

_LOOKBACK_DAYS = 7   # for daily/weekly series — true 7-calendar-day window
_MONTHLY_NOTE  = "monthly — may not have changed"

# ── Indicator config ──────────────────────────────────────────────────────────
# Each entry: series_id, display name, unit label, higher=worse flag,
# and whether it's a derived (computed) value rather than raw FRED

_INDICATORS = [
    {
        "series_id":  "T10Y3M",
        "label":      "10Y–3M Treasury Spread",
        "unit":       "%",
        "higher_bad": False,   # positive spread = good
        "freq":       "daily",
        "fmt":        lambda v: f"{v:+.2f}%",
    },
    {
        "series_id":  "BAMLH0A0HYM2",
        "label":      "High-Yield OAS",
        "unit":       "bps",
        "higher_bad": True,    # widening spreads = bad
        "freq":       "daily",
        "fmt":        lambda v: f"{v:.0f} bps",
    },
    {
        "series_id":  "NFCI",
        "label":      "Chicago Fed NFCI",
        "unit":       "",
        "higher_bad": True,    # positive = tighter conditions = bad
        "freq":       "weekly",
        "fmt":        lambda v: f"{v:+.3f}",
    },
    {
        "series_id":  "ICSA",
        "label":      "Initial Jobless Claims",
        "unit":       "k",
        "higher_bad": True,
        "freq":       "weekly",
        "fmt":        lambda v: f"{v/1000:.0f}k",
    },
    {
        "series_id":  "SAHMREALTIME",
        "label":      "Sahm Rule",
        "unit":       "",
        "higher_bad": True,
        "freq":       "monthly",
        "fmt":        lambda v: f"{v:.2f}",
    },
    {
        "series_id":  "CFNAI",
        "label":      "CFNAI",
        "unit":       "",
        "higher_bad": False,   # more positive = better growth
        "freq":       "monthly",
        "fmt":        lambda v: f"{v:+.2f}",
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _delta_color(delta: float, higher_bad: bool) -> str:
    """Return a CSS colour string: red if worsening, green if improving."""
    if abs(delta) < 1e-6:
        return "#888888"
    worsening = (delta > 0) == higher_bad
    return "#e74c3c" if worsening else "#2ecc71"


def _arrow(delta: float) -> str:
    if abs(delta) < 1e-6:
        return "→"
    return "↑" if delta > 0 else "↓"


def _get_prior_value(
    series_id: str,
    freq: str,
    lookback_days: int = _LOOKBACK_DAYS,
) -> tuple[Optional[float], Optional[date]]:
    """
    Fetch (from cache) the value of a FRED series approx. `lookback_days` ago.
    For monthly series, returns the penultimate observation.

    Returns (prior_value, prior_date) or (None, None) if not available.
    """
    try:
        result = fetch_series(series_id, start_date="2020-01-01")
        data: pd.Series = result.get("data", pd.Series(dtype=float))

        if data.empty or len(data) < 2:
            return None, None

        if freq == "monthly":
            # Return the second-to-last monthly observation
            prior_val  = float(data.iloc[-2])
            prior_date = data.index[-2].date() if hasattr(data.index[-2], "date") else data.index[-2]
            return prior_val, prior_date

        # Daily / weekly: find last value before the 7-day cutoff
        cutoff = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=lookback_days)
        # Handle tz-naive index
        if data.index.tz is not None:
            past = data[data.index <= cutoff]
        else:
            past = data[data.index <= cutoff.tz_localize(None)]

        if past.empty:
            return None, None

        prior_val  = float(past.iloc[-1])
        prior_date = past.index[-1].date() if hasattr(past.index[-1], "date") else past.index[-1]
        return prior_val, prior_date

    except Exception:
        return None, None


# ── Main renderer ─────────────────────────────────────────────────────────────

def render_weekly_diff(
    model_output,          # RecessionModelOutput
    phase_output,          # CyclePhaseOutput
    prev_month_prob: Optional[float],
    prev_phase: Optional[str] = None,
) -> None:
    """
    Render the collapsible "What changed" expander on the Dashboard.

    Args:
        model_output:     Current RecessionModelOutput from run_recession_model()
        phase_output:     Current CyclePhaseOutput from classify_cycle_phase()
        prev_month_prob:  Recession probability from previous backtest period
        prev_phase:       Cycle phase from previous period (optional)
    """
    with st.expander("📊 What changed", expanded=False):

        # ── Recession probability row ─────────────────────────────────────────
        st.markdown("##### Recession probability")

        curr_prob = model_output.probability

        if prev_month_prob is not None:
            prob_delta = curr_prob - prev_month_prob
            prob_color = _delta_color(prob_delta, higher_bad=True)
            prob_arrow = _arrow(prob_delta)
            prob_label = (
                f"<span style='color:{prob_color}; font-weight:600'>"
                f"{prob_arrow} {abs(prob_delta):.1f}pp vs last month</span>"
            )
        else:
            prob_label = "<span style='color:#888'>No prior data</span>"

        col_a, col_b, col_c = st.columns([2, 2, 3])
        with col_a:
            st.markdown(
                f"<div style='font-size:0.8rem;color:#888'>Now</div>"
                f"<div style='font-size:1.3rem;font-weight:600;color:{model_output.color}'>"
                f"{curr_prob:.1f}%</div>",
                unsafe_allow_html=True,
            )
        with col_b:
            if prev_month_prob is not None:
                tl_prev = "green" if prev_month_prob < 25 else "yellow" if prev_month_prob < 50 else "red"
                prev_color = {"green": "#2ecc71", "yellow": "#f39c12", "red": "#e74c3c"}[tl_prev]
                st.markdown(
                    f"<div style='font-size:0.8rem;color:#888'>Last month</div>"
                    f"<div style='font-size:1.3rem;font-weight:600;color:{prev_color}'>"
                    f"{prev_month_prob:.1f}%</div>",
                    unsafe_allow_html=True,
                )
        with col_c:
            st.markdown(
                f"<div style='font-size:0.8rem;color:#888'>Change</div>"
                f"<div style='font-size:1.1rem;margin-top:2px'>{prob_label}</div>",
                unsafe_allow_html=True,
            )

        # ── Cycle phase row ───────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### Cycle phase")

        phase_colors = {
            "Early Expansion": "#2ecc71",
            "Mid Expansion":   "#27ae60",
            "Late Expansion":  "#f39c12",
            "Peak":            "#e67e22",
            "Contraction":     "#e74c3c",
            "Trough":          "#9b59b6",
        }
        curr_phase = phase_output.phase
        curr_phase_color = phase_colors.get(curr_phase, "#888")

        if prev_phase and prev_phase != curr_phase:
            prev_phase_color = phase_colors.get(prev_phase, "#888")
            phase_html = (
                f"<span style='color:{prev_phase_color}'>{prev_phase}</span>"
                f" → "
                f"<span style='color:{curr_phase_color};font-weight:600'>{curr_phase}</span>"
                f" <span style='color:#f39c12;font-size:0.8rem'>⚡ phase change</span>"
            )
        else:
            phase_html = (
                f"<span style='color:{curr_phase_color};font-weight:600'>{curr_phase}</span>"
                f"<span style='color:#888;font-size:0.85rem;margin-left:8px'>unchanged</span>"
            )

        st.markdown(
            f"<div style='font-size:1.05rem;padding:4px 0'>{phase_html}</div>",
            unsafe_allow_html=True,
        )

        # ── Per-indicator rows ────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### Indicator movements")

        # Build a lookup of current values from model_output.features
        current_vals: dict[str, float] = {
            f.series_id: f.current_value
            for f in model_output.features
            if f.current_value is not None
        }

        # Header row
        hcols = st.columns([3, 2, 2, 2, 1])
        for col, label in zip(hcols, ["Indicator", "Now", "Prior", "Change", "7d?"]):
            col.markdown(
                f"<div style='font-size:0.75rem;color:#666;font-weight:600;"
                f"text-transform:uppercase;letter-spacing:0.05em'>{label}</div>",
                unsafe_allow_html=True,
            )

        for ind in _INDICATORS:
            sid      = ind["series_id"]
            fmt      = ind["fmt"]
            freq     = ind["freq"]
            is_daily = freq in ("daily", "weekly")

            curr_val  = current_vals.get(sid)
            prior_val, prior_date = _get_prior_value(sid, freq)

            row_cols = st.columns([3, 2, 2, 2, 1])

            # Label
            row_cols[0].markdown(
                f"<div style='font-size:0.85rem;color:#ccc;padding:6px 0'>"
                f"{ind['label']}</div>",
                unsafe_allow_html=True,
            )

            # Current value
            if curr_val is not None:
                row_cols[1].markdown(
                    f"<div style='font-size:0.85rem;font-weight:500;color:#eee;padding:6px 0'>"
                    f"{fmt(curr_val)}</div>",
                    unsafe_allow_html=True,
                )
            else:
                row_cols[1].markdown(
                    "<div style='font-size:0.8rem;color:#555;padding:6px 0'>—</div>",
                    unsafe_allow_html=True,
                )

            # Prior value
            if prior_val is not None:
                row_cols[2].markdown(
                    f"<div style='font-size:0.85rem;color:#888;padding:6px 0'>"
                    f"{fmt(prior_val)}</div>",
                    unsafe_allow_html=True,
                )
            else:
                row_cols[2].markdown(
                    "<div style='font-size:0.8rem;color:#555;padding:6px 0'>—</div>",
                    unsafe_allow_html=True,
                )

            # Delta
            if curr_val is not None and prior_val is not None:
                delta = curr_val - prior_val
                color = _delta_color(delta, ind["higher_bad"])
                arrow = _arrow(delta)
                if abs(delta) < 1e-6:
                    delta_html = "<span style='color:#888'>unchanged</span>"
                else:
                    delta_html = (
                        f"<span style='color:{color};font-weight:600'>"
                        f"{arrow} {fmt(abs(delta)).lstrip('+-').lstrip('+')}"
                        f"</span>"
                    )
                row_cols[3].markdown(
                    f"<div style='font-size:0.85rem;padding:6px 0'>{delta_html}</div>",
                    unsafe_allow_html=True,
                )
            else:
                row_cols[3].markdown(
                    "<div style='font-size:0.8rem;color:#555;padding:6px 0'>—</div>",
                    unsafe_allow_html=True,
                )

            # Frequency badge
            badge_color = "#1a3a5c" if is_daily else "#2a2a2a"
            badge_text  = "7d" if is_daily else "mo"
            row_cols[4].markdown(
                f"<div style='padding:6px 0'>"
                f"<span style='background:{badge_color};color:#aaa;font-size:0.7rem;"
                f"padding:2px 6px;border-radius:4px'>{badge_text}</span></div>",
                unsafe_allow_html=True,
            )

        # ── Footer note ───────────────────────────────────────────────────────
        st.markdown(
            "<div style='margin-top:12px;font-size:0.75rem;color:#555'>"
            "Daily/weekly series: 7-calendar-day lookback · "
            "Monthly series: compared to prior monthly observation · "
            "All data from FRED (cached)"
            "</div>",
            unsafe_allow_html=True,
        )
