"""
Pulse360 — Tab 7: Housing, Consumer & Sentiment
=================================================
Charts: Housing Starts + Building Permits, Case-Shiller HPI YoY,
        Consumer Sentiment, Retail Sales, Personal Savings Rate.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from data.fred_client import fetch_series
from components.chart_utils import (
    dark_layout, add_nber, chart_meta, time_window_start, yoy_pct
)
from ai.claude_client import get_investment_implications


DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)


def render_tab7(model_output, phase_output) -> None:
    st.subheader("Housing, Consumer & Sentiment")

    # ── Time window ───────────────────────────────────────────────────────────
    col_title, col_window = st.columns([5, 1])
    with col_window:
        start = time_window_start("tab7_window")

    # ── Fetch data ────────────────────────────────────────────────────────────
    houst   = fetch_series("HOUST",    start_date=start)
    permit  = fetch_series("PERMIT",   start_date=start)
    cs_hpi  = fetch_series("CSUSHPISA", start_date=start)
    umcsent = fetch_series("UMCSENT",  start_date=start)
    rsxfs   = fetch_series("RSXFS",    start_date=start)
    rsfsxmv = fetch_series("RSFSXMV",  start_date=start)
    psavert = fetch_series("PSAVERT",  start_date=start)

    # ── Row 1: Housing Starts | Building Permits ──────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### Housing Starts (HOUST)")
        if not houst["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=houst["data"].index, y=houst["data"].values,
                mode="lines", line={"color": "#3498db", "width": 2},
                name="Housing Starts (000s)",
                fill="tozeroy", fillcolor="rgba(52,152,219,0.08)",
            ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Thousands of Units (SAAR)")
            st.plotly_chart(fig, use_container_width=True, key="tab7_houst")
        chart_meta(houst, decimals=0)

    with col2:
        st.markdown("##### Building Permits (PERMIT)")
        if not permit["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=permit["data"].index, y=permit["data"].values,
                mode="lines", line={"color": "#2ecc71", "width": 2},
                name="Building Permits (000s)",
                fill="tozeroy", fillcolor="rgba(46,204,113,0.08)",
            ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Thousands of Units (SAAR)")
            st.plotly_chart(fig, use_container_width=True, key="tab7_permit")
        chart_meta(permit, decimals=0)

    # ── Row 2: Case-Shiller HPI YoY | Consumer Sentiment ─────────────────────
    col3, col4 = st.columns(2)

    with col3:
        st.markdown("##### Case-Shiller National HPI (YoY %)")
        if not cs_hpi["data"].empty:
            cs_yoy = yoy_pct(cs_hpi["data"], periods=12).dropna()
            if not cs_yoy.empty:
                colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in cs_yoy.values]
                fig = go.Figure(go.Bar(
                    x=cs_yoy.index, y=cs_yoy.values,
                    marker_color=colors,
                    name="Case-Shiller HPI YoY %",
                ))
                fig.add_hline(y=0, line_dash="dash", line_color="#555", line_width=1)
                fig = add_nber(fig, start_date=start)
                fig = dark_layout(fig, yaxis_title="YoY %")
                st.plotly_chart(fig, use_container_width=True, key="tab7_cshpi")
        chart_meta(cs_hpi, decimals=1)

    with col4:
        st.markdown("##### U of Michigan Consumer Sentiment")
        if not umcsent["data"].empty:
            sent_val = umcsent["last_value"] or 0
            line_color = "#2ecc71" if sent_val >= 80 else "#f39c12" if sent_val >= 60 else "#e74c3c"
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=umcsent["data"].index, y=umcsent["data"].values,
                mode="lines", line={"color": line_color, "width": 2},
                name="Consumer Sentiment",
            ))
            fig.add_hline(y=80, line_dash="dot", line_color="#2ecc71",
                          line_width=1, annotation_text="80 — confident",
                          annotation_font_color="#2ecc71", annotation_font_size=10)
            fig.add_hline(y=60, line_dash="dot", line_color="#e74c3c",
                          line_width=1, annotation_text="60 — pessimistic",
                          annotation_font_color="#e74c3c", annotation_font_size=10)
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Index Level")
            st.plotly_chart(fig, use_container_width=True, key="tab7_sentiment")
        chart_meta(umcsent, decimals=1)

    # ── Row 3: Retail Sales | Personal Savings Rate ───────────────────────────
    col5, col6 = st.columns(2)

    with col5:
        st.markdown("##### Retail Sales YoY (ex-Food Services)")
        if not rsxfs["data"].empty:
            rs_yoy = yoy_pct(rsxfs["data"]).dropna()
            if not rs_yoy.empty:
                colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in rs_yoy.values]
                fig = go.Figure(go.Bar(
                    x=rs_yoy.index, y=rs_yoy.values,
                    marker_color=colors,
                    name="Retail Sales YoY %",
                ))
                fig.add_hline(y=0, line_dash="dash", line_color="#555", line_width=1)
                fig = add_nber(fig, start_date=start)
                fig = dark_layout(fig, yaxis_title="YoY %")
                st.plotly_chart(fig, use_container_width=True, key="tab7_retail")
        chart_meta(rsxfs, decimals=1)

    with col6:
        st.markdown("##### Personal Savings Rate (PSAVERT)")
        if not psavert["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=psavert["data"].index, y=psavert["data"].values,
                mode="lines", line={"color": "#9b59b6", "width": 2},
                name="Savings Rate",
                fill="tozeroy", fillcolor="rgba(155,89,182,0.08)",
            ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="% of Disposable Income")
            st.plotly_chart(fig, use_container_width=True, key="tab7_savings")
        chart_meta(psavert, decimals=1)

    # ── Investment Implications ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=False):
        tab_readings: dict[str, str] = {}
        if houst["last_value"] is not None:
            tab_readings["Housing Starts"] = (
                f"{houst['last_value']:,.0f}K SAAR · as of {houst['last_date']}"
            )
        if permit["last_value"] is not None:
            tab_readings["Building Permits"] = f"{permit['last_value']:,.0f}K SAAR"
        if not cs_hpi["data"].empty:
            cs_yoy_last = yoy_pct(cs_hpi["data"]).dropna()
            if not cs_yoy_last.empty:
                tab_readings["Case-Shiller HPI (YoY)"] = (
                    f"{cs_yoy_last.iloc[-1]:+.1f}%"
                )
        if umcsent["last_value"] is not None:
            level = "confident" if umcsent["last_value"] >= 80 else "neutral" if umcsent["last_value"] >= 60 else "pessimistic"
            tab_readings["Consumer Sentiment (UMich)"] = (
                f"{umcsent['last_value']:.1f} — {level}"
            )
        if not rsxfs["data"].empty:
            rs_yoy_last = yoy_pct(rsxfs["data"]).dropna()
            if not rs_yoy_last.empty:
                tab_readings["Retail Sales ex-Food (YoY)"] = f"{rs_yoy_last.iloc[-1]:+.1f}%"
        if psavert["last_value"] is not None:
            tab_readings["Personal Savings Rate"] = f"{psavert['last_value']:.1f}%"

        if tab_readings:
            with st.spinner("Generating implications…"):
                text = get_investment_implications(
                    tab_key               = "housing",
                    cycle_phase           = phase_output.phase,
                    recession_probability = model_output.probability,
                    traffic_light         = model_output.traffic_light,
                    tab_readings          = tab_readings,
                    phase_notes           = phase_output.notes,
                )
            st.markdown(text)
        else:
            st.info("No data available for implications.")

    st.markdown("---")
    st.caption(DISCLAIMER)
