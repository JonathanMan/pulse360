"""
Pulse360 — Scenario Simulator
================================
Adjust any of the 7 model inputs via sliders and watch the recession
probability update in real time. Use preset scenarios to jump to
historical stress episodes, or build a custom hypothetical.

The "Analyse this scenario" button streams a Claude Haiku interpretation
of whatever combination you have dialled in.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from models.recession_model import (
    _stress_t10y3m,
    _stress_sahm,
    _stress_cfnai,
    _stress_nfci,
    _stress_claims_yoy,
    _stress_hy_oas,
    _stress_ism,
)
from ai.claude_client import stream_scenario_analysis

st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .main .block-container { padding-top: 1rem; max-width: 1400px; }
    div[data-testid="metric-container"] {
        background: #1a1a2e; border-radius: 8px;
        padding: 12px 16px; border: 1px solid #333;
    }
    .stExpander { border: 1px solid #333 !important; border-radius: 8px !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("# 🎛️ Scenario Simulator")
st.caption(
    "Adjust any input to see how the recession probability responds · "
    "Hit 'Analyse' to get a Claude interpretation of the scenario"
)

DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Pulse360 is not a Registered Investment Advisor.*"
)

# ── Feature configuration ─────────────────────────────────────────────────────
# Mirrors _FEATURES in recession_model.py — weights must match exactly

_FEAT_CFG = [
    {
        "id":      "t10y3m",
        "name":    "10Y–3M Treasury Spread",
        "weight":  0.30,
        "unit":    "%",
        "min":     -3.0,
        "max":     3.0,
        "step":    0.05,
        "fn":      _stress_t10y3m,
        "fmt":     lambda v: f"{v:+.2f}%",
    },
    {
        "id":      "sahm",
        "name":    "Sahm Rule",
        "weight":  0.20,
        "unit":    "",
        "min":     0.0,
        "max":     1.5,
        "step":    0.01,
        "fn":      _stress_sahm,
        "fmt":     lambda v: f"{v:.2f}",
    },
    {
        "id":      "cfnai",
        "name":    "CFNAI (3-month avg)",
        "weight":  0.15,
        "unit":    "",
        "min":     -3.0,
        "max":     3.0,
        "step":    0.05,
        "fn":      _stress_cfnai,
        "fmt":     lambda v: f"{v:+.2f}",
    },
    {
        "id":      "nfci",
        "name":    "Chicago Fed NFCI",
        "weight":  0.10,
        "unit":    "",
        "min":     -1.5,
        "max":     2.0,
        "step":    0.05,
        "fn":      _stress_nfci,
        "fmt":     lambda v: f"{v:+.2f}",
    },
    {
        "id":      "claims",
        "name":    "Initial Claims YoY",
        "weight":  0.10,
        "unit":    "%",
        "min":     -30.0,
        "max":     60.0,
        "step":    1.0,
        "fn":      _stress_claims_yoy,
        "fmt":     lambda v: f"{v:+.0f}%",
    },
    {
        "id":      "hyoas",
        "name":    "High-Yield OAS",
        "weight":  0.10,
        "unit":    " bps",
        "min":     200.0,
        "max":     1500.0,
        "step":    5.0,
        "fn":      _stress_hy_oas,
        "fmt":     lambda v: f"{v:.0f} bps",
    },
    {
        "id":      "ism",
        "name":    "ISM Manufacturing PMI",
        "weight":  0.05,
        "unit":    "",
        "min":     35.0,
        "max":     65.0,
        "step":    0.5,
        "fn":      _stress_ism,
        "fmt":     lambda v: f"{v:.1f}",
    },
]

# ── Preset scenarios ──────────────────────────────────────────────────────────

PRESETS: dict[str, dict[str, float]] = {
    "📍 Current baseline":      {"t10y3m": 1.00, "sahm": 0.12, "cfnai": -0.20, "nfci": -0.20, "claims":  0.0, "hyoas": 310.0, "ism": 48.5},
    "🟢 Bull market 2017":      {"t10y3m": 1.60, "sahm": 0.05, "cfnai":  0.30, "nfci": -0.50, "claims": -5.0, "hyoas": 340.0, "ism": 58.0},
    "🔴 2008 financial crisis": {"t10y3m":-0.30, "sahm": 0.90, "cfnai": -3.00, "nfci":  1.80, "claims": 45.0, "hyoas":1500.0, "ism": 34.0},
    "🔴 COVID 2020 shock":      {"t10y3m": 1.50, "sahm": 0.80, "cfnai": -3.00, "nfci":  0.60, "claims":100.0, "hyoas": 900.0, "ism": 41.0},
}

# ── Session state initialisation ──────────────────────────────────────────────

if "sim_ready" not in st.session_state:
    for k, v in PRESETS["📍 Current baseline"].items():
        st.session_state[f"sim_{k}"] = v
    st.session_state["sim_ready"] = True

# ── Preset buttons ────────────────────────────────────────────────────────────

preset_cols = st.columns(len(PRESETS))
for col, (label, vals) in zip(preset_cols, PRESETS.items()):
    with col:
        if st.button(label, use_container_width=True):
            for k, v in vals.items():
                st.session_state[f"sim_{k}"] = v
            st.session_state.pop("sim_analysis", None)
            st.rerun()

st.markdown("---")

# ── Two-column layout ─────────────────────────────────────────────────────────

col_left, col_right = st.columns([12, 10])

# ── Left column: sliders ──────────────────────────────────────────────────────

with col_left:
    st.markdown("##### Model inputs")
    for feat in _FEAT_CFG:
        label = f"**{feat['name']}** · {feat['weight']*100:.0f}% weight"
        st.markdown(label)
        val = st.slider(
            label          = feat["name"],
            min_value      = feat["min"],
            max_value      = feat["max"],
            step           = feat["step"],
            key            = f"sim_{feat['id']}",
            label_visibility = "collapsed",
        )
        stress, desc = feat["fn"](float(val))
        stress_emoji = "🔴" if stress >= 0.70 else "🟡" if stress >= 0.40 else "🟢"
        st.caption(f"{stress_emoji} Stress **{stress:.2f}** · {desc}")

# ── Compute model output (using live slider values) ───────────────────────────

total_stress = 0.0
feature_results: list[dict] = []

for feat in _FEAT_CFG:
    raw = st.session_state.get(f"sim_{feat['id']}", 0.0)
    val = float(raw)
    stress, desc = feat["fn"](val)
    contrib = feat["weight"] * stress
    total_stress += contrib
    feature_results.append({
        "name":            feat["name"],
        "weight":          feat["weight"],
        "value":           val,
        "stress":          stress,
        "contribution":    round(contrib * 100, 2),
        "description":     desc,
        "formatted_value": feat["fmt"](val),
    })

probability   = round(total_stress * 100, 1)
traffic_light = "green" if probability < 25 else "yellow" if probability < 50 else "red"
tl_color      = {"green": "#2ecc71", "yellow": "#f39c12", "red": "#e74c3c"}[traffic_light]

# Simple phase from scenario (no UNRATE trend available in simulator)
def _scenario_phase(prob: float, cfnai: float, t10y3m: float) -> tuple[str, str]:
    lei_neg = cfnai < 0
    inverted = t10y3m < 0
    if prob > 70:
        return "Contraction",    "#e74c3c"
    if prob > 50:
        return "Peak",           "#e67e22"
    if prob > 30:
        return "Late Expansion", "#f39c12"
    if prob < 20 and not lei_neg:
        return "Early Expansion","#2ecc71"
    return "Mid Expansion",      "#27ae60"

phase_name, phase_color = _scenario_phase(
    probability,
    st.session_state.get("sim_cfnai", -0.20),
    st.session_state.get("sim_t10y3m", 1.0),
)

# ── Right column: results ─────────────────────────────────────────────────────

with col_right:

    # ── Probability gauge ─────────────────────────────────────────────────────
    fig_gauge = go.Figure(go.Indicator(
        mode   = "gauge+number",
        value  = probability,
        number = {"suffix": "%", "font": {"size": 52, "color": tl_color}},
        gauge  = {
            "axis": {
                "range":     [0, 100],
                "tickvals":  [0, 25, 50, 75, 100],
                "tickwidth": 1,
                "tickcolor": "#555",
                "tickfont":  {"color": "#888", "size": 11},
            },
            "bar":       {"color": tl_color, "thickness": 0.22},
            "bgcolor":   "rgba(0,0,0,0)",
            "borderwidth": 0,
            "steps": [
                {"range": [0,  25], "color": "rgba(46,204,113,0.12)"},
                {"range": [25, 50], "color": "rgba(243,156,18,0.12)"},
                {"range": [50,100], "color": "rgba(231,76,60,0.12)"},
            ],
            "threshold": {
                "line":      {"color": tl_color, "width": 4},
                "thickness": 0.75,
                "value":     probability,
            },
        },
    ))
    fig_gauge.update_layout(
        height       = 220,
        margin       = {"l": 20, "r": 20, "t": 10, "b": 10},
        paper_bgcolor = "rgba(0,0,0,0)",
        font         = {"color": "#aaa"},
    )
    st.plotly_chart(fig_gauge, use_container_width=True, key="sim_gauge")

    # ── Phase badge ───────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="text-align:center; margin: -12px 0 16px; '
        f'background:{phase_color}22; border:1px solid {phase_color}55; '
        f'border-radius:8px; padding:8px; font-weight:600; color:{phase_color}; font-size:1rem;">'
        f'{phase_name}</div>',
        unsafe_allow_html=True,
    )

    # ── Feature contribution chart ────────────────────────────────────────────
    st.markdown("##### Feature contributions (pp)")
    names   = [r["name"].replace("Treasury Spread","Spread").replace("Manufacturing ","") for r in feature_results]
    contribs = [r["contribution"] for r in feature_results]
    bar_colors = [
        "#e74c3c" if r["stress"] >= 0.70 else "#f39c12" if r["stress"] >= 0.40 else "#2ecc71"
        for r in feature_results
    ]
    fig_bar = go.Figure(go.Bar(
        x           = contribs,
        y           = names,
        orientation = "h",
        marker_color = bar_colors,
        text        = [f"{c:.1f}pp" for c in contribs],
        textposition = "outside",
        textfont    = {"size": 11, "color": "#aaa"},
        hovertemplate = "%{y}: <b>%{x:.2f}pp</b><extra></extra>",
    ))
    fig_bar.update_layout(
        height        = 240,
        margin        = {"l": 10, "r": 50, "t": 10, "b": 10},
        paper_bgcolor  = "rgba(0,0,0,0)",
        plot_bgcolor   = "rgba(0,0,0,0)",
        xaxis         = {"title": "", "color": "#555", "showgrid": False, "zeroline": False},
        yaxis         = {"color": "#aaa", "automargin": True, "tickfont": {"size": 11}},
        showlegend    = False,
    )
    st.plotly_chart(fig_bar, use_container_width=True, key="sim_contribs")

    # ── Analyse button ────────────────────────────────────────────────────────
    if st.button("🤖 Analyse this scenario", use_container_width=True, key="sim_analyse"):
        st.session_state["sim_analysis"] = {
            "inputs":       feature_results,
            "probability":  probability,
            "traffic_light": traffic_light,
            "phase":        phase_name,
        }

# ── Full-width analysis output ────────────────────────────────────────────────

if "sim_analysis" in st.session_state:
    snap = st.session_state["sim_analysis"]
    st.markdown("---")
    st.markdown("#### 🤖 Scenario Analysis")
    st.caption(
        f"Probability: **{snap['probability']:.1f}%** · "
        f"Phase: **{snap['phase']}** · "
        f"Traffic light: **{snap['traffic_light'].upper()}**"
    )
    placeholder = st.empty()
    full_text   = ""
    for chunk in stream_scenario_analysis(
        scenario_inputs = snap["inputs"],
        probability     = snap["probability"],
        traffic_light   = snap["traffic_light"],
        cycle_phase     = snap["phase"],
    ):
        full_text += chunk
        placeholder.markdown(full_text + "▌")
    placeholder.markdown(full_text)
    del st.session_state["sim_analysis"]

st.markdown("---")
st.caption(DISCLAIMER)
