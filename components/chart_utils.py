"""
Pulse360 — shared chart utilities
===================================
Shared helpers used by app.py and all tab components.

Exports:
    dark_layout(fig, ...)          → go.Figure   (light theme + hover + rangeselector)
    add_nber(fig, start_date)      → go.Figure   (NBER recession shading)
    add_end_labels(fig, ...)       → go.Figure   (direct line labels, no legend)
    chart_meta(result, decimals)   → None        (renders metadata + percentile + deltas)
    hover_tmpl(name, ...)          → str         (Tableau-style hovertemplate string)
    time_window_start(key)         → str         (ISO date string, 10Y default)
    yoy_pct(series)                → pd.Series
    threshold_line(fig, ...)       → go.Figure
    render_action_item(text, color)→ None        (styled action-item card below charts)
    percentile_rank(series, value) → float|None  (0–100 percentile of current value)
    render_percentile_badge(pctile)→ None        (standalone percentile pill widget)
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
    "bgcolor":     "#ffffff",
    "activecolor": "#0a0a0a",
    "bordercolor": "#ececec",
    "borderwidth": 1,
    "font":        {"color": "#a0a0a0", "size": 9, "family": "Geist Mono, monospace"},
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
        "gridcolor":     "#ececec",
        "color":         "#a0a0a0",
        "tickfont":      {"family": "Geist Mono, monospace", "size": 10, "color": "#a0a0a0"},
        "showgrid":      True,
        "rangeselector": _RANGESELECTOR,
    }
    if rangeslider:
        xaxis_cfg["rangeslider"] = {
            "visible":     True,
            "bgcolor":     "#ffffff",
            "bordercolor": "#ececec",
            "thickness":   0.05,
        }

    fig.update_layout(
        title        = {"text": title, "font": {"size": 13, "color": "#0a0a0a"}},
        paper_bgcolor= "rgba(0,0,0,0)",
        plot_bgcolor = "rgba(0,0,0,0)",
        font         = {"color": "#0a0a0a"},
        xaxis        = xaxis_cfg,
        yaxis        = {
            "gridcolor": "#ececec",
            "color":     "#6a6a6a",
            "showgrid":  True,
            "title":     yaxis_title,
        },
        margin       = {"t": 55, "b": 30, "l": 55, "r": 20},
        hovermode    = "x unified",
        # ── Tableau-style tooltip card ────────────────────────────────────────
        hoverlabel   = {
            "bgcolor":    "#ffffff",
            "bordercolor":"#ececec",
            "font":       {"size": 12, "color": "#0a0a0a", "family": "Geist Mono, monospace"},
            "align":      "left",
            "namelength": -1,   # never truncate series names
        },
        legend       = {
            "bgcolor":     "rgba(0,0,0,0)",
            "font":        {"color": "#6a6a6a"},
            "orientation": "h",
            "y":           -0.15,
        },
    )

    if yaxis2_title:
        fig.update_layout(yaxis2={
            "gridcolor": "#ececec",
            "color":     "#6a6a6a",
            "title":     yaxis2_title,
            "overlaying":"y",
            "side":      "right",
            "showgrid":  False,
        })

    fig.update_xaxes(tickfont=dict(family="Geist Mono, monospace", size=10, color="#a0a0a0"))
    fig.update_yaxes(tickfont=dict(family="Geist Mono, monospace", size=10, color="#a0a0a0"))
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
        color = "#495057"
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
            bgcolor     = "rgba(255,255,255,0.92)",
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
# Percentile ranking utilities
# ─────────────────────────────────────────────────────────────────────────────

def percentile_rank(series: pd.Series, value: float | None = None) -> float | None:
    """
    Compute the percentile rank (0–100) of the last — or a specified — value
    within the full distribution of `series`.

    Uses a rank-style percentile: fraction of observations ≤ the target value.
    Requires at least 20 non-NaN data points to return a meaningful result.

    Args:
        series: pd.Series of historical values (DatetimeIndex, float).
        value:  Override the target value; defaults to series.iloc[-1].

    Returns:
        Float 0–100, or None if data is insufficient.
    """
    clean = series.dropna()
    if len(clean) < 20:
        return None
    try:
        v = float(clean.iloc[-1]) if value is None else float(value)
        pct = float((clean <= v).sum()) / len(clean) * 100
        return round(pct, 1)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Period-over-period delta utilities  (MoM / QoQ / 1W / 1D  +  YoY)
# ─────────────────────────────────────────────────────────────────────────────

def _infer_frequency(series: pd.Series) -> str:
    """
    Infer the observation frequency of a FRED series from the median gap
    between consecutive data points.

    Returns one of: "daily", "weekly", "monthly", "quarterly", "unknown".
    """
    if len(series) < 3 or not isinstance(series.index, pd.DatetimeIndex):
        return "unknown"
    gaps = series.index.to_series().diff().dropna().dt.days
    median_gap = gaps.median()
    if median_gap <= 3:
        return "daily"
    if median_gap <= 10:
        return "weekly"
    if median_gap <= 50:
        return "monthly"
    return "quarterly"


def _delta_badge_html(label: str, delta: float, decimals: int = 2) -> str:
    """
    Return an inline HTML delta badge: coloured ▲/▼ value + period label.

    Args:
        label:    Period label, e.g. "MoM", "YoY", "QoQ", "1W".
        delta:    Absolute change (same units as the series value).
        decimals: Decimal places for formatting (mirrors chart_meta decimals).

    Colour convention (direction-neutral for the label; value drives colour):
        positive → green  (#28a745)
        negative → red    (#d92626)
        zero     → muted  (#6a6a6a)
    """
    if delta > 0:
        arrow, color = "▲", "#28a745"
    elif delta < 0:
        arrow, color = "▼", "#d92626"
    else:
        arrow, color = "─", "#6a6a6a"

    formatted = f"{delta:+.{decimals}f}"
    return (
        f'<span style="display:inline-flex;align-items:center;gap:1px;'
        f'font-size:0.70rem;font-weight:600;color:{color};margin-left:7px;">'
        f'{arrow}&thinsp;{formatted}'
        f'<span style="font-weight:400;color:#6a6a6a;margin-left:2px;">{label}</span>'
        f'</span>'
    )


def _pctile_badge_html(pctile: float) -> str:
    """
    Return an inline HTML pill string for the given percentile rank.

    Colour coding (direction-neutral — flags historical extremes):
      P0–P10   / P90–P100  → amber  (unusual low / unusual high)
      P10–P25  / P75–P90   → blue   (below / above average)
      P25–P75              → green  (normal range)
    """
    p = round(pctile)
    if p <= 10 or p >= 90:
        bg, border, color = "#fff8e5", "#c98800", "#7a5000"
        label = f"P{p} ⚡"
    elif p <= 25 or p >= 75:
        bg, border, color = "#f4f4f4", "#0a0a0a", "#1a4a8a"
        label = f"P{p}"
    else:
        bg, border, color = "#e8f8ee", "#28a745", "#1a5c30"
        label = f"P{p}"

    return (
        f'<span title="Percentile rank: current value is higher than {p}% '
        f'of all historical observations in this window" '
        f'style="display:inline-flex;align-items:center;'
        f'background:{bg};border:1px solid {border};border-radius:999px;'
        f'padding:1px 7px;font-size:0.70rem;font-weight:700;color:{color};'
        f'margin-left:6px;cursor:default;">'
        f'{label}</span>'
    )


def render_percentile_badge(pctile: float, prefix: str = "") -> None:
    """
    Render a standalone percentile pill badge via st.markdown().

    Useful for placing a badge anywhere outside of chart_meta() —
    e.g. in the Overview Row or next to a metric tile.

    Args:
        pctile: Float 0–100 from percentile_rank().
        prefix: Optional text rendered before the pill (plain text).
    """
    html = f'<span style="font-size:0.8rem;color:#6a6a6a;">{prefix}</span>' if prefix else ""
    html += _pctile_badge_html(pctile)
    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Chart metadata footer
# ─────────────────────────────────────────────────────────────────────────────

def chart_meta(result: dict, decimals: int = 2) -> None:
    """
    Render a rich metadata line below every chart:

        SERIES_ID · Current: X.XX  ▲ +Y MoM  ▼ -Z YoY  P42

    Components (all auto-computed from result["data"]):
      • Series ID chip + current value + as-of date
      • Short-period delta badge (MoM / QoQ / 1W / 1D) — absolute change
      • Year-over-year delta badge — absolute change
      • Percentile rank pill (P0–P100, colour-coded by extremity)

    Stale / error warnings are rendered below if present.

    Args:
        result:   Dict returned by fetch_series().
        decimals: Decimal places for current value AND delta formatting.
    """
    if result["last_value"] is not None:
        series_data: pd.Series | None = result.get("data")
        delta_html  = ""
        pctile_html = ""

        if series_data is not None and not series_data.empty:
            clean = series_data.dropna()

            # ── Delta badges ──────────────────────────────────────────────────
            if len(clean) >= 2:
                freq = _infer_frequency(clean)
                last = float(clean.iloc[-1])

                # Short-period delta
                _short_label = {"daily": "1D", "weekly": "1W",
                                "monthly": "MoM", "quarterly": "QoQ"}.get(freq)
                if _short_label:
                    short_delta = last - float(clean.iloc[-2])
                    delta_html += _delta_badge_html(_short_label, short_delta, decimals)

                # YoY delta (look back ~1 year worth of observations)
                _yoy_n = {"daily": 252, "weekly": 52,
                          "monthly": 12, "quarterly": 4}.get(freq, 12)
                if len(clean) > _yoy_n:
                    yoy_delta = last - float(clean.iloc[-(_yoy_n + 1)])
                    delta_html += _delta_badge_html("YoY", yoy_delta, decimals)

            # ── Percentile badge ──────────────────────────────────────────────
            pct = percentile_rank(clean)
            if pct is not None:
                pctile_html = _pctile_badge_html(pct)

        st.markdown(
            f'<span style="font-size:0.78rem;color:#6a6a6a;">'
            f'<code style="font-size:0.75rem;background:#f4f4f4;'
            f'border:1px solid #ececec;border-radius:4px;padding:1px 5px;'
            f'color:#0a0a0a;">{result["series_id"]}</code>'
            f'&nbsp;·&nbsp;Current:&nbsp;'
            f'<strong style="color:#0a0a0a;">{result["last_value"]:.{decimals}f}</strong>'
            f'&nbsp;·&nbsp;As&nbsp;of:&nbsp;{result["last_date"]}'
            f'{delta_html}'
            f'{pctile_html}</span>',
            unsafe_allow_html=True,
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
    color: str = "#d92626",
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
    Render an Investment Implications callout using Streamlit's native alert
    components, colour-keyed to the traffic-light signal.

    Green  → st.success  (green card)
    Yellow → st.warning  (amber card)
    Red    → st.error    (red card)

    The disclaimer is separated from the main body and rendered as a small
    st.caption below the card.

    Args:
        text:          Raw text from get_investment_implications() —
                       main body + optional "\\n\\n---\\n*disclaimer*".
        traffic_light: "green", "yellow", or "red" (defaults to "green").
    """
    # Split body from disclaimer at the separator injected by prompts.py
    parts    = text.split("\n\n---\n", 1)
    main_md  = parts[0].strip()
    disc_raw = parts[1].strip() if len(parts) > 1 else (
        "Educational macro analysis only — not personalised investment advice. "
        "Consult a licensed financial advisor before making investment decisions."
    )
    disc_txt = re.sub(r"\*(.+?)\*", r"\1", disc_raw)

    tl = (traffic_light or "green").lower()
    if tl == "red":
        st.error(main_md,    icon="💡")
    elif tl == "yellow":
        st.warning(main_md,  icon="💡")
    else:
        st.success(main_md,  icon="💡")

    st.caption(f"*{disc_txt}*")


# ─────────────────────────────────────────────────────────────────────────────
# Action-item card  (signal-coloured callout below charts and sections)
# ─────────────────────────────────────────────────────────────────────────────

def render_action_item(text: str, color: str = "#c98800") -> None:
    """
    Render a styled action-item card below a chart or dashboard section.

    Displays a left-accent card with a bold "Action" label in the signal
    colour and white body text — larger and more visually distinct than a
    plain st.caption().

    Args:
        text:  The action message. Leading "→ " is stripped automatically.
        color: Hex accent colour, typically signal-matched:
               "#00a35a" green · "#c98800" amber · "#d92626" red
    """
    clean = text.lstrip("→ ").strip()
    st.markdown(
        f"""
        <div style="
            background: {color}12;
            border: 1px solid {color}55;
            border-left: 3px solid {color};
            border-radius: 0;
            padding: 10px 16px;
            margin: 10px 0 6px 0;
        ">
            <span style="color:{color}; font-weight:700; font-size:13px; margin-right:6px;">
                Action
            </span>
            <span style="color:#0a0a0a; font-size:13px; line-height:1.6;">
                {clean}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
