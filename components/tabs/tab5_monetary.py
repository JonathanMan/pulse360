"""
Pulse360 — Tab 5: Monetary Policy & Financial Conditions
==========================================================
Charts: Live yield curve snapshot, Yield spreads (10Y-3M + 10Y-2Y),
        Fed Funds vs 10Y Treasury, NFCI, IG OAS Credit Spread,
        30Y Mortgage Rate.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from data.fred_client import fetch_series
from components.chart_utils import (
    dark_layout, add_nber, chart_meta, time_window_start, threshold_line
)
from ai.claude_client import get_investment_implications


DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)

# Maturities in order for yield curve snapshot
_YIELD_CURVE_SERIES = [
    ("1M",  "DGS1MO"),
    ("3M",  "DGS3MO"),
    ("6M",  "DGS6MO"),
    ("1Y",  "DGS1"),
    ("2Y",  "DGS2"),
    ("5Y",  "DGS5"),
    ("10Y", "DGS10"),
    ("30Y", "DGS30"),
]


def render_tab5(model_output, phase_output) -> None:
    st.subheader("Monetary Policy & Financial Conditions")

    # ── Time window ───────────────────────────────────────────────────────────
    col_title, col_window = st.columns([5, 1])
    with col_window:
        start = time_window_start("tab5_window")

    # ── Fetch spread and rate data ────────────────────────────────────────────
    t10y3m   = fetch_series("T10Y3M",      start_date=start)
    t10y2y   = fetch_series("T10Y2Y",      start_date=start)
    fedfunds = fetch_series("FEDFUNDS",    start_date=start)
    dgs10    = fetch_series("DGS10",       start_date=start)
    dgs2     = fetch_series("DGS2",        start_date=start)
    nfci     = fetch_series("NFCI",        start_date=start)
    ig_oas   = fetch_series("BAMLC0A0CM",  start_date=start)
    hy_oas   = fetch_series("BAMLH0A0HYM2", start_date=start)
    mortgage = fetch_series("MORTGAGE30US", start_date=start)

    # ── Yield curve snapshot (current) ───────────────────────────────────────
    st.markdown("##### Current Yield Curve Snapshot")
    curve_maturities = []
    curve_yields     = []

    for label, sid in _YIELD_CURVE_SERIES:
        # Use short start date to get latest value efficiently
        res = fetch_series(sid, start_date="2023-01-01")
        if res["last_value"] is not None:
            curve_maturities.append(label)
            curve_yields.append(res["last_value"])

    if curve_maturities:
        # Color by inversion (where short > long)
        colors = []
        for i, y in enumerate(curve_yields):
            if i == 0:
                colors.append("#3498db")
            else:
                colors.append("#e74c3c" if y < curve_yields[i - 1] else "#3498db")

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=curve_maturities, y=curve_yields,
            mode="lines+markers",
            line={"color": "#3498db", "width": 2},
            marker={"color": colors, "size": 8},
            name="Yield Curve",
        ))
        fig = dark_layout(fig, yaxis_title="Yield (%)")
        st.plotly_chart(fig, use_container_width=True, key="tab5_yield_curve")
        st.caption(
            "Red markers = inverted segment (short rate > preceding maturity). "
            f"Fed Funds target: {fedfunds['last_value']:.2f}% · "
            f"10Y Treasury: {dgs10['last_value']:.2f}% · "
            f"2Y–10Y Spread: {t10y2y['last_value']:+.2f}pp" if (
                fedfunds["last_value"] and dgs10["last_value"] and t10y2y["last_value"]
            ) else ""
        )

    # ── Row 2: Yield Spreads | Fed Funds vs 10Y ──────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### Yield Curve Spreads")
        if not t10y3m["data"].empty or not t10y2y["data"].empty:
            fig = go.Figure()
            if not t10y3m["data"].empty:
                fig.add_trace(go.Scatter(
                    x=t10y3m["data"].index, y=t10y3m["data"].values,
                    mode="lines", line={"color": "#3498db", "width": 2},
                    name="10Y – 3M Spread",
                ))
            if not t10y2y["data"].empty:
                fig.add_trace(go.Scatter(
                    x=t10y2y["data"].index, y=t10y2y["data"].values,
                    mode="lines", line={"color": "#9b59b6", "width": 1.5, "dash": "dot"},
                    name="10Y – 2Y Spread",
                ))
            fig = threshold_line(fig, 0, "0 — inversion threshold", "#e74c3c", "dash")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Spread (pp)")
            st.plotly_chart(fig, use_container_width=True, key="tab5_spreads")
        col_a, col_b = st.columns(2)
        with col_a:
            chart_meta(t10y3m, decimals=2)
        with col_b:
            chart_meta(t10y2y, decimals=2)

    with col2:
        st.markdown("##### Fed Funds vs 10Y Treasury")
        if not fedfunds["data"].empty or not dgs10["data"].empty:
            fig = go.Figure()
            if not fedfunds["data"].empty:
                fig.add_trace(go.Scatter(
                    x=fedfunds["data"].index, y=fedfunds["data"].values,
                    mode="lines", line={"color": "#e74c3c", "width": 2},
                    name="Fed Funds Rate",
                ))
            if not dgs10["data"].empty:
                fig.add_trace(go.Scatter(
                    x=dgs10["data"].index, y=dgs10["data"].values,
                    mode="lines", line={"color": "#3498db", "width": 1.5},
                    name="10Y Treasury",
                ))
            if not dgs2["data"].empty:
                fig.add_trace(go.Scatter(
                    x=dgs2["data"].index, y=dgs2["data"].values,
                    mode="lines", line={"color": "#9b59b6", "width": 1.5, "dash": "dot"},
                    name="2Y Treasury",
                ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Yield / Rate (%)")
            st.plotly_chart(fig, use_container_width=True, key="tab5_rates")
        chart_meta(fedfunds, decimals=2)

    # ── Row 3: NFCI | Credit Spreads ─────────────────────────────────────────
    col3, col4 = st.columns(2)

    with col3:
        st.markdown("##### Chicago Fed NFCI (Financial Conditions)")
        if not nfci["data"].empty:
            nfci_val = nfci["last_value"] or 0
            line_color = "#e74c3c" if nfci_val > 0.5 else "#f39c12" if nfci_val > 0 else "#2ecc71"
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=nfci["data"].index, y=nfci["data"].values,
                mode="lines", line={"color": line_color, "width": 2},
                name="NFCI",
                fill="tozeroy", fillcolor="rgba(231,76,60,0.06)",
            ))
            fig = threshold_line(fig, 0, "0 — neutral conditions", "#888", "dash")
            fig = threshold_line(fig, 0.5, "0.5 — tightening", "#f39c12", "dot")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="NFCI Index")
            st.plotly_chart(fig, use_container_width=True, key="tab5_nfci")
        chart_meta(nfci, decimals=2)

    with col4:
        st.markdown("##### Credit Spreads — HY & IG OAS")
        if not hy_oas["data"].empty or not ig_oas["data"].empty:
            fig = go.Figure()
            if not hy_oas["data"].empty:
                fig.add_trace(go.Scatter(
                    x=hy_oas["data"].index, y=hy_oas["data"].values,
                    mode="lines", line={"color": "#e74c3c", "width": 2},
                    name="HY OAS (bps)",
                ))
            if not ig_oas["data"].empty:
                fig.add_trace(go.Scatter(
                    x=ig_oas["data"].index, y=ig_oas["data"].values,
                    mode="lines", line={"color": "#3498db", "width": 1.5, "dash": "dot"},
                    name="IG OAS (bps)",
                ))
            fig = threshold_line(fig, 500, "500 bps HY — stress signal", "#e74c3c", "dot")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="OAS (bps)")
            st.plotly_chart(fig, use_container_width=True, key="tab5_oas")
        col_e, col_f = st.columns(2)
        with col_e:
            chart_meta(hy_oas, decimals=0)
        with col_f:
            chart_meta(ig_oas, decimals=0)

    # ── 30Y Mortgage Rate ─────────────────────────────────────────────────────
    st.markdown("##### 30-Year Mortgage Rate")
    if not mortgage["data"].empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=mortgage["data"].index, y=mortgage["data"].values,
            mode="lines", line={"color": "#1abc9c", "width": 2},
            name="30Y Mortgage Rate",
        ))
        fig = add_nber(fig, start_date=start)
        fig = dark_layout(fig, yaxis_title="Rate (%)")
        st.plotly_chart(fig, use_container_width=True, key="tab5_mortgage")
    chart_meta(mortgage, decimals=2)

    # ── Investment Implications ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=False):
        tab_readings: dict[str, str] = {}
        if t10y3m["last_value"] is not None:
            tab_readings["10Y–3M Spread"] = (
                f"{t10y3m['last_value']:+.2f}pp · "
                f"{'INVERTED' if t10y3m['last_value'] < 0 else 'positive'}"
            )
        if t10y2y["last_value"] is not None:
            tab_readings["10Y–2Y Spread"] = (
                f"{t10y2y['last_value']:+.2f}pp · "
                f"{'INVERTED' if t10y2y['last_value'] < 0 else 'positive'}"
            )
        if fedfunds["last_value"] is not None:
            tab_readings["Fed Funds Rate"] = f"{fedfunds['last_value']:.2f}%"
        if dgs10["last_value"] is not None:
            tab_readings["10Y Treasury Yield"] = f"{dgs10['last_value']:.2f}%"
        if nfci["last_value"] is not None:
            tab_readings["NFCI (Financial Conditions)"] = (
                f"{nfci['last_value']:.2f} · "
                f"{'tight (>0.5)' if nfci['last_value'] > 0.5 else 'slightly tight' if nfci['last_value'] > 0 else 'accommodative'}"
            )
        if hy_oas["last_value"] is not None:
            tab_readings["HY OAS (Credit Spread)"] = (
                f"{hy_oas['last_value']:.0f} bps · "
                f"{'stress signal (>500)' if hy_oas['last_value'] > 500 else 'elevated' if hy_oas['last_value'] > 350 else 'benign'}"
            )
        if ig_oas["last_value"] is not None:
            tab_readings["IG OAS (Credit Spread)"] = f"{ig_oas['last_value']:.0f} bps"
        if mortgage["last_value"] is not None:
            tab_readings["30Y Mortgage Rate"] = f"{mortgage['last_value']:.2f}%"

        if tab_readings:
            with st.spinner("Generating implications…"):
                text = get_investment_implications(
                    tab_key               = "monetary",
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
