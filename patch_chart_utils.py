#!/usr/bin/env python3
"""
patch_chart_utils.py
====================
Applies Terminal Light v2 changes to components/chart_utils.py.

Run from the root of the pulse360 repo:
    python3 patch_chart_utils.py

Makes three targeted string replacements:
  1. _RANGESELECTOR  — black active colour, Geist Mono font, p360 border
  2. dark_layout()   — p360 grid/axis/font colours, Geist Mono tick labels
  3. render_action_item() — sharp corners, mono label, updated colours

Also replaces old Taplox signal colours wherever they appear in chart_utils.py:
  #2ecc71 → #00a35a   (green)
  #f39c12 → #c98800   (amber)
  #e74c3c → #d92626   (red)
  #293241 → #0a0a0a   (primary text)
  #6c757d → #6a6a6a   (secondary text)
  #adb5bd → #a0a0a0   (muted)
  #e9ecef → #ececec   (border)
"""

import re
import sys
from pathlib import Path

CHART_UTILS = Path("components/chart_utils.py")

if not CHART_UTILS.exists():
    print(f"ERROR: {CHART_UTILS} not found. Run from the repo root.")
    sys.exit(1)

src = CHART_UTILS.read_text()
original = src  # keep for diff summary

# ── 1. _RANGESELECTOR ─────────────────────────────────────────────────────────
OLD_RANGESELECTOR = re.compile(
    r'_RANGESELECTOR\s*=\s*\{.*?^\}',
    re.DOTALL | re.MULTILINE,
)

NEW_RANGESELECTOR = '''\
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
}\
'''

src, n = OLD_RANGESELECTOR.subn(NEW_RANGESELECTOR, src, count=1)
print(f"  _RANGESELECTOR: {'✓ patched' if n else '✗ not found — check manually'}")

# ── 2. dark_layout() — fig.update_layout(...) block ──────────────────────────
OLD_UPDATE_LAYOUT = re.compile(
    r'(def dark_layout\b.*?""".*?""".*?)'   # keep signature + docstring
    r'(    xaxis_cfg: dict = \{.*?fig\.update_layout\(.*?\))',
    re.DOTALL,
)

NEW_LAYOUT_BODY = '''\
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
            "bgcolor":     "#fafafa",
            "bordercolor": "#ececec",
            "thickness":   0.04,
        }

    fig.update_layout(
        title        = {"text": title, "font": {"size": 13, "color": "#0a0a0a",
                         "family": "Geist, sans-serif"}, "x": 0, "xanchor": "left"},
        paper_bgcolor= "rgba(0,0,0,0)",
        plot_bgcolor = "rgba(0,0,0,0)",
        font         = {"color": "#0a0a0a", "family": "Geist, sans-serif"},
        xaxis        = xaxis_cfg,
        yaxis        = {
            "gridcolor": "#ececec",
            "color":     "#a0a0a0",
            "tickfont":  {"family": "Geist Mono, monospace", "size": 10, "color": "#a0a0a0"},
            "showgrid":  True,
            "title":     {"text": yaxis_title, "font": {"size": 11, "color": "#6a6a6a"}},
        },
        margin       = {"t": 50, "b": 28, "l": 52, "r": 16},
        hovermode    = "x unified",
        hoverlabel   = {
            "bgcolor":    "#ffffff",
            "bordercolor":"#ececec",
            "font":       {"size": 12, "color": "#0a0a0a",
                           "family": "Geist Mono, monospace"},
            "align":      "left",
            "namelength": -1,
        },
        legend       = {
            "bgcolor":     "rgba(0,0,0,0)",
            "font":        {"color": "#6a6a6a", "size": 11,
                            "family": "Geist Mono, monospace"},
            "orientation": "h",
            "y":           -0.15,
        },
    )\
'''

# Simpler, safer approach: replace just the xaxis_cfg block + fig.update_layout call
OLD_XAXIS_TO_LAYOUT = re.compile(
    r'    xaxis_cfg: dict = \{[^}]+\}(?:\s+if rangeslider:.*?}\s+})?'
    r'\s+fig\.update_layout\([^)]*(?:\([^)]*\)[^)]*)*\)',
    re.DOTALL,
)
src, n = OLD_XAXIS_TO_LAYOUT.subn(NEW_LAYOUT_BODY, src, count=1)
print(f"  dark_layout body: {'✓ patched' if n else '✗ not found — check manually'}")

# ── 3. render_action_item() ───────────────────────────────────────────────────
OLD_ACTION_ITEM = re.compile(
    r'(def render_action_item\(.*?\).*?""".*?""")'
    r'(.*?st\.markdown\(.*?\),\s*unsafe_allow_html=True\s*\))',
    re.DOTALL,
)

NEW_ACTION_BODY = '''
    import streamlit as _st
    clean = text.lstrip("→ ").strip()
    _st.markdown(
        f"""
        <div style="
            background: {color}0f;
            border: 1px solid {color}44;
            border-left: 2px solid {color};
            border-radius: 0;
            padding: 10px 14px;
            margin: 10px 0 0 0;
            font-size: 13px;
            line-height: 1.55;
            color: #0a0a0a;
        ">
            <span style="
                font-family: 'Geist Mono', monospace;
                font-weight: 600;
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.14em;
                color: {color};
                margin-right: 10px;
            ">Action</span>{clean}
        </div>
        """,
        unsafe_allow_html=True,
    )'''

src, n = OLD_ACTION_ITEM.subn(lambda m: m.group(1) + NEW_ACTION_BODY, src, count=1)
print(f"  render_action_item: {'✓ patched' if n else '✗ not found — check manually'}")

# ── 4. Global colour substitutions ───────────────────────────────────────────
colour_map = {
    "#293241": "#0a0a0a",   # primary text
    "#6c757d": "#6a6a6a",   # secondary
    "#adb5bd": "#a0a0a0",   # muted
    "#e9ecef": "#ececec",   # border
    "#2ecc71": "#00a35a",   # green signal
    "#f39c12": "#c98800",   # amber signal
    "#e74c3c": "#d92626",   # red signal
    "#3b7ddd": "#0a0a0a",   # Taplox blue → black
    "#e8f1fb": "#f4f4f4",   # Taplox blue-light → subtle-bg
}

for old, new in colour_map.items():
    count = src.count(old)
    src = src.replace(old, new)
    if count:
        print(f"  colour {old} → {new}: {count} replacement(s)")

# ── Write result ──────────────────────────────────────────────────────────────
if src != original:
    CHART_UTILS.write_text(src)
    print(f"\n✓ {CHART_UTILS} updated successfully.")
else:
    print("\n⚠ No changes made — patterns may not have matched. Review manually.")
