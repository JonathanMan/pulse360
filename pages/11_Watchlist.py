"""
Pulse360 — Watchlist
======================
A browser-persistent list of stocks the user wants to track.

Features
--------
• Add tickers manually or carry them over from Buffett Score
• Live Buffett scores (cached 1 hr) with sub-score breakdown
• Macro regime overlay — see how each stock is adjusted in any regime
• Action alert badge — flags quality gaps, macro mismatches
• Price trend indicator (vs 200-day MA)
• Remove individual tickers or clear all
• CSV export of the scored watchlist
• Scores persist via @st.cache_data; watchlist order persists via localStorage
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from components.watchlist_store import (
    add_to_watchlist,
    clear_watchlist,
    in_watchlist,
    load_watchlist,
    remove_from_watchlist,
)
from components.stock_score_utils import (
    DISCLAIMER,
    _FALLBACK_SCORES,
    _MACRO_ADJ,
    _badge,
    _compute_score,
    _macro_adj_score,
    _macro_sens_cell,
    _price_trend,
    _score_color,
    _score_color_sub,
    fetch_stock_data,
)

# ── Page styles ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main .block-container { max-width: 1200px; padding-top: 1rem; }
    .stApp { background-color: #0e1117; }
</style>
""", unsafe_allow_html=True)

# ── Score a single ticker (cached) ────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _score_ticker(ticker: str) -> dict:
    data = fetch_stock_data(ticker)
    if data:
        scores = _compute_score(data)
        scores["Ticker"]  = ticker
        scores["Company"] = data.get("shortName", ticker)
        scores["Sector"]  = data.get("sector", "Unknown")
        scores["Price"]   = data.get("currentPrice")
        scores["FCF_Yield"] = data.get("fcf_yield")
        scores["Fwd_PE"]  = data.get("forwardPE")
        trend, t_color, t_tip = _price_trend(data)
        scores["Trend"]      = trend
        scores["TrendColor"] = t_color
        scores["TrendTip"]   = t_tip
        scores["_cached"]    = False
        return scores
    # Fallback
    fb = _FALLBACK_SCORES.get(ticker)
    if fb:
        sc = fb.copy()
        sc["_cached"] = True
        return sc
    return {}


def _quick_action(score: int, sector: str, regime: str) -> tuple[str, str]:
    """Return (emoji, tooltip) for a quick action badge."""
    adj = _macro_adj_score(score, sector, regime)
    delta = adj - score
    if score < 45:
        return "🔴", "Low quality — consider removing"
    if delta <= -8:
        return "⚠️", f"Headwind in {regime} regime (−{abs(delta)} pts)"
    if delta >= 8:
        return "✅", f"Tailwind in {regime} regime (+{delta} pts)"
    return "🟢", "Holding well in current regime"


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## ⭐ Watchlist")
st.caption(
    "Your personal list of tracked stocks — scores auto-refresh every hour. "
    "Watchlist is saved to your browser and persists across sessions."
)

# ── Add ticker form ────────────────────────────────────────────────────────────
with st.form("add_ticker_form", clear_on_submit=True):
    add_col, btn_col = st.columns([4, 1])
    with add_col:
        new_ticker = st.text_input(
            "Add a ticker",
            placeholder="e.g. AAPL, NVDA, BRK-B",
            label_visibility="collapsed",
        )
    with btn_col:
        submitted = st.form_submit_button(
            "➕ Add", type="primary", use_container_width=True
        )

if submitted and new_ticker:
    # Support comma-separated batch adds
    for raw in new_ticker.split(","):
        t = raw.strip().upper()
        if t:
            if add_to_watchlist(t):
                st.success(f"**{t}** added to watchlist.", icon="⭐")
            else:
                st.info(f"**{t}** is already in your watchlist.")
    st.rerun()

# ── Load watchlist ─────────────────────────────────────────────────────────────
watchlist = load_watchlist()

if not watchlist:
    st.markdown("---")
    st.markdown("""
<div style="text-align:center;padding:3rem 0;">
  <div style="font-size:2.5rem;margin-bottom:0.5rem;">⭐</div>
  <div style="color:#aaa;font-size:1rem;">Your watchlist is empty.</div>
  <div style="color:#666;font-size:0.85rem;margin-top:0.4rem;">
    Add tickers above, or use the <strong>⭐ Add to Watchlist</strong> button
    on the Buffett Score page after analysing a stock.
  </div>
</div>
""", unsafe_allow_html=True)
    st.stop()

# ── Controls row ──────────────────────────────────────────────────────────────
ctrl_left, ctrl_mid, ctrl_right = st.columns([3, 2, 2])

with ctrl_left:
    regime_options = list(_MACRO_ADJ.keys())
    saved_regime   = st.session_state.get("default_regime", "Normal")
    macro_regime   = st.selectbox(
        "Macro regime overlay",
        options=regime_options,
        index=regime_options.index(saved_regime) if saved_regime in regime_options else 0,
        help="Adjusts scores ±15 pts based on sector sensitivity to the selected regime.",
    )

with ctrl_mid:
    sort_col = st.selectbox(
        "Sort by",
        ["Score (macro adj.)", "Buffett Score", "Ticker A–Z", "Sector"],
    )

with ctrl_right:
    st.markdown("")
    st.markdown("")
    refresh_btn = st.button("🔄 Refresh scores", use_container_width=True,
                            help="Clears the score cache and re-fetches live data.")
    if refresh_btn:
        _score_ticker.clear()
        st.rerun()

st.markdown("---")

# ── Score all watchlist tickers ───────────────────────────────────────────────
scored: list[dict] = []
failed: list[str]  = []

with st.spinner(f"Scoring {len(watchlist)} ticker(s)…"):
    for ticker in watchlist:
        result = _score_ticker(ticker)
        if result:
            scored.append(result)
        else:
            failed.append(ticker)

if failed:
    st.warning(
        f"Could not score: **{', '.join(failed)}** — "
        "check the ticker symbols or try refreshing.",
        icon="⚠️",
    )

if not scored:
    st.error("No scores available. Try refreshing or check your tickers.")
    st.stop()

# ── Apply macro adjustment & sort ─────────────────────────────────────────────
for s in scored:
    base = int(s.get("Score", 0))
    sec  = s.get("Sector", "Unknown")
    s["MacroAdj"] = _macro_adj_score(base, sec, macro_regime)
    emoji, tip    = _quick_action(base, sec, macro_regime)
    s["AlertEmoji"] = emoji
    s["AlertTip"]   = tip

sort_key = {
    "Score (macro adj.)": lambda x: -x["MacroAdj"],
    "Buffett Score":       lambda x: -int(x.get("Score", 0)),
    "Ticker A–Z":          lambda x: x.get("Ticker", ""),
    "Sector":              lambda x: x.get("Sector", ""),
}[sort_col]
scored.sort(key=sort_key)

# ── Summary metrics ───────────────────────────────────────────────────────────
avg_score  = sum(s.get("MacroAdj", 0) for s in scored) / len(scored)
top_ticker = max(scored, key=lambda x: x.get("MacroAdj", 0))
bot_ticker = min(scored, key=lambda x: x.get("MacroAdj", 0))
alerts     = sum(1 for s in scored if s["AlertEmoji"] in ("🔴", "⚠️"))

m1, m2, m3, m4 = st.columns(4)
m1.metric("Tickers tracked",  len(scored))
m2.metric("Avg score",        f"{avg_score:.0f} / 100")
m3.metric("Top pick",         f"{top_ticker['Ticker']} ({top_ticker['MacroAdj']})")
m4.metric("Needs attention",  f"{alerts} ticker{'s' if alerts != 1 else ''}",
          delta=f"in {macro_regime}" if alerts else None,
          delta_color="inverse")

st.markdown("")

# ── Watchlist table ───────────────────────────────────────────────────────────
row_pad  = "5px 8px"
row_font = "0.82rem"

rows_html = ""
for s in scored:
    ticker   = s.get("Ticker", "—")
    company  = s.get("Company", ticker)
    sector   = s.get("Sector",  "—")
    base_sc  = int(s.get("Score", 0))
    mac_sc   = int(s.get("MacroAdj", base_sc))
    col      = _score_color(base_sc)
    mac_col  = _score_color(mac_sc)
    is_cached = s.get("_cached", False)

    # Score cell with delta
    delta = mac_sc - base_sc
    if macro_regime == "Normal" or delta == 0:
        score_cell = f'<span style="color:{col};font-weight:700;">{base_sc}</span>'
    else:
        d_color = "#2ecc71" if delta > 0 else "#e74c3c"
        d_sign  = "+" if delta > 0 else ""
        score_cell = (
            f'<span style="color:{mac_col};font-weight:800;">{mac_sc}</span>'
            f'<span style="color:{d_color};font-size:0.68rem;margin-left:3px;">'
            f'({d_sign}{delta})</span>'
        )

    # Cached indicator
    cache_tag = (
        ' <span style="color:#555;font-size:0.65rem;" title="Fallback data">📦</span>'
        if is_cached else ""
    )

    price_str = f"${s['Price']:.2f}" if s.get("Price") else "—"
    fcf_str   = f"{s['FCF_Yield']:.1f}%" if s.get("FCF_Yield") is not None else "—"
    fpe_str   = f"{s['Fwd_PE']:.1f}x"    if s.get("Fwd_PE") is not None else "—"
    t_arrow   = s.get("Trend", "→")
    t_color   = s.get("TrendColor", "#888")
    t_tip     = s.get("TrendTip", "")
    macro_sens = _macro_sens_cell(sector, macro_regime)
    alert_html = (
        f'<span title="{s["AlertTip"]}" style="font-size:1rem;">{s["AlertEmoji"]}</span>'
    )

    rows_html += (
        f'<tr style="border-bottom:1px solid #1a1a2a;">'
        f'<td style="color:#3498db;font-weight:700;padding:{row_pad};font-size:{row_font};">'
        f'{ticker}{cache_tag}</td>'
        f'<td style="color:#ccc;padding:{row_pad};font-size:{row_font};">{company[:28]}</td>'
        f'<td style="color:#999;padding:{row_pad};font-size:0.72rem;">{sector}</td>'
        f'<td style="text-align:center;padding:{row_pad};">{score_cell}</td>'
        f'<td style="text-align:center;padding:{row_pad};">{macro_sens}</td>'
        f'<td style="text-align:center;padding:{row_pad};font-size:1rem;" '
        f'title="{s["AlertTip"]}">{s["AlertEmoji"]}</td>'
        f'<td style="color:{t_color};font-size:1.1rem;text-align:center;" title="{t_tip}">{t_arrow}</td>'
        f'<td style="color:{_score_color_sub(int(s.get("Moat",0)),40)};font-size:0.75rem;'
        f'text-align:center;font-weight:600;">{int(s.get("Moat",0))}/40</td>'
        f'<td style="color:{_score_color_sub(int(s.get("Fortress",0)),25)};font-size:0.75rem;'
        f'text-align:center;font-weight:600;">{int(s.get("Fortress",0))}/25</td>'
        f'<td style="color:{_score_color_sub(int(s.get("Valuation",0)),20)};font-size:0.75rem;'
        f'text-align:center;font-weight:600;">{int(s.get("Valuation",0))}/20</td>'
        f'<td style="color:{_score_color_sub(int(s.get("Momentum",0)),10)};font-size:0.75rem;'
        f'text-align:center;font-weight:600;">{int(s.get("Momentum",0))}/10</td>'
        f'<td style="color:#aef;font-size:0.75rem;text-align:center;">{fcf_str}</td>'
        f'<td style="color:#aef;font-size:0.75rem;text-align:center;">{fpe_str}</td>'
        f'<td style="color:#ccc;font-size:0.75rem;text-align:right;">{price_str}</td>'
        f'<td style="font-size:0.75rem;padding:{row_pad};">{_badge(mac_sc)}</td>'
        f'</tr>'
    )

st.markdown(
    f"""
    <div style="overflow-x:auto;margin:10px 0;">
    <table style="width:100%;border-collapse:collapse;background:#0e1117;font-size:{row_font};">
      <thead>
        <tr style="border-bottom:2px solid #333;color:#555;font-size:0.65rem;
                   text-transform:uppercase;letter-spacing:.05em;">
          <th style="padding:{row_pad};text-align:left;">Ticker</th>
          <th style="padding:{row_pad};text-align:left;">Company</th>
          <th style="padding:{row_pad};text-align:left;">Sector</th>
          <th style="padding:{row_pad};text-align:center;"
              title="Buffett score, macro-adjusted if regime selected">Score</th>
          <th style="padding:{row_pad};text-align:center;"
              title="Sector sensitivity to selected regime">Macro Sens.</th>
          <th style="padding:{row_pad};text-align:center;"
              title="Quick action signal in current regime">Signal</th>
          <th style="padding:{row_pad};text-align:center;"
              title="Price vs 200-day MA">Trend</th>
          <th style="padding:{row_pad};text-align:center;">Moat</th>
          <th style="padding:{row_pad};text-align:center;">Fortress</th>
          <th style="padding:{row_pad};text-align:center;">Val.</th>
          <th style="padding:{row_pad};text-align:center;">Mom.</th>
          <th style="padding:{row_pad};text-align:center;"
              title="FCF / Market Cap">FCF Yld</th>
          <th style="padding:{row_pad};text-align:center;"
              title="Forward P/E">Fwd P/E</th>
          <th style="padding:{row_pad};text-align:right;">Price</th>
          <th style="padding:{row_pad};text-align:left;">Verdict</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Per-ticker remove buttons ──────────────────────────────────────────────────
st.markdown("#### Manage tickers")
remove_cols = st.columns(min(len(scored), 8))
for idx, s in enumerate(scored):
    ticker = s["Ticker"]
    with remove_cols[idx % len(remove_cols)]:
        score_val = s.get("MacroAdj", s.get("Score", 0))
        color = _score_color(int(score_val))
        st.markdown(
            f'<div style="text-align:center;font-size:0.7rem;color:{color};">'
            f'{ticker}<br><strong>{score_val}</strong></div>',
            unsafe_allow_html=True,
        )
        if st.button("✕", key=f"rm_{ticker}", use_container_width=True,
                     help=f"Remove {ticker} from watchlist"):
            remove_from_watchlist(ticker)
            st.rerun()

# Clear all
st.markdown("")
clr_col, _ = st.columns([1, 5])
with clr_col:
    if st.button("🗑️ Clear watchlist", use_container_width=True):
        clear_watchlist()
        st.rerun()

# ── CSV Export ────────────────────────────────────────────────────────────────
st.markdown("---")
export_data = [
    {
        "Ticker":    s.get("Ticker"),
        "Company":   s.get("Company"),
        "Sector":    s.get("Sector"),
        "Score":     s.get("Score"),
        "MacroAdj":  s.get("MacroAdj"),
        "Signal":    s.get("AlertEmoji"),
        "Moat":      s.get("Moat"),
        "Fortress":  s.get("Fortress"),
        "Valuation": s.get("Valuation"),
        "Momentum":  s.get("Momentum"),
        "FCF_Yield": s.get("FCF_Yield"),
        "Fwd_PE":    s.get("Fwd_PE"),
        "Price":     s.get("Price"),
    }
    for s in scored
]
csv_buf = io.StringIO()
pd.DataFrame(export_data).to_csv(csv_buf, index=False)
csv_col, _ = st.columns([1, 4])
with csv_col:
    st.download_button(
        label="📥 Export CSV",
        data=csv_buf.getvalue(),
        file_name=f"watchlist_{macro_regime.replace(' / ', '_').replace(' ', '_').lower()}.csv",
        mime="text/csv",
        key="watchlist_csv",
    )

st.caption(
    "💡 **Signal**: 🔴 low quality · ⚠️ regime headwind · ✅ regime tailwind · 🟢 neutral. "
    "Scores cached 1 hr · Price trend = vs 200-day MA. "
    + DISCLAIMER
)
