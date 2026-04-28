"""
Pulse360 Overview Row Component
=================================
Persistent top-of-page summary rendered on every tab:
  • Cycle phase badge
  • Recession probability gauge (Plotly)
  • LEI 6-month growth widget
  • 5-indicator risk scorecard
  • Expandable feature contributions breakdown
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.chart_utils import render_action_item
from models.cycle_classifier import CyclePhaseOutput
from models.recession_model import RecessionModelOutput


# ---------------------------------------------------------------------------
# Recession probability gauge
# ---------------------------------------------------------------------------

def _recession_gauge(probability: float, traffic_light: str) -> go.Figure:
    bar_color = {
        "green":  "#2ecc71",
        "yellow": "#f39c12",
        "red":    "#e74c3c",
    }.get(traffic_light, "#95a5a6")

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=probability,
        number={"suffix": "%", "font": {"size": 30, "color": "#ffffff"}},
        gauge={
            "axis": {
                "range": [0, 100],
                "tickvals": [0, 25, 50, 75, 100],
                "ticktext": ["0", "25", "50", "75", "100"],
                "tickfont": {"size": 10, "color": "#cccccc"},
                "tickwidth": 1,
                "tickcolor": "#888",
            },
            "bar":       {"color": bar_color, "thickness": 0.65},
            "bgcolor":   "#1a1a2e",
            "borderwidth": 0,
            "steps": [
                {"range": [0,  25], "color": "#0d2218"},
                {"range": [25, 50], "color": "#221a0d"},
                {"range": [50, 100],"color": "#220d0d"},
            ],
        },
        domain={"x": [0, 1], "y": [0, 1]},
    ))
    fig.update_layout(
        height=190,
        margin={"t": 10, "b": 5, "l": 20, "r": 20},
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": "#ffffff"},
    )
    return fig


# ---------------------------------------------------------------------------
# Feature contributions bar chart
# ---------------------------------------------------------------------------

def _contributions_chart(model_output: RecessionModelOutput) -> go.Figure:
    features = sorted(model_output.features, key=lambda f: f.contribution, reverse=True)

    bar_colors = [
        "#e74c3c" if f.stress_score > 0.66
        else "#f39c12" if f.stress_score > 0.33
        else "#2ecc71"
        for f in features
    ]

    fig = go.Figure(go.Bar(
        x=[f.contribution for f in features],
        y=[f.name for f in features],
        orientation="h",
        marker_color=bar_colors,
        text=[f"{f.contribution:.1f}pp" for f in features],
        textposition="outside",
        textfont={"size": 11, "color": "#ffffff"},
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Contribution: %{x:.2f} pp<br>"
            "<extra></extra>"
        ),
    ))
    fig.update_layout(
        height=270,
        margin={"t": 10, "b": 10, "l": 10, "r": 70},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={
            "title": "Contribution to Probability (percentage points)",
            "color": "#cccccc",
            "gridcolor": "#333",
            "range": [0, max(f.contribution for f in features) * 1.35],
        },
        yaxis={"color": "#ffffff", "gridcolor": "rgba(0,0,0,0)"},
        font={"color": "#ffffff"},
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# 5-light risk scorecard
# ---------------------------------------------------------------------------

_SCORECARD_IDS = ["T10Y3M", "SAHMREALTIME", "USSLIND", "NFCI", "BAMLH0A0HYM2"]
_SCORECARD_LABELS = {
    "T10Y3M":       "Yield Curve",
    "SAHMREALTIME": "Labor (Sahm)",
    "USSLIND":      "LEI",
    "NFCI":         "Fin. Conditions",
    "BAMLH0A0HYM2": "Credit Spreads",
}


def _risk_scorecard(model_output: RecessionModelOutput) -> None:
    feat_map = {f.series_id: f for f in model_output.features}
    cols     = st.columns(5)

    for i, sid in enumerate(_SCORECARD_IDS):
        feat = feat_map.get(sid)
        if feat is None:
            continue

        if feat.stress_score > 0.66:
            icon, status, bg = "🔴", "Stressed",  "#3a1a1a"
        elif feat.stress_score > 0.33:
            icon, status, bg = "🟡", "Elevated",  "#3a2e1a"
        else:
            icon, status, bg = "🟢", "Normal",    "#1a3a2a"

        with cols[i]:
            st.markdown(
                f"""
                <div style="text-align:center; padding:10px 6px;
                            background:{bg}; border-radius:10px;
                            border:1px solid #444; min-height:80px;">
                    <div style="font-size:22px; line-height:1;">{icon}</div>
                    <div style="font-size:11px; color:#ffffff; margin-top:5px;
                                font-weight:600;">{_SCORECARD_LABELS[sid]}</div>
                    <div style="font-size:10px; color:#cccccc; margin-top:2px;">
                        {status}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Feature contributions table
# ---------------------------------------------------------------------------

def _contributions_table(model_output: RecessionModelOutput) -> None:
    rows = []
    for f in sorted(model_output.features, key=lambda x: x.contribution, reverse=True):
        stale_flag = f" ⚠️" if f.is_stale else ""
        rows.append({
            "Indicator":        f.name,
            "Series ID":        f.series_id,
            "Weight":           f"{f.weight:.0%}",
            "Value":            f"{f.current_value:.3f}" if f.current_value is not None else "N/A",
            "Stress":           f"{f.stress_score:.2f}",
            "Contribution (pp)": f"{f.contribution:.2f}",
            "Signal":           f.signal_description[:65] + stale_flag,
            "As of":            str(f.last_date) if f.last_date else "N/A",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Dynamic action-item helpers
# ---------------------------------------------------------------------------

def _phase_action(phase: str) -> str:
    actions = {
        "Early Expansion": "→ Rotate into cyclicals, small caps & commodities — risk appetite is rewarded early in the cycle.",
        "Mid Expansion":   "→ Stay long risk assets and maintain equity overweight; growth & momentum sectors typically lead here.",
        "Late Expansion":  "→ Begin trimming high-beta positions and building a quality/defensive tilt; valuations stretch late-cycle.",
        "Peak":            "→ Reduce equity risk, favour short duration, and build cash — cycle turns happen fast from Peak.",
        "Contraction":     "→ Shift to defensives, treasuries & gold; preserve capital until leading indicators stabilise.",
    }
    return actions.get(phase, "→ Monitor leading indicators closely before adding or reducing risk exposure.")


def _prob_action(prob: float) -> str:
    if prob < 25:
        return "→ Macro risk is low — maintain strategic allocation; no defensive tilt warranted at this level."
    if prob < 50:
        return "→ Elevated risk — consider partial equity hedge and reduce high-yield credit exposure."
    return "→ High recession probability — defensive rotation warranted; reduce risk assets and extend duration."


def _lei_action(growth: float) -> str:
    if growth > 1.0:
        return "→ Rising LEI confirms expansion — leading indicators support staying long risk assets."
    if growth >= 0:
        return "→ Flat LEI trend — growth momentum is stalling; watch for consecutive monthly declines."
    return "→ Falling LEI signals weakening activity ahead — reduce cyclical exposure and watch for trend reversal."


def _scorecard_action(model_output: RecessionModelOutput) -> str:
    stressed  = sum(1 for f in model_output.features if f.stress_score > 0.66)
    elevated  = sum(1 for f in model_output.features if 0.33 < f.stress_score <= 0.66)
    if stressed >= 3:
        return f"→ {stressed} indicators stressed — broad macro deterioration; review portfolio defensiveness urgently."
    if stressed >= 1 or elevated >= 3:
        return f"→ {stressed + elevated} signals elevated or stressed — watch for contagion; consider trimming risk incrementally."
    return "→ All indicators within normal range — no immediate portfolio adjustment required."


def render_overview_row(
    model_output: RecessionModelOutput,
    phase_output: CyclePhaseOutput,
    lei_growth:   Optional[float],
    prob_delta:   Optional[float] = None,
) -> None:
    """
    Render the persistent top overview row.
    Call this once at the top of app.py, before the tab switcher.
    """
    st.markdown("---")

    # ── Row 1: phase · gauge · LEI ───────────────────────────────────────────
    col_phase, col_gauge, col_lei = st.columns([1.6, 2, 1.4])

    with col_phase:
        st.markdown("**Cycle Phase**")
        st.markdown(
            f"""
            <div style="background:{phase_output.color}1a;
                        border:2px solid {phase_output.color};
                        border-radius:12px; padding:14px 10px;
                        text-align:center; margin-bottom:8px;">
                <div style="font-size:34px; line-height:1;">{phase_output.emoji}</div>
                <div style="font-size:17px; font-weight:700;
                            color:{phase_output.color}; margin-top:6px;">
                    {phase_output.phase}
                </div>
                <div style="font-size:11px; color:{phase_output.confidence_color};
                            margin-top:4px; font-weight:500;">
                    {phase_output.confidence} confidence
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(phase_output.notes)
        for ind in phase_output.confirming_indicators[:3]:
            st.markdown(
                f"<div style='font-size:11px; color:#dddddd; margin-top:2px;'>✓ {ind}</div>",
                unsafe_allow_html=True,
            )
        _pa_text = _phase_action(phase_output.phase)
        _pa_color = phase_output.color if hasattr(phase_output, "color") else "#f39c12"
        render_action_item(_pa_text, _pa_color)

    with col_gauge:
        st.markdown("**Recession Probability**")
        st.plotly_chart(
            _recession_gauge(model_output.probability, model_output.traffic_light),
            use_container_width=True,
            key="overview_gauge",
        )
        if prob_delta is not None:
            delta_color  = "#e74c3c" if prob_delta > 0 else "#2ecc71"
            delta_neutral = "#888888"
            d_color = delta_color if abs(prob_delta) >= 0.1 else delta_neutral
            d_arrow = "▲" if prob_delta > 0 else ("▼" if prob_delta < 0 else "─")
            st.markdown(
                f"<div style='text-align:center; font-size:13px; color:{d_color}; "
                f"margin-top:-6px; margin-bottom:4px;'>"
                f"{d_arrow} {prob_delta:+.1f}pp vs last month</div>",
                unsafe_allow_html=True,
            )
        if model_output.has_stale_data:
            st.warning(
                f"⚠️ Stale: {', '.join(model_output.stale_features)}",
                icon=None,
            )
        if model_output.data_as_of:
            st.caption(f"Data as of {model_output.data_as_of.strftime('%Y-%m-%d')}")
        _prob_color = "#2ecc71" if model_output.probability < 25 else "#f39c12" if model_output.probability < 50 else "#e74c3c"
        render_action_item(_prob_action(model_output.probability), _prob_color)

    with col_lei:
        st.markdown("**LEI Momentum**")
        if lei_growth is not None:
            arrow = "↑" if lei_growth > 0 else "↓"
            color = "#2ecc71" if lei_growth > 0 else "#e74c3c"
            st.markdown(
                f"""
                <div style="background:#1a1a2e; border:1px solid #444;
                            border-radius:12px; padding:16px; text-align:center;
                            margin-top:4px;">
                    <div style="font-size:30px; color:{color}; line-height:1;">
                        {arrow}
                    </div>
                    <div style="font-size:24px; font-weight:700; color:{color};
                                margin-top:4px;">
                        {lei_growth:+.1f}%
                    </div>
                    <div style="font-size:11px; color:#dddddd; margin-top:4px;">
                        6-mo annualised
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.info("LEI data unavailable", icon="⚠️")
        if lei_growth is not None:
            _lei_color = "#2ecc71" if lei_growth > 1.0 else "#f39c12" if lei_growth >= 0 else "#e74c3c"
            render_action_item(_lei_action(lei_growth), _lei_color)

    # ── Row 2: risk scorecard ────────────────────────────────────────────────
    st.markdown("<div style='margin-top:12px;'><b>Risk Scorecard</b></div>",
                unsafe_allow_html=True)
    _risk_scorecard(model_output)
    _sc_stressed = sum(1 for f in model_output.features if f.stress_score > 0.66)
    _sc_elevated = sum(1 for f in model_output.features if 0.33 < f.stress_score <= 0.66)
    _sc_color = "#e74c3c" if _sc_stressed >= 3 else "#f39c12" if (_sc_stressed >= 1 or _sc_elevated >= 3) else "#2ecc71"
    render_action_item(_scorecard_action(model_output), _sc_color)

    # ── Row 3: expandable model detail ───────────────────────────────────────
    with st.expander("📊 Recession Model — Feature Contributions", expanded=False):
        st.plotly_chart(
            _contributions_chart(model_output),
            use_container_width=True,
            key="overview_contributions",
        )
        _contributions_table(model_output)

    st.markdown("---")
