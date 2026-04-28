"""
Pulse360 — Backtest Page
=========================
Historical validation of the recession probability model against
NBER-dated recessions from 1997 to present.

Answers: would this model have caught 2001, 2008, and 2020 in time?
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from data.fred_client import fetch_series
from models.backtest import (
    run_historical_backtest,
    compute_recession_stats,
    compute_false_positive_periods,
)
from components.chart_utils import dark_layout, add_nber

# ── Dark-theme CSS ───────────────────────────────────────────────────────────
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

st.markdown("# 📉 Model Backtest")
st.caption(
    "Point-in-time historical validation · 1997–present · "
    "Covers 3 NBER recessions: 2001, 2007–09, 2020"
)
st.markdown(
    "This page tests whether the recession probability model would have worked historically. "
    "At every calendar month from 1997 to today, the model is re-run using only the data that "
    "was actually available at that moment — no hindsight, no future data leaked in. "
    "The result is a continuous probability curve plotted against the three NBER-dated recessions "
    "(grey shading). "
    "**How to interpret it:** look for whether the model crossed 50% before or early in each recession "
    "(lead time), whether it stayed low during expansions (low false-positive rate), and how quickly "
    "it recovered after each downturn. The summary stats below the chart quantify all three. "
    "A model that consistently leads recessions by 2–3 months with few false positives is useful for "
    "tilting defensively before conditions deteriorate — the backtest tells you whether this one earns that trust."
)
st.markdown(
    "> **Methodology:** At each calendar month, the model is run using only data "
    "available *up to that date* — no look-ahead bias. "
    "HY OAS data begins Dec 1996, so the full backtest starts Jan 1997."
)

# ── Run backtest ──────────────────────────────────────────────────────────────
with st.spinner("Running historical backtest… (this may take 20–30s on first load, then cached for 24h)"):
    bt_df = run_historical_backtest(start_date="1997-01-01")

usrec_result = fetch_series("USREC", start_date="1997-01-01")
usrec_series = usrec_result["data"]

if bt_df.empty:
    st.error("Backtest failed — check FRED API connection.")
    st.stop()

# ── Summary metrics ───────────────────────────────────────────────────────────
rec_stats = compute_recession_stats(bt_df, usrec_series)
fp_list   = compute_false_positive_periods(bt_df, usrec_series, threshold=25.0)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Recessions Covered", len(rec_stats))
with col2:
    early = [s["yellow_lead_months"] for s in rec_stats if s["yellow_lead_months"] is not None and s["yellow_lead_months"] > 0]
    avg_lead = f"{sum(early)/len(early):.0f} months" if early else "—"
    st.metric("Avg Yellow-flag Lead", avg_lead, help="Months before recession start that model crossed 25%")
with col3:
    caught = sum(1 for s in rec_stats if s["yellow_lead_months"] is not None and s["yellow_lead_months"] >= 0)
    st.metric("Recessions Flagged (≥25%)", f"{caught}/{len(rec_stats)}")
with col4:
    st.metric("False Positive Periods", len(fp_list), help="Times model stayed ≥25% for 2+ months outside a recession window")

st.markdown("---")

# ── Main chart: probability over time ─────────────────────────────────────────
st.subheader("Recession Probability — Historical Model Output")

fig = go.Figure()

# Colour-coded area fill: split into green/yellow/red bands
prob = bt_df["probability"]
dates = prob.index

# Green band (0–25)
fig.add_trace(go.Scatter(
    x=list(dates) + list(dates[::-1]),
    y=list(prob.clip(upper=25)) + [0] * len(dates),
    fill="toself",
    fillcolor="rgba(46,204,113,0.08)",
    line={"width": 0},
    showlegend=False,
    hoverinfo="skip",
))

# Yellow band (25–50)
fig.add_trace(go.Scatter(
    x=list(dates) + list(dates[::-1]),
    y=list(prob.clip(lower=25, upper=50)) + [25] * len(dates),
    fill="toself",
    fillcolor="rgba(243,156,18,0.08)",
    line={"width": 0},
    showlegend=False,
    hoverinfo="skip",
))

# Red band (50+)
fig.add_trace(go.Scatter(
    x=list(dates) + list(dates[::-1]),
    y=list(prob.clip(lower=50)) + [50] * len(dates),
    fill="toself",
    fillcolor="rgba(231,76,60,0.10)",
    line={"width": 0},
    showlegend=False,
    hoverinfo="skip",
))

# Main probability line
fig.add_trace(go.Scatter(
    x=dates,
    y=prob.values,
    mode="lines",
    line={"color": "#3498db", "width": 2},
    name="Recession Probability (%)",
    hovertemplate="%{x|%b %Y}: <b>%{y:.1f}%</b><extra></extra>",
))

# Threshold lines
fig.add_hline(y=25, line_dash="dot", line_color="#f39c12", line_width=1,
              annotation_text="25% — Yellow", annotation_font_color="#f39c12",
              annotation_position="top right")
fig.add_hline(y=50, line_dash="dash", line_color="#e74c3c", line_width=1,
              annotation_text="50% — Red", annotation_font_color="#e74c3c",
              annotation_position="top right")

# NBER recession shading
fig = add_nber(fig, start_date="1997-01-01")

fig = dark_layout(fig, yaxis_title="Recession Probability (%)")
fig.update_layout(height=420, yaxis={"range": [0, 100]})
st.plotly_chart(fig, use_container_width=True, key="bt_main")

st.markdown("---")

# ── Recession performance table ────────────────────────────────────────────────
st.subheader("Performance by Recession")

if rec_stats:
    rows = []
    for s in rec_stats:
        yl = s["yellow_lead_months"]
        rl = s["red_lead_months"]

        def _fmt_lead(months):
            if months is None:
                return "❌ Never"
            if months > 0:
                return f"✅ {months}m early"
            if months == 0:
                return f"⚠️ Same month"
            return f"⚠️ {abs(months)}m late"

        rows.append({
            "Recession":            f"{s['recession_start']} – {s['recession_end']}",
            "Yellow flag (25%)":    f"{s['first_yellow']}  ({_fmt_lead(yl)})",
            "Red flag (50%)":       f"{s['first_red']}  ({_fmt_lead(rl)})",
            "Peak probability":     f"{s['peak_probability']:.1f}%  ({s['peak_date']})" if s["peak_probability"] else "—",
        })

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No NBER recessions found in the backtest window.")

st.markdown("---")

# ── Feature stress evolution ───────────────────────────────────────────────────
st.subheader("Feature Stress Over Time")
st.caption("Each line shows how stressed a model input was at each point in time (0 = no stress, 1 = maximum stress).")

stress_cols = [c for c in bt_df.columns if c.startswith("stress_")]

feature_colors = {
    "stress_10y3m_treasury_spread": "#3498db",
    "stress_sahm_rule":             "#e74c3c",
    "stress_cfnai_(activity_index)":"#9b59b6",
    "stress_chicago_fed_nfci":      "#f39c12",
    "stress_initial_claims_yoy":    "#2ecc71",
    "stress_high-yield_oas":        "#e67e22",
    "stress_ism_manufacturing_pmi": "#1abc9c",
}

feature_labels = {
    "stress_10y3m_treasury_spread": "10Y–3M Spread (30%)",
    "stress_sahm_rule":             "Sahm Rule (20%)",
    "stress_cfnai_(activity_index)":"CFNAI (15%)",
    "stress_chicago_fed_nfci":      "NFCI (10%)",
    "stress_initial_claims_yoy":    "Initial Claims YoY (10%)",
    "stress_high-yield_oas":        "High-Yield OAS (10%)",
    "stress_ism_manufacturing_pmi": "ISM PMI (5%)",
}

fig2 = go.Figure()
for col in stress_cols:
    fig2.add_trace(go.Scatter(
        x=bt_df.index,
        y=bt_df[col].values,
        mode="lines",
        line={"color": feature_colors.get(col, "#888"), "width": 1.5},
        name=feature_labels.get(col, col.replace("stress_", "").replace("_", " ").title()),
        hovertemplate="%{x|%b %Y}: <b>%{y:.3f}</b><extra></extra>",
    ))

fig2.add_hline(y=0.5, line_dash="dot", line_color="#555", line_width=1,
               annotation_text="0.5 — neutral", annotation_font_color="#555")
fig2 = add_nber(fig2, start_date="1997-01-01")
fig2 = dark_layout(fig2, yaxis_title="Stress Score (0–1)")
fig2.update_layout(height=380, yaxis={"range": [0, 1]})
st.plotly_chart(fig2, use_container_width=True, key="bt_stress")

st.markdown("---")

# ── False positive analysis ───────────────────────────────────────────────────
st.subheader("False Positive Periods (≥25% without recession)")

if fp_list:
    st.dataframe(
        pd.DataFrame(fp_list).rename(columns={
            "start":     "Period Start",
            "end":       "Period End",
            "peak_prob": "Peak Probability (%)",
        }),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "A false positive is a sustained period above 25% that was not followed "
        "by an NBER recession within 12 months."
    )
else:
    st.success("No false positive periods identified in this window.")

st.markdown("---")

# ── Interpretation notes ──────────────────────────────────────────────────────
with st.expander("📖 How to read this backtest", expanded=False):
    st.markdown("""
**What this shows**

The model is run at each calendar month from Jan 1997 to today, using only the
data that existed at that point in time. No future data is used in any calculation.

**What it doesn't show**

- The model weights were chosen *after* seeing these recessions. This is a
  calibration check, not an out-of-sample forecast test.
- Real-time FRED data differs slightly from today's vintage due to revisions.
  A true out-of-sample test would require a real-time data archive (e.g. ALFRED).
- The stress function parameters were tuned heuristically, not fitted to this data.
  A proper in-sample fit would show higher apparent performance.

**What a "good" result looks like**

- Model crosses 25% several months before each recession start
- Peak probability well above 50% during each recession
- Few or short false positive periods
- Low current probability in non-recessionary periods

**Honest interpretation**

If the model performs well here, it is *consistent* with the model being useful —
not proof that it will work in the future. The real validation is out-of-sample
performance, which requires waiting.
""")

st.caption(
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)
