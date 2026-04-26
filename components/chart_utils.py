"""
Pulse360 — shared chart utilities
===================================
Shared helpers used by app.py and all tab components.

Exports:
    dark_layout(fig, ...)          → go.Figure   (dark theme + hover + rangeselector)
    add_nber(fig, start_date)      → go.Figure   (NBER recession shading)
    add_end_labels(fig, ...)       → go.Figure   (direct line labels, no legend)
    chart_meta(result, decimals)   → None        (renders st.caption / warnings)
    hover_tmpl(name, ...)          → str         (Tableau-style hovertemplate string)
    time_window_start(key)         → str         (ISO date string, 10Y default)
    yoy_pct(series)                → pd.Series
    threshold_line(fig, ...)       → go.Figure
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.fred_client import fetch_series


# ─────────────────────────────────────────────────────────────────────────────
# Dark layout template  (all three visual upgrades live here)
# ─────────────────────────────────────────────────────────────────────────────

_RANGESELECTOR = {
    "buttons": [
        {"count": 1,  "label": "1Y",  "step": "year", "stepmode": "backward"},
        {"count": 5,  "label": "5Y",  "step": "year", "stepmode": "backward"},
        {"count": 10, "label": "10Y", "step": "year", "stepmode": "backward"},
        {"step": "all", "label": "Max"},
    ],
    "bgcolor":     "#1a1a2e",
    "activecolor": "#3498db",
    "bordercolor": "#444",
    "borderwidth": 1,
    "font":        {"color": "#888", "size": 10},
    "x":           0,
    "xanchor":     "left",
    "y":           1.0,
    "yanchor":     "bottom",
}


def dark_layout(
    fig: go.Figure,
    title: str = "",
    yaxis_title: str = "",
    yaxis2_title: str = "",
    rangeslider: bool = False,
) -> go.Figure:
    """
    Apply Pulse360 dark theme to a Plotly figure.

    Includes:
    - Tableau-style hoverlabel (dark card, white text, left-aligned)
    - Plotly rangeselector buttons (1Y / 5Y / 10Y / Max) on date axes
    - Optional rangeslider (thin scrubber bar beneath chart)
    """
    xaxis_cfg: dict = {
        "gridcolor":     "#1e1e2e",
        "color":         "#888",
        "showgrid":      True,
        "rangeselector": _RANGESELECTOR,
    }
    if rangeslider:
        xaxis_cfg["rangeslider"] = {
            "visible":     True,
            "bgcolor":     "#0e1117",
            "bordercolor": "#333",
            "thickness":   0.05,
        }

    fig.update_layout(
        title        = {"text": title, "font": {"size": 13, "color": "#dddddd"}},
        paper_bgcolor= "rgba(0,0,0,0)",
        plot_bgcolor = "#0e1117",
        font         = {"color": "#cccccc"},
        xaxis        = xaxis_cfg,
        yaxis        = {
            "gridcolor": "#1e1e2e",
            "color":     "#888",
            "showgrid":  True,
            "title":     yaxis_title,
        },
        margin       = {"t": 55, "b": 30, "l": 55, "r": 20},
        hovermode    = "x unified",
        # ── Tableau-style tooltip card ────────────────────────────────────────
        hoverlabel   = {
            "bgcolor":    "#1a1a2e",
            "bordercolor":"#444",
            "font":       {"size": 12, "color": "#ffffff"},
            "align":      "left",
            "namelength": -1,   # never truncate series names
        },
        legend       = {
            "bgcolor":     "rgba(0,0,0,0)",
            "font":        {"color": "#888"},
            "orientation": "h",
            "y":           -0.15,
        },
    )

    if yaxis2_title:
        fig.update_layout(yaxis2={
            "gridcolor": "#1e1e2e",
            "color":     "#888",
            "title":     yaxis2_title,
            "overlaying":"y",
            "side":      "right",
            "showgrid":  False,
        })
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
                annotation_font_color="#555",
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
# Direct end-of-line labels  (replaces legend on multi-trace charts)
# ─────────────────────────────────────────────────────────────────────────────

def add_end_labels(
    fig: go.Figure,
    fmt: str = ".1f",
    unit: str = "",
) -> go.Figure:
    """
    Replace the chart legend with a direct label at the last data point of
    each Scatter trace. Labels use the trace colour so they read as inline.

    Args:
        fig:  The Plotly figure to annotate.
        fmt:  Python format spec for the y value (e.g. ".1f", "+.2f", ",.0f").
        unit: Unit suffix appended to the value (e.g. "%", " bps", "pp").

    Returns:
        The figure with annotations added and legend hidden.
    """
    for trace in fig.data:
        if isinstance(trace, go.Bar):
            continue
        if not hasattr(trace, "x") or trace.x is None or not len(trace.x):
            continue
        if not hasattr(trace, "y") or trace.y is None or not len(trace.y):
            continue

        name = getattr(trace, "name", "") or ""
        if not name:
            continue

        # Walk backwards to find last finite value
        last_x = last_y = None
        for xi, yi in zip(reversed(list(trace.x)), reversed(list(trace.y))):
            if yi is not None and not (isinstance(yi, float) and math.isnan(yi)):
                last_x, last_y = xi, yi
                break
        if last_x is None:
            continue

        # Resolve trace colour
        color = "#cccccc"
        if hasattr(trace, "line") and trace.line and getattr(trace.line, "color", None):
            color = trace.line.color

        try:
            val_str = f"{last_y:{fmt}}{unit}"
        except (ValueError, TypeError):
            val_str = str(last_y)

        fig.add_annotation(
            x           = last_x,
            y           = last_y,
            text        = f"<b>{name}</b><br>{val_str}",
            showarrow   = False,
            xanchor     = "left",
            xshift      = 8,
            align       = "left",
            font        = {"size": 9, "color": color},
            bgcolor     = "rgba(14,17,23,0.85)",
            borderpad   = 3,
            bordercolor = color,
            borderwidth = 0.5,
        )

    fig.update_layout(showlegend=False, margin={"r": 120})
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Tableau-style hover template builder
# ─────────────────────────────────────────────────────────────────────────────

def hover_tmpl(
    name: str,
    y_fmt: str = ",.2f",
    unit: str = "",
    date_fmt: str = "%b %Y",
    context: str = "",
) -> str:
    """
    Build a rich Plotly hovertemplate in Tableau style:
      Series name (bold)
      Value + unit
      Date
      Optional context line (italic)

    Args:
        name:     Series label shown in bold.
        y_fmt:    Format spec for the y value (e.g. ".1f", "+.2f", ",.0f").
        unit:     Suffix after value (e.g. "%", " bps").
        date_fmt: strftime string for the date row.
        context:  Optional interpretive note shown in italic.

    Returns:
        A Plotly hovertemplate string.

    Example:
        hover_tmpl("CPI All Items", y_fmt=".1f", unit="%", context="2% = Fed target")
        → "<b>CPI All Items</b><br>%{y:.1f}%<br>%{x|%b %Y}<br><i>2% = Fed target</i><extra></extra>"
    """
    lines = [
        f"<b>{name}</b>",
        "%{y:" + y_fmt + "}" + unit,
        "%{x|" + date_fmt + "}",
    ]
    if context:
        lines.append(f"<i>{context}</i>")
    lines.append("<extra></extra>")
    return "<br>".join(lines)


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
# Time window selector  (default: 10Y — feeds rangeselector in dark_layout)
# ─────────────────────────────────────────────────────────────────────────────

def time_window_start(key: str = "window") -> str:
    """
    Render a horizontal radio button (5Y / 10Y / 20Y) and return the
    corresponding ISO start date string.

    Default is 10Y so the native Plotly rangeselector (1Y / 5Y / 10Y / Max)
    has enough data to be useful out of the box.
    """
    today  = date.today()
    choice = st.radio(
        "View",
        options  = ["5Y", "10Y", "20Y"],
        index    = 1,          # 10Y default
        horizontal = True,
        key      = key,
        label_visibility = "collapsed",
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
        y                  = y,
        line_dash          = dash,
        line_color         = color,
        line_width         = 1,
        annotation_text    = label,
        annotation_font_color = color,
        annotation_font_size  = 10,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Investment Implications styled card
# ─────────────────────────────────────────────────────────────────────────────

def render_implications(text: str, traffic_light: str = "green") -> None:
    """
    Render an Investment Implications card with a coloured left border keyed
    to the current traffic-light signal (green / yellow / red).

    Splits the raw Haiku output into main body and disclaimer, then renders
    both in a dark card with visual hierarchy:
      - Accent-coloured header label
      - Main analysis at 14px, high contrast
      - Disclaimer small and muted at the bottom

    Args:
        text:          Raw text from get_investment_implications() —
                       main body and optional "\\n\\n---\\n*disclaimer*".
        traffic_light: "green", "yellow", or "red" (defaults to "green").
    """
    accent = {"green": "#2ecc71", "yellow": "#f39c12", "red": "#e74c3c"}.get(
        (traffic_light or "green").lower(), "#3498db"
    )

    # Split on the disclaimer separator injected by prompts.py
    parts    = text.split("\n\n---\n", 1)
    main_md  = parts[0].strip()
    disc_raw = parts[1].strip() if len(parts) > 1 else (
        "Educational macro analysis only — not personalised investment advice. "
        "Consult a licensed financial advisor before making investment decisions."
    )

    # Strip markdown italics from disclaimer (rendered in plain HTML)
    disc_txt = re.sub(r"\*(.+?)\*", r"\1", disc_raw)

    # Convert basic markdown in main body to inline HTML
    main_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", main_md)
    main_html = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         main_html)
    # Preserve paragraph breaks as <br><br>; collapse single newlines
    main_html = re.sub(r"\n{2,}", "<br><br>", main_html)
    main_html = main_html.replace("\n", " ")

    st.markdown(
        f"""<div style="
                background:#13131f;
                border-left:4px solid {accent};
                border-radius:0 8px 8px 0;
                padding:16px 20px 14px 20px;
                margin:4px 0 20px 0;">
            <div style="
                font-size:10px;
                color:{accent};
                font-weight:700;
                letter-spacing:.1em;
                text-transform:uppercase;
                margin-bottom:10px;">
                💡 Investment Implications
            </div>
            <div style="
                font-size:14px;
                color:#e8e8e8;
                line-height:1.8;">
                {main_html}
            </div>
            <div style="
                font-size:10px;
                color:#555;
                margin-top:12px;
                border-top:1px solid #222;
                padding-top:8px;
                font-style:italic;">
                {disc_txt}
            </div>
        </div>""",
        unsafe_allow_html=True,
    )
