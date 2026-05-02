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
    dark_layout, add_nber, add_end_labels, chart_meta,
    hover_tmpl, time_window_start, threshold_line, render_implications, render_action_item
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
                sp_norm = (sp500["data"] / sp500["data"].iloc[0]) * 100
                fig.add_trace(go.Scatter(
                    x=sp_norm.index, y=sp_norm.values,
                    mode="lines", line={"color": "#3498db", "width": 2},
                    name="S&P 500",
                    hovertemplate=hover_tmpl(
                        "S&P 500 (rebased to 100)", y_fmt=",.1f",
                        context="100 = start of selected window",
                    ),
                ))
            if not nasdaq["data"].empty:
                nq_norm = (nasdaq["data"] / nasdaq["data"].iloc[0]) * 100
                fig.add_trace(go.Scatter(
                    x=nq_norm.index, y=nq_norm.values,
                    mode="lines", line={"color": "#9b59b6", "width": 1.5, "dash": "dot"},
                    name="NASDAQ",
                    hovertemplate=hover_tmpl(
                        "NASDAQ Composite (rebased to 100)", y_fmt=",.1f",
                        context="100 = start of selected window",
                    ),
                ))
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="Index (rebased to 100 at start)")
            fig = add_end_labels(fig, fmt=",.0f")
            st.plotly_chart(fig, use_container_width=True, key="tab6_equity")
        col_a, col_b = st.columns(2)
        with col_a:
            chart_meta(sp500, decimals=0)
        with col_b:
            chart_meta(nasdaq, decimals=0)

        # ── Action item ──────────────────────────────────────────────────────
        if not sp500["data"].empty and len(sp500["data"]) >= 22:
            _sp_mom = (sp500["data"].iloc[-1] / sp500["data"].iloc[-22] - 1) * 100
            if _sp_mom >= 5:
                render_action_item(f"S&P 500 up {_sp_mom:.1f}% over past month — momentum positive; maintain equity overweight and favour momentum sectors.", "#00a35a")
            elif _sp_mom >= 0:
                render_action_item(f"S&P 500 up {_sp_mom:.1f}% over past month — modest gains; hold positions and watch for breakout or reversal.", "#c98800")
            elif _sp_mom >= -5:
                render_action_item(f"S&P 500 down {abs(_sp_mom):.1f}% over past month — equities under pressure; review support levels before adding.", "#c98800")
            else:
                render_action_item(f"S&P 500 down {abs(_sp_mom):.1f}% over past month — risk-off selloff; increase cash and defensives.", "#d92626")

    with col2:
        st.markdown("##### VIX — Volatility Index")
        if not vix["data"].empty:
            vix_val = vix["last_value"] or 0
            line_color = "#d92626" if vix_val > 30 else "#c98800" if vix_val > 20 else "#00a35a"
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=vix["data"].index, y=vix["data"].values,
                mode="lines", line={"color": line_color, "width": 2},
                name="VIX",
                fill="tozeroy", fillcolor="rgba(231,76,60,0.06)",
            ))
            fig = threshold_line(fig, 20, "20 — elevated volatility", "#c98800", "dot")
            fig = threshold_line(fig, 30, "30 — high fear", "#d92626", "dash")
            fig = add_nber(fig, start_date=start)
            fig = dark_layout(fig, yaxis_title="VIX Level")
            st.plotly_chart(fig, use_container_width=True, key="tab6_vix")
        chart_meta(vix, decimals=1)

        if vix["last_value"] is not None:
            _vv = vix["last_value"]
            if _vv > 30:
                render_action_item(f"VIX at {_vv:.1f} — high fear; historically a contrarian buying opportunity in expansions; defensive in confirmed recessions.", "#d92626")
            elif _vv > 20:
                render_action_item(f"VIX at {_vv:.1f} — elevated; market uncertainty rising; reduce position sizing and review hedges.", "#c98800")
            else:
                render_action_item(f"VIX at {_vv:.1f} — calm; low-volatility environment favours carry strategies and risk-on positioning.", "#00a35a")

    # ── Row 2: Credit Spreads ─────────────────────────────────────────────────
    st.markdown("##### Credit Spreads — HY & IG Option-Adjusted Spread")
    if not hy_oas["data"].empty or not ig_oas["data"].empty:
        fig = go.Figure()
        if not hy_oas["data"].empty:
            fig.add_trace(go.Scatter(
                x=hy_oas["data"].index, y=hy_oas["data"].values,
                mode="lines", line={"color": "#d92626", "width": 2},
                name="HY OAS",
                hovertemplate=hover_tmpl(
                    "High-Yield OAS", y_fmt=",.0f", unit=" bps",
                    context=">500 bps = stress signal",
                ),
            ))
        if not ig_oas["data"].empty:
            fig.add_trace(go.Scatter(
                x=ig_oas["data"].index, y=ig_oas["data"].values,
                mode="lines", line={"color": "#3498db", "width": 1.5, "dash": "dot"},
                name="IG OAS",
                hovertemplate=hover_tmpl(
                    "Investment-Grade OAS", y_fmt=",.0f", unit=" bps",
                    context="Tighter = risk-on",
                ),
            ))
        fig = threshold_line(fig, 500, "500 bps HY — stress signal", "#d92626", "dot")
        fig = add_nber(fig, start_date=start)
        fig = dark_layout(fig, yaxis_title="OAS (bps)")
        fig = add_end_labels(fig, fmt=",.0f", unit=" bps")
        st.plotly_chart(fig, use_container_width=True, key="tab6_oas")

    col3, col4 = st.columns(2)
    with col3:
        chart_meta(hy_oas, decimals=0)
    with col4:
        chart_meta(ig_oas, decimals=0)

    # ── Action item ──────────────────────────────────────────────────────────
    if hy_oas["last_value"] is not None:
        _hv = hy_oas["last_value"]
        if _hv > 500:
            render_action_item(f"HY spreads at {_hv:.0f} bps — stress-level; credit market pricing recession; avoid high-yield.", "#d92626")
        elif _hv > 350:
            render_action_item(f"HY spreads at {_hv:.0f} bps — elevated; reduce HY allocation and extend investment-grade duration.", "#c98800")
        else:
            render_action_item(f"HY spreads at {_hv:.0f} bps — benign; selective high-yield positioning supported.", "#00a35a")

    # ── Row 3: Sector ETF Returns ─────────────────────────────────────────────
    st.markdown("##### Sector ETF Performance — 1-Month Returns")
    sector_data = fetch_sector_returns(period_days=22)   # returns pd.DataFrame

    if not sector_data.empty:
        labels  = sector_data["Sector"].str[:20].tolist()
        returns = sector_data["Return (%)"].tolist()
        colors  = ["#00a35a" if r >= 0 else "#d92626" for r in returns]

        fig = go.Figure(go.Bar(
            x=returns, y=labels,
            orientation="h",
            marker_color=colors,
            name="1-Month Return %",
        ))
        fig.add_vline(x=0, line_dash="dash", line_color="#555", line_width=1)
        fig = dark_layout(fig, yaxis_title="", title="Sector ETF 1-Month Returns")
        fig.update_layout(height=350, margin={"l": 140})
        st.plotly_chart(fig, use_container_width=True, key="tab6_sectors")
        st.caption("Data via yfinance. Returns ≈ 22 trading days (~1 month).")

        if not sector_data.empty:
            _best = sector_data.iloc[0]
            _worst = sector_data.iloc[-1]
            _best_ret = _best["Return (%)"]
            _worst_ret = _worst["Return (%)"]
            if _best_ret > 0:
                render_action_item(f"Leading sector: {_best['Sector']} ({_best_ret:+.1f}%) — rotation into {_best['Sector']} consistent with current cycle phase; laggard: {_worst['Sector']} ({_worst_ret:+.1f}%).", "#00a35a")
            else:
                render_action_item(f"All sectors negative in past month — broad risk-off; defensive positioning across the board warranted.", "#d92626")
    else:
        st.info("Sector return data unavailable.")

    # ── Shiller CAPE (if available) ───────────────────────────────────────────
    st.markdown("##### Shiller CAPE Ratio (P/E 10)")
    cape = fetch_shiller_cape()   # returns dict with "data", "last_value", etc.
    cape_series = cape.get("data", pd.Series(dtype=float))
    if cape["last_value"] is not None and not cape_series.empty:
        fig = go.Figure()
        cape_filtered = cape_series[cape_series.index >= pd.Timestamp(start)]
        if cape_filtered.empty:
            cape_filtered = cape_series
        fig.add_trace(go.Scatter(
            x=cape_filtered.index, y=cape_filtered.values,
            mode="lines", line={"color": "#c98800", "width": 2},
            name="CAPE",
        ))
        long_run_avg = float(cape_series.mean())
        fig = threshold_line(fig, long_run_avg, f"Long-run avg: {long_run_avg:.1f}", "#888", "dot")
        fig = threshold_line(fig, 25, "25 — historically elevated", "#d92626", "dot")
        fig = dark_layout(fig, yaxis_title="CAPE Ratio")
        st.plotly_chart(fig, use_container_width=True, key="tab6_cape")
        st.caption(
            f"Shiller CAPE · Current: **{cape['last_value']:.1f}** · "
            f"Long-run avg: {long_run_avg:.1f} · As of: {cape['last_date']}"
        )

        if cape["last_value"] is not None:
            _cv = cape["last_value"]
            if _cv > 35:
                render_action_item(f"CAPE at {_cv:.1f} — extremely elevated; long-run return expectations historically poor at these levels; reduce equity overweight.", "#d92626")
            elif _cv > 25:
                render_action_item(f"CAPE at {_cv:.1f} — above long-run average; equities richly valued; favour value over growth and tighten stop-losses.", "#c98800")
            else:
                render_action_item(f"CAPE at {_cv:.1f} — near/below long-run average; valuation not a headwind; supports maintaining equity allocation.", "#00a35a")
    else:
        st.info(f"Shiller CAPE data unavailable. {cape.get('error', '')}")

    # ── Investment Implications ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=True):
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
        if not sector_data.empty:
            best_row  = sector_data.iloc[0]
            worst_row = sector_data.iloc[-1]
            tab_readings["Best Sector (1M)"]  = f"{best_row['Sector']} ({best_row['Return (%)']:+.1f}%)"
            tab_readings["Worst Sector (1M)"] = f"{worst_row['Sector']} ({worst_row['Return (%)']:+.1f}%)"
        if cape["last_value"] is not None:
            tab_readings["Shiller CAPE"] = (
                f"{cape['last_value']:.1f} · "
                f"{'elevated (>25)' if cape['last_value'] > 25 else 'moderate'}"
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
            render_implications(text, model_output.traffic_light)
        else:
            st.info("No data available for implications.")

    st.markdown("---")
    st.caption(DISCLAIMER)
