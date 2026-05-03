"""
Pulse360 — Settings
=====================
User-facing preferences page.

Sections:
  1. Investor Profile   — switch between Beginner / Investor / Analyst with
                          rich feature-preview cards
  2. Dashboard defaults — default macro regime, compact mode toggle
  3. Data & API         — FRED / Anthropic key status, cache controls
  4. About              — version, data sources, disclaimer
"""

from __future__ import annotations

import streamlit as st

from components.user_profile import PROFILES, feature_visible, get_profile, get_profile_key
from components.profile_store import save_profile
from components.supabase_client import get_user_email

# ── Page config ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main .block-container { max-width: 860px; padding-top: 1.2rem; }

    /* Profile cards */
    .sp-card {
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 18px 20px;
        margin-bottom: 10px;
        background: #0e0e1a;
        transition: border-color .2s, background .2s;
        cursor: pointer;
    }
    .sp-card.active {
        border-color: #6c63ff;
        background: #13132a;
        box-shadow: 0 0 0 1px #6c63ff33;
    }
    .sp-card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 8px;
    }
    .sp-card-name {
        font-size: 1.05rem;
        font-weight: 700;
        color: #ffffff;
    }
    .sp-card-badge {
        font-size: 0.72rem;
        font-weight: 600;
        padding: 2px 9px;
        border-radius: 10px;
        letter-spacing: .03em;
    }
    .sp-card-desc {
        font-size: 0.83rem;
        color: #aaaaaa;
        margin-bottom: 10px;
        line-height: 1.45;
    }
    .sp-feature {
        font-size: 0.8rem;
        color: #cccccc;
        margin-bottom: 3px;
    }
    .sp-feature::before { content: "✓  "; color: #00a35a; }
    .sp-locked {
        font-size: 0.78rem;
        color: #444;
        margin-bottom: 2px;
    }
    .sp-locked::before { content: "🔒  "; }

    /* Section headers */
    .settings-section {
        font-size: 0.72rem;
        font-weight: 700;
        color: #555;
        text-transform: uppercase;
        letter-spacing: .08em;
        margin: 28px 0 12px 0;
        padding-bottom: 6px;
        border-bottom: 1px solid #1e1e3a;
    }

    /* Status pills */
    .status-ok   { color: #00a35a; font-weight: 600; font-size: 0.82rem; }
    .status-warn { color: #c98800; font-weight: 600; font-size: 0.82rem; }
    .status-err  { color: #d92626; font-weight: 600; font-size: 0.82rem; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## ⚙️ Settings")
st.caption("Customise how Pulse360 works for you. Changes take effect immediately.")

# ═══════════════════════════════════════════════════════════════════════════════
# 1. INVESTOR PROFILE
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="settings-section">Investor Profile</div>', unsafe_allow_html=True)

st.markdown(
    "Your profile controls which features are visible across the app. "
    "Switch any time — your data is never lost.",
    unsafe_allow_html=False,
)

current_key = get_profile_key()

_BADGE_COLOURS: dict[str, tuple[str, str]] = {
    "Beginner": ("#00a35a", "#0e2a1a"),
    "Investor": ("#3498db", "#0a1e2e"),
    "Analyst":  ("#9b59b6", "#1a0e2a"),
}

cols = st.columns(3)
for idx, (key, prof) in enumerate(PROFILES.items()):
    fg, bg = _BADGE_COLOURS[key]
    is_active = key == current_key
    active_cls = "active" if is_active else ""
    features_html = "".join(f'<div class="sp-feature">{f}</div>' for f in prof["features"])
    locked_html   = "".join(f'<div class="sp-locked">{h}</div>'  for h in prof["hidden"])

    with cols[idx]:
        st.markdown(f"""
<div class="sp-card {active_cls}">
  <div class="sp-card-header">
    <span class="sp-card-name">{prof["icon"]}  {prof["label"]}</span>
    <span class="sp-card-badge" style="color:{fg};background:{bg};">
      {'Active' if is_active else key}
    </span>
  </div>
  <div class="sp-card-desc">{prof["description"]}</div>
  {features_html}
  {('<div style="margin-top:8px;">' + locked_html + '</div>') if locked_html else ''}
</div>
""", unsafe_allow_html=True)

        btn_label = "✓ Current profile" if is_active else f"Switch to {prof['label']}"
        btn_type  = "primary" if is_active else "secondary"
        if st.button(
            btn_label,
            key=f"profile_btn_{key}",
            type=btn_type,
            use_container_width=True,
            disabled=is_active,
        ):
            st.session_state["pulse360_profile"] = key
            save_profile(get_user_email(), key)
            for clear_key in ["portfolio_scored", "heatmap_prefill", "heatmap_extract_msg"]:
                st.session_state.pop(clear_key, None)
            st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# 2. DASHBOARD DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="settings-section">Dashboard Defaults</div>', unsafe_allow_html=True)

dcol1, dcol2 = st.columns(2)

with dcol1:
    from components.stock_score_utils import _MACRO_ADJ  # noqa: E402
    regime_options = list(_MACRO_ADJ.keys())
    saved_regime   = st.session_state.get("default_regime", "Normal")
    if saved_regime not in regime_options:
        saved_regime = "Normal"

    new_regime = st.selectbox(
        "Default macro regime",
        options=regime_options,
        index=regime_options.index(saved_regime),
        help=(
            "Pre-selects this regime in the Stock Screener and Portfolio Heatmap "
            "each time you open them."
        ),
    )
    if new_regime != saved_regime:
        st.session_state["default_regime"] = new_regime
        st.success(f"Default regime set to **{new_regime}**.", icon="✅")

with dcol2:
    compact_on = st.toggle(
        "Compact table mode",
        value=st.session_state.get("compact_mode", False),
        help="Reduces row padding in the Stock Screener for a denser view.",
    )
    if compact_on != st.session_state.get("compact_mode", False):
        st.session_state["compact_mode"] = compact_on

    st.caption(
        "Compact mode is currently **on**." if compact_on
        else "Compact mode is currently **off**."
    )

# ═══════════════════════════════════════════════════════════════════════════════
# 3. DATA & API STATUS
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="settings-section">Data & API Status</div>', unsafe_allow_html=True)

def _key_status(secret_key: str) -> tuple[str, str]:
    """Return (status_class, label) for a secrets key."""
    try:
        val = st.secrets.get(secret_key, "")
        if val and len(str(val)) > 8:
            return "status-ok", "Connected ✓"
        return "status-warn", "Key present but looks short"
    except Exception:
        return "status-err", "Not configured"


fred_cls,  fred_lbl  = _key_status("FRED_API_KEY")
anth_cls,  anth_lbl  = _key_status("ANTHROPIC_API_KEY")

api_col1, api_col2, api_col3 = st.columns(3)

with api_col1:
    st.markdown("**FRED API**")
    st.markdown(f'<span class="{fred_cls}">{fred_lbl}</span>', unsafe_allow_html=True)
    st.caption("Powers all economic indicator charts (GDP, CPI, PMI, yield curve…)")

with api_col2:
    st.markdown("**Anthropic API**")
    st.markdown(f'<span class="{anth_cls}">{anth_lbl}</span>', unsafe_allow_html=True)
    st.caption("Powers AI Research Desk, Daily Briefing, and screenshot extraction.")

with api_col3:
    st.markdown("**Live market data**")
    try:
        import yfinance as yf  # type: ignore
        st.markdown('<span class="status-ok">yfinance available ✓</span>', unsafe_allow_html=True)
    except ImportError:
        st.markdown('<span class="status-err">yfinance not installed</span>', unsafe_allow_html=True)
    st.caption("Powers stock price, FCF yield, forward P/E, and price trend columns.")

st.markdown("")

# Cache controls
with st.expander("🗂️  Cache controls", expanded=False):
    st.caption(
        "Pulse360 caches stock scores and FRED data for up to 1 hour to keep "
        "the app fast. Use the buttons below to bust the cache for a specific area."
    )
    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        if st.button("🔄 Clear stock score cache", use_container_width=True):
            # Clear all @st.cache_data decorated functions that score stocks
            try:
                from components.stock_score_utils import fetch_stock_data
                fetch_stock_data.clear()
                st.success("Stock score cache cleared.")
            except Exception as e:
                st.warning(f"Could not clear: {e}")
    with cc2:
        if st.button("🔄 Clear FRED cache", use_container_width=True):
            try:
                # Dashboard caches data via @st.cache_data — clear all
                st.cache_data.clear()
                st.success("All cached data cleared.")
            except Exception as e:
                st.warning(f"Could not clear: {e}")
    with cc3:
        if st.button("🔄 Clear all caches", use_container_width=True):
            st.cache_data.clear()
            st.success("All caches cleared. Next page load will re-fetch live data.")

# ═══════════════════════════════════════════════════════════════════════════════
# 4. ABOUT
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="settings-section">About</div>', unsafe_allow_html=True)

about_col1, about_col2 = st.columns([2, 1])

with about_col1:
    st.markdown("""
**Pulse360** is an AI-powered economic cycle dashboard for real-time business
cycle monitoring and investment decision-making.

**Data sources**
- Federal Reserve Economic Data (FRED) — macroeconomic indicators
- Yahoo Finance (yfinance) — live equity prices, fundamentals
- Anthropic Claude — AI analysis, briefings, portfolio extraction

**Scoring framework**
The Buffett Score is a 100-point composite across four pillars:
Moat (40 pts), Financial Fortress (25 pts), Valuation (20 pts),
and Momentum (10 pts), plus a macro regime overlay (±15 pts).
""")

with about_col2:
    st.markdown("**Feature availability by profile**")
    feature_table = [
        ("DCF / Owner Earnings",    1),
        ("Altman Z detail",          1),
        ("Stock Screener",           1),
        ("Portfolio Heatmap",        1),
        ("Conviction threshold",     2),
        ("Macro Beta column",        2),
        ("Model Track Record",       2),
        ("SBC toggle (DCF)",         2),
    ]
    current_level = get_profile()["level"]
    rows = ""
    for feat, min_lvl in feature_table:
        if current_level >= min_lvl:
            icon  = "✅"
            color = "#00a35a"
        else:
            icon  = "🔒"
            color = "#444"
        rows += (
            f'<tr>'
            f'<td style="padding:3px 6px;font-size:0.78rem;color:#ccc;">{feat}</td>'
            f'<td style="padding:3px 6px;text-align:center;">{icon}</td>'
            f'</tr>'
        )
    st.markdown(
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr>'
        f'<th style="font-size:0.65rem;color:#555;text-align:left;padding:3px 6px;">Feature</th>'
        f'<th style="font-size:0.65rem;color:#555;text-align:center;padding:3px 6px;">You</th>'
        f'</tr></thead>'
        f'<tbody>{rows}</tbody>'
        f'</table>',
        unsafe_allow_html=True,
    )
    st.caption("Switch profile above to unlock more features.")

st.markdown("---")
st.caption(
    "Pulse360 is for informational purposes only and does not constitute financial advice. "
    "Always do your own research before making investment decisions."
)
