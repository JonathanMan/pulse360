"""
Pie360 — Watchlist
======================
A browser-persistent list of stocks the user wants to track.

Features
--------
• Add tickers manually or carry them over from Buffett Score
• Live Buffett scores (cached 1 hr) with sub-score breakdown
• Macro regime overlay — see how each stock is adjusted in any regime
• Action alert badge — flags quality gaps, macro mismatches
• Price trend indicator (vs 200-day MA)
• Circle of Competence dot badge per ticker
• 📅 Earnings Radar — upcoming earnings cards for the next 45 days
• Earnings date column in watchlist table with day-countdown
• Remove individual tickers or clear all
• CSV export of the scored watchlist
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import streamlit as st

from components.watchlist_store import (
    add_to_watchlist,
    clear_watchlist,
    load_watchlist,
    remove_from_watchlist,
)
from components.stock_score_utils import (
    DISCLAIMER,
    _COMPLEXITY,
    _MACRO_ADJ,
    _earnings_date_cached,
    _macro_adj_score,
    _macro_sens_cell,
    _score_color,
    _score_color_sub,
    score_ticker_cached,
)


def _badge(score: int) -> str:
    """Coloured verdict badge."""
    if score >= 75:
        return '<span style="color:#00a35a;font-weight:700;">⭐ Elite</span>'
    if score >= 60:
        return '<span style="color:#27ae60;font-weight:700;">✅ Strong</span>'
    if score >= 45:
        return '<span style="color:#c98800;font-weight:700;">🟡 Fair</span>'
    if score >= 30:
        return '<span style="color:#e67e22;font-weight:700;">⚠️ Weak</span>'
    return '<span style="color:#d92626;font-weight:700;">🔴 Avoid</span>'


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


def _earnings_cell(ed_str: str | None, today: date) -> str:
    """Return an HTML table cell value for the earnings date column."""
    if not ed_str:
        return '<span style="color:#444;">—</span>'
    try:
        ed = date.fromisoformat(ed_str[:10])
        days = (ed - today).days
        if days < 0:
            return '<span style="color:#444;">—</span>'
        label = ed.strftime("%b %-d")
        if days == 0:
            color, tip = "#d92626", "Earnings today!"
        elif days <= 6:
            color, tip = "#d92626", f"In {days}d — imminent!"
        elif days <= 14:
            color, tip = "#c98800", f"In {days} days"
        elif days <= 30:
            color, tip = "#00a35a", f"In {days} days"
        else:
            color, tip = "#666", f"In {days} days"
        return (
            f'<span style="color:{color};font-size:0.72rem;font-weight:600;" '
            f'title="{tip}">{label}</span>'
        )
    except Exception:
        return '<span style="color:#444;">—</span>'


# ── Page styles ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main .block-container { max-width: 1200px; padding-top: 1rem; }
    .stApp { background-color: #ffffff; }
    .earnings-card {
        background: #f8f9fa; border-radius: 8px; padding: 10px 14px;
        border-left: 3px solid; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## ⭐ Watchlist")
st.caption(
    "Your personal list of tracked stocks — scores auto-refresh every hour. "
    "Watchlist is saved to your browser and persists across sessions."
)

# ── Guest gate ────────────────────────────────────────────────────────────────
from components.auth import render_login_gate  # noqa: E402
if not render_login_gate(
    title="Sign in to use Watchlist",
    body="Track stocks you care about with live Buffett scores, macro regime overlays, and earnings alerts.",
    feature_bullets=[
        "Save up to 50 tickers — persists across sessions",
        "Macro-adjusted scores for the current cycle phase",
        "Earnings Radar — know what's reporting in the next 45 days",
        "Action alerts when a stock's macro fit changes",
    ],
    return_page="pages/11_Watchlist.py",
):
    st.stop()

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

# Known ETFs / indices that can't be Buffett-scored — warn the user immediately
_KNOWN_ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO", "EEM", "GLD",
    "SLV", "TLT", "IEF", "HYG", "LQD", "XLK", "XLF", "XLV", "XLE", "XLI",
    "XLP", "XLY", "XLU", "XLB", "XLRE", "ARKK", "ARKW", "ARKG", "ARKF",
    "BTC", "ETH", "BTC-USD", "ETH-USD",
    "SPX", "NDX", "RUT", "DOW",
}

if submitted and new_ticker:
    for raw in new_ticker.split(","):
        t = raw.strip().upper()
        if t:
            if t in _KNOWN_ETFS:
                st.warning(
                    f"**{t}** is an ETF or index — the Buffett scoring model "
                    "requires individual stocks with fundamental data (P/E, earnings, FCF). "
                    f"**{t}** will be added but will show as unscorable.",
                    icon="⚠️",
                )
            if add_to_watchlist(t):
                st.success(f"**{t}** added to watchlist.", icon="⭐")
            else:
                st.info(f"**{t}** is already in your watchlist.")
    # Do NOT call st.rerun() here.
    # Calling st.rerun() immediately after _js_write() creates a race condition
    # where the browser may not have had time to execute the localStorage.setItem()
    # JS before the new render arrives, causing the write to be silently lost.
    # The session_state cache is already updated by add_to_watchlist(), so the
    # watchlist table below will render with the new ticker on this same pass.

# ── Load watchlist ─────────────────────────────────────────────────────────────
watchlist = load_watchlist()

if not watchlist:
    st.markdown("---")
    st.markdown(
        '<div style="text-align:center;padding:3rem 0;">'
        '<div style="font-size:2.5rem;margin-bottom:0.5rem;">⭐</div>'
        '<div style="color:#6a6a6a;font-size:1rem;">Your watchlist is empty.</div>'
        '<div style="color:#9aa0ac;font-size:0.85rem;margin-top:0.4rem;">'
        'Add tickers above, or use the <strong>⭐ Add to Watchlist</strong> button '
        'on the Buffett Score page after analysing a stock.'
        '</div></div>',
        unsafe_allow_html=True,
    )
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
        ["Score (macro adj.)", "Buffett Score", "Ticker A–Z", "Sector", "Earnings Date"],
    )

with ctrl_right:
    st.markdown("")
    st.markdown("")
    refresh_btn = st.button("🔄 Refresh scores", use_container_width=True,
                            help="Clears the score cache and re-fetches live data.")
    if refresh_btn:
        score_ticker_cached.clear()
        _earnings_date_cached.clear()
        st.rerun()

st.markdown("---")

# ── Score all tickers + fetch earnings dates ──────────────────────────────────
scored: list[dict] = []
failed: list[str]  = []
earnings_map: dict[str, str | None] = {}

today = date.today()

with st.spinner(f"Scoring {len(watchlist)} ticker(s)…"):
    for ticker in watchlist:
        result = score_ticker_cached(ticker)
        if result:
            scored.append(result)
        else:
            failed.append(ticker)
        earnings_map[ticker] = _earnings_date_cached(ticker)

if failed:
    st.warning(
        f"Could not score: **{', '.join(failed)}** — "
        "ETFs, indices, and crypto are not supported (no Buffett fundamentals). "
        "Individual stocks only. Use the ✕ buttons below to remove unsupported tickers.",
        icon="⚠️",
    )

if not scored:
    st.error("No scores available. Try refreshing or check your tickers.")
    st.stop()

# ── Apply macro adjustment ────────────────────────────────────────────────────
for s in scored:
    try:
        base = int(s.get("Score") or 0)   # guard against None / non-numeric Score
        sec  = s.get("Sector", "Unknown")
        s["MacroAdj"]   = _macro_adj_score(base, sec, macro_regime)
        emoji, tip      = _quick_action(base, sec, macro_regime)
        s["AlertEmoji"] = emoji
        s["AlertTip"]   = tip
    except Exception:
        s.setdefault("MacroAdj",   int(s.get("Score") or 0))
        s.setdefault("AlertEmoji", "⚠️")
        s.setdefault("AlertTip",   "Score unavailable")
    ed_str = earnings_map.get(s.get("Ticker", ""))
    try:
        s["_earnings_days"] = (date.fromisoformat(ed_str[:10]) - today).days if ed_str else 9999
    except Exception:
        s["_earnings_days"] = 9999

# ── Sort ──────────────────────────────────────────────────────────────────────
sort_key = {
    "Score (macro adj.)": lambda x: -(x.get("MacroAdj") or 0),
    "Buffett Score":       lambda x: -int(x.get("Score") or 0),
    "Ticker A–Z":          lambda x: x.get("Ticker", ""),
    "Sector":              lambda x: x.get("Sector", ""),
    "Earnings Date":       lambda x: x.get("_earnings_days", 9999),
}[sort_col]
scored.sort(key=sort_key)

# ── Summary metrics ───────────────────────────────────────────────────────────
avg_score  = sum(s.get("MacroAdj") or 0 for s in scored) / len(scored)
top_ticker = max(scored, key=lambda x: x.get("MacroAdj") or 0)
bot_ticker = min(scored, key=lambda x: x.get("MacroAdj") or 0)
alerts     = sum(1 for s in scored if s.get("AlertEmoji") in ("🔴", "⚠️"))
upcoming_count = sum(
    1 for s in scored if 0 <= s.get("_earnings_days", 9999) <= 30
)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Tickers tracked",  len(scored))
m2.metric("Avg score",        f"{avg_score:.0f} / 100")
m3.metric("Top pick",         f"{top_ticker.get('Ticker', '?')} ({top_ticker.get('MacroAdj', 'N/A')})")
m4.metric("Needs attention",  f"{alerts} ticker{'s' if alerts != 1 else ''}",
          delta=f"in {macro_regime}" if alerts else None, delta_color="inverse")
m5.metric("Earnings ≤30d",    f"{upcoming_count} ticker{'s' if upcoming_count != 1 else ''}")

st.markdown("")

# ── 📅 Earnings Radar ─────────────────────────────────────────────────────────
upcoming: list[tuple[str, date, int]] = []
for s in scored:
    ticker = s.get("Ticker", "")
    ed_str = earnings_map.get(ticker)
    if not ed_str:
        continue
    try:
        ed    = date.fromisoformat(ed_str[:10])
        days  = (ed - today).days
        if 0 <= days <= 45:
            upcoming.append((ticker, ed, days))
    except Exception:
        pass
upcoming.sort(key=lambda x: x[1])

if upcoming:
    st.markdown("#### 📅 Earnings Radar")
    n_cards  = min(len(upcoming), 6)
    card_cols = st.columns(n_cards)
    for idx, (tkr, ed, days) in enumerate(upcoming[:n_cards]):
        s_match   = next((s for s in scored if s.get("Ticker") == tkr), {})
        company   = s_match.get("Company", tkr)[:22]
        score_val = s_match.get("MacroAdj", s_match.get("Score", 0))
        sc_color  = _score_color(int(score_val))
        if days == 0:
            border, bg, countdown = "#d92626", "#fff5f5", "🔴 Today"
        elif days <= 6:
            border, bg, countdown = "#d92626", "#fff0f0", f"🔴 in {days}d"
        elif days <= 14:
            border, bg, countdown = "#c98800", "#fffbf0", f"🟡 in {days}d"
        else:
            border, bg, countdown = "#00a35a", "#f0fff4", f"🟢 in {days}d"
        date_str = ed.strftime("%b %-d")
        with card_cols[idx]:
            st.markdown(
                f'<div style="background:{bg};border-radius:8px;padding:10px 12px;'
                f'border-left:3px solid {border};text-align:center;margin-bottom:4px;">'
                f'<div style="color:{sc_color};font-weight:800;font-size:0.9rem;">{tkr}</div>'
                f'<div style="color:#888;font-size:0.65rem;margin:2px 0;">{company}</div>'
                f'<div style="color:#ccc;font-size:0.8rem;font-weight:600;">{date_str}</div>'
                f'<div style="font-size:0.7rem;margin-top:3px;">{countdown}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    if len(upcoming) > 6:
        extras = ", ".join(f"{t} ({d}d)" for t, _, d in upcoming[6:])
        st.caption(f"Also upcoming: {extras}")
    st.markdown("")

# ── Watchlist table ───────────────────────────────────────────────────────────
row_pad  = "5px 8px"
row_font = "0.82rem"

rows_html = ""
for s in scored:
    ticker    = s.get("Ticker", "—")
    company   = s.get("Company", ticker)
    sector    = s.get("Sector",  "—")
    base_sc   = int(s.get("Score", 0))
    mac_sc    = int(s.get("MacroAdj", base_sc))
    col       = _score_color(base_sc)
    mac_col   = _score_color(mac_sc)
    is_stale  = s.get("_stale", False)
    cached_at = s.get("_cached_at") or ""

    # Circle of Competence dot
    _tier      = _COMPLEXITY.get(ticker, "moderate")
    _tier_color = {"straightforward": "#00a35a", "moderate": "#c98800", "specialist": "#d92626"}[_tier]
    _tier_tip   = {
        "straightforward": "Straightforward — clear moat, simple model; suitable for all investors",
        "moderate":        "Moderate complexity — understandable with research",
        "specialist":      "Specialist — complex balance sheet; extra due diligence required",
    }[_tier]
    _coc_dot = (
        f' <span style="color:{_tier_color};font-size:0.6rem;cursor:help;"'
        f' title="{_tier_tip}">●</span>'
    )

    # Score cell with delta
    delta = mac_sc - base_sc
    if macro_regime == "Normal" or delta == 0:
        score_cell = f'<span style="color:{col};font-weight:700;">{base_sc}</span>'
    else:
        d_color = "#00a35a" if delta > 0 else "#d92626"
        d_sign  = "+" if delta > 0 else ""
        score_cell = (
            f'<span style="color:{mac_col};font-weight:800;">{mac_sc}</span>'
            f'<span style="color:{d_color};font-size:0.68rem;margin-left:3px;">'
            f'({d_sign}{delta})</span>'
        )

    # Stale data indicator
    stale_tip = f"Stale data — as of {cached_at}" if cached_at else "Stale data"
    cache_tag = (
        f' <span style="color:#c98800;font-size:0.65rem;" title="{stale_tip}">📦</span>'
        if is_stale else ""
    )

    # Earnings cell
    earn_cell = _earnings_cell(earnings_map.get(ticker), today)

    price_str  = f"${s['Price']:.2f}" if s.get("Price") else "—"
    fcf_str    = f"{s['FCF_Yield']:.1f}%" if s.get("FCF_Yield") is not None else "—"
    fpe_str    = f"{s['Fwd_PE']:.1f}x"    if s.get("Fwd_PE") is not None else "—"
    t_arrow    = s.get("Trend", "→")
    t_color    = s.get("TrendColor", "#888")
    t_tip      = s.get("TrendTip", "")
    macro_sens = _macro_sens_cell(sector, macro_regime)

    rows_html += (
        f'<tr style="border-bottom:1px solid #ececec;">'
        f'<td style="color:#3498db;font-weight:700;padding:{row_pad};font-size:{row_font};">'
        f'{ticker}{_coc_dot}{cache_tag}</td>'
        f'<td style="color:#495057;padding:{row_pad};font-size:{row_font};">{company[:28]}</td>'
        f'<td style="color:#6a6a6a;padding:{row_pad};font-size:0.72rem;">{sector}</td>'
        f'<td style="text-align:center;padding:{row_pad};">{score_cell}</td>'
        f'<td style="text-align:center;padding:{row_pad};">{macro_sens}</td>'
        f'<td style="text-align:center;padding:{row_pad};font-size:1rem;" '
        f'title="{s["AlertTip"]}">{s["AlertEmoji"]}</td>'
        f'<td style="color:{t_color};font-size:1.1rem;text-align:center;" title="{t_tip}">{t_arrow}</td>'
        f'<td style="text-align:center;padding:{row_pad};">{earn_cell}</td>'
        f'<td style="color:{_score_color_sub(int(s.get("Moat",0)),40)};font-size:0.75rem;'
        f'text-align:center;font-weight:600;">{int(s.get("Moat",0))}/40</td>'
        f'<td style="color:{_score_color_sub(int(s.get("Fortress",0)),25)};font-size:0.75rem;'
        f'text-align:center;font-weight:600;">{int(s.get("Fortress",0))}/25</td>'
        f'<td style="color:{_score_color_sub(int(s.get("Valuation",0)),20)};font-size:0.75rem;'
        f'text-align:center;font-weight:600;">{int(s.get("Valuation",0))}/20</td>'
        f'<td style="color:{_score_color_sub(int(s.get("Momentum",0)),10)};font-size:0.75rem;'
        f'text-align:center;font-weight:600;">{int(s.get("Momentum",0))}/10</td>'
        f'<td style="color:#0a0a0a;font-size:0.75rem;text-align:center;">{fcf_str}</td>'
        f'<td style="color:#0a0a0a;font-size:0.75rem;text-align:center;">{fpe_str}</td>'
        f'<td style="color:#495057;font-size:0.75rem;text-align:right;">{price_str}</td>'
        f'<td style="font-size:0.75rem;padding:{row_pad};">{_badge(mac_sc)}</td>'
        f'</tr>'
    )

# ── Render table (HTML starts at column 0 — avoids CommonMark code-fence) ────
_thead = (
    f'<div style="overflow-x:auto;margin:10px 0;">'
    f'<table style="width:100%;border-collapse:collapse;background:#ffffff;font-size:{row_font};">'
    f'<thead><tr style="border-bottom:2px solid #dee2e6;color:#6a6a6a;font-size:0.65rem;'
    f'text-transform:uppercase;letter-spacing:.05em;">'
    f'<th style="padding:{row_pad};text-align:left;">Ticker</th>'
    f'<th style="padding:{row_pad};text-align:left;">Company</th>'
    f'<th style="padding:{row_pad};text-align:left;">Sector</th>'
    f'<th style="padding:{row_pad};text-align:center;" '
    f'title="Buffett score, macro-adjusted if regime selected">Score</th>'
    f'<th style="padding:{row_pad};text-align:center;" '
    f'title="Sector sensitivity to selected regime">Macro Sens.</th>'
    f'<th style="padding:{row_pad};text-align:center;" '
    f'title="Quick action signal in current regime">Signal</th>'
    f'<th style="padding:{row_pad};text-align:center;" '
    f'title="Price vs 200-day MA">Trend</th>'
    f'<th style="padding:{row_pad};text-align:center;" '
    f'title="Next earnings date — red &lt;7d · yellow 7-14d · green 15-30d">Earnings</th>'
    f'<th style="padding:{row_pad};text-align:center;">Moat</th>'
    f'<th style="padding:{row_pad};text-align:center;">Fortress</th>'
    f'<th style="padding:{row_pad};text-align:center;">Val.</th>'
    f'<th style="padding:{row_pad};text-align:center;">Mom.</th>'
    f'<th style="padding:{row_pad};text-align:center;" title="FCF / Market Cap">FCF Yld</th>'
    f'<th style="padding:{row_pad};text-align:center;" title="Forward P/E">Fwd P/E</th>'
    f'<th style="padding:{row_pad};text-align:right;">Price</th>'
    f'<th style="padding:{row_pad};text-align:left;">Verdict</th>'
    f'</tr></thead><tbody>'
)
# Append greyed-out rows for tickers that couldn't be scored (ETFs, bad symbols)
if failed:
    for tkr in failed:
        colspan_cells = "".join(
            f'<td style="color:#aaa;font-size:0.75rem;text-align:center;'
            f'padding:{row_pad};">—</td>'
            for _ in range(14)
        )
        rows_html += (
            f'<tr style="border-bottom:1px solid #ececec;opacity:0.55;">'
            f'<td style="color:#999;font-weight:700;padding:{row_pad};font-size:{row_font};">'
            f'{tkr}</td>'
            f'<td style="color:#bbb;padding:{row_pad};font-size:{row_font};" colspan="2">'
            f'<em>Not scorable (ETF / index / invalid ticker)</em></td>'
            f'{colspan_cells}'
            f'</tr>'
        )

st.markdown(_thead + rows_html + "</tbody></table></div>", unsafe_allow_html=True)

# ── Per-ticker remove buttons ──────────────────────────────────────────────────
st.markdown("#### Manage tickers")
all_tickers_for_manage = [s.get("Ticker", "?") for s in scored] + failed
remove_cols = st.columns(min(len(all_tickers_for_manage), 8))
for idx, ticker in enumerate(all_tickers_for_manage):
    s = next((x for x in scored if x.get("Ticker") == ticker), None)
    with remove_cols[idx % len(remove_cols)]:
        if s:
            score_val = s.get("MacroAdj", s.get("Score", 0))
            color     = _score_color(int(score_val))
            label     = str(score_val)
        else:
            color = "#aaa"
            label = "N/A"
        st.markdown(
            f'<div style="text-align:center;font-size:0.7rem;color:{color};">'
            f'{ticker}<br><strong>{label}</strong></div>',
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

# ── How scores work ───────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("📖 How scores work", expanded=False):
    st.markdown("""
**The Buffett Score** is a 0–100 composite that evaluates each stock across five sections,
inspired by Warren Buffett's criteria for identifying high-quality businesses at fair prices.

| Section | Max | What it measures |
|---|---|---|
| **Quality Moat** | 40 | Gross & net margin vs sector peers · Return on equity · Revenue CAGR · Cash earnings quality |
| **Financial Fortress** | 25 | Piotroski F-Score (9-signal balance sheet strength) · Altman Z-Score (bankruptcy risk) · Debt/Equity ratio |
| **Valuation** | 20 | FCF yield · P/E vs sector median · Price/Book · DCF margin-of-safety bonus (+2 pts if ≥20% upside) |
| **Momentum & Trend** | 10 | Price above 200-day MA · 200-day MA slope rising · Net income improving YoY |
| **Shareholder Alignment** | 5 | Share count declining (buybacks) · Total shareholder yield |

**Verdicts**

| Score | Label | Meaning |
|---|---|---|
| 75 – 100 | 🟢 Strong Buy | High-quality, fairly-or-undervalued business with strong fundamentals |
| 60 – 74 | 🟩 Buy | Solid fundamentals with minor weaknesses in valuation or momentum |
| 45 – 59 | 🟡 Hold | Passing on most metrics but not compelling enough to add at current price |
| 30 – 44 | 🟠 Weak | Material weaknesses in quality, balance sheet, or valuation |
| 0 – 29 | 🔴 Avoid | Fails most criteria — deteriorating fundamentals or severely overvalued |

**Macro-Adjusted Score** takes the raw Buffett Score and shifts it up or down by up to ±15 points
based on how sensitive the stock's sector is to the economic regime you've selected above.
For example, a defensive healthcare stock gets a tailwind in a contraction while a cyclical industrial
gets a headwind. The raw score is always shown alongside the adjustment so you can see its effect.

The **sub-scores** in the table (Moat/40, Fortress/25, Val./20, Mom./10) let you spot exactly
where a stock is strong or weak at a glance — a high overall score with a low Valuation sub-score,
for instance, means a great business that is currently expensive.

*All data sourced from Yahoo Finance via yfinance and cached for 1–6 hours. Scores are a
quantitative starting point for research, not a buy/sell recommendation.*
""")

# ── CSV Export ────────────────────────────────────────────────────────────────
st.markdown("---")
export_data = [
    {
        "Ticker":        s.get("Ticker"),
        "Company":       s.get("Company"),
        "Sector":        s.get("Sector"),
        "Score":         s.get("Score"),
        "MacroAdj":      s.get("MacroAdj"),
        "Signal":        s.get("AlertEmoji"),
        "Earnings_Date": earnings_map.get(s.get("Ticker", ""), ""),
        "Moat":          s.get("Moat"),
        "Fortress":      s.get("Fortress"),
        "Valuation":     s.get("Valuation"),
        "Momentum":      s.get("Momentum"),
        "FCF_Yield":     s.get("FCF_Yield"),
        "Fwd_PE":        s.get("Fwd_PE"),
        "Price":         s.get("Price"),
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
    "**Earnings**: 🔴 &lt;7d · 🟡 7-14d · 🟢 15-30d. "
    "● = Circle of Competence tier. "
    "Scores & earnings cached 1–6 hr. "
    + DISCLAIMER
)
