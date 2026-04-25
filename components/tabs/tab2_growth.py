"""
Pulse360 — Tab 2: Growth & Business Activity
=============================================
Charts: Industrial Production, Capacity Utilization,
        ISM Manufacturing + Services PMI, Durable Goods Orders.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from data.fred_client import fetch_series
from components.chart_utils import dark_layout, add_nber, chart_meta, time_window_start, threshold_line
from ai.claude_client import get_investment_implications


DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)


def render_tab2(model_output, phase_output) -> None:
    st.subheader("Growth & Business Activity")

    # ── Time window ───────────────────────────────────────────────────────────
    col_title, col_window = st.columns([5, 1])
    with col_window:
        start = time_window_start("tab2_window")

    # ── Fetch data ────────────────────────────────────────────────────────────
    indpro = fetch_series("INDPRO",  start_date=start)
    tcu    = fetch_series("TCU",     start_date=start)
    napm   = fetch_series("NAPM",    start_date=start)
    nmfci  = fetch_series("NMFCI",   start_date=start)
    adxtno = fetch_series("ADXTNO",  start_date=start)

    # ── Row 1: Industrial Production | Capacity Utilization ──────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### Industrial Production (INDPRO)")
        if not indpro["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=indpro["data"].index, y=indpro["data"].values,
                mode="lines", line={"color": "#3498db", "width": 2},
                name="Industrial Production",
            ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Index (2017=100)")
            st.plotly_chart(fig, use_container_width=True, key="tab2_indpro")
        chart_meta(indpro, decimals=1)

    with col2:
        st.markdown("##### Capacity Utilization (TCU)")
        if not tcu["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=tcu["data"].index, y=tcu["data"].values,
                mode="lines", line={"color": "#2ecc71", "width": 2},
                name="Capacity Utilization",
            ))
            fig = threshold_line(fig, 80, "80% — historical ceiling", "#e67e22", "dot")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="% of Capacity")
            st.plotly_chart(fig, use_container_width=True, key="tab2_tcu")
        chart_meta(tcu, decimals=1)

    # ── Row 2: ISM Manufacturing + Services PMI ───────────────────────────────
    st.markdown("##### ISM PMI — Manufacturing vs Services")
    if not napm["data"].empty or not nmfci["data"].empty:
        fig = go.Figure()
        if not napm["data"].empty:
            fig.add_trace(go.Scatter(
                x=napm["data"].index, y=napm["data"].values,
                mode="lines", line={"color": "#3498db", "width": 2},
                name="ISM Manufacturing",
            ))
        if not nmfci["data"].empty:
            fig.add_trace(go.Scatter(
                x=nmfci["data"].index, y=nmfci["data"].values,
                mode="lines", line={"color": "#e67e22", "width": 2, "dash": "dot"},
                name="ISM Services",
            ))
        fig = threshold_line(fig, 50, "50 — expansion/contraction", "#e74c3c", "dash")
        fig = add_nber(fig, start_date=start)
        fig = dark_layout(fig, yaxis_title="PMI Index")
        st.plotly_chart(fig, use_container_width=True, key="tab2_ism")

    col3, col4 = st.columns(2)
    with col3:
        chart_meta(napm, decimals=1)
    with col4:
        chart_meta(nmfci, decimals=1)

    # ── Row 3: Durable Goods Orders ───────────────────────────────────────────
    st.markdown("##### Durable Goods Orders ex-Defense ex-Aircraft (ADXTNO)")
    if not adxtno["data"].empty:
        mom = adxtno["data"].pct_change() * 100
        colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in mom.values]
        fig = go.Figure(go.Bar(
            x=mom.index, y=mom.values,
            marker_color=colors,
            name="Durable Goods MoM %",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="#555", line_width=1)
        fig = add_nber(fig, start_date=start)
        fig = dark_layout(fig, yaxis_title="% Month-over-Month")
        st.plotly_chart(fig, use_container_width=True, key="tab2_durable")
    chart_meta(adxtno, decimals=1)

    # ── Investment Implications ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=False):
        tab_readings: dict[str, str] = {}
        if indpro["last_value"] is not None:
            tab_readings["Industrial Production (INDPRO)"] = (
                f"{indpro['last_value']:.1f} (index 2017=100) · as of {indpro['last_date']}"
            )
        if tcu["last_value"] is not None:
            tab_readings["Capacity Utilization (TCU)"] = (
                f"{tcu['last_value']:.1f}% · "
                f"{'above 80% ceiling' if tcu['last_value'] >= 80 else 'below 80% ceiling'}"
            )
        if napm["last_value"] is not None:
            tab_readings["ISM Manufacturing PMI"] = (
                f"{napm['last_value']:.1f} · "
                f"{'expansion' if napm['last_value'] > 50 else 'contraction'} territory"
            )
        if nmfci["last_value"] is not None:
            tab_readings["ISM Services PMI"] = (
                f"{nmfci['last_value']:.1f} · "
                f"{'expansion' if nmfci['last_value'] > 50 else 'contraction'} territory"
            )
        if adxtno["last_value"] is not None:
            tab_readings["Durable Goods ex-def ex-aircraft"] = (
                f"{adxtno['last_value']:.1f} (level)"
            )

        if tab_readings:
            with st.spinner("Generating implications…"):
                text = get_investment_implications(
                    tab_key               = "growth",
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
