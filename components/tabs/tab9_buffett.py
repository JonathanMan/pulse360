"""
Pulse360 — Tab 9: Buffett Indicator
=====================================
The Warren Buffett Indicator: Total US Market Cap / GDP ratio.
Buffett called it "probably the best single measure of where
valuations stand at any given moment."

Data sources:
  WILL5000INDFC — Wilshire 5000 Full Cap Index (total market cap proxy)
  GDP           — US Nominal GDP (quarterly, billions $)
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai.claude_client import get_buffett_analysis
from components.chart_utils import add_nber, dark_layout, render_action_item
from data.fred_client import fetch_series

DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)

# ── Valuation zones ───────────────────────────────────────────────────────────
_ZONES = [
    (0,    75,  "Significantly Undervalued", "#2ecc71"),
    (75,  100,  "Modestly Undervalued",      "#27ae60"),
    (100, 115,  "Fair Value",                "#f1c40f"),
    (115, 135,  "Modestly Overvalued",       "#e67e22"),
    (135, 165,  "Overvalued",                "#e74c3c"),
    (165, 999,  "Significantly Overvalued",  "#c0392b"),
]

def _get_zone(ratio: float) -> tuple[str, str]:
    for lo, hi, label, color in _ZONES:
        if lo <= ratio < hi:
            return label, color
    return "Extremely Overvalued", "#8e0000"


def render_tab9(model_output, phase_output) -> None:
    st.subheader("Buffett Indicator")
    st.caption(
        "The Warren Buffett Indicator measures total US stock market capitalisation "
        "relative to US GDP — Buffett's preferred gauge of market valuation. "
        "He called it 'probably the best single measure of where valuations stand at any given moment.' "
        "Approximated using the Wilshire 5000 Full Cap Index as a market cap proxy against nominal GDP."
    )

    # ── Fetch data ────────────────────────────────────────────────────────────
    with st.spinner("Loading market cap and GDP data…"):
        wilshire = fetch_series("WILL5000INDFC", start_date="1971-01-01")
        gdp      = fetch_series("GDP",           start_date="1971-01-01")

    if wilshire["data"].empty or gdp["data"].empty:
        st.error("Unable to fetch required data — check FRED API connection.")
        return

    # ── Compute ratio ─────────────────────────────────────────────────────────
    # Wilshire 5000 Full Cap ≈ total US market cap (index pts ≈ billions $)
    # GDP is nominal quarterly in billions
    # Both in compatible units → ratio gives approximate Buffett Indicator %
    w_q = wilshire["data"].resample("QE").last().dropna()
    g_q = gdp["data"].resample("QE").last().ffill().dropna()

    common = w_q.index.intersection(g_q.index)
    w_q = w_q.loc[common]
    g_q = g_q.loc[common]

    ratio = (w_q / g_q * 100).dropna()
    if ratio.empty:
        st.error("Could not compute Buffett Indicator — data alignment failed.")
        return

    current_ratio  = float(ratio.iloc[-1])
    hist_mean      = float(ratio.mean())
    hist_pct       = float((ratio < current_ratio).mean() * 100)
    premium        = current_ratio - hist_mean
    zone_label, zone_color = _get_zone(current_ratio)

    # ── Metric row ────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    qoq_delta = current_ratio - float(ratio.iloc[-2]) if len(ratio) >= 2 else None
    with c1:
        st.metric(
            "Buffett Indicator",
            f"{current_ratio:.1f}%",
            delta=f"{qoq_delta:+.1f}pp QoQ" if qoq_delta is not None else None,
        )
    with c2:
        st.metric("Historical Average", f"{hist_mean:.1f}%")
    with c3:
        delta_color = "normal" if abs(premium) < 5 else "inverse" if premium > 0 else "normal"
        st.metric("Premium / Discount to Avg", f"{premium:+.1f}pp")
    with c4:
        st.metric("Historical Percentile", f"{hist_pct:.0f}th")

    # ── Zone badge ────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="text-align:center; margin:10px 0 18px; '
        f'background:{zone_color}22; border:2px solid {zone_color}66; '
        f'border-radius:10px; padding:12px; font-weight:700; '
        f'color:{zone_color}; font-size:1.15rem;">'
        f'⚖️ Market Valuation: {zone_label} ({current_ratio:.1f}% of GDP)</div>',
        unsafe_allow_html=True,
    )

    # ── Action item ───────────────────────────────────────────────────────────
    if current_ratio > 165:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — significantly overvalued; "
            f"Buffett historically accumulates cash and avoids crowded markets at these levels; "
            f"consider reducing equity allocation and raising quality bar.",
            "#e74c3c",
        )
    elif current_ratio > 135:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — overvalued; "
            f"favour quality and value over growth; avoid leverage; hold above-average cash.",
            "#e74c3c",
        )
    elif current_ratio > 115:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — modestly overvalued; "
            f"maintain strategic allocation but avoid aggressive new equity purchases at elevated prices.",
            "#f39c12",
        )
    elif current_ratio > 100:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — near fair value; "
            f"standard strategic allocation supported; no major over/underweight warranted.",
            "#f39c12",
        )
    elif current_ratio > 75:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — modestly undervalued; "
            f"equities offer reasonable long-term value; incremental equity overweight supported.",
            "#2ecc71",
        )
    else:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — significantly undervalued; "
            f"Buffett would be buying aggressively; strong long-term entry opportunity.",
            "#2ecc71",
        )

    st.markdown("---")

    # ── Historical chart ──────────────────────────────────────────────────────
    st.markdown("##### Buffett Indicator — Historical (1971–Present)")
    st.caption(
        "Each quarterly data point shows total US market cap as a % of nominal GDP. "
        "Grey shading = NBER recessions. "
        "Coloured bands show Buffett's own valuation zones. "
        "The dotted line is the long-run average."
    )

    fig = go.Figure()

    # Background zone bands
    for lo, hi, label, color in _ZONES:
        fig.add_hrect(
            y0=lo, y1=min(hi, 300),
            fillcolor=f"{color}14",
            line_width=0, layer="below",
            annotation_text=label,
            annotation_position="right",
            annotation_font_color=color,
            annotation_font_size=9,
        )

    # Main ratio line
    fig.add_trace(go.Scatter(
        x=ratio.index, y=ratio.values,
        mode="lines",
        line={"color": zone_color, "width": 2.5},
        name="Buffett Indicator (%)",
        fill="tozeroy", fillcolor=f"{zone_color}18",
        hovertemplate="%{x|%b %Y}: <b>%{y:.1f}%</b><extra></extra>",
    ))

    # Historical mean
    fig.add_hline(
        y=hist_mean, line_dash="dot", line_color="#888", line_width=1.5,
        annotation_text=f"Avg {hist_mean:.0f}%",
        annotation_font_color="#888", annotation_position="top left",
    )

    # Key thresholds
    for thresh, label, color in [
        (75,  "75% Undervalued",  "#2ecc71"),
        (100, "100% Fair Value",  "#f1c40f"),
        (135, "135% Overvalued",  "#e74c3c"),
    ]:
        fig.add_hline(
            y=thresh, line_dash="dash", line_color=color, line_width=1,
            annotation_text=label, annotation_font_color=color,
            annotation_position="top right", annotation_font_size=9,
        )

    fig = add_nber(fig, start_date="1971-01-01")
    fig = dark_layout(fig, yaxis_title="Market Cap / GDP (%)")
    fig.update_layout(
        height=440,
        yaxis={"range": [0, min(300, max(ratio.values) * 1.15)]},
    )
    st.plotly_chart(fig, use_container_width=True, key="tab9_buffett_main")

    # ── Market cap vs GDP divergence chart ────────────────────────────────────
    st.markdown("##### Market Cap vs GDP — Divergence (Rebased to 100 at Start)")
    st.caption(
        "When the blue line (market cap growth) diverges above the green line (GDP growth), "
        "the Buffett Indicator rises — prices are growing faster than the economy. "
        "Sustained divergence historically signals stretched valuations."
    )

    w_norm = (w_q / w_q.iloc[0] * 100)
    g_norm = (g_q / g_q.iloc[0] * 100)

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=w_norm.index, y=w_norm.values,
        mode="lines", line={"color": "#3498db", "width": 2},
        name="Total Market Cap (rebased to 100)",
        hovertemplate="%{x|%b %Y}: <b>%{y:.0f}</b><extra></extra>",
    ))
    fig2.add_trace(go.Scatter(
        x=g_norm.index, y=g_norm.values,
        mode="lines", line={"color": "#2ecc71", "width": 2, "dash": "dot"},
        name="Nominal GDP (rebased to 100)",
        hovertemplate="%{x|%b %Y}: <b>%{y:.0f}</b><extra></extra>",
    ))
    fig2 = add_nber(fig2, start_date="1971-01-01")
    fig2 = dark_layout(fig2, yaxis_title="Index (1971 = 100)")
    fig2.update_layout(height=300)
    st.plotly_chart(fig2, use_container_width=True, key="tab9_buffett_diverge")

    st.markdown("---")

    # ── AI Daily Brief ────────────────────────────────────────────────────────
    st.markdown("### 🤖 Buffett Indicator — AI Analysis")
    st.caption("Claude Sonnet · Cached 6 hours · Answers: what does the Buffett Indicator say today?")

    if st.button("📊 Generate Buffett Analysis", use_container_width=True, key="buffett_brief_btn"):
        st.session_state["show_buffett_brief"] = True
        st.session_state.pop("buffett_brief_text", None)

    if st.session_state.get("show_buffett_brief"):
        if "buffett_brief_text" not in st.session_state:
            placeholder = st.empty()
            full_text   = ""
            for chunk in get_buffett_analysis(
                current_ratio         = round(current_ratio, 1),
                historical_avg        = round(hist_mean, 1),
                historical_percentile = round(hist_pct, 0),
                zone_label            = zone_label,
                cycle_phase           = phase_output.phase,
                recession_probability = round(model_output.probability, 1),
                traffic_light         = model_output.traffic_light,
                premium_to_avg        = round(premium, 1),
            ):
                full_text += chunk
                placeholder.markdown(full_text + "▌")
            placeholder.markdown(full_text)
            st.session_state["buffett_brief_text"] = full_text
        else:
            st.markdown(st.session_state["buffett_brief_text"])

    st.markdown("---")
    st.caption(DISCLAIMER)
