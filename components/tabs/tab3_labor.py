"""
Pulse360 — Tab 3: Labor Market
================================
Charts: Unemployment Rate, Sahm Rule, Nonfarm Payrolls MoM,
        Initial Claims 4-week avg, JOLTS Openings, U-6 Underemployment.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from data.fred_client import fetch_series
from components.chart_utils import dark_layout, add_nber, chart_meta, time_window_start, threshold_line, yoy_pct, render_implications, render_action_item
from ai.claude_client import get_investment_implications


DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)


def render_tab3(model_output, phase_output) -> None:
    st.subheader("Labor Market")

    # ── Time window ───────────────────────────────────────────────────────────
    col_title, col_window = st.columns([5, 1])
    with col_window:
        start = time_window_start("tab3_window")

    # ── Fetch data ────────────────────────────────────────────────────────────
    unrate = fetch_series("UNRATE",        start_date=start)
    sahm   = fetch_series("SAHMREALTIME",  start_date=start)
    payems = fetch_series("PAYEMS",        start_date=start)
    ic4w   = fetch_series("IC4WSA",        start_date=start)
    jolts  = fetch_series("JTSJOL",        start_date=start)
    u6     = fetch_series("U6RATE",        start_date=start)

    # ── Row 1: Unemployment Rate | Sahm Rule ─────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### Unemployment Rate (UNRATE)")
        if not unrate["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=unrate["data"].index, y=unrate["data"].values,
                mode="lines", line={"color": "#3498db", "width": 2},
                name="Unemployment Rate",
            ))
            if not u6["data"].empty:
                # Trim U-6 to same window
                fig.add_trace(go.Scatter(
                    x=u6["data"].index, y=u6["data"].values,
                    mode="lines", line={"color": "#9b59b6", "width": 1.5, "dash": "dot"},
                    name="U-6 Underemployment",
                ))
            fig = threshold_line(fig, 4.0, "4% — cycle trough proxy", "#00a35a", "dot")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="% Unemployed")
            st.plotly_chart(fig, use_container_width=True, key="tab3_unrate")
        chart_meta(unrate, decimals=1)
        if unrate["last_value"] is not None:
            if unrate["last_value"] <= 4.0:
                render_action_item(f"Unemployment at {unrate['last_value']:.1f}% — tight labor market; watch for wage pressure and sustained Fed hawkishness.", "#c98800")
            elif unrate["last_value"] <= 5.0:
                render_action_item(f"Unemployment at {unrate['last_value']:.1f}% — labor market healthy; no immediate recession signal from this metric.", "#00a35a")
            else:
                render_action_item(f"Unemployment at {unrate['last_value']:.1f}% — labor market weakening; defensive positioning and reduced equity risk warranted.", "#d92626")

    with col2:
        st.markdown("##### Sahm Rule Recession Indicator")
        if not sahm["data"].empty:
            sahm_val = sahm["last_value"] or 0
            line_color = "#d92626" if sahm_val >= 0.5 else "#c98800" if sahm_val >= 0.3 else "#00a35a"
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=sahm["data"].index, y=sahm["data"].values,
                mode="lines", line={"color": line_color, "width": 2},
                name="Sahm Rule",
                fill="tozeroy", fillcolor="rgba(231,76,60,0.08)",
            ))
            fig = threshold_line(fig, 0.5, "0.5 — recession trigger", "#d92626", "dash")
            fig = threshold_line(fig, 0.3, "0.3 — warning zone", "#c98800", "dot")
            fig = dark_layout(fig, yaxis_title="Sahm Indicator (pp)")
            st.plotly_chart(fig, use_container_width=True, key="tab3_sahm")
        chart_meta(sahm, decimals=2)
        if sahm["last_value"] is not None:
            if sahm["last_value"] >= 0.5:
                render_action_item(f"Sahm Rule TRIGGERED at {sahm['last_value']:.2f} — recession signal active; shift decisively to defensives and capital preservation.", "#d92626")
            elif sahm["last_value"] >= 0.3:
                render_action_item(f"Sahm Rule at {sahm['last_value']:.2f} — warning zone; trim cyclical exposure and build cash buffer.", "#c98800")
            else:
                render_action_item(f"Sahm Rule at {sahm['last_value']:.2f} — benign; no labor deterioration detected; maintain current positioning.", "#00a35a")

    # ── Row 2: Nonfarm Payrolls MoM | Initial Claims ─────────────────────────
    col3, col4 = st.columns(2)

    with col3:
        st.markdown("##### Nonfarm Payrolls (MoM Change)")
        if not payems["data"].empty:
            mom_payems = payems["data"].diff().dropna()
            colors = ["#00a35a" if v >= 0 else "#d92626" for v in mom_payems.values]
            fig = go.Figure(go.Bar(
                x=mom_payems.index, y=mom_payems.values / 1000,  # convert to thousands
                marker_color=colors,
                name="Payrolls MoM (000s)",
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="#555", line_width=1)
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Change (000s)")
            st.plotly_chart(fig, use_container_width=True, key="tab3_payems")
        chart_meta(payems, decimals=0)
        if not payems["data"].empty and len(payems["data"]) >= 2:
            _pay_mom = payems["data"].diff().iloc[-1] / 1000
            if _pay_mom >= 200:
                render_action_item(f"+{_pay_mom:.0f}K jobs added — strong job creation; consumer spending engine intact; risk assets supported.", "#00a35a")
            elif _pay_mom >= 0:
                render_action_item(f"+{_pay_mom:.0f}K jobs added — moderate growth; expansion continues but momentum moderating; monitor trend.", "#c98800")
            else:
                render_action_item(f"{_pay_mom:.0f}K jobs lost — labor market contracting; defensive rotation and duration extension warranted.", "#d92626")

    with col4:
        st.markdown("##### Initial Claims 4-Week Avg (IC4WSA)")
        if not ic4w["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=ic4w["data"].index, y=ic4w["data"].values / 1000,
                mode="lines", line={"color": "#e67e22", "width": 2},
                name="Initial Claims 4W Avg",
            ))
            fig = threshold_line(fig, 300, "300K — elevated threshold", "#d92626", "dot")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Claims (000s)")
            st.plotly_chart(fig, use_container_width=True, key="tab3_ic4w")
        chart_meta(ic4w, decimals=0)
        if ic4w["last_value"] is not None:
            if ic4w["last_value"] > 300000:
                render_action_item(f"Claims at {ic4w['last_value']/1000:.0f}K — above 300K threshold; labor market stress elevated; watch before adding equity risk.", "#d92626")
            else:
                render_action_item(f"Claims at {ic4w['last_value']/1000:.0f}K — normal range; no meaningful layoff trend; labor market remains supportive.", "#00a35a")

    # ── Row 3: JOLTS Job Openings ─────────────────────────────────────────────
    st.markdown("##### JOLTS Job Openings (JTSJOL)")
    if not jolts["data"].empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=jolts["data"].index, y=jolts["data"].values / 1000,
            mode="lines", line={"color": "#1abc9c", "width": 2},
            name="JOLTS Openings",
            fill="tozeroy", fillcolor="rgba(26,188,156,0.08)",
        ))
        fig = add_nber(fig, start_date=start)
        fig = dark_layout(fig, yaxis_title="Job Openings (000s)")
        st.plotly_chart(fig, use_container_width=True, key="tab3_jolts")
    chart_meta(jolts, decimals=0)
    if jolts["last_value"] is not None:
        _jolts_m = jolts["last_value"] / 1_000_000
        if _jolts_m > 8:
            render_action_item(f"JOLTS openings at {_jolts_m:.1f}M — labor demand strong; wage inflation risk; Fed likely to stay restrictive.", "#c98800")
        elif _jolts_m >= 5:
            render_action_item(f"JOLTS openings at {_jolts_m:.1f}M — labor market rebalancing toward sustainable levels; benign signal.", "#00a35a")
        else:
            render_action_item(f"JOLTS openings at {_jolts_m:.1f}M — labor demand weakening; monitor unemployment rate for follow-through.", "#d92626")

    # ── Investment Implications ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=True):
        tab_readings: dict[str, str] = {}
        if unrate["last_value"] is not None:
            tab_readings["Unemployment Rate (U-3)"] = (
                f"{unrate['last_value']:.1f}% · as of {unrate['last_date']}"
            )
        if u6["last_value"] is not None:
            tab_readings["U-6 Underemployment"] = (
                f"{u6['last_value']:.1f}%"
            )
        if sahm["last_value"] is not None:
            trigger = "TRIGGERED" if sahm["last_value"] >= 0.5 else (
                "warning zone" if sahm["last_value"] >= 0.3 else "normal"
            )
            tab_readings["Sahm Rule Indicator"] = (
                f"{sahm['last_value']:.2f} — {trigger} (0.50 = recession trigger)"
            )
        if payems["last_value"] is not None:
            payems_mom = payems["data"].diff().iloc[-1] / 1000 if not payems["data"].empty else None
            mom_str = f", MoM: {payems_mom:+.1f}K" if payems_mom is not None else ""
            tab_readings["Nonfarm Payrolls (level)"] = (
                f"{payems['last_value']:,.0f}K{mom_str}"
            )
        if ic4w["last_value"] is not None:
            tab_readings["Initial Claims 4-Week Avg"] = (
                f"{ic4w['last_value']:,.0f} · "
                f"{'elevated (>300K)' if ic4w['last_value'] > 300000 else 'normal range'}"
            )
        if jolts["last_value"] is not None:
            tab_readings["JOLTS Job Openings"] = (
                f"{jolts['last_value'] / 1000:.1f}M"
            )

        if tab_readings:
            with st.spinner("Generating implications…"):
                text = get_investment_implications(
                    tab_key               = "labor",
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
