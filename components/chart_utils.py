"""
Pulse360 — shared chart utilities
===================================
Shared helpers used by app.py and all tab components.

Exports:
    dark_layout(fig, title, yaxis_title) → go.Figure
    add_nber(fig, start_date)            → go.Figure
    chart_meta(result, decimals)         → None  (renders st.caption / warnings)
    time_window_start(key)               → str   (ISO date string)
    yoy_pct(series)                      → pd.Series
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.fred_client import fetch_series


# ─────────────────────────────────────────────────────────────────────────────
# Dark layout template
# ─────────────────────────────────────────────────────────────────────────────

def dark_layout(
    fig: go.Figure,
    title: str = "",
    yaxis_title: str = "",
    yaxis2_title: str = "",
) -> go.Figure:
    """Apply Pulse360 dark theme to a Plotly figure."""
    fig.update_layout(
        title         = {"text": title, "font": {"size": 13, "color": "#dddddd"}},
        paper_bgcolor = "rgba(0,0,0,0)",
        plot_bgcolor  = "#0e1117",
        font          = {"color": "#cccccc"},
        xaxis         = {"gridcolor": "#1e1e2e", "color": "#888", "showgrid": True},
        yaxis         = {
            "gridcolor": "#1e1e2e", "color": "#888", "showgrid": True,
            "title": yaxis_title,
        },
        margin        = {"t": 40, "b": 30, "l": 55, "r": 20},
        hovermode     = "x unified",
        legend        = {
            "bgcolor": "rgba(0,0,0,0)", "font": {"color": "#888"},
            "orientation": "h", "y": -0.15,
        },
    )
    if yaxis2_title:
        fig.update_layout(
            yaxis2={"gridcolor": "#1e1e2e", "color": "#888", "title": yaxis2_title,
                    "overlaying": "y", "side": "right", "showgrid": False}
        )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# NBER recession shading
# ─────────────────────────────────────────────────────────────────────────────

def add_nber(fig: go.Figure, start_date: str = "2000-01-01") -> go.Figure:
    """Overlay NBER recession shading on a Plotly figure."""
    usrec = fetch_series("USREC", start_date=start_date)
    if usrec["data"].empty:
        return fig

    in_rec    = False
    rec_start = None
    first     = True

    for dt, val in usrec["data"].items():
        if val == 1 and not in_rec:
            in_rec, rec_start = True, dt
        elif val == 0 and in_rec:
            in_rec = False
            fig.add_vrect(
                x0=rec_start, x1=dt,
                fillcolor="rgba(160,160,160,0.12)",
                layer="below", line_width=0,
                annotation_text="Recession" if first else "",
                annotation_position="top left",
                annotation_font_size=9,
                annotation_font_color="#666",
            )
            first = False

    if in_rec and rec_start is not None:
        fig.add_vrect(
            x0=rec_start, x1=usrec["data"].index[-1],
            fillcolor="rgba(160,160,160,0.12)",
            layer="below", line_width=0,
        )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Chart metadata footer
# ─────────────────────────────────────────────────────────────────────────────

def chart_meta(result: dict, decimals: int = 2) -> None:
    """Render series ID, current value, and staleness info below a chart."""
    if result["last_value"] is not None:
        st.caption(
            f"`{result['series_id']}` · "
            f"Current: **{result['last_value']:.{decimals}f}** · "
            f"As of: {result['last_date']}"
        )
    if result["is_stale"]:
        st.warning(f"⚠️ {result['series_id']}: {result['stale_message']}", icon=None)
    elif result["error"]:
        st.error(f"❌ {result['series_id']}: {result['error']}")


# ─────────────────────────────────────────────────────────────────────────────
# Time window selector
# ─────────────────────────────────────────────────────────────────────────────

def time_window_start(key: str = "window") -> str:
    """
    Render a horizontal radio button (5Y / 10Y / 20Y) and return the
    corresponding ISO start date string.
    """
    today  = date.today()
    choice = st.radio(
        "View",
        options=["5Y", "10Y", "20Y"],
        index=0,
        horizontal=True,
        key=key,
        label_visibility="collapsed",
    )
    offsets = {"5Y": 5 * 365, "10Y": 10 * 365, "20Y": 20 * 365}
    return (today - timedelta(days=offsets[choice])).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────────────────────
# Derived series helpers
# ─────────────────────────────────────────────────────────────────────────────

def yoy_pct(series: pd.Series, periods: int = 12) -> pd.Series:
    """
    Compute year-over-year % change.
    Works on monthly series (periods=12) or quarterly (periods=4).
    """
    return series.pct_change(periods=periods) * 100


def threshold_line(
    fig: go.Figure,
    y: float,
    label: str = "",
    color: str = "#e74c3c",
    dash: str = "dash",
) -> go.Figure:
    """Add a horizontal threshold line to a figure."""
    fig.add_hline(
        y=y,
        line_dash=dash,
        line_color=color,
        line_width=1,
        annotation_text=label,
        annotation_font_color=color,
        annotation_font_size=10,
    )
    return fig
