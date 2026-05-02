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

from components.chart_utils import render_action_item, _pctile_badge_html
from models.cycle_classifier import CyclePhaseOutput
from models.recession_model import RecessionModelOutput


# Lazy import for historical parallels — avoids circular deps and
# allows the overview row to render even if the parallels module fails
def _get_parallels(model_output: RecessionModelOutput):
    try:
        from models.historical_parallels import find_historical_parallels
        return find_historical_parallels(model_output, n=3)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Recession probability gauge
# ---------------------------------------------------------------------------

def _recession_gauge(probability: float, traffic_light: str) -> go.Figure:
    bar_color = {
        "green":  "#00a35a",
        "yellow": "#c98800",
        "red":    "#d92626",
    }.get(traffic_light, "#a0a0a0")

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=probability,
        number={"suffix": "%", "font": {"size": 30, "color": "#0a0a0a"}},
        gauge={
            "axis": {
                "range": [0, 100],
                "tickvals": [0, 25, 50, 75, 100],
                "ticktext": ["0", "25", "50", "75", "100"],
                "tickfont": {"size": 10, "color": "#6a6a6a"},
                "tickwidth": 1,
                "tickcolor": "#a0a0a0",
            },
            "bar":       {"color": bar_color, "thickness": 0.65},
            "bgcolor":   "#f4f4f4",
            "borderwidth": 0,
            "steps": [
                {"range": [0,  25], "color": "#e8f8ee"},
                {"range": [25, 50], "color": "#fff8e5"},
                {"range": [50, 100],"color": "#fde8e8"},
            ],
        },
        domain={"x": [0, 1], "y": [0, 1]},
    ))
    fig.update_layout(
        height=190,
        margin={"t": 10, "b": 5, "l": 20, "r": 20},
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": "#0a0a0a"},
    )
    return fig


# ---------------------------------------------------------------------------
# Feature contributions bar chart
# ---------------------------------------------------------------------------

def _contributions_chart(model_output: RecessionModelOutput) -> go.Figure:
    features = sorted(model_output.features, key=lambda f: f.contribution, reverse=True)

    bar_colors = [
        "#d92626" if f.stress_score > 0.66
        else "#c98800" if f.stress_score > 0.33
        else "#00a35a"
        for f in features
    ]

    fig = go.Figure(go.Bar(
        x=[f.contribution for f in features],
        y=[f.name for f in features],
        orientation="h",
        marker_color=bar_colors,
        text=[f"{f.contribution:.1f}pp" for f in features],
        textposition="outside",
        textfont={"size": 11, "color": "#0a0a0a"},
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
            "color": "#6a6a6a",
            "gridcolor": "#ececec",
            "range": [0, max(f.contribution for f in features) * 1.35],
        },
        yaxis={"color": "#0a0a0a", "gridcolor": "rgba(0,0,0,0)"},
        font={"color": "#0a0a0a"},
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
            icon, status, bg = "🔴", "Stressed",  "#fde8e8"
        elif feat.stress_score > 0.33:
            icon, status, bg = "🟡", "Elevated",  "#fff8e5"
        else:
            icon, status, bg = "🟢", "Normal",    "#e8f8ee"

        # Stress score as a pseudo-percentile (0 = most benign, 100 = max stress)
        stress_pct = round(feat.stress_score * 100)
        pctile_html = _pctile_badge_html(stress_pct)

        with cols[i]:
            st.markdown(
                f"""
                <div style="text-align:center; padding:10px 6px;
                            background:{bg}; border-radius: 2px;
                            border:1px solid #ececec; min-height:90px;">
                    <div style="font-size:22px; line-height:1;">{icon}</div>
                    <div style="font-size:11px; color:#0a0a0a; margin-top:5px;
                                font-weight:600;">{_SCORECARD_LABELS[sid]}</div>
                    <div style="font-size:10px; color:#6a6a6a; margin-top:2px;">
                        {status}
                    </div>
                    <div style="margin-top:5px;">{pctile_html}</div>
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
# Historical parallels renderer
# ---------------------------------------------------------------------------

def _ret_html(val: float | None) -> str:
    """Format a return value as coloured HTML — green positive, red negative."""
    if val is None:
        return '<span style="color:#a0a0a0;">—</span>'
    color  = "#28a745" if val > 0 else "#d92626" if val < 0 else "#6a6a6a"
    prefix = "+" if val > 0 else ""
    return f'<span style="color:{color};font-weight:600;">{prefix}{val:.1f}%</span>'


def _render_historical_parallels(model_output: RecessionModelOutput) -> None:
    """
    Show the 3 closest historical macro periods plus forward asset returns.
    Calls _get_parallels() which lazy-imports the parallels engine.
    """
    st.caption(
        "The recession model's current stress-vector fingerprint is compared "
        "against every month since 1997.  The three closest matches are shown "
        "below — what the macro environment looked like then, and how key "
        "asset classes performed over the following 6 and 12 months.  "
        "**Not investment advice — past parallels don't guarantee future returns.**"
    )

    with st.spinner("Finding historical parallels…"):
        parallels = _get_parallels(model_output)

    if not parallels:
        st.info(
            "Historical parallels unavailable — backtest data may still be loading. "
            "Try refreshing the page.",
            icon="⏳",
        )
        return

    # Feature labels for the mini comparison
    _SID_LABELS = {
        "T10Y3M":       "Yield Curve",
        "SAHMREALTIME": "Sahm Rule",
        "CFNAI":        "Activity (CFNAI)",
        "NFCI":         "Fin. Conditions",
        "ICSA":         "Jobless Claims",
        "BAMLH0A0HYM2": "HY Spreads",
    }

    tl_colors = {"green": "#00a35a", "yellow": "#c98800", "red": "#d92626"}
    tl_bg     = {"green": "#e8f8ee", "yellow": "#fff8e5", "red": "#fde8e8"}

    cols = st.columns(len(parallels))

    for col, p in zip(cols, parallels):
        tl_c  = tl_colors.get(p.traffic_light, "#95a5a6")
        tl_b  = tl_bg.get(p.traffic_light, "#f4f4f4")
        month_str = p.date.strftime("%b %Y")

        # Similarity bar (0–100)
        sim_color = "#00a35a" if p.similarity_pct > 80 else "#c98800" if p.similarity_pct > 60 else "#d92626"
        sim_bar_w = round(p.similarity_pct)

        # Feature vector mini comparison (current vs then)
        current_fmap = {f.series_id: f.stress_score for f in model_output.features}
        feat_rows_html = ""
        for sid, label in _SID_LABELS.items():
            then_val = p.feature_vector.get(sid, 0.5)
            now_val  = current_fmap.get(sid, 0.5)
            then_bar_color = "#d92626" if then_val > 0.66 else "#c98800" if then_val > 0.33 else "#00a35a"
            now_bar_color  = "#d92626" if now_val  > 0.66 else "#c98800" if now_val  > 0.33 else "#00a35a"
            feat_rows_html += (
                f'<tr>'
                f'<td style="font-size:10px;color:#6a6a6a;padding:2px 4px;white-space:nowrap;">{label}</td>'
                f'<td style="padding:2px 4px;">'
                f'<div style="background:#f4f4f4;border-radius:3px;height:8px;width:100%;">'
                f'<div style="background:{then_bar_color};border-radius:3px;height:8px;'
                f'width:{round(then_val*100)}%;"></div></div></td>'
                f'<td style="padding:2px 4px;">'
                f'<div style="background:#f4f4f4;border-radius:3px;height:8px;width:100%;">'
                f'<div style="background:{now_bar_color};border-radius:3px;height:8px;'
                f'width:{round(now_val*100)}%;"></div></div></td>'
                f'</tr>'
            )

        # Forward returns table
        ret_rows_html = ""
        for fr in p.forward_returns:
            ret_rows_html += (
                f'<tr>'
                f'<td style="font-size:11px;padding:3px 4px;white-space:nowrap;">'
                f'{fr.emoji} {fr.asset}</td>'
                f'<td style="font-size:11px;text-align:right;padding:3px 6px;">'
                f'{_ret_html(fr.ret_6m)}</td>'
                f'<td style="font-size:11px;text-align:right;padding:3px 6px;">'
                f'{_ret_html(fr.ret_12m)}</td>'
                f'</tr>'
            )

        outcome_html = (
            f'<div style="font-size:10px;color:#6a6a6a;margin-top:8px;'
            f'padding:5px 8px;background:#f4f4f4;border-radius: 2px;">'
            f'{p.outcome_note}</div>'
            if p.outcome_note else ""
        )

        with col:
            st.markdown(
                f"""
                <div style="border:1px solid #ececec;border-radius: 2px;padding:12px 14px;
                            background:#ffffff;height:100%;">

                  <!-- Header -->
                  <div style="display:flex;align-items:center;justify-content:space-between;
                              margin-bottom:8px;">
                    <div style="font-size:15px;font-weight:700;color:#0a0a0a;">
                      #{p.rank} · {month_str}
                    </div>
                    <div style="background:{tl_b};border:1px solid {tl_c};border-radius: 2px;
                                padding:2px 8px;font-size:10px;font-weight:700;color:{tl_c};">
                      {p.recession_prob:.0f}% risk
                    </div>
                  </div>

                  <!-- Similarity bar -->
                  <div style="font-size:10px;color:#6a6a6a;margin-bottom:3px;">
                    Similarity
                  </div>
                  <div style="background:#f4f4f4;border-radius: 2px;height:10px;
                              margin-bottom:10px;width:100%;">
                    <div style="background:{sim_color};border-radius: 2px;height:10px;
                                width:{sim_bar_w}%;transition:width 0.4s;"></div>
                  </div>
                  <div style="font-size:11px;color:#6a6a6a;margin-top:-8px;
                              margin-bottom:10px;text-align:right;">
                    {p.similarity_pct:.0f}% match
                  </div>

                  <!-- Feature comparison -->
                  <div style="font-size:10px;font-weight:700;color:#6a6a6a;
                              text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;">
                    Stress profile
                  </div>
                  <table style="width:100%;border-collapse:collapse;margin-bottom:10px;">
                    <tr>
                      <th style="font-size:9px;color:#a0a0a0;font-weight:400;
                                 padding:1px 4px;text-align:left;"></th>
                      <th style="font-size:9px;color:#6a6a6a;font-weight:700;
                                 padding:1px 4px;text-align:left;">{month_str[:3]}'
                        {month_str[-2:]}</th>
                      <th style="font-size:9px;color:#0a0a0a;font-weight:700;
                                 padding:1px 4px;text-align:left;">Now</th>
                    </tr>
                    {feat_rows_html}
                  </table>

                  <!-- Forward returns -->
                  <div style="font-size:10px;font-weight:700;color:#6a6a6a;
                              text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;">
                    What followed
                  </div>
                  <table style="width:100%;border-collapse:collapse;">
                    <tr>
                      <th style="font-size:9px;color:#6a6a6a;font-weight:400;
                                 padding:2px 4px;text-align:left;">Asset</th>
                      <th style="font-size:9px;color:#6a6a6a;font-weight:700;
                                 padding:2px 6px;text-align:right;">6M</th>
                      <th style="font-size:9px;color:#6a6a6a;font-weight:700;
                                 padding:2px 6px;text-align:right;">12M</th>
                    </tr>
                    {ret_rows_html}
                  </table>

                  {outcome_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.caption(
        "Similarity is 100% minus the weighted Euclidean distance across the 6 model "
        "stress dimensions (yield curve, Sahm, CFNAI, NFCI, claims, HY spreads). "
        "Forward returns are actual historical price returns — not forecasts."
    )


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
        with st.container(border=True):
            st.markdown("**Cycle Phase**")
            st.markdown(
                f"""
                <div style="border-top:2px solid {phase_output.color};
                            border-radius:0; padding:12px 0 10px 0;
                            margin-bottom:8px;">
                    <div style="font-size:11px; font-weight:600;
                                color:#a0a0a0; text-transform:uppercase;
                                letter-spacing:0.12em;
                                font-family:'Geist Mono',monospace;">
                        CONFIDENCE · {phase_output.confidence.upper()}
                    </div>
                    <div style="font-size:22px; font-weight:700;
                                color:#0a0a0a; margin-top:8px;
                                letter-spacing:-0.03em; line-height:1.1;">
                        {phase_output.phase}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(phase_output.notes)
            for ind in phase_output.confirming_indicators[:3]:
                st.markdown(
                    f"<div style='font-size:11px; color:#6a6a6a; margin-top:2px;'>✓ {ind}</div>",
                    unsafe_allow_html=True,
                )
            _pa_text = _phase_action(phase_output.phase)
            _pa_color = phase_output.color if hasattr(phase_output, "color") else "#c98800"
            render_action_item(_pa_text, _pa_color)

    with col_gauge:
        with st.container(border=True):
            st.markdown("**Recession Probability**")
            st.plotly_chart(
                _recession_gauge(model_output.probability, model_output.traffic_light),
                use_container_width=True,
                key="overview_gauge",
            )
            if prob_delta is not None:
                delta_color  = "#d92626" if prob_delta > 0 else "#28a745"
                delta_neutral = "#6a6a6a"
                d_color = delta_color if abs(prob_delta) >= 0.1 else delta_neutral
                d_arrow = "▲" if prob_delta > 0 else ("▼" if prob_delta < 0 else "─")
                st.markdown(
                    f"<div style='text-align:center; font-size:13px; color:{d_color}; "
                    f"margin-top:-6px; margin-bottom:4px;'>"
                    f"{d_arrow} {prob_delta:+.1f}pp vs last month</div>",
                    unsafe_allow_html=True,
                )
            # ── Stress percentile badge (aggregate across all 5 features) ────
            if model_output.features:
                avg_stress = sum(f.stress_score for f in model_output.features) / len(model_output.features)
                stress_pct = round(avg_stress * 100)
                pctile_badge = _pctile_badge_html(stress_pct)
                st.markdown(
                    f'<div style="text-align:center; margin-bottom:4px;">'
                    f'<span style="font-size:0.72rem;color:#6a6a6a;">Stress level</span>'
                    f'&nbsp;{pctile_badge}</div>',
                    unsafe_allow_html=True,
                )
            if model_output.has_stale_data:
                stale_labels = ", ".join(model_output.stale_features)
                st.markdown(
                    f'<span style="display:inline-flex;align-items:center;gap:6px;'
                    f'background:#fff8e5;border:1px solid #c98800;border-radius:999px;'
                    f'padding:3px 12px;font-size:0.78rem;font-weight:600;color:#7a5000;">'
                    f'⚠️ Stale: {stale_labels}</span>',
                    unsafe_allow_html=True,
                )
            if model_output.data_as_of:
                st.caption(f"Data as of {model_output.data_as_of.strftime('%Y-%m-%d')}")
            _prob_color = "#28a745" if model_output.probability < 25 else "#c98800" if model_output.probability < 50 else "#d92626"
            render_action_item(_prob_action(model_output.probability), _prob_color)

    with col_lei:
        with st.container(border=True):
            st.markdown("**LEI Momentum**")
            if lei_growth is not None:
                arrow = "↑" if lei_growth > 0 else "↓"
                color = "#28a745" if lei_growth > 0 else "#d92626"
                st.markdown(
                    f"""
                    <div style="text-align:center; padding:16px 8px 8px 8px;">
                        <div style="font-size:30px; color:{color}; line-height:1;">
                            {arrow}
                        </div>
                        <div style="font-size:24px; font-weight:700; color:{color};
                                    margin-top:4px;">
                            {lei_growth:+.1f}%
                        </div>
                        <div style="font-size:11px; color:#6a6a6a; margin-top:4px;">
                            6-mo annualised
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.info("LEI data unavailable", icon="⚠️")
            if lei_growth is not None:
                _lei_color = "#28a745" if lei_growth > 1.0 else "#c98800" if lei_growth >= 0 else "#d92626"
                render_action_item(_lei_action(lei_growth), _lei_color)

    # ── Row 2: risk scorecard ────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Risk Scorecard**")
        _risk_scorecard(model_output)
        _sc_stressed = sum(1 for f in model_output.features if f.stress_score > 0.66)
        _sc_elevated = sum(1 for f in model_output.features if 0.33 < f.stress_score <= 0.66)
        _sc_color = "#d92626" if _sc_stressed >= 3 else "#c98800" if (_sc_stressed >= 1 or _sc_elevated >= 3) else "#28a745"
        render_action_item(_scorecard_action(model_output), _sc_color)

    # ── Row 3: expandable model detail ───────────────────────────────────────
    with st.expander("📊 Recession Model — Feature Contributions", expanded=False):
        st.plotly_chart(
            _contributions_chart(model_output),
            use_container_width=True,
            key="overview_contributions",
        )
        _contributions_table(model_output)

    # ── Row 4: historical parallels ───────────────────────────────────────────
    with st.expander("🕰️ Historical Parallels — Closest Macro Matches", expanded=False):
        _render_historical_parallels(model_output)

    st.markdown("---")
