"""
Pulse360 — Historical Phase Returns Page
==========================================
Asset class return statistics broken down by economic cycle phase.
Answers: what has historically happened to equities, bonds, gold, and oil
during Expansion, Late Cycle, Contraction, and Recovery phases?
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np

from data.fred_client import fetch_series
from models.backtest import run_historical_backtest
from models.phase_returns import (
    label_phases,
    compute_phase_returns,
    PHASE_COLORS,
    PHASES,
    ASSET_CLASSES,
)
from components.chart_utils import dark_layout, add_nber

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

st.markdown("# 📊 Historical Phase Returns")
st.caption(
    "How each asset class has performed during Expansion, Late Cycle, "
    "Contraction, and Recovery phases · 1997–present"
)

# ── Load dependencies ─────────────────────────────────────────────────────────
with st.spinner("Loading backtest and asset class data… (cached after first run)"):
    bt_df       = run_historical_backtest(start_date="1997-01-01")
    usrec_res   = fetch_series("USREC", start_date="1997-01-01")
    usrec_series = usrec_res["data"]

if bt_df.empty:
    st.error("Backtest data unavailable — check FRED API connection.")
    st.stop()

phase_labels = label_phases(bt_df, usrec_series)

# Serialise for cache key (compute_phase_returns needs JSON-serialisable args)
# Use ISO date format to avoid pd.read_json misinterpreting epoch-ms integers
# as file paths in newer pandas versions.
prob_json   = bt_df["probability"].to_json(date_format="iso")
phase_json  = phase_labels.to_json(date_format="iso")

with st.spinner("Computing return statistics by phase…"):
    results = compute_phase_returns(
        backtest_prob_json = prob_json,
        phase_labels_json  = phase_json,
        start_date         = "1997-01-01",
    )

if not results:
    st.error("Phase return computation failed — asset data unavailable.")
    st.stop()

returns_table = results["returns_table"]
winrate_table = results["winrate_table"]
vol_table     = results["vol_table"]
phase_stats   = results["phase_stats"]
coverage      = results["coverage"]

# ── Current phase callout ─────────────────────────────────────────────────────
current_phase = phase_labels.iloc[-1] if not phase_labels.empty else "Unknown"
current_prob  = float(bt_df["probability"].iloc[-1]) if not bt_df.empty else 0.0
phase_color   = PHASE_COLORS.get(current_phase, "#888888")

st.markdown(
    f"""
    <div style="background:{phase_color}22; border:1px solid {phase_color};
                border-radius:8px; padding:16px 20px; margin-bottom:16px;">
        <span style="font-size:1.3rem; font-weight:700; color:{phase_color}">
            {current_phase}
        </span>
        &nbsp;&nbsp;
        <span style="color:#aaa; font-size:0.9rem;">
            Current phase · Model probability {current_prob:.1f}%
        </span>
        <br><br>
        <span style="color:#ccc; font-size:0.9rem;">
            Based on this phase, historical median outcomes: &nbsp;
    """,
    unsafe_allow_html=True,
)

# Inline quick stats for current phase
if current_phase in returns_table.index and not returns_table.empty:
    cols_inline = st.columns(len(ASSET_CLASSES))
    for i, asset in enumerate(returns_table.columns):
        val = returns_table.loc[current_phase, asset]
        with cols_inline[i]:
            color = "#2ecc71" if (val or 0) >= 0 else "#e74c3c"
            label = f"{val:+.1f}%" if val is not None else "—"
            st.metric(label=asset, value=label)

st.markdown("---")

# ── Phase timeline ────────────────────────────────────────────────────────────
st.subheader("Cycle Phase Timeline")
st.caption("Each bar represents one calendar month, coloured by the phase assigned by the model.")

fig_tl = go.Figure()
for phase in PHASES:
    mask = phase_labels == phase
    if mask.any():
        fig_tl.add_trace(go.Bar(
            x=phase_labels[mask].index,
            y=[1] * int(mask.sum()),
            name=phase,
            marker_color=PHASE_COLORS[phase],
            hovertemplate=f"{phase} · %{{x|%b %Y}}<extra></extra>",
        ))

fig_tl = dark_layout(fig_tl, yaxis_title="")
fig_tl.update_layout(
    barmode="stack",
    bargap=0,
    height=130,
    yaxis={"showticklabels": False, "range": [0, 1]},
    margin={"t": 10, "b": 10},
    legend={"orientation": "h", "y": -0.3},
)
st.plotly_chart(fig_tl, use_container_width=True, key="phase_timeline")

# Phase month counts
phase_counts = phase_labels.value_counts()
count_cols = st.columns(len(PHASES))
for i, phase in enumerate(PHASES):
    n = int(phase_counts.get(phase, 0))
    pct = round(n / len(phase_labels) * 100, 0) if len(phase_labels) > 0 else 0
    with count_cols[i]:
        st.metric(
            label=phase,
            value=f"{n} months",
            delta=f"{pct:.0f}% of history",
            delta_color="off",
        )

st.markdown("---")

# ── Returns matrix ────────────────────────────────────────────────────────────
st.subheader("Annualised Returns by Phase (%)")
st.caption("Arithmetic annualisation of mean monthly return for each phase × asset class combination.")

def _color_cell(val):
    if pd.isna(val) or val is None:
        return "color: #555"
    if val > 15:
        return "background-color: rgba(46,204,113,0.35); color: white; font-weight:600"
    if val > 5:
        return "background-color: rgba(46,204,113,0.18); color: white"
    if val > 0:
        return "background-color: rgba(46,204,113,0.08); color: #ccc"
    if val > -5:
        return "background-color: rgba(231,76,60,0.08); color: #ccc"
    if val > -15:
        return "background-color: rgba(231,76,60,0.18); color: white"
    return "background-color: rgba(231,76,60,0.35); color: white; font-weight:600"

display_returns = returns_table.copy()
for col in display_returns.columns:
    display_returns[col] = display_returns[col].apply(
        lambda x: f"{x:+.1f}%" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—"
    )

st.dataframe(
    returns_table.style
        .format(lambda x: f"{x:+.1f}%" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—")
        .applymap(_color_cell)
        .set_table_styles([{
            "selector": "th",
            "props": [("background-color", "#1a1a2e"), ("color", "white"), ("font-weight", "600")]
        }]),
    use_container_width=True,
)

# Win rate and volatility in expander
with st.expander("📐 Win Rate & Volatility by Phase", expanded=False):
    col_wr, col_vl = st.columns(2)
    with col_wr:
        st.markdown("**Win Rate (% of months positive)**")
        st.dataframe(
            winrate_table.style
                .format(lambda x: f"{x:.0f}%" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—")
                .background_gradient(cmap="RdYlGn", vmin=30, vmax=70, axis=None),
            use_container_width=True,
        )
    with col_vl:
        st.markdown("**Annualised Volatility (%)**")
        st.dataframe(
            vol_table.style
                .format(lambda x: f"{x:.1f}%" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—")
                .background_gradient(cmap="YlOrRd", vmin=5, vmax=40, axis=None),
            use_container_width=True,
        )

st.markdown("---")

# ── Bar chart: returns by asset, faceted by phase ─────────────────────────────
st.subheader("Returns by Asset Class")

fig_bar = go.Figure()
for phase in PHASES:
    if phase not in returns_table.index:
        continue
    vals = returns_table.loc[phase]
    colors = [
        "#2ecc71" if (v or 0) >= 0 else "#e74c3c"
        for v in vals
    ]
    fig_bar.add_trace(go.Bar(
        name=phase,
        x=list(vals.index),
        y=list(vals.values),
        marker_color=PHASE_COLORS[phase],
        opacity=0.85,
        hovertemplate="%{x}: <b>%{y:+.1f}%</b><extra>" + phase + "</extra>",
    ))

fig_bar.add_hline(y=0, line_color="#555", line_width=1)
fig_bar = dark_layout(fig_bar, yaxis_title="Annualised Return (%)")
fig_bar.update_layout(
    barmode="group",
    height=380,
    legend={"orientation": "h", "y": -0.15},
)
st.plotly_chart(fig_bar, use_container_width=True, key="phase_bar")

st.markdown("---")

# ── Detailed drill-down per asset ─────────────────────────────────────────────
st.subheader("Asset Class Detail")

asset_tabs = st.tabs(list(ASSET_CLASSES.keys()))
for i, (asset_name, series_id) in enumerate(ASSET_CLASSES.items()):
    with asset_tabs[i]:
        if asset_name not in phase_stats:
            st.info(f"Data unavailable for {asset_name}.")
            continue

        stats = phase_stats[asset_name]
        cov   = coverage.get(asset_name, {})
        st.caption(
            f"Series: `{series_id}` · "
            f"Data from: {cov.get('start', '—')} · "
            f"{cov.get('n_months', 0)} months"
        )

        detail_rows = []
        for phase in PHASES:
            s = stats[phase]
            detail_rows.append({
                "Phase":             phase,
                "Ann. Return":       f"{s['ann_return']:+.1f}%" if s["ann_return"] is not None else "—",
                "Win Rate":          f"{s['win_rate']:.0f}%"   if s["win_rate"]    is not None else "—",
                "Ann. Volatility":   f"{s['ann_vol']:.1f}%"    if s["ann_vol"]     is not None else "—",
                "Best Month":        f"{s['best_month']:+.1f}%" if s["best_month"] is not None else "—",
                "Worst Month":       f"{s['worst_month']:+.1f}%" if s["worst_month"] is not None else "—",
                "Sample (months)":   s["n_months"],
            })

        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

        # Mini return chart for this asset over time, coloured by phase
        asset_ret = results["asset_returns"].get(asset_name)
        if asset_ret is not None and not asset_ret.empty:
            # Cumulative return index
            cum = (1 + asset_ret).cumprod() * 100
            fig_asset = go.Figure()
            fig_asset.add_trace(go.Scatter(
                x=cum.index, y=cum.values,
                mode="lines",
                line={"color": "#3498db", "width": 2},
                name=f"{asset_name} (cumulative, rebased 100)",
                hovertemplate="%{x|%b %Y}: <b>%{y:.0f}</b><extra></extra>",
            ))
            fig_asset = add_nber(fig_asset, start_date="1997-01-01")
            fig_asset = dark_layout(fig_asset, yaxis_title="Cumulative Return (rebased 100)")
            fig_asset.update_layout(height=260, margin={"t": 10})
            st.plotly_chart(fig_asset, use_container_width=True, key=f"asset_{i}")

st.markdown("---")

# ── Caveats ───────────────────────────────────────────────────────────────────
with st.expander("⚠️ Important limitations of this analysis", expanded=False):
    st.markdown("""
**In-sample phase labels**

The phase labels (Expansion / Late Cycle / Contraction / Recovery) come from the
Pulse360 recession model, which was calibrated using the same historical data.
This means the model implicitly "knew" which periods were stressed when its
parameters were chosen — so return differences between phases may partly reflect
that calibration rather than genuine predictive power.

**Small sample size**

The backtest window covers only three NBER contractions (2001, 2008, 2020).
Three data points are not enough to draw statistically significant conclusions
about contraction-phase asset returns. Treat the contraction row as directional,
not precise.

**No transaction costs or rebalancing**

Returns are buy-and-hold within each phase. Real-world phase-based allocation
strategies incur transaction costs, slippage, and rebalancing friction that would
reduce reported returns.

**Phase transitions are noisy in real time**

The model identifies phases with a lag. In practice you would not know you were
entering a Late Cycle phase until several months into it. The returns shown
assume perfect phase knowledge at each month-start.

**Oil is a price return, not a total return**

Oil returns reflect WTI spot price changes only — no roll yield, convenience
yield, or storage costs that would apply to a futures-based commodity position.
Actual commodity exposure would differ.
""")

st.caption(
    f"Phase labels: Expansion (prob <25%), Late Cycle (≥25%, no NBER), "
    f"Contraction (NBER active), Recovery (6 months post-recession). "
    f"Data: FRED. · "
    "*Educational macro analysis only — not personalised investment advice. "
    "Pulse360 is not a Registered Investment Advisor.*"
)
