"""
Pulse360 — Tab 6: Markets, Valuations & Sentiment
====================================================
Charts: S&P 500 + NASDAQ, VIX, HY/IG OAS credit spreads,
        Wilshire 5000, sector ETF 1-month returns (via yfinance).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from data.fred_client import fetch_series
from data.market_client import fetch_sector_returns, fetch_shiller_cape
from components.chart_utils import (
    dark_layout, add_nber, chart_meta, time_window_start, threshold_line
)
from ai.claude_client import get_investment_implications


DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)


def render_tab6(model_output, phase_output) -> None:
    st.subheader("Markets, Valuations & Sentiment")

    # ── Time window ───────────────────────────────────────────────────────────
    col_title, col_window = st.columns([5, 1])
    with col_window:
        start = time_window_start("tab6_window")

    # ── Fetch data ────────────────────────────────────────────────────────────
    sp500   = fetch_series("SP500",          start_date=start)
    nasdaq  = fetch_series("NASDAQCOM",      start_date=start)
    vix     = fetch_series("VIXCLS",         start_date=start)
    hy_oas  = fetch_series("BAMLH0A0HYM2",   start_date=start)
    ig_oas  = fetch_series("BAMLC0A0CM",     start_date=start)
    w5000   = fetch_series("WILL5000INDFC",  start_date=start)

    # ── Row 1: S&P 500 | VIX ─────────────────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### S&P 500 & NASDAQ")
        if not sp500["data"].empty or not nasdaq["data"].empty:
            fig = go.Figure()
            if not sp500["data"].empty:
                # Normalise to 100 at window start for comparison
                sp_norm = (sp500["data"] / sp500["data"].iloc[0]) * 100
                fig.add_trace(go.Scatter(
                    x=sp_norm.index, y=sp_norm.values,
                    mode="lines", line={"color": "#3498db", "width": 2},
                    name="S&P 500 (rebased)",
                ))
            if not nasdaq["data"].empty:
                nq_norm = (nasdaq["data"] / nasdaq["data"].iloc[0]) * 100
                fig.add_trace(go.Scatter(
                    x=nq_norm.index, y=nq_norm.values,
                    mode="lines", line={"color": "#9b59b6", "width": 1.5, "dash": "dot"},
                    name="NASDAQ (rebased)",
                ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Index (rebased to 100 at start)")
            st.plotly_chart(fig, use_container_width=True, key="tab6_equity")
        col_a, col_b = st.columns(2)
        with col_a:
            chart_meta(sp500, decimals=0)
        with col_b:
            chart_meta(nasdaq, decimals=0)

    with col2:
        st.markdown("##### VIX — Volatility Index")
        if not vix["data"].empty:
            vix_val = vix["last_value"] or 0
            line_color = "#e74c3c" if vix_val > 30 else "#f39c12" if vix_val > 20 else "#2ecc71"
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=vix["data"].index, y=vix["data"].values,
                mode="lines", line={"color": line_color, "width": 2},
                name="VIX",
                fill="tozeroy", fillcolor="rgba(231,76,60,0.06)",
            ))
            fig = threshold_line(fig, 20, "20 — elevated volatility", "#f39c12", "dot")
            fig = threshold_line(fig, 30, "30 — high fear", "#e74c3c", "dash")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="VIX Level")
            st.plotly_chart(fig, use_container_width=True, key="tab6_vix")
        chart_meta(vix, decimals=1)

    # ── Row 2: Credit Spreads ─────────────────────────────────────────────────
    st.markdown("##### Credit Spreads — HY & IG Option-Adjusted Spread")
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
        st.plotly_chart(fig, use_container_width=True, key="tab6_oas")

    col3, col4 = st.columns(2)
    with col3:
        chart_meta(hy_oas, decimals=0)
    with col4:
        chart_meta(ig_oas, decimals=0)

    # ── Row 3: Sector ETF Returns ─────────────────────────────────────────────
    st.markdown("##### Sector ETF Performance — 1-Month Returns")
    sector_data = fetch_sector_returns(period_days=22)

    if sector_data:
        labels  = [v["name"][:20] for v in sector_data.values()]
        returns = [v["return_pct"] for v in sector_data.values()]
        colors  = ["#2ecc71" if r >= 0 else "#e74c3c" for r in returns]

        # Sort by return descending
        sorted_pairs = sorted(zip(returns, labels, colors), reverse=True)
        returns_s, labels_s, colors_s = zip(*sorted_pairs)

        fig = go.Figure(go.Bar(
            x=list(returns_s), y=list(labels_s),
            orientation="h",
            marker_color=list(colors_s),
            name="1-Month Return %",
        ))
        fig.add_vline(x=0, line_dash="dash", line_color="#555", line_width=1)
        fig = dark_layout(fig, yaxis_title="", title="Sector ETF 1-Month Returns")
        fig.update_layout(height=350, margin={"l": 140})
        st.plotly_chart(fig, use_container_width=True, key="tab6_sectors")
        st.caption("Data via yfinance. Returns ≈ 22 trading days (~1 month).")
    else:
        st.info("Sector return data unavailable.")

    # ── Shiller CAPE (if available) ───────────────────────────────────────────
    st.markdown("##### Shiller CAPE Ratio (P/E 10)")
    cape = fetch_shiller_cape()
    if cape is not None and not cape.empty:
        fig = go.Figure()
        # Filter to window start if possible
        cape_filtered = cape[cape.index >= start] if not cape.empty else cape
        if not cape_filtered.empty:
            fig.add_trace(go.Scatter(
                x=cape_filtered.index, y=cape_filtered.values,
                mode="lines", line={"color": "#f39c12", "width": 2},
                name="CAPE",
            ))
            long_run_avg = cape.mean()
            fig = threshold_line(fig, long_run_avg, f"Long-run avg: {long_run_avg:.1f}", "#888", "dot")
            fig = threshold_line(fig, 25, "25 — historically elevated", "#e74c3c", "dot")
            fig = dark_layout(fig, yaxis_title="CAPE Ratio")
            st.plotly_chart(fig, use_container_width=True, key="tab6_cape")
            latest = cape_filtered.iloc[-1] if not cape_filtered.empty else None
            if latest:
                st.caption(f"Shiller CAPE · Current: **{latest:.1f}** · Long-run avg: {long_run_avg:.1f}")
    else:
        st.info("Shiller CAPE data unavailable (requires internet access to Yale).")

    # ── Investment Implications ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=False):
        tab_readings: dict[str, str] = {}
        if sp500["last_value"] is not None:
            tab_readings["S&P 500 Level"] = f"{sp500['last_value']:,.0f}"
        if vix["last_value"] is not None:
            tab_readings["VIX (Volatility)"] = (
                f"{vix['last_value']:.1f} · "
                f"{'high fear (>30)' if vix['last_value'] > 30 else 'elevated (>20)' if vix['last_value'] > 20 else 'calm (<20)'}"
            )
        if hy_oas["last_value"] is not None:
            tab_readings["HY OAS (Credit Spread)"] = (
                f"{hy_oas['last_value']:.0f} bps · "
                f"{'stress signal' if hy_oas['last_value'] > 500 else 'elevated' if hy_oas['last_value'] > 350 else 'benign'}"
            )
        if ig_oas["last_value"] is not None:
            tab_readings["IG OAS (Credit Spread)"] = f"{ig_oas['last_value']:.0f} bps"
        if sector_data:
            best  = max(sector_data.values(), key=lambda v: v["return_pct"])
            worst = min(sector_data.values(), key=lambda v: v["return_pct"])
            tab_readings["Best Sector (1M)"] = f"{best['name']} ({best['return_pct']:+.1f}%)"
            tab_readings["Worst Sector (1M)"] = f"{worst['name']} ({worst['return_pct']:+.1f}%)"
        if cape is not None and not cape.empty and not cape[cape.index >= start].empty:
            tab_readings["Shiller CAPE"] = (
                f"{cape[cape.index >= start].iloc[-1]:.1f} · "
                f"{'elevated (>25)' if cape[cape.index >= start].iloc[-1] > 25 else 'moderate'}"
            )

        if tab_readings:
            with st.spinner("Generating implications…"):
                text = get_investment_implications(
                    tab_key               = "markets",
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
