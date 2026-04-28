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
from components.chart_utils import dark_layout, add_nber, chart_meta, time_window_start, threshold_line, render_implications, render_action_item
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
    adxtno = fetch_series("ADXTNO",  start_date=start)
    # Note: NAPM (ISM Mfg PMI) and NMFCI (ISM Services PMI) were removed from
    # FRED by ISM due to data licensing restrictions (~2024). Not fetchable.

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
        if indpro["last_value"] is not None and len(indpro["data"]) >= 2:
            _ip_trend = indpro["data"].iloc[-1] - indpro["data"].iloc[-2]
            if _ip_trend > 0:
                render_action_item("Industrial output expanding — supports cyclical exposure; materials and industrials historically outperform.", "#2ecc71")
            else:
                render_action_item("Industrial output contracting — reduce cyclical exposure; watch for sustained decline as a recession precursor.", "#e74c3c")

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
        if tcu["last_value"] is not None:
            if tcu["last_value"] >= 80:
                render_action_item(f"Utilization at {tcu['last_value']:.1f}% — near full capacity; watch for inflationary pressure and margin compression.", "#f39c12")
            elif tcu["last_value"] >= 75:
                render_action_item(f"Utilization at {tcu['last_value']:.1f}% — healthy growth without overheating; no capacity constraint concerns.", "#2ecc71")
            else:
                render_action_item(f"Utilization at {tcu['last_value']:.1f}% — significant slack in the economy; conditions support accommodative policy.", "#e74c3c")

    # ── Row 2: ISM PMI notice ─────────────────────────────────────────────────
    st.markdown("##### ISM PMI — Manufacturing &amp; Services")
    st.markdown(
        """
        <div style="background:#1a1a2e; border:1px solid #444; border-left:3px solid #f39c12;
                    border-radius:6px; padding:12px 16px; color:#bbb; font-size:13px;">
            <strong style="color:#f39c12;">⚠ Data unavailable via FRED</strong><br>
            ISM removed its Manufacturing and Services PMI data from the FRED API in 2024
            due to licensing restrictions. These series (<code>NAPM</code>, <code>NMFCI</code>)
            can no longer be fetched programmatically for free.<br><br>
            <strong style="color:#ccc;">Alternatives:</strong>
            The <strong>Industrial Production Index</strong> (row above) and
            <strong>Durable Goods Orders</strong> (row below) capture overlapping manufacturing
            cycle signals. For live PMI data, see
            <a href="https://www.ismworld.org" target="_blank" style="color:#3498db;">ismworld.org</a>
            or subscribe to a data vendor.
        </div>
        """,
        unsafe_allow_html=True,
    )

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
    if not adxtno["data"].empty and len(adxtno["data"]) >= 2:
        _dg_mom = adxtno["data"].pct_change().iloc[-1] * 100
        if _dg_mom >= 1.0:
            render_action_item(f"Durable goods orders +{_dg_mom:.1f}% MoM — business investment expanding; supports industrials and capex-linked equities.", "#2ecc71")
        elif _dg_mom >= 0:
            render_action_item(f"Durable goods orders +{_dg_mom:.1f}% MoM — capex momentum stalling; watch for consecutive months of weakness.", "#f39c12")
        else:
            render_action_item(f"Durable goods orders {_dg_mom:.1f}% MoM — capex contraction signal; reduce industrials exposure and monitor trend.", "#e74c3c")

    # ── Investment Implications ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=True):
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
        # ISM PMI (NAPM, NMFCI) no longer available via FRED — omitted from AI context
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
            render_implications(text, model_output.traffic_light)
        else:
            st.info("No data available for implications.")

    st.markdown("---")
    st.caption(DISCLAIMER)
