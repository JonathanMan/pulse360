"""
Pulse360 — Buffett Stock Screener
===================================
Scores a curated universe of ~80 US large-cap stocks using the same
100-point Buffett framework as pages/7_Stock_Score.py, then ranks
them with an optional macro-regime overlay (±15 pts sector adjustment).

Features:
  • Live yfinance data with 1-hour cache
  • Fallback scores for 14 key blue chips when rate-limited
  • Macro Overlay: Normal / High Inflation / Rising Rates / Recession Risk / Recovery
  • Regime Focus callout — highlights which section and sectors matter most
  • Price Trend column: ↑/→/↓ based on price vs 200-day MA (not just YoY fundamentals)
  • FCF Yield & Forward P/E columns
  • Share-count YoY (buyback detection)
  • Data-status bar (live vs cached vs failed count)
  • Compact Mode toggle for dense professional layouts
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.stock_score_utils import (
    DISCLAIMER,
    _FALLBACK_SCORES,
    _MACRO_ADJ,
    _REGIME_FOCUS,
    _SCREENER_UNIVERSE,
    _compute_score,
    _macro_adj_score,
    _macro_sens_cell,
    _price_trend,
    _score_color,
    _score_color_sub,
    _sf,
    fetch_stock_data,
)

# ── Page styles ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .main .block-container { padding-top: 1rem; max-width: 1300px; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("# 🏆 Buffett Stock Screener")
st.caption(
    "Scores ~80 US large-cap stocks on the same 100-point Buffett/Munger framework. "
    "Sector-relative benchmarks · Piotroski F-Score · Altman Z · Owner Earnings DCF · "
    "200-day MA momentum. Apply a **Macro Overlay** to re-rank by cycle-adjusted score."
)

# ── Top control bar ───────────────────────────────────────────────────────────
ctrl_left, ctrl_right = st.columns([7, 3])
with ctrl_right:
    compact = st.toggle(
        "Compact Mode",
        value=False,
        key="screener_compact",
        help="Reduces row height and font size for higher data density.",
    )

# ── Macro Overlay ─────────────────────────────────────────────────────────────
_REGIME_META = {
    "Normal":               ("⚪", "#888888", "No adjustment — pure Buffett score"),
    "High Inflation":       ("🔴", "#e74c3c", "Energy & Materials ↑  ·  Tech & Real Estate ↓"),
    "Rising Rates":         ("🟠", "#e67e22", "Banks & Insurance ↑  ·  Utilities & REITs ↓"),
    "Recession Risk":       ("🟡", "#f1c40f", "Staples & Healthcare ↑  ·  Cyclicals & Industrials ↓"),
    "Recovery / Expansion": ("🟢", "#2ecc71", "Cyclicals & Industrials ↑  ·  Defensives ↓"),
}

with ctrl_left:
    st.markdown(
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">'
        '<span style="font-size:1.05rem;">🌐</span>'
        '<span style="font-size:1.0rem;font-weight:700;color:#fff;">Macro Overlay</span>'
        '<span style="color:#555;font-size:0.78rem;margin-left:4px;">'
        '— re-ranks by macro-adjusted score (±15 pts sector adjustment)</span>'
        '</div>',
        unsafe_allow_html=True,
    )

ov_left, ov_right = st.columns([3, 9])
with ov_left:
    macro_regime = st.selectbox(
        "Regime",
        options=list(_MACRO_ADJ.keys()),
        index=0,
        key="screener_macro_regime",
        label_visibility="collapsed",
        help="Adjusts each sector's score ±15 pts based on sensitivity to the selected macro environment.",
    )
with ov_right:
    icon, accent, summary = _REGIME_META[macro_regime]
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;'
        f'background:#161b27;border:1px solid {accent}44;border-left:3px solid {accent};'
        f'border-radius:6px;padding:9px 14px;height:38px;box-sizing:border-box;">'
        f'<span style="font-size:1rem;">{icon}</span>'
        f'<span style="color:#ccc;font-size:0.82rem;font-weight:500;">'
        f'<strong style="color:{accent};">{macro_regime}</strong>'
        f'&nbsp;&nbsp;<span style="color:#666;">|</span>&nbsp;&nbsp;'
        f'{summary}'
        f'</span></div>',
        unsafe_allow_html=True,
    )

# ── Regime Focus callout ──────────────────────────────────────────────────────
focus = _REGIME_FOCUS.get(macro_regime)
if focus:
    focus_sectors, focus_section, focus_rationale = focus
    icon, accent, _ = _REGIME_META[macro_regime]
    st.markdown(
        f'<div style="background:#0e1220;border:1px solid {accent}33;'
        f'border-left:3px solid {accent};border-radius:6px;'
        f'padding:8px 14px;margin:6px 0 10px;display:flex;gap:14px;align-items:flex-start;">'
        f'<div style="margin-top:1px;font-size:0.9rem;">{icon}</div>'
        f'<div>'
        f'<span style="color:{accent};font-size:0.75rem;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:.04em;">Regime Focus</span>'
        f'&nbsp;&nbsp;'
        f'<span style="color:#ccc;font-size:0.78rem;">'
        f'Prioritise <strong style="color:#fff;">{focus_section}</strong>'
        f' · Favoured sectors: <em style="color:#aaa;">{focus_sectors}</em>'
        f'</span>'
        f'<div style="color:#666;font-size:0.73rem;margin-top:3px;">{focus_rationale}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

st.markdown("")

# ── Run / Clear buttons ───────────────────────────────────────────────────────
btn_col1, btn_col2, _ = st.columns([1, 1, 5])
with btn_col1:
    run_screener = st.button("▶ Run Screener", key="run_screener_btn", type="primary")
with btn_col2:
    if st.session_state.get("screener_results"):
        if st.button("🗑 Clear", key="clear_screener_btn"):
            st.session_state.pop("screener_results", None)
            st.session_state.pop("screener_errors", None)
            st.rerun()

if run_screener:
    st.session_state.pop("screener_results", None)
    st.session_state.pop("screener_errors", None)

# ── Run the screener ──────────────────────────────────────────────────────────
if run_screener:
    results_list: list[dict] = []
    errors_list:  list[str]  = []
    total_tickers = len(_SCREENER_UNIVERSE)
    progress_bar  = st.progress(0, text="Starting screener…")
    status_text   = st.empty()

    for i, tkr in enumerate(_SCREENER_UNIVERSE, 1):
        progress_bar.progress(i / total_tickers,
                              text=f"Scoring {tkr}… ({i}/{total_tickers})")
        status_text.caption(f"Fetching **{tkr}**")
        try:
            raw_s = fetch_stock_data(tkr)
            if raw_s.get("error") or not raw_s.get("info"):
                if tkr in _FALLBACK_SCORES:
                    fb = dict(_FALLBACK_SCORES[tkr])
                    fb["Ticker"]  = tkr
                    fb["_cached"] = True
                    fb.setdefault("ShareChg", None)
                    results_list.append(fb)
                else:
                    errors_list.append(tkr)
                continue

            sc      = _compute_score(raw_s)
            info_s  = raw_s["info"]

            # Price-momentum trend (200MA / 50MA based) — more actionable than YoY fundamentals
            t_arrow, t_color, t_tip = _price_trend(info_s)

            fcf  = _sf(info_s.get("freeCashflow"))
            mktc = _sf(info_s.get("marketCap"))
            fcf_yield = round(fcf / mktc * 100, 1) if (fcf and mktc and mktc > 0) else None
            fwd_pe    = _sf(info_s.get("forwardPE"))
            sector_s  = info_s.get("sector") or "—"

            results_list.append({
                "Ticker":     tkr,
                "Company":    (info_s.get("shortName") or info_s.get("longName") or tkr)[:28],
                "Sector":     sector_s[:22],
                "Score":      sc["total"],
                "Moat":       sc["sections"]["moat"]["score"],
                "Fortress":   sc["sections"]["fortress"]["score"],
                "Valuation":  sc["sections"]["valuation"]["score"],
                "Momentum":   sc["sections"]["momentum"]["score"],
                "Shareholder":sc["sections"]["shareholder"]["score"],
                "ShareChg":   sc["sections"]["shareholder"].get("sh_chg"),
                "Trend":      t_arrow,
                "TrendColor": t_color,
                "TrendTip":   t_tip,
                "FCF_Yield":  fcf_yield,
                "Fwd_PE":     round(fwd_pe, 1) if fwd_pe and fwd_pe > 0 else None,
                "Price":      _sf(info_s.get("currentPrice") or info_s.get("regularMarketPrice")),
                "Mkt Cap $B": round((_sf(info_s.get("marketCap")) or 0) / 1e9, 1),
                "_cached":    False,
            })

        except Exception as exc:
            errors_list.append(f"{tkr} ({exc})")

    progress_bar.empty()
    status_text.empty()
    st.session_state["screener_results"] = results_list
    st.session_state["screener_errors"]  = errors_list

# ── Render results ─────────────────────────────────────────────────────────────
if st.session_state.get("screener_results"):
    scr_df = pd.DataFrame(st.session_state["screener_results"])

    # Apply macro adjustment
    scr_df["MacroAdj"] = scr_df.apply(
        lambda r: _macro_adj_score(int(r["Score"]), r["Sector"], macro_regime), axis=1
    )

    sort_col = "MacroAdj" if macro_regime != "Normal" else "Score"
    scr_df   = scr_df.sort_values(sort_col, ascending=False).reset_index(drop=True)
    top20    = scr_df.head(20).copy()
    top20.index = range(1, len(top20) + 1)

    # ── Data status bar ────────────────────────────────────────────────────────
    _all  = st.session_state.get("screener_results", [])
    _live = sum(1 for r in _all if not r.get("_cached"))
    _cach = sum(1 for r in _all if r.get("_cached"))
    _fail = len(st.session_state.get("screener_errors", []))
    parts = []
    if _live: parts.append(f'<span style="color:#2ecc71;">🟢 {_live} live</span>')
    if _cach: parts.append(f'<span style="color:#f39c12;">📦 {_cach} cached</span>')
    if _fail: parts.append(f'<span style="color:#e74c3c;">⚠️ {_fail} failed</span>')
    st.markdown(
        f'<div style="font-size:0.75rem;color:#666;margin-bottom:8px;">'
        f'Data status: &nbsp;' + ' &nbsp;·&nbsp; '.join(parts) +
        f'&nbsp;&nbsp;<span style="color:#444;font-style:italic;">· scores cached 1 hr</span></div>',
        unsafe_allow_html=True,
    )

    regime_label = (
        "" if macro_regime == "Normal"
        else f" <span style='color:#f39c12;font-size:0.75rem;'>sorted by {macro_regime} macro-adjusted score</span>"
    )
    st.markdown(
        f"#### Top 20 Results &nbsp; "
        f"<span style='color:#888;font-size:0.8rem;'>({len(scr_df)} stocks scored)</span>"
        f"{regime_label}",
        unsafe_allow_html=True,
    )

    def _badge(score: int) -> str:
        if score >= 75: return "🟢 Strong Buy"
        if score >= 60: return "🟢 Deep Dive"
        if score >= 45: return "🟡 Caution"
        if score >= 30: return "🟠 Red Flags"
        return "🔴 Fails"

    # Row density settings driven by Compact Mode toggle
    if compact:
        row_pad  = "4px 5px"
        row_font = "0.72rem"
        cell_pad = "4px 4px"
    else:
        row_pad  = "7px 5px"
        row_font = "0.8rem"
        cell_pad = "7px 5px"

    rows_html = ""
    for rank, row in top20.iterrows():
        sc_val  = int(row["Score"])
        mac_sc  = int(row["MacroAdj"])
        col     = _score_color(sc_val)
        mac_col = _score_color(mac_sc)

        is_cached   = row.get("_cached", False)
        ticker_cell = (
            row["Ticker"]
            + (' <span style="color:#555;font-size:0.65rem;" '
               'title="Fallback cache — live data unavailable">📦</span>'
               if is_cached else "")
        )

        price_str = f"${row['Price']:.2f}" if row.get("Price") else "—"
        fcf_str   = f"{row['FCF_Yield']:.1f}%" if row.get("FCF_Yield") is not None else "—"
        fpe_str   = f"{row['Fwd_PE']:.1f}x"   if row.get("Fwd_PE")   is not None else "—"
        t_arrow   = row.get("Trend", "→")
        t_color   = row.get("TrendColor", "#888")
        t_tip     = row.get("TrendTip", "")
        macro_sens = _macro_sens_cell(row.get("Sector", ""), macro_regime)

        sh_chg_val = row.get("ShareChg")
        if sh_chg_val is not None:
            sh_color = "#2ecc71" if sh_chg_val <= -1 else ("#e74c3c" if sh_chg_val > 1 else "#f39c12")
            sh_tip   = "Buybacks ✓" if sh_chg_val <= -1 else ("Dilution ⚠" if sh_chg_val > 1 else "Stable")
            sh_cell  = f'<span style="color:{sh_color};font-weight:600;" title="{sh_tip}">{sh_chg_val:+.1f}%</span>'
        else:
            sh_cell = '<span style="color:#444;">—</span>'

        # Macro delta badge
        delta = mac_sc - sc_val
        if macro_regime == "Normal" or delta == 0:
            mac_cell = f'<span style="color:{col};font-weight:700;">{sc_val}</span>'
        else:
            d_color = "#2ecc71" if delta > 0 else "#e74c3c"
            d_sign  = "+" if delta > 0 else ""
            mac_cell = (
                f'<span style="color:{mac_col};font-weight:800;">{mac_sc}</span>'
                f'<span style="color:{d_color};font-size:0.68rem;margin-left:3px;">'
                f'({d_sign}{delta})</span>'
            )

        rows_html += (
            f'<tr style="border-bottom:1px solid #1a1a2a;">'
            f'<td style="color:#666;text-align:center;padding:{cell_pad};font-size:0.73rem;">{rank}</td>'
            f'<td style="color:#3498db;font-weight:700;padding:{cell_pad};font-size:{row_font};">{ticker_cell}</td>'
            f'<td style="color:#ccc;padding:{cell_pad};font-size:{row_font};">{row["Company"]}</td>'
            f'<td style="color:#999;padding:{cell_pad};font-size:0.72rem;">{row["Sector"]}</td>'
            f'<td style="text-align:center;padding:{cell_pad};">{mac_cell}</td>'
            f'<td style="text-align:center;padding:{cell_pad};font-size:{row_font};">{macro_sens}</td>'
            f'<td style="color:{t_color};font-size:1.1rem;text-align:center;" title="{t_tip}">{t_arrow}</td>'
            f'<td style="color:{_score_color_sub(int(row["Moat"]),40)};font-size:0.75rem;text-align:center;font-weight:600;">{int(row["Moat"])}/40</td>'
            f'<td style="color:{_score_color_sub(int(row["Fortress"]),25)};font-size:0.75rem;text-align:center;font-weight:600;">{int(row["Fortress"])}/25</td>'
            f'<td style="color:{_score_color_sub(int(row["Valuation"]),20)};font-size:0.75rem;text-align:center;font-weight:600;">{int(row["Valuation"])}/20</td>'
            f'<td style="color:{_score_color_sub(int(row["Momentum"]),10)};font-size:0.75rem;text-align:center;font-weight:600;">{int(row["Momentum"])}/10</td>'
            f'<td style="text-align:center;padding:{cell_pad};font-size:0.75rem;">{sh_cell}</td>'
            f'<td style="color:#aef;font-size:0.75rem;text-align:center;">{fcf_str}</td>'
            f'<td style="color:#aef;font-size:0.75rem;text-align:center;">{fpe_str}</td>'
            f'<td style="color:#ccc;font-size:0.75rem;text-align:right;">{price_str}</td>'
            f'<td style="font-size:0.75rem;padding:{cell_pad};">{_badge(mac_sc)}</td>'
            f'</tr>'
        )

    st.markdown(
        f"""
        <div style="overflow-x:auto;margin:10px 0;">
        <table style="width:100%;border-collapse:collapse;background:#0e1117;font-size:{row_font};">
          <thead>
            <tr style="border-bottom:2px solid #333;color:#555;font-size:0.68rem;
                       text-transform:uppercase;letter-spacing:.05em;">
              <th style="padding:{cell_pad};text-align:center;">#</th>
              <th style="padding:{cell_pad};text-align:left;">Ticker</th>
              <th style="padding:{cell_pad};text-align:left;">Company</th>
              <th style="padding:{cell_pad};text-align:left;">Sector</th>
              <th style="padding:7px 8px;text-align:center;"
                  title="Score (macro-adjusted if regime selected)">Score</th>
              <th style="padding:{cell_pad};text-align:center;"
                  title="Sector sensitivity to selected macro regime (±15 pts max)">Macro Sens.</th>
              <th style="padding:{cell_pad};text-align:center;"
                  title="Price vs 200-day MA: ↑ confirmed uptrend · → consolidating · ↓ technical downtrend">Price Trend</th>
              <th style="padding:{cell_pad};text-align:center;">Moat</th>
              <th style="padding:{cell_pad};text-align:center;">Fortress</th>
              <th style="padding:{cell_pad};text-align:center;">Val.</th>
              <th style="padding:{cell_pad};text-align:center;">Mom.</th>
              <th style="padding:{cell_pad};text-align:center;"
                  title="YoY share count change — negative = buybacks (good)">Shares YoY</th>
              <th style="padding:{cell_pad};text-align:center;"
                  title="Free Cash Flow Yield = FCF / Market Cap">FCF Yld</th>
              <th style="padding:{cell_pad};text-align:center;"
                  title="Forward P/E ratio">Fwd P/E</th>
              <th style="padding:{cell_pad};text-align:right;">Price</th>
              <th style="padding:{cell_pad};text-align:left;">Verdict</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
        </div>
        """,
        unsafe_allow_html=True,
    )

    errs = st.session_state.get("screener_errors", [])
    if errs:
        st.caption(
            f"⚠️ Could not fetch: {', '.join(errs[:10])}"
            + (" and more…" if len(errs) > 10 else "")
        )

    st.caption(
        "💡 **Price Trend** = price vs 200-day MA: ↑ >+3% (uptrend) · ↓ <-3% (downtrend) · → consolidating. "
        "**Macro Sens.** = sector score adjustment for selected regime (±15 pts max). "
        "**Shares YoY** = green (buybacks ✓) / red (dilution ⚠). "
        "**FCF Yield** = FCF / Market Cap. Scores cached 1 hr."
    )

else:
    # ── Empty state ────────────────────────────────────────────────────────────
    st.markdown("""
<div style="text-align:center;padding:48px 24px;color:#444;">
    <div style="font-size:3rem;margin-bottom:16px;">🏆</div>
    <div style="font-size:1.1rem;font-weight:600;color:#666;margin-bottom:8px;">
        Ready to screen
    </div>
    <div style="font-size:0.85rem;color:#444;max-width:480px;margin:0 auto;">
        Select a macro regime above, then click
        <strong style="color:#3498db;">▶ Run Screener</strong>
        to score ~80 large-caps on the Buffett framework.
        Results are cached for 1 hour — subsequent runs are instant.
    </div>
</div>
""", unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(DISCLAIMER)
