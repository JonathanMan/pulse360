"""
Pulse360 — Tab 8: Global & External Factors
=============================================
Charts: Trade-Weighted USD (broad), USD/EUR exchange rate,
        USD/JPY exchange rate, Brent Crude Oil,
        Global Commodity Price Index.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from data.fred_client import fetch_series
from components.chart_utils import (
    dark_layout, add_nber, chart_meta, time_window_start, render_implications
)
from ai.claude_client import get_investment_implications


DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)


def render_tab8(model_output, phase_output) -> None:
    st.subheader("Global & External Factors")

    # ── Time window ───────────────────────────────────────────────────────────
    col_title, col_window = st.columns([5, 1])
    with col_window:
        start = time_window_start("tab8_window")

    # ── Fetch data ────────────────────────────────────────────────────────────
    usd_broad = fetch_series("DTWEXBGS",       start_date=start)
    eur_usd   = fetch_series("DEXUSEU",        start_date=start)
    jpy_usd   = fetch_series("DEXJPUS",        start_date=start)
    brent     = fetch_series("DCOILBRENTEU",   start_date=start)
    commodity = fetch_series("PALLFNFINDEXQ",  start_date=start)

    # ── Row 1: USD Broad Index | EUR/USD ──────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### Trade-Weighted USD (Broad Index)")
        if not usd_broad["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=usd_broad["data"].index, y=usd_broad["data"].values,
                mode="lines", line={"color": "#3498db", "width": 2},
                name="USD Broad Index",
            ))
            # Add long-run average reference
            avg = usd_broad["data"].mean()
            fig.add_hline(
                y=avg, line_dash="dot", line_color="#555", line_width=1,
                annotation_text=f"Avg: {avg:.1f}",
                annotation_font_color="#666", annotation_font_size=10,
            )
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Index (Jan 2006 = 100)")
            st.plotly_chart(fig, use_container_width=True, key="tab8_usd_broad")
        chart_meta(usd_broad, decimals=2)

    with col2:
        st.markdown("##### EUR/USD Exchange Rate")
        if not eur_usd["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=eur_usd["data"].index, y=eur_usd["data"].values,
                mode="lines", line={"color": "#e67e22", "width": 2},
                name="EUR/USD",
            ))
            fig.add_hline(
                y=1.0, line_dash="dot", line_color="#888", line_width=1,
                annotation_text="Parity (1.00)",
                annotation_font_color="#888", annotation_font_size=10,
            )
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="USD per EUR")
            st.plotly_chart(fig, use_container_width=True, key="tab8_eurusd")
        chart_meta(eur_usd, decimals=4)

    # ── Row 2: USD/JPY | Brent Crude ─────────────────────────────────────────
    col3, col4 = st.columns(2)

    with col3:
        st.markdown("##### USD/JPY Exchange Rate")
        if not jpy_usd["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=jpy_usd["data"].index, y=jpy_usd["data"].values,
                mode="lines", line={"color": "#9b59b6", "width": 2},
                name="USD/JPY",
            ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="JPY per USD")
            st.plotly_chart(fig, use_container_width=True, key="tab8_jpyusd")
        chart_meta(jpy_usd, decimals=2)

    with col4:
        st.markdown("##### Brent Crude Oil ($/bbl)")
        if not brent["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=brent["data"].index, y=brent["data"].values,
                mode="lines", line={"color": "#e74c3c", "width": 2},
                name="Brent Crude",
                fill="tozeroy", fillcolor="rgba(231,76,60,0.06)",
            ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="USD / barrel")
            st.plotly_chart(fig, use_container_width=True, key="tab8_brent")
        chart_meta(brent, decimals=2)

    # ── Global Commodity Index ────────────────────────────────────────────────
    st.markdown("##### Global Commodity Price Index (World Bank / FRED)")
    if not commodity["data"].empty:
        # Normalise to latest 100 for visibility
        norm = (commodity["data"] / commodity["data"].iloc[-1]) * 100
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=norm.index, y=norm.values,
            mode="lines", line={"color": "#1abc9c", "width": 2},
            name="Global Commodity Index (rebased)",
            fill="tozeroy", fillcolor="rgba(26,188,156,0.06)",
        ))
        fig = add_nber(fig, start_date=start)
        fig = dark_layout(fig, yaxis_title="Index (current = 100)")
        st.plotly_chart(fig, use_container_width=True, key="tab8_commodity")
    chart_meta(commodity, decimals=1)

    # ── Metrics row ───────────────────────────────────────────────────────────
    st.markdown("##### Current Readings at a Glance")
    items = [
        ("USD Broad Index", usd_broad, ".2f"),
        ("EUR/USD", eur_usd, ".4f"),
        ("USD/JPY", jpy_usd, ".2f"),
        ("Brent Crude ($/bbl)", brent, ".2f"),
    ]
    cols = st.columns(4)
    for col, (label, res, fmt) in zip(cols, items):
        with col:
            if res["last_value"] is not None:
                st.metric(
                    label=label,
                    value=f"{res['last_value']:{fmt}}",
                    help=f"As of {res['last_date']}",
                )
                if res["is_stale"]:
                    st.caption(f"⚠️ {res['stale_message']}")
            else:
                st.metric(label=label, value="N/A")

    # ── Investment Implications ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=True):
        tab_readings: dict[str, str] = {}
        if usd_broad["last_value"] is not None:
            # Compute rough change context
            data = usd_broad["data"]
            recent_chg = ""
            if len(data) >= 22:
                chg = (data.iloc[-1] / data.iloc[-22] - 1) * 100
                recent_chg = f", 1M chg: {chg:+.1f}%"
            tab_readings["Trade-Weighted USD (Broad)"] = (
                f"{usd_broad['last_value']:.2f}{recent_chg} · "
                f"{'strong (>long-run avg)' if usd_broad['last_value'] > usd_broad['data'].mean() else 'weak'}"
            )
        if eur_usd["last_value"] is not None:
            tab_readings["EUR/USD"] = (
                f"{eur_usd['last_value']:.4f} · "
                f"{'above parity' if eur_usd['last_value'] > 1.0 else 'below parity'}"
            )
        if jpy_usd["last_value"] is not None:
            tab_readings["USD/JPY"] = f"{jpy_usd['last_value']:.2f} JPY per USD"
        if brent["last_value"] is not None:
            tab_readings["Brent Crude Oil"] = f"${brent['last_value']:.2f}/bbl"
        if commodity["last_value"] is not None:
            if len(commodity["data"]) >= 4:
                yoy_comm = (commodity["data"].iloc[-1] / commodity["data"].iloc[-5] - 1) * 100
                tab_readings["Global Commodity Index"] = (
                    f"{commodity['last_value']:.1f} · YoY chg: {yoy_comm:+.1f}%"
                )
            else:
                tab_readings["Global Commodity Index"] = f"{commodity['last_value']:.1f}"

        if tab_readings:
            with st.spinner("Generating implications…"):
                text = get_investment_implications(
                    tab_key               = "global",
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
