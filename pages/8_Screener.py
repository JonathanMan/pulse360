"""
Pulse360 — Buffett Stock Screener
===================================
Scores a curated universe of ~80 US large-cap stocks using the same 100-point
Buffett framework as the single-stock page, then ranks them with an optional
macro-regime overlay (±15 pts sector adjustment).

Features:
  • One-click Presets: Classic Buffett / Value Deep Dive / Quality Growth /
    Recession Shield / Inflation Plays
  • Macro Beta column: range of score across all 5 regimes (regime sensitivity)
  • Regime Focus callout: tells you which section and sectors matter most
  • Price Trend: ↑/→/↓ based on price vs 200-day MA
  • FCF Yield & Forward P/E columns
  • Share-count YoY (buyback detection)
  • Data-status bar (live vs cached vs failed count)
  • Compact Mode toggle for dense professional layouts
  • CSV Export of results
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from components.user_profile import feature_visible

from components.stock_score_utils import (
    DISCLAIMER,
    _COMPLEXITY,
    _FALLBACK_SCORES,
    _MACRO_ADJ,
    _REGIME_FOCUS,
    _SCREENER_UNIVERSE,
    _macro_adj_score,
    _macro_beta_cell,
    _macro_sens_cell,
    _macro_sensitivity,
    _score_color,
    _score_color_sub,
    _sf,
    score_ticker_cached,
)

# ── Page styles ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .main .block-container { padding-top: 1rem; max-width: 1350px; }
    .preset-btn button { font-size: 0.78rem !important; padding: 4px 10px !important; }
</style>
""", unsafe_allow_html=True)

# ── Preset definitions ────────────────────────────────────────────────────────
# Each preset sets a macro regime and a sub-score sort column.
PRESETS: dict[str, dict] = {
    "🏆 Classic Buffett":  {"regime": "Normal",               "sort": "Score",
                            "desc": "Pure quality ranking — no regime overlay"},
    "💎 Value Deep Dive":  {"regime": "Normal",               "sort": "Valuation",
                            "desc": "Sorted by Valuation sub-score — FCF yield & P/E focus"},
    "📈 Quality Growth":   {"regime": "Recovery / Expansion", "sort": "Moat",
                            "desc": "Wide-moat leaders in an expanding cycle"},
    "🛡️ Recession Shield": {"regime": "Recession Risk",       "sort": "Fortress",
                            "desc": "Defensive durability — balance sheet first"},
    "🔥 Inflation Plays":  {"regime": "High Inflation",       "sort": "Score",
                            "desc": "Commodity / pricing-power names in a hot CPI env"},
}

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("# 🏆 Buffett Stock Screener")
st.caption(
    "Scores ~80 US large-cap stocks on the 100-point Buffett/Munger framework. "
    "Apply a **Macro Overlay** to re-rank by cycle-adjusted score, or use a "
    "**Preset** to jump straight to a specific investment style."
)

# ── Presets row ───────────────────────────────────────────────────────────────
st.markdown(
    '<div style="color:#888;font-size:0.72rem;font-weight:700;text-transform:uppercase;'
    'letter-spacing:.05em;margin-bottom:6px;">Quick Presets</div>',
    unsafe_allow_html=True,
)
active_preset = st.session_state.get("screener_active_preset", None)
p_cols = st.columns(len(PRESETS))
for col, (name, cfg) in zip(p_cols, PRESETS.items()):
    is_active = (active_preset == name)
    label = f"✓ {name}" if is_active else name
    with col:
        if st.button(label, key=f"preset_{name}", use_container_width=True,
                     help=cfg["desc"],
                     type="primary" if is_active else "secondary"):
            st.session_state["screener_active_preset"] = name
            st.session_state["screener_macro_regime"]  = cfg["regime"]
            st.session_state["screener_sort_col"]      = cfg["sort"]
            st.rerun()

st.markdown("")

# ── Top control bar (compact mode toggle) ─────────────────────────────────────
_, ctrl_right = st.columns([9, 3])
with ctrl_right:
    compact = st.toggle(
        "Compact Mode", value=False, key="screener_compact",
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
        help="Adjusts each sector's score ±15 pts. Use Presets above to jump to a specific regime.",
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
        f'&nbsp;&nbsp;<span style="color:#666;">|</span>&nbsp;&nbsp;{summary}'
        f'</span></div>',
        unsafe_allow_html=True,
    )

# ── Regime Focus callout ──────────────────────────────────────────────────────
focus = _REGIME_FOCUS.get(macro_regime)
if focus:
    focus_sectors, focus_section, focus_rationale = focus
    icon2, accent2, _ = _REGIME_META[macro_regime]
    st.markdown(
        f'<div style="background:#0e1220;border:1px solid {accent2}33;'
        f'border-left:3px solid {accent2};border-radius:6px;'
        f'padding:8px 14px;margin:6px 0 10px;display:flex;gap:14px;align-items:flex-start;">'
        f'<div style="margin-top:1px;font-size:0.9rem;">{icon2}</div>'
        f'<div>'
        f'<span style="color:{accent2};font-size:0.75rem;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:.04em;">Regime Focus</span>'
        f'&nbsp;&nbsp;<span style="color:#ccc;font-size:0.78rem;">'
        f'Prioritise <strong style="color:#fff;">{focus_section}</strong>'
        f' · Favoured: <em style="color:#aaa;">{focus_sectors}</em></span>'
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
        result = score_ticker_cached(tkr)
        if result:
            result.setdefault("Shareholder", 0)
            result.setdefault("Mkt Cap $B",  0)
            results_list.append(result)
        else:
            errors_list.append(tkr)

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

    # Macro Beta: range of score across all regimes
    scr_df["MacroBeta"] = scr_df.apply(
        lambda r: _macro_sensitivity(int(r["Score"]), r["Sector"])["range"], axis=1
    )

    # Sort: preset-driven sub-score override for Normal regime, else MacroAdj
    preset_sort = st.session_state.get("screener_sort_col", None)
    if macro_regime != "Normal":
        sort_col = "MacroAdj"
    elif preset_sort and preset_sort in scr_df.columns:
        sort_col = preset_sort
    else:
        sort_col = "Score"

    scr_df = scr_df.sort_values(sort_col, ascending=False).reset_index(drop=True)
    top20  = scr_df.head(20).copy()
    top20.index = range(1, len(top20) + 1)

    # ── Data status bar ────────────────────────────────────────────────────────
    _all  = st.session_state.get("screener_results", [])
    _live = sum(1 for r in _all if not r.get("_stale"))
    _cach = sum(1 for r in _all if r.get("_stale"))
    _fail = len(st.session_state.get("screener_errors", []))
    parts = []
    if _live: parts.append(f'<span style="color:#2ecc71;">🟢 {_live} live</span>')
    if _cach: parts.append(f'<span style="color:#f39c12;">📦 {_cach} stale</span>')
    if _fail: parts.append(f'<span style="color:#e74c3c;">⚠️ {_fail} failed</span>')
    sort_label = (f' · sorted by <strong style="color:#3498db;">{sort_col}</strong>'
                  if sort_col != "Score" else "")
    regime_label = (
        "" if macro_regime == "Normal"
        else f" · <span style='color:#f39c12;'>{macro_regime} overlay</span>"
    )
    st.markdown(
        f'<div style="font-size:0.75rem;color:#666;margin-bottom:8px;">'
        f'Data: &nbsp;' + ' &nbsp;·&nbsp; '.join(parts) +
        f'{sort_label}{regime_label}'
        f'&nbsp;&nbsp;<span style="color:#444;font-style:italic;">· cached 1 hr</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"#### Top 20 Results &nbsp; "
        f"<span style='color:#888;font-size:0.8rem;'>({len(scr_df)} stocks scored)</span>",
        unsafe_allow_html=True,
    )

    def _badge(score: int) -> str:
        if score >= 75: return "🟢 Strong Buy"
        if score >= 60: return "🟢 Deep Dive"
        if score >= 45: return "🟡 Caution"
        if score >= 30: return "🟠 Red Flags"
        return "🔴 Fails"

    # Row density
    if compact:
        row_pad  = "4px 4px"
        row_font = "0.72rem"
    else:
        row_pad  = "7px 5px"
        row_font = "0.8rem"

    rows_html = ""
    for rank, row in top20.iterrows():
        sc_val  = int(row["Score"])
        mac_sc  = int(row["MacroAdj"])
        col     = _score_color(sc_val)
        mac_col = _score_color(mac_sc)

        is_stale    = row.get("_stale", False)
        cached_at   = row.get("_cached_at") or ""
        stale_tip   = f"Stale data — as of {cached_at}" if cached_at else "Stale data"

        # Circle of Competence badge — inline in ticker cell
        _tier = _COMPLEXITY.get(str(row["Ticker"]), "moderate")
        _tier_color = {"straightforward": "#2ecc71", "moderate": "#f39c12",
                       "specialist": "#e74c3c"}[_tier]
        _tier_tip = {
            "straightforward": "Straightforward — clear moat, simple business model; suitable for all investors",
            "moderate":        "Moderate complexity — understandable with research and sector knowledge",
            "specialist":      "Specialist company — complex balance sheet or opaque revenue streams; extra due diligence required",
        }[_tier]
        _circle_badge = (
            f' <span style="color:{_tier_color};font-size:0.6rem;cursor:help;"'
            f' title="{_tier_tip}">●</span>'
        )

        ticker_cell = (
            row["Ticker"]
            + _circle_badge
            + (f' <span style="color:#f39c12;font-size:0.65rem;"'
               f' title="{stale_tip}">📦</span>' if is_stale else "")
        )

        price_str  = f"${row['Price']:.2f}" if row.get("Price") else "—"
        fcf_str    = f"{row['FCF_Yield']:.1f}%" if row.get("FCF_Yield") is not None else "—"
        fpe_str    = f"{row['Fwd_PE']:.1f}x"    if row.get("Fwd_PE") is not None else "—"
        t_arrow    = row.get("Trend", "→")
        t_color    = row.get("TrendColor", "#888")
        t_tip      = row.get("TrendTip", "")
        macro_sens = _macro_sens_cell(row.get("Sector", ""), macro_regime)
        beta_cell  = _macro_beta_cell(int(row.get("MacroBeta", 0)))
        _show_beta = feature_visible("screener_macro_beta_col")

        sh_chg_val = row.get("ShareChg")
        if sh_chg_val is not None:
            sh_color = "#2ecc71" if sh_chg_val <= -1 else ("#e74c3c" if sh_chg_val > 1 else "#f39c12")
            sh_tip   = "Buybacks ✓" if sh_chg_val <= -1 else ("Dilution ⚠" if sh_chg_val > 1 else "Stable")
            sh_cell  = (f'<span style="color:{sh_color};font-weight:600;"'
                        f' title="{sh_tip}">{sh_chg_val:+.1f}%</span>')
        else:
            sh_cell = '<span style="color:#444;">—</span>'

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

        _beta_td = (
            f'<td style="text-align:center;padding:{row_pad};" title="Macro Beta: score range across all 5 regimes">{beta_cell}</td>'
            if _show_beta else ""
        )
        rows_html += (
            f'<tr style="border-bottom:1px solid #1a1a2a;">'
            f'<td style="color:#666;text-align:center;padding:{row_pad};font-size:0.73rem;">{rank}</td>'
            f'<td style="color:#3498db;font-weight:700;padding:{row_pad};font-size:{row_font};">{ticker_cell}</td>'
            f'<td style="color:#ccc;padding:{row_pad};font-size:{row_font};">{row["Company"]}</td>'
            f'<td style="color:#999;padding:{row_pad};font-size:0.72rem;">{row["Sector"]}</td>'
            f'<td style="text-align:center;padding:{row_pad};">{mac_cell}</td>'
            f'<td style="text-align:center;padding:{row_pad};">{macro_sens}</td>'
            + _beta_td +
            f'<td style="color:{t_color};font-size:1.1rem;text-align:center;" title="{t_tip}">{t_arrow}</td>'
            f'<td style="color:{_score_color_sub(int(row["Moat"]),40)};font-size:0.75rem;text-align:center;font-weight:600;">{int(row["Moat"])}/40</td>'
            f'<td style="color:{_score_color_sub(int(row["Fortress"]),25)};font-size:0.75rem;text-align:center;font-weight:600;">{int(row["Fortress"])}/25</td>'
            f'<td style="color:{_score_color_sub(int(row["Valuation"]),20)};font-size:0.75rem;text-align:center;font-weight:600;">{int(row["Valuation"])}/20</td>'
            f'<td style="color:{_score_color_sub(int(row["Momentum"]),10)};font-size:0.75rem;text-align:center;font-weight:600;">{int(row["Momentum"])}/10</td>'
            f'<td style="text-align:center;padding:{row_pad};font-size:0.75rem;">{sh_cell}</td>'
            f'<td style="color:#aef;font-size:0.75rem;text-align:center;">{fcf_str}</td>'
            f'<td style="color:#aef;font-size:0.75rem;text-align:center;">{fpe_str}</td>'
            f'<td style="color:#ccc;font-size:0.75rem;text-align:right;">{price_str}</td>'
            f'<td style="font-size:0.75rem;padding:{row_pad};">{_badge(mac_sc)}</td>'
            f'</tr>'
        )

    _beta_th = (
        f'<th style="padding:{row_pad};text-align:center;"'
        f' title="Macro Beta: score range across all 5 regimes — higher = more regime-sensitive">Macro &#946;</th>'
        if feature_visible("screener_macro_beta_col") else ""
    )
    # NOTE: Build table_html via concatenation (not a single f-string) so that:
    #   1. No leading whitespace — CommonMark treats 4+ spaces as a code block even
    #      with unsafe_allow_html=True; the <div> must start at column 0 of the string.
    #   2. rows_html stays outside any f-string so stray { } in HTML don't misfire.
    _thead = (
        f'<div style="overflow-x:auto;margin:10px 0;">'
        f'<table style="width:100%;border-collapse:collapse;background:#0e1117;font-size:{row_font};">'
        f'<thead><tr style="border-bottom:2px solid #333;color:#555;font-size:0.65rem;'
        f'text-transform:uppercase;letter-spacing:.05em;">'
        f'<th style="padding:{row_pad};text-align:center;">#</th>'
        f'<th style="padding:{row_pad};text-align:left;">Ticker</th>'
        f'<th style="padding:{row_pad};text-align:left;">Company</th>'
        f'<th style="padding:{row_pad};text-align:left;">Sector</th>'
        f'<th style="padding:{row_pad};text-align:center;"'
        f' title="Score (macro-adjusted if regime selected)">Score</th>'
        f'<th style="padding:{row_pad};text-align:center;"'
        f' title="Sector sensitivity to selected regime (pts adjustment, ±15 max)">Macro Sens.</th>'
        + _beta_th +
        f'<th style="padding:{row_pad};text-align:center;"'
        f' title="Price vs 200-day MA: ↑ uptrend · ↓ downtrend · → consolidating">Price Trend</th>'
        f'<th style="padding:{row_pad};text-align:center;">Moat</th>'
        f'<th style="padding:{row_pad};text-align:center;">Fortress</th>'
        f'<th style="padding:{row_pad};text-align:center;">Val.</th>'
        f'<th style="padding:{row_pad};text-align:center;">Mom.</th>'
        f'<th style="padding:{row_pad};text-align:center;"'
        f' title="YoY share count change">Shares YoY</th>'
        f'<th style="padding:{row_pad};text-align:center;"'
        f' title="FCF / Market Cap">FCF Yld</th>'
        f'<th style="padding:{row_pad};text-align:center;"'
        f' title="Forward P/E">Fwd P/E</th>'
        f'<th style="padding:{row_pad};text-align:right;">Price</th>'
        f'<th style="padding:{row_pad};text-align:left;">Verdict</th>'
        f'</tr></thead><tbody>'
    )
    table_html = _thead + rows_html + '</tbody></table></div>'
    st.markdown(table_html, unsafe_allow_html=True)

    errs = st.session_state.get("screener_errors", [])
    if errs:
        st.caption(
            f"⚠️ Could not fetch: {', '.join(errs[:10])}"
            + (" and more…" if len(errs) > 10 else "")
        )

    # ── CSV Export ─────────────────────────────────────────────────────────────
    export_cols = ["Ticker", "Company", "Sector", "Score", "MacroAdj", "MacroBeta",
                   "Moat", "Fortress", "Valuation", "Momentum", "Shareholder",
                   "FCF_Yield", "Fwd_PE", "Price", "Mkt Cap $B"]
    export_df = scr_df[[c for c in export_cols if c in scr_df.columns]].head(20).copy()
    csv_buf = io.StringIO()
    export_df.to_csv(csv_buf, index=False)

    exp_left, exp_right = st.columns([1, 5])
    with exp_left:
        st.download_button(
            label="📥 Export CSV",
            data=csv_buf.getvalue(),
            file_name=f"buffett_screener_{macro_regime.replace(' / ','_').replace(' ','_').lower()}.csv",
            mime="text/csv",
            key="screener_csv_export",
            help="Download the top 20 results as a CSV file.",
        )

    _beta_legend = (
        "💡 **Macro β** = score range across all 5 regimes (green ≤8 stable · orange 9–14 · red ≥15 high). "
        if feature_visible("screener_macro_beta_col") else "💡 "
    )
    st.caption(
        _beta_legend
        + "**Price Trend** = price vs 200MA. **Macro Sens.** = pts adjustment in current regime "
        "(hover for rationale). "
        "**● Circle of Competence**: 🟢 straightforward · 🟡 moderate · 🔴 specialist (hover for detail). "
        "FCF Yield = FCF / Mkt Cap. Scores cached 1 hr."
    )

else:
    # ── Empty state ────────────────────────────────────────────────────────────
    st.markdown("""
<div style="text-align:center;padding:48px 24px;color:#444;">
    <div style="font-size:3rem;margin-bottom:16px;">🏆</div>
    <div style="font-size:1.1rem;font-weight:600;color:#666;margin-bottom:8px;">
        Ready to screen
    </div>
    <div style="font-size:0.85rem;color:#444;max-width:520px;margin:0 auto;">
        Pick a <strong style="color:#3498db;">Preset</strong> above for a one-click style,
        or select a Macro Overlay and click
        <strong style="color:#3498db;">▶ Run Screener</strong>.
        Results are cached for 1 hour — re-running is instant.
    </div>
</div>
""", unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(DISCLAIMER)
