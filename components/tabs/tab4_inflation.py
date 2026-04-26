"""
Pulse360 — Tab 4: Inflation & Prices
======================================
Charts: CPI YoY (All + Core), PCE YoY (All + Core),
        Breakeven Inflation (5Y + 10Y), WTI Crude Oil, PPI Final Demand.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from data.fred_client import fetch_series
from components.chart_utils import (
    dark_layout, add_nber, add_end_labels, chart_meta,
    hover_tmpl, time_window_start, threshold_line, yoy_pct
)
from ai.claude_client import get_investment_implications


DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)


def render_tab4(model_output, phase_output) -> None:
    st.subheader("Inflation & Prices")

    # ── Time window ───────────────────────────────────────────────────────────
    col_title, col_window = st.columns([5, 1])
    with col_window:
        start = time_window_start("tab4_window")

    # ── Fetch data ────────────────────────────────────────────────────────────
    cpi      = fetch_series("CPIAUCSL",   start_date=start)
    core_cpi = fetch_series("CPILFESL",   start_date=start)
    pce      = fetch_series("PCEPI",      start_date=start)
    core_pce = fetch_series("PCEPILFE",   start_date=start)
    be5y     = fetch_series("T5YIE",      start_date=start)
    be10y    = fetch_series("T10YIE",     start_date=start)
    wti      = fetch_series("DCOILWTICO", start_date=start)
    ppi      = fetch_series("PPIFIS",     start_date=start)

    # ── Row 1: CPI YoY | PCE YoY ─────────────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### CPI Year-over-Year")
        if not cpi["data"].empty or not core_cpi["data"].empty:
            fig = go.Figure()
            if not cpi["data"].empty:
                cpi_yoy = yoy_pct(cpi["data"]).dropna()
                fig.add_trace(go.Scatter(
                    x=cpi_yoy.index, y=cpi_yoy.values,
                    mode="lines", line={"color": "#e74c3c", "width": 2},
                    name="CPI All Items",
                    hovertemplate=hover_tmpl(
                        "CPI All Items", y_fmt=".1f", unit="%",
                        context="2% = Fed target",
                    ),
                ))
            if not core_cpi["data"].empty:
                core_yoy = yoy_pct(core_cpi["data"]).dropna()
                fig.add_trace(go.Scatter(
                    x=core_yoy.index, y=core_yoy.values,
                    mode="lines", line={"color": "#e67e22", "width": 1.5, "dash": "dot"},
                    name="Core CPI",
                    hovertemplate=hover_tmpl(
                        "Core CPI (ex-food & energy)", y_fmt=".1f", unit="%",
                        context="Fed preferred measure of underlying inflation",
                    ),
                ))
            fig = threshold_line(fig, 2.0, "2% Fed target", "#2ecc71", "dash")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="YoY %")
            fig = add_end_labels(fig, fmt=".1f", unit="%")
            st.plotly_chart(fig, use_container_width=True, key="tab4_cpi")
        col_a, col_b = st.columns(2)
        with col_a:
            chart_meta(cpi, decimals=1)
        with col_b:
            chart_meta(core_cpi, decimals=1)

    with col2:
        st.markdown("##### PCE Year-over-Year")
        if not pce["data"].empty or not core_pce["data"].empty:
            fig = go.Figure()
            if not pce["data"].empty:
                pce_yoy = yoy_pct(pce["data"]).dropna()
                fig.add_trace(go.Scatter(
                    x=pce_yoy.index, y=pce_yoy.values,
                    mode="lines", line={"color": "#9b59b6", "width": 2},
                    name="PCE All Items",
                    hovertemplate=hover_tmpl(
                        "PCE All Items", y_fmt=".1f", unit="%",
                        context="2% = Fed inflation target",
                    ),
                ))
            if not core_pce["data"].empty:
                core_pce_yoy = yoy_pct(core_pce["data"]).dropna()
                fig.add_trace(go.Scatter(
                    x=core_pce_yoy.index, y=core_pce_yoy.values,
                    mode="lines", line={"color": "#8e44ad", "width": 1.5, "dash": "dot"},
                    name="Core PCE",
                    hovertemplate=hover_tmpl(
                        "Core PCE (Fed preferred)", y_fmt=".1f", unit="%",
                        context="Primary Fed inflation gauge",
                    ),
                ))
            fig = threshold_line(fig, 2.0, "2% Fed target", "#2ecc71", "dash")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="YoY %")
            fig = add_end_labels(fig, fmt=".1f", unit="%")
            st.plotly_chart(fig, use_container_width=True, key="tab4_pce")
        col_c, col_d = st.columns(2)
        with col_c:
            chart_meta(pce, decimals=1)
        with col_d:
            chart_meta(core_pce, decimals=1)

    # ── Row 2: Breakeven Inflation ────────────────────────────────────────────
    st.markdown("##### Breakeven Inflation (Market-Implied)")
    if not be5y["data"].empty or not be10y["data"].empty:
        fig = go.Figure()
        if not be5y["data"].empty:
            fig.add_trace(go.Scatter(
                x=be5y["data"].index, y=be5y["data"].values,
                mode="lines", line={"color": "#1abc9c", "width": 2},
                name="5Y Breakeven",
                hovertemplate=hover_tmpl(
                    "5Y Breakeven Inflation", y_fmt=".2f", unit="%",
                    context="Market-implied avg inflation over next 5 years",
                ),
            ))
        if not be10y["data"].empty:
            fig.add_trace(go.Scatter(
                x=be10y["data"].index, y=be10y["data"].values,
                mode="lines", line={"color": "#3498db", "width": 1.5, "dash": "dot"},
                name="10Y Breakeven",
                hovertemplate=hover_tmpl(
                    "10Y Breakeven Inflation", y_fmt=".2f", unit="%",
                    context="Market-implied avg inflation over next 10 years",
                ),
            ))
        fig = threshold_line(fig, 2.0, "2% Fed target", "#2ecc71", "dash")
        fig = threshold_line(fig, 2.5, "2.5% — elevated", "#f39c12", "dot")
        fig = dark_layout(fig, yaxis_title="Implied Inflation (%)")
        fig = add_end_labels(fig, fmt=".2f", unit="%")
        st.plotly_chart(fig, use_container_width=True, key="tab4_breakeven")

    col5, col6 = st.columns(2)
    with col5:
        chart_meta(be5y, decimals=2)
    with col6:
        chart_meta(be10y, decimals=2)

    # ── Row 3: WTI Crude | PPI ────────────────────────────────────────────────
    col7, col8 = st.columns(2)

    with col7:
        st.markdown("##### WTI Crude Oil ($/bbl)")
        if not wti["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=wti["data"].index, y=wti["data"].values,
                mode="lines", line={"color": "#e67e22", "width": 2},
                name="WTI Crude",
                fill="tozeroy", fillcolor="rgba(230,126,34,0.08)",
            ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="USD / barrel")
            st.plotly_chart(fig, use_container_width=True, key="tab4_wti")
        chart_meta(wti, decimals=2)

    with col8:
        st.markdown("##### PPI Final Demand YoY")
        if not ppi["data"].empty:
            ppi_yoy = yoy_pct(ppi["data"]).dropna()
            colors = ["#e74c3c" if v >= 2 else "#2ecc71" for v in ppi_yoy.values]
            fig = go.Figure(go.Bar(
                x=ppi_yoy.index, y=ppi_yoy.values,
                marker_color=colors,
                name="PPI YoY %",
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="#555", line_width=1)
            fig = threshold_line(fig, 2.0, "2%", "#f39c12", "dot")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="YoY %")
            st.plotly_chart(fig, use_container_width=True, key="tab4_ppi")
        chart_meta(ppi, decimals=1)

    # ── Investment Implications ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=False):
        tab_readings: dict[str, str] = {}

        # Compute latest YoY for CPI
        if not cpi["data"].empty:
            cpi_latest_yoy = yoy_pct(cpi["data"]).dropna()
            if not cpi_latest_yoy.empty:
                tab_readings["CPI All Items (YoY)"] = (
                    f"{cpi_latest_yoy.iloc[-1]:.1f}% · "
                    f"{'above' if cpi_latest_yoy.iloc[-1] > 2 else 'at/below'} 2% target"
                )
        if not core_cpi["data"].empty:
            core_cpi_yoy = yoy_pct(core_cpi["data"]).dropna()
            if not core_cpi_yoy.empty:
                tab_readings["Core CPI (YoY)"] = f"{core_cpi_yoy.iloc[-1]:.1f}%"

        if not core_pce["data"].empty:
            core_pce_yoy = yoy_pct(core_pce["data"]).dropna()
            if not core_pce_yoy.empty:
                tab_readings["Core PCE (YoY) — Fed preferred"] = (
                    f"{core_pce_yoy.iloc[-1]:.1f}% · "
                    f"{'above' if core_pce_yoy.iloc[-1] > 2 else 'at/below'} 2% target"
                )
        if be5y["last_value"] is not None:
            tab_readings["5Y Breakeven Inflation"] = (
                f"{be5y['last_value']:.2f}% · "
                f"{'elevated' if be5y['last_value'] > 2.5 else 'anchored'}"
            )
        if be10y["last_value"] is not None:
            tab_readings["10Y Breakeven Inflation"] = f"{be10y['last_value']:.2f}%"
        if wti["last_value"] is not None:
            tab_readings["WTI Crude Oil"] = f"${wti['last_value']:.1f}/bbl"
        if ppi["last_value"] is not None:
            ppi_yoy_last = yoy_pct(ppi["data"]).dropna()
            ppi_yoy_str = f", YoY: {ppi_yoy_last.iloc[-1]:.1f}%" if not ppi_yoy_last.empty else ""
            tab_readings["PPI Final Demand"] = f"{ppi['last_value']:.1f} (index{ppi_yoy_str})"

        if tab_readings:
            with st.spinner("Generating implications…"):
                text = get_investment_implications(
                    tab_key               = "inflation",
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
