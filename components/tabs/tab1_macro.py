"""
Pulse360 — Tab 1: Macro Overview & Cycle Phase
================================================
Charts: Real GDP Level, Real GDP Growth (QoQ Ann.), CFNAI.
Includes Investment Implications callout (Claude Haiku, cached 2h).
"""

from __future__ import annotations

from typing import Optional

import plotly.graph_objects as go
import streamlit as st

from ai.claude_client import get_investment_implications
from components.chart_utils import add_nber, chart_meta, dark_layout, time_window_start, render_implications
from data.fred_client import fetch_series


DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)


def render_tab1(model_output, phase_output, lei_growth: Optional[float] = None) -> None:
    st.subheader("Macro Overview & Cycle Phase")

    # ── Time window ───────────────────────────────────────────────────────────
    _, col_window = st.columns([5, 1])
    with col_window:
        start = time_window_start("tab1_window")

    # ── Fetch data ────────────────────────────────────────────────────────────
    gdp_lvl = fetch_series("GDPC1",          start_date=start)
    gdp_gr  = fetch_series("A191RL1Q225SBEA", start_date=start)
    lei_res = fetch_series("CFNAI",           start_date=start)

    # ── Row 1: Real GDP Level | Real GDP Growth ───────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### Real GDP Level")
        if not gdp_lvl["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=gdp_lvl["data"].index, y=gdp_lvl["data"].values,
                mode="lines", line={"color": "#3498db", "width": 2},
                name="Real GDP",
            ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Billions (2017 $)")
            st.plotly_chart(fig, use_container_width=True, key="tab1_gdp_lvl")
        chart_meta(gdp_lvl)

    with col2:
        st.markdown("##### Real GDP Growth (QoQ Ann.)")
        if not gdp_gr["data"].empty:
            colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in gdp_gr["data"].values]
            fig = go.Figure(go.Bar(
                x=gdp_gr["data"].index, y=gdp_gr["data"].values,
                marker_color=colors, name="GDP Growth",
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="#555", line_width=1)
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="% QoQ Annualised")
            st.plotly_chart(fig, use_container_width=True, key="tab1_gdp_gr")
        chart_meta(gdp_gr)

    # ── Row 2: CFNAI ──────────────────────────────────────────────────────────
    st.markdown("##### Chicago Fed National Activity Index (CFNAI)")
    if not lei_res["data"].empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=lei_res["data"].index, y=lei_res["data"].values,
            mode="lines", line={"color": "#9b59b6", "width": 2},
            name="CFNAI",
        ))
        fig.add_hline(
            y=lei_res["data"].mean(), line_dash="dot",
            line_color="#555", line_width=1,
            annotation_text="Long-run avg", annotation_font_color="#666",
        )
        fig = add_nber(fig, start_date=start)
        fig = dark_layout(fig, yaxis_title="Index Level")
        st.plotly_chart(fig, use_container_width=True, key="tab1_cfnai")
    chart_meta(lei_res)

    # ── Investment Implications ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=True):
        tab_readings: dict[str, str] = {}
        if gdp_gr["last_value"] is not None:
            tab_readings["Real GDP Growth (latest quarter)"] = (
                f"{gdp_gr['last_value']:+.1f}% QoQ annualised · as of {gdp_gr['last_date']}"
            )
        if lei_res["last_value"] is not None:
            tab_readings["CFNAI"] = (
                f"{lei_res['last_value']:.2f} · "
                f"6-mo growth: {lei_growth:+.1f}%" if lei_growth is not None
                else f"{lei_res['last_value']:.2f}"
            )
        tab_readings["Recession Probability"] = (
            f"{model_output.probability:.1f}% ({model_output.traffic_light.upper()})"
        )
        tab_readings["Cycle Phase"] = (
            f"{phase_output.phase} ({phase_output.confidence} confidence)"
        )

        if tab_readings:
            with st.spinner("Generating implications…"):
                text = get_investment_implications(
                    tab_key               = "macro",
                    cycle_phase           = phase_output.phase,
                    recession_probability = model_output.probability,
                    traffic_light         = model_output.traffic_light,
                    tab_readings          = tab_readings,
                    phase_notes           = phase_output.notes,
                )
            render_implications(text, model_output.traffic_light)
        else:
            st.info("No data available for implications.")

    st.markdown("---")
    st.caption(DISCLAIMER)
