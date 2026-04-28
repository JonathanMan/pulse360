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
    dark_layout, add_nber, chart_meta, time_window_start, render_implications, render_action_item
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

        if usd_broad["last_value"] is not None and not usd_broad["data"].empty:
            _avg = usd_broad["data"].mean()
            if usd_broad["last_value"] > _avg * 1.03:
                render_action_item(f"USD broad index at {usd_broad['last_value']:.1f} — strong dollar; headwind for US multinationals and EM assets; favour domestic US exposure.", "#f39c12")
            elif usd_broad["last_value"] < _avg * 0.97:
                render_action_item(f"USD broad index at {usd_broad['last_value']:.1f} — weak dollar; tailwind for US multinationals and EM equities; consider international diversification.", "#2ecc71")
            else:
                render_action_item(f"USD broad index at {usd_broad['last_value']:.1f} — near long-run average; FX neutral; no major cross-currency headwind or tailwind.", "#2ecc71")

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

        if eur_usd["last_value"] is not None:
            _ev = eur_usd["last_value"]
            if _ev > 1.10:
                render_action_item(f"EUR/USD at {_ev:.4f} — dollar weakness; European equities more competitive; consider EUR-hedged international exposure.", "#2ecc71")
            elif _ev >= 1.0:
                render_action_item(f"EUR/USD at {_ev:.4f} — near parity zone; FX neutral; no significant cross-currency tailwind or headwind.", "#f39c12")
            else:
                render_action_item(f"EUR/USD at {_ev:.4f} — below parity; USD dominance; potential European economic stress; underweight EUR assets.", "#e74c3c")

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

        if jpy_usd["last_value"] is not None:
            _jv = jpy_usd["last_value"]
            if _jv > 145:
                render_action_item(f"USD/JPY at {_jv:.1f} — yen weakness; Japanese exporters benefit but Bank of Japan intervention risk elevated.", "#f39c12")
            elif _jv >= 120:
                render_action_item(f"USD/JPY at {_jv:.1f} — moderate range; yen normalising; Japan equities fairly valued on FX basis.", "#2ecc71")
            else:
                render_action_item(f"USD/JPY at {_jv:.1f} — strong yen; Japanese export competitiveness at risk; underweight Japan exporters.", "#e74c3c")

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

        if brent["last_value"] is not None:
            _bv = brent["last_value"]
            if _bv > 90:
                render_action_item(f"Brent at ${_bv:.0f}/bbl — energy inflation risk elevated; overweight energy sector; monitor consumer spending impact.", "#e74c3c")
            elif _bv >= 60:
                render_action_item(f"Brent at ${_bv:.0f}/bbl — moderate range; energy market balanced; no major inflation shock from oil.", "#f39c12")
            else:
                render_action_item(f"Brent at ${_bv:.0f}/bbl — below $60; weak global demand signal; avoid energy sector; deflation risk elevated.", "#e74c3c")

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

    if commodity["last_value"] is not None and len(commodity["data"]) >= 5:
        _yoy_comm = (commodity["data"].iloc[-1] / commodity["data"].iloc[-5] - 1) * 100
        if _yoy_comm > 10:
            render_action_item(f"Global commodities +{_yoy_comm:.1f}% YoY — real asset inflation hedge; favour commodity producers and materials.", "#f39c12")
        elif _yoy_comm >= -5:
            render_action_item(f"Global commodities {_yoy_comm:+.1f}% YoY — stable; no major inflationary or deflationary commodity shock.", "#2ecc71")
        else:
            render_action_item(f"Global commodities {_yoy_comm:.1f}% YoY — falling sharply; global demand weakness signal; avoid cyclical commodity exposure.", "#e74c3c")

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
