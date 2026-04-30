"""
pages/9_Portfolio.py
=====================
Portfolio Macro Heatmap — Pulse360

Paste a list of tickers and see how your portfolio scores across all 5 macro
regimes. The heatmap instantly reveals your weakest holdings in each scenario
so you can stress-test positioning before conditions shift.

Features
--------
• Plotly heatmap (y = tickers, x = regime, z = macro-adjusted Buffett score)
• Color scale: red → yellow → green (0–100)
• Sorted by base Buffett score descending (best quality at top)
• Vulnerability table: worst-scoring holding per regime + score delta vs best
• Macro Beta summary: most/least regime-sensitive names
• Regime selector to focus the vulnerability lens on one scenario
• Compact annotations toggle (show/hide score numbers on heatmap cells)
• Fallback to _FALLBACK_SCORES when yfinance is rate-limited
• Disclaimer + "not investment advice" notice
"""

from __future__ import annotations

import io
import time
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from components.stock_score_utils import (
    fetch_stock_data,
    _compute_score,
    _macro_adj_score,
    _macro_sensitivity,
    _MACRO_ADJ,
    _MACRO_DESCRIPTIONS,
    _FALLBACK_SCORES,
    DISCLAIMER,
)

# ── Constants ──────────────────────────────────────────────────────────────────
REGIMES: list[str] = list(_MACRO_ADJ.keys())

REGIME_ICONS: dict[str, str] = {
    "Normal":               "⚪",
    "High Inflation":       "🔥",
    "Rising Rates":         "📈",
    "Recession Risk":       "🛡️",
    "Recovery / Expansion": "🚀",
}

_DEFAULT_TICKERS = "AAPL, MSFT, KO, JNJ, V, XOM, PG, GOOGL"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _score_color_css(score: int) -> str:
    """Return a CSS background colour for a score 0-100 (RdYlGn gradient)."""
    if score >= 75:
        return "#27ae60"
    if score >= 60:
        return "#2ecc71"
    if score >= 45:
        return "#f1c40f"
    if score >= 30:
        return "#e67e22"
    return "#e74c3c"


def _score_text_css(score: int) -> str:
    return "#000000" if 40 <= score <= 65 else "#ffffff"


@st.cache_data(ttl=3600, show_spinner=False)
def _score_ticker(ticker: str) -> dict | None:
    """
    Fetch + compute Buffett score for one ticker.
    Returns dict with keys: ticker, company, sector, base_score, regime_scores, macro_range.
    Falls back to _FALLBACK_SCORES if live data unavailable.
    """
    t = ticker.upper().strip()

    # ── Try live data first ──────────────────────────────────────────────────
    try:
        raw = fetch_stock_data(t)
        if raw:
            result = _compute_score(raw)
            if result and result.get("total", 0) > 0:
                base = result["total"]
                sector = raw.get("info", {}).get("sector") or raw.get("info", {}).get("sectorDisp")
                company = raw.get("info", {}).get("shortName") or t
                regime_scores = {r: _macro_adj_score(base, sector, r) for r in REGIMES}
                sens = _macro_sensitivity(base, sector)
                return {
                    "ticker": t,
                    "company": company,
                    "sector": sector or "Unknown",
                    "base_score": base,
                    "regime_scores": regime_scores,
                    "macro_range": sens["range"],
                    "best_regime": sens["best"],
                    "worst_regime": sens["worst"],
                }
    except Exception:
        pass

    # ── Fallback cache ───────────────────────────────────────────────────────
    fb = _FALLBACK_SCORES.get(t)
    if fb:
        base = fb["Score"]
        sector = fb.get("Sector")
        regime_scores = {r: _macro_adj_score(base, sector, r) for r in REGIMES}
        sens = _macro_sensitivity(base, sector)
        return {
            "ticker": t,
            "company": fb.get("Company", t),
            "sector": sector or "Unknown",
            "base_score": base,
            "regime_scores": regime_scores,
            "macro_range": sens["range"],
            "best_regime": sens["best"],
            "worst_regime": sens["worst"],
            "fallback": True,
        }

    return None


def _build_heatmap_df(scored: list[dict]) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Return (z_df, y_labels, x_labels) ready for go.Heatmap."""
    # Sort by base score descending
    scored_sorted = sorted(scored, key=lambda d: d["base_score"], reverse=True)
    y_labels = [f"{d['ticker']}  ({d['base_score']})" for d in scored_sorted]
    x_labels = REGIMES
    z_data = [[d["regime_scores"][r] for r in REGIMES] for d in scored_sorted]
    return pd.DataFrame(z_data, index=y_labels, columns=x_labels), y_labels, x_labels


# ── Page ───────────────────────────────────────────────────────────────────────

st.title("🗂️ Portfolio Macro Heatmap")
st.caption(
    "Stress-test your holdings across 5 macro regimes. "
    "Green = quality tailwind · Red = regime headwind · Numbers = Buffett score."
)

# ── Ticker input ───────────────────────────────────────────────────────────────
with st.expander("📋 Enter your portfolio tickers", expanded=True):
    raw_input = st.text_area(
        "Tickers (comma or newline separated)",
        value=_DEFAULT_TICKERS,
        height=90,
        placeholder="e.g. AAPL, MSFT, KO, JNJ, V",
        help="Up to 20 tickers. Fetches live data then falls back to cached scores.",
    )

    col_opt1, col_opt2, _ = st.columns([1, 1, 3])
    with col_opt1:
        show_annotations = st.toggle("Show scores on cells", value=True)
    with col_opt2:
        focus_regime = st.selectbox(
            "Vulnerability lens",
            options=["All regimes"] + REGIMES,
            index=0,
            help="Focus the vulnerability table on a specific scenario",
        )

    run_btn = st.button("🔍 Analyse Portfolio", type="primary", use_container_width=False)

# ── Run analysis ───────────────────────────────────────────────────────────────
if not run_btn and "portfolio_scored" not in st.session_state:
    st.info("Enter your tickers above and click **Analyse Portfolio** to begin.")
    st.stop()

if run_btn:
    # Parse tickers
    raw_tickers = [
        t.strip().upper()
        for t in raw_input.replace("\n", ",").split(",")
        if t.strip()
    ]
    raw_tickers = list(dict.fromkeys(raw_tickers))[:20]  # deduplicate, cap at 20

    if not raw_tickers:
        st.warning("Please enter at least one ticker.")
        st.stop()

    scored_list: list[dict] = []
    failed: list[str] = []

    progress = st.progress(0, text="Fetching data…")
    for i, tk in enumerate(raw_tickers):
        progress.progress((i + 1) / len(raw_tickers), text=f"Scoring {tk}…")
        result = _score_ticker(tk)
        if result:
            scored_list.append(result)
        else:
            failed.append(tk)
        time.sleep(0.05)
    progress.empty()

    if failed:
        st.warning(f"Could not score: **{', '.join(failed)}** — not found or insufficient data.")

    st.session_state["portfolio_scored"] = scored_list
    st.session_state["portfolio_focus_regime"] = focus_regime
    st.session_state["portfolio_show_annotations"] = show_annotations

# ── Render results ─────────────────────────────────────────────────────────────
scored_list = st.session_state.get("portfolio_scored", [])
focus_regime = st.session_state.get("portfolio_focus_regime", focus_regime)
show_annotations = st.session_state.get("portfolio_show_annotations", show_annotations)

if not scored_list:
    st.stop()

# ── Summary metrics ────────────────────────────────────────────────────────────
n = len(scored_list)
avg_base = sum(d["base_score"] for d in scored_list) / n
strongest = max(scored_list, key=lambda d: d["base_score"])
most_sensitive = max(scored_list, key=lambda d: d["macro_range"])
most_stable = min(scored_list, key=lambda d: d["macro_range"])

m1, m2, m3, m4 = st.columns(4)
m1.metric("Holdings Scored", n)
m2.metric("Avg Buffett Score", f"{avg_base:.0f} / 100")
m3.metric("🔴 Most Macro-Sensitive", f"{most_sensitive['ticker']} (β {most_sensitive['macro_range']})")
m4.metric("🟢 Most Regime-Stable", f"{most_stable['ticker']} (β {most_stable['macro_range']})")

st.markdown("---")

# ── Heatmap ────────────────────────────────────────────────────────────────────
hm_df, y_labels, x_labels = _build_heatmap_df(scored_list)

z = hm_df.values.tolist()
text = [[str(int(v)) for v in row] for row in z] if show_annotations else None

# Build x-axis labels with icons
x_display = [f"{REGIME_ICONS.get(r, '')} {r}" for r in x_labels]

fig = go.Figure(
    go.Heatmap(
        z=z,
        x=x_display,
        y=y_labels,
        text=text,
        texttemplate="%{text}" if show_annotations else "",
        textfont={"size": 11, "color": "white"},
        colorscale=[
            [0.00, "#e74c3c"],
            [0.30, "#e67e22"],
            [0.50, "#f1c40f"],
            [0.70, "#2ecc71"],
            [1.00, "#27ae60"],
        ],
        zmin=0,
        zmax=100,
        colorbar=dict(
            title="Buffett Score",
            titleside="right",
            tickvals=[0, 25, 50, 75, 100],
            ticktext=["0 — Poor", "25", "50 — Avg", "75", "100 — Elite"],
            thickness=16,
            len=0.8,
        ),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Regime: %{x}<br>"
            "Score: <b>%{z}</b><br>"
            "<extra></extra>"
        ),
        xgap=2,
        ygap=2,
    )
)

cell_h = max(36, min(56, 700 // max(n, 1)))
fig.update_layout(
    height=max(320, n * cell_h + 120),
    margin=dict(l=20, r=20, t=60, b=60),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    title=dict(
        text="Portfolio Buffett Score by Macro Regime",
        font=dict(size=15, color="#cccccc"),
        x=0.01,
    ),
    xaxis=dict(
        side="top",
        tickfont=dict(size=11, color="#cccccc"),
        showgrid=False,
    ),
    yaxis=dict(
        autorange="reversed",
        tickfont=dict(size=11, color="#cccccc"),
        showgrid=False,
    ),
    font=dict(color="#cccccc"),
)

st.plotly_chart(fig, use_container_width=True)

# Fallback notice
fallback_tickers = [d["ticker"] for d in scored_list if d.get("fallback")]
if fallback_tickers:
    st.caption(
        f"ℹ️ Cached fallback scores used for: **{', '.join(fallback_tickers)}** "
        "(live data unavailable — refresh to retry)."
    )

st.markdown("---")

# ── Vulnerability Table ────────────────────────────────────────────────────────
st.subheader("🔎 Vulnerability Analysis")

regimes_to_show = [focus_regime] if focus_regime != "All regimes" else REGIMES

vuln_rows = []
for regime in regimes_to_show:
    regime_scores = [(d["ticker"], d["company"], d["regime_scores"][regime]) for d in scored_list]
    regime_scores.sort(key=lambda x: x[2])
    worst_tk, worst_co, worst_sc = regime_scores[0]
    best_tk, best_co, best_sc = regime_scores[-1]
    avg_sc = sum(s for _, _, s in regime_scores) / len(regime_scores)
    delta = worst_sc - best_sc  # always negative

    vuln_rows.append({
        "Regime": f"{REGIME_ICONS.get(regime, '')} {regime}",
        "⚠️ Weakest Holding": f"{worst_tk} — {worst_co}",
        "Weakest Score": worst_sc,
        "⭐ Strongest Holding": f"{best_tk} — {best_co}",
        "Strongest Score": best_sc,
        "Portfolio Avg": round(avg_sc, 1),
        "Spread (W→S)": abs(delta),
    })

vuln_df = pd.DataFrame(vuln_rows)

# Style the dataframe
def _highlight_vuln(row):
    styles = [""] * len(row)
    score_idx = vuln_df.columns.get_loc("Weakest Score")
    score = row.iloc[score_idx]
    if score < 30:
        styles[score_idx] = "background-color:#4d1a1a;color:#ff6b6b;"
    elif score < 45:
        styles[score_idx] = "background-color:#4d3300;color:#f39c12;"
    else:
        styles[score_idx] = "color:#2ecc71;"
    return styles

st.dataframe(
    vuln_df.style.apply(_highlight_vuln, axis=1),
    use_container_width=True,
    hide_index=True,
)

st.markdown("---")

# ── Per-Regime Weakness Callouts ───────────────────────────────────────────────
with st.expander("📊 Regime Detail — Per-Holding Scores", expanded=False):
    focus_r = st.selectbox(
        "Select regime to inspect",
        options=REGIMES,
        format_func=lambda r: f"{REGIME_ICONS.get(r, '')} {r}",
        key="detail_regime",
    )
    st.caption(_MACRO_DESCRIPTIONS.get(focus_r, ""))

    detail_rows = []
    for d in sorted(scored_list, key=lambda x: x["regime_scores"][focus_r], reverse=True):
        adj = d["regime_scores"][focus_r]
        base = d["base_score"]
        delta = adj - base
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        detail_rows.append({
            "Ticker": d["ticker"],
            "Company": d["company"],
            "Sector": d["sector"],
            "Base Score": base,
            f"{focus_r} Score": adj,
            "Δ vs Base": delta_str,
            "Macro β": d["macro_range"],
        })

    detail_df = pd.DataFrame(detail_rows)
    st.dataframe(detail_df, use_container_width=True, hide_index=True)

# ── Macro Beta Ranking ─────────────────────────────────────────────────────────
with st.expander("⚡ Macro Beta — Regime Sensitivity Ranking", expanded=False):
    st.caption(
        "Macro Beta = score range across all 5 regimes. "
        "High β names swing most between regimes — useful for tactical tilts."
    )
    beta_rows = sorted(scored_list, key=lambda d: d["macro_range"], reverse=True)
    beta_df = pd.DataFrame([
        {
            "Ticker": d["ticker"],
            "Company": d["company"],
            "Sector": d["sector"],
            "Base Score": d["base_score"],
            "Macro β": d["macro_range"],
            "Best Regime": f"{REGIME_ICONS.get(d['best_regime'], '')} {d['best_regime']}",
            "Worst Regime": f"{REGIME_ICONS.get(d['worst_regime'], '')} {d['worst_regime']}",
        }
        for d in beta_rows
    ])
    st.dataframe(beta_df, use_container_width=True, hide_index=True)

# ── CSV Export ─────────────────────────────────────────────────────────────────
st.markdown("---")
export_rows = []
for d in sorted(scored_list, key=lambda x: x["base_score"], reverse=True):
    row = {
        "Ticker": d["ticker"],
        "Company": d["company"],
        "Sector": d["sector"],
        "Base Score": d["base_score"],
        "Macro Beta": d["macro_range"],
        "Best Regime": d["best_regime"],
        "Worst Regime": d["worst_regime"],
    }
    for r in REGIMES:
        row[r] = d["regime_scores"][r]
    export_rows.append(row)

export_df = pd.DataFrame(export_rows)
csv_buf = io.StringIO()
export_df.to_csv(csv_buf, index=False)

st.download_button(
    label="📥 Export Heatmap as CSV",
    data=csv_buf.getvalue(),
    file_name="pulse360_portfolio_heatmap.csv",
    mime="text/csv",
    help="Download regime scores for all holdings",
)

st.caption(DISCLAIMER)
