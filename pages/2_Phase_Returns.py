"""
Pie360 — What to Own & When
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

from components.pulse360_theme import inject_theme
inject_theme()

st.markdown("""
<style>
    .main .block-container { padding-top: 1rem; max-width: 1400px; }
</style>
""", unsafe_allow_html=True)

st.markdown("# 📊 What to Own & When")
st.caption(
    "How each asset class has performed during Expansion, Late Cycle, "
    "Contraction, and Recovery phases · 1997–present"
)
st.markdown(
    "This page answers a simple but powerful question: given the current cycle phase, what have "
    "equities, bonds, gold, oil, and the dollar historically done? "
    "Every month since 1997 is assigned to a phase (Expansion, Late Cycle, Contraction, or Recovery) "
    "using the same model that runs on the Dashboard, and the actual asset class returns for those "
    "months are then aggregated into statistics. "
    "**How to interpret it:** the annualised return bars show the average tailwind or headwind each "
    "asset class has faced in a given phase — a tall green bar means that phase has historically been "
    "a strong tailwind, a red bar means a headwind. "
    "Pair this with the current phase shown on the Dashboard to understand which asset classes have "
    "the historical wind at their back right now, and use the win rate and volatility stats to judge "
    "how consistent and smooth that historical edge has been."
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
        <span style="color:#6a6a6a; font-size:0.9rem;">
            Current phase · Model probability {current_prob:.1f}%
        </span>
        <br><br>
        <span style="color:#0a0a0a; font-size:0.9rem;">
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
            color = "#00a35a" if (val or 0) >= 0 else "#d92626"
            label = f"{val:+.1f}%" if val is not None else "—"
            st.metric(label=asset, value=label)

st.markdown("---")

# ── Phase timeline ────────────────────────────────────────────────────────────
st.subheader("Cycle Phase Timeline")
st.caption(
    "Each vertical bar is one calendar month, coloured by the phase the model assigned to it: "
    "green for Expansion, amber for Late Cycle, red for Contraction, and blue for Recovery. "
    "The month counts below show how many months of history fall into each phase — "
    "this matters because phases with very few months (e.g. Contraction) produce return statistics "
    "based on a thin sample, so treat those figures as directional rather than precise. "
    "**What to look for:** long unbroken stretches of green confirm a stable expansion; "
    "a shift to amber or red in recent months is the signal to watch."
)

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
st.caption(
    "Each cell shows the average annualised return for that asset class during that cycle phase, "
    "calculated by annualising the mean monthly return across all months in that phase since 1997. "
    "Deep green cells indicate a strong historical tailwind; deep red cells indicate a headwind. "
    "**How to use it:** find the row matching the current cycle phase shown on the Dashboard, "
    "then read across to see which asset classes have historically had the wind at their back. "
    "A positive number means the phase has been favourable on average — "
    "but check the win rate and volatility (in the expander below) before drawing conclusions, "
    "as a high average return with a low win rate means the gains came from a small number of extreme months."
)

def _color_cell(val):
    if pd.isna(val) or val is None:
        return "color: #6a6a6a"
    if val > 15:
        return "background-color: rgba(40,167,69,0.20); color: #1a5c30; font-weight:600"
    if val > 5:
        return "background-color: rgba(40,167,69,0.10); color: #1a5c30"
    if val > 0:
        return "background-color: rgba(40,167,69,0.05); color: #0a0a0a"
    if val > -5:
        return "background-color: rgba(231,76,60,0.05); color: #0a0a0a"
    if val > -15:
        return "background-color: rgba(231,76,60,0.10); color: #8b1a1a"
    return "background-color: rgba(231,76,60,0.20); color: #8b1a1a; font-weight:600"

display_returns = returns_table.copy()
for col in display_returns.columns:
    display_returns[col] = display_returns[col].apply(
        lambda x: f"{x:+.1f}%" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—"
    )

st.dataframe(
    returns_table.style
        .format(lambda x: f"{x:+.1f}%" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—")
        .map(_color_cell)
        .set_table_styles([{
            "selector": "th",
            "props": [("background-color", "#f4f4f4"), ("color", "#0a0a0a"), ("font-weight", "600")]
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
st.caption(
    "Each group of bars shows how one asset class has performed across all four cycle phases. "
    "Bars above zero are phases where that asset has historically been a winner; bars below zero are phases to be cautious. "
    "Colours represent the phase, not the direction. "
    "**What to look for:** asset classes where one phase bar towers above the rest have a strong phase dependence — "
    "gold and bonds, for example, tend to have their largest bars during Contraction. "
    "Asset classes where all bars are similarly sized are less cycle-sensitive and behave more like all-weather holdings."
)

fig_bar = go.Figure()
for phase in PHASES:
    if phase not in returns_table.index:
        continue
    vals = returns_table.loc[phase]
    colors = [
        "#00a35a" if (v or 0) >= 0 else "#d92626"
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
st.caption(
    "Select an asset class tab to see a full breakdown: annualised return, win rate, volatility, "
    "best and worst single months, and sample size for each phase. "
    "Below the stats table is the cumulative return chart for that asset since 1997, "
    "with NBER recessions shaded in grey — this lets you visually verify whether the phase statistics "
    "match what you can see in the price history. "
    "**Pay attention to the sample size column:** phases with fewer than 20 months of data "
    "produce unreliable averages, so treat those rows with extra caution."
)

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
Pie360 recession model, which was calibrated using the same historical data.
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
    "Pie360 is not a Registered Investment Advisor.*"
)
