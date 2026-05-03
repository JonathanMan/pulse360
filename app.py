"""
Pulse360 — Navigation Router
==============================
Entry point for Streamlit Cloud. Defines all pages explicitly via
st.navigation() so page discovery works regardless of repo layout.

Run locally:  streamlit run app.py
Deploy:       push to GitHub → connect to Streamlit Cloud → add secrets
"""

import streamlit as st
from components.pulse360_theme import (
    inject_theme, BLUE, BORDER, TEXT_PRI, TEXT_SEC, TEXT_MUT, CARD_BG, PAGE_BG,
    FG_PRIMARY, FG_SEC, FG_MUTED, SUCCESS, DANGER,
)
from components.auth import require_auth, render_logout_button
from components.profile_store import load_profile, save_profile
from components.analytics import log_page_view, is_admin


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_wl_prices(tickers: tuple) -> dict:
    """Fetch latest price + day % change for each ticker. Cached 5 min."""
    if not tickers:
        return {}
    import yfinance as yf
    result = {}
    try:
        ts = yf.Tickers(" ".join(tickers))
        for t in tickers:
            try:
                info = ts.tickers[t].fast_info
                price = info.last_price
                prev  = info.previous_close
                chg   = ((price - prev) / prev * 100) if (price and prev) else None
                result[t] = {"price": price, "chg_pct": chg}
            except Exception:
                result[t] = {"price": None, "chg_pct": None}
    except Exception:
        result = {t: {"price": None, "chg_pct": None} for t in tickers}
    return result

st.set_page_config(
    page_title="Pulse360",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global Taplox theme (light mode) ─────────────────────────────────────────
inject_theme()

# ── Onboarding card styles (light variants) ───────────────────────────────────
st.markdown(f"""
<style>
    .profile-card {{
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 8px;
        background: {CARD_BG};
        cursor: pointer;
        transition: border-color 0.2s;
    }}
    .profile-card.selected {{
        border-color: {BLUE};
        background: #eef4ff;
    }}
    .profile-card-title {{
        font-size: 1rem;
        font-weight: 700;
        color: {TEXT_PRI};
        margin-bottom: 4px;
    }}
    .profile-card-desc {{
        font-size: 0.82rem;
        color: {TEXT_SEC};
        line-height: 1.4;
    }}
    .profile-badge {{
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
    }}
</style>
""", unsafe_allow_html=True)


# ── Onboarding ─────────────────────────────────────────────────────────────────
def _render_onboarding() -> None:
    """
    Full-page onboarding shown on first visit.
    Left column  — profile question + radio + Get Started button.
    Right column — live nav preview that updates as the user picks a profile.
    Calls st.stop() to block normal page rendering until done.
    """
    from components.user_profile import PROFILES

    # ── Full nav structure: (icon, label, min_level, section) ─────────────────
    _NAV_ITEMS = [
        # Main section
        ("📊", "Dashboard",           0, ""),
        ("🗂️", "Investment Analyser", 0, ""),
        ("🔬", "AI Research Desk",    0, ""),
        ("🔍", "Buffett Score",       0, ""),
        ("⭐", "Watchlist",           0, ""),
        ("🏆", "Stock Screener",      1, ""),
        ("📋", "Portfolio Heatmap",   1, ""),
        ("⚖️", "Buffett Indicator",   0, ""),
        # Analysis section
        ("📈", "What to Own & When",  0, "Analysis"),
        ("🎛️", "Stress Test",         1, "Analysis"),
        ("📉", "Model Track Record",  2, "Analysis"),
        # Account section
        ("⚙️", "Settings",            0, "Account"),
    ]

    # ── Styles ─────────────────────────────────────────────────────────────────
    st.markdown(f"""
<style>
  .ob-nav-preview {{
    background: {PAGE_BG};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 16px 18px;
    height: 100%;
  }}
  .ob-nav-header {{
    font-size: 0.68rem;
    font-weight: 700;
    color: {TEXT_SEC};
    text-transform: uppercase;
    letter-spacing: .07em;
    margin: 14px 0 6px 0;
  }}
  .ob-nav-header:first-child {{ margin-top: 0; }}
  .ob-nav-item {{
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 10px;
    border-radius: 7px;
    margin-bottom: 2px;
    font-size: 0.85rem;
    font-weight: 500;
  }}
  .ob-nav-item.available {{
    color: {TEXT_PRI};
    background: #e8f1fb;
  }}
  .ob-nav-item.locked {{
    color: {TEXT_MUT};
    background: transparent;
  }}
  .ob-nav-item .ob-lock {{
    font-size: 0.65rem;
    margin-left: auto;
    color: {TEXT_MUT};
  }}
  .ob-profile-card {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 14px 16px;
    margin: 10px 0 18px 0;
    background: {CARD_BG};
  }}
</style>
""", unsafe_allow_html=True)

    # ── Page header ────────────────────────────────────────────────────────────
    st.markdown(f"""
<div style="text-align:center; padding: 2rem 0 1.2rem 0;">
  <div style="font-size:2.8rem; margin-bottom:0.3rem;">📊</div>
  <h1 style="font-size:2.2rem; font-weight:800; color:{TEXT_PRI}; margin:0;">
    Welcome to Pulse360
  </h1>
  <p style="color:{TEXT_SEC}; font-size:1rem; margin-top:0.5rem;">
    AI-Powered Economic Cycle Dashboard &nbsp;·&nbsp; Real-time Business Cycle Monitoring
  </p>
</div>
""", unsafe_allow_html=True)

    st.markdown("---")

    left_col, right_col = st.columns([1, 1], gap="large")

    # ── Left: profile question ─────────────────────────────────────────────────
    with left_col:
        st.markdown("#### How would you describe yourself as an investor?")
        st.caption("Pulse360 adapts to your level. You can change this any time from ⚙️ Settings.")

        chosen = st.radio(
            "Profile",
            options=list(PROFILES.keys()),
            format_func=lambda k: f"{PROFILES[k]['icon']}  {PROFILES[k]['label']}",
            label_visibility="collapsed",
            key="onboarding_choice",
        )

        p       = PROFILES[chosen]
        fg, bg  = {"Beginner": ("#2ecc71","#0e2a1a"),
                   "Investor": ("#3498db","#0a1e2e"),
                   "Analyst":  ("#9b59b6","#1a0e2a")}[chosen]

        features_html = "".join(
            f'<div style="color:{TEXT_PRI};font-size:0.83rem;margin-bottom:4px;">✓ {f}</div>'
            for f in p["features"]
        )
        st.markdown(f"""
<div class="ob-profile-card">
  <div style="font-size:0.7rem;color:{TEXT_SEC};text-transform:uppercase;
              letter-spacing:.05em;font-weight:700;margin-bottom:8px;">
    What you'll see
  </div>
  {features_html}
  <div style="margin-top:10px;font-size:0.75rem;color:{TEXT_MUT};line-height:1.4;">
    You can change this any time — no data is lost when switching profiles.
  </div>
</div>
""", unsafe_allow_html=True)

        if st.button("Get Started →", type="primary", use_container_width=True):
            st.session_state["pulse360_profile"] = chosen
            from components.supabase_client import get_user_email as _get_email_ob
            save_profile(_get_email_ob(), chosen)
            for key in ["portfolio_scored", "heatmap_prefill", "heatmap_extract_msg"]:
                st.session_state.pop(key, None)
            st.rerun()

    # ── Right: live nav preview ────────────────────────────────────────────────
    with right_col:
        level = PROFILES[chosen]["level"]

        # Build nav item HTML
        sections_seen: set[str] = set()
        nav_html = ""
        for icon, label, min_lvl, section in _NAV_ITEMS:
            # Section header
            if section not in sections_seen:
                sections_seen.add(section)
                if section:
                    nav_html += (
                        f'<div class="ob-nav-header">{section}</div>'
                    )

            available = level >= min_lvl
            css_cls   = "available" if available else "locked"
            lock_tag  = "" if available else '<span class="ob-lock">🔒</span>'
            nav_html += (
                f'<div class="ob-nav-item {css_cls}">'
                f'<span>{icon}</span>'
                f'<span>{label}</span>'
                f'{lock_tag}'
                f'</div>'
            )

        unlocked = sum(1 for _, _, ml, _ in _NAV_ITEMS if level >= ml)
        total    = len(_NAV_ITEMS)

        st.markdown(f"""
<div class="ob-nav-preview">
  <div style="font-size:0.72rem;font-weight:700;color:{TEXT_SEC};
              text-transform:uppercase;letter-spacing:.07em;margin-bottom:10px;">
    Your navigation
    <span style="float:right;font-weight:400;color:{TEXT_MUT};text-transform:none;
                 letter-spacing:0;">{unlocked} of {total} pages</span>
  </div>
  {nav_html}
</div>
""", unsafe_allow_html=True)

    st.stop()


# ── Auth gate — must pass before any page renders ─────────────────────────────
require_auth()

# ── Restore saved profile from Supabase (first load per session only) ─────────
if "pulse360_profile" not in st.session_state:
    from components.supabase_client import get_user_email as _get_email_boot
    _saved_profile = load_profile(_get_email_boot())
    if _saved_profile:
        st.session_state["pulse360_profile"] = _saved_profile

# ── Run onboarding if no profile set ──────────────────────────────────────────
if "pulse360_profile" not in st.session_state:
    _render_onboarding()

# ── Build dynamic navigation ───────────────────────────────────────────────────
from components.user_profile import get_nav_pages, get_profile, PROFILES  # noqa: E402

nav_sections = get_nav_pages()
if is_admin():
    nav_sections["Account"].append(
        st.Page("pages/13_Admin.py", title="Analytics", icon=":material/monitoring:")
    )
pg = st.navigation(nav_sections)

# ── Log page view (once per navigation, deduped in session) ───────────────────
log_page_view(pg.title)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    profile = get_profile()
    profile_key = st.session_state.get("pulse360_profile", "Beginner")

    # ── Watchlist mini-preview (top of sidebar, below nav) ───────────────────
    # Read from session_state cache — avoids calling st_javascript inside the
    # sidebar (which triggers a double-render rerun cycle).
    from components.supabase_client import get_user_email as _get_email
    _raw_wl = st.session_state.get(f"_watchlist_{_get_email()}", [])
    _wl = [t for t in _raw_wl if t] if isinstance(_raw_wl, list) else []

    if _wl:
        _prices = _fetch_wl_prices(tuple(_wl))
        rows_html = ""
        for _t in _wl[:8]:
            _d     = _prices.get(_t, {})
            _price = _d.get("price")
            _chg   = _d.get("chg_pct")
            _price_str = f"{_price:,.2f}" if _price else "—"
            if _chg is not None:
                _chg_color = SUCCESS if _chg >= 0 else DANGER
                _chg_str   = f"{_chg:+.2f}%"
            else:
                _chg_color = FG_MUTED
                _chg_str   = "—"
            rows_html += (
f'<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-top:1px solid {BORDER};">'
f'<span style="font-family:\'Geist Mono\',monospace;font-size:0.78rem;font-weight:600;color:{FG_PRIMARY};">{_t}</span>'
f'<span style="font-family:\'Geist Mono\',monospace;font-size:0.75rem;color:{FG_SEC};">{_price_str}</span>'
f'<span class="wl-chg" style="font-family:\'Geist Mono\',monospace;font-size:0.75rem;font-weight:600;color:{_chg_color};min-width:54px;text-align:right;">{_chg_str}</span>'
f'</div>'
            )
        st.markdown(
f'<div style="border:1px solid {BORDER};background:{CARD_BG};padding:10px 12px 6px 12px;margin-bottom:0.75rem;">'
f'<div style="font-family:\'Geist Mono\',monospace;font-size:0.62rem;font-weight:600;color:{FG_MUTED};letter-spacing:0.14em;text-transform:uppercase;padding-bottom:4px;">Watchlist</div>'
f'{rows_html}'
f'</div>',
unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div style="border:1px solid {BORDER};background:{CARD_BG};padding:10px 12px;margin-bottom:0.75rem;">'
            f'<div style="font-family:\'Geist Mono\',monospace;font-size:0.62rem;font-weight:600;color:{FG_MUTED};letter-spacing:0.14em;text-transform:uppercase;padding-bottom:6px;">Watchlist</div>'
            f'<div style="font-family:\'Geist Mono\',monospace;font-size:0.72rem;color:{FG_MUTED};letter-spacing:0.04em;">No tickers yet'
            f' — <a href="/Watchlist" target="_self" style="color:{FG_PRIMARY};">add from Watchlist</a></div>'
            f'</div>',
            unsafe_allow_html=True,
        )





    st.markdown(f'<div style="border-top:1px solid {BORDER};margin:12px 0 8px 0;"></div>', unsafe_allow_html=True)
    render_logout_button()

# ── Alert engine — check rules on every page load ─────────────────────────────
# We only run the check when the dashboard has already cached live values in
# session state (key: "pulse360_live_values"), so we never trigger a fresh FRED
# pull from the router itself.  The Dashboard page populates that key.
try:
    from components.alert_engine import check_and_render_alerts as _check_alerts
    _live = st.session_state.get("pulse360_live_values")
    _prob = st.session_state.get("pulse360_recession_prob")
    if _live is not None:
        _check_alerts(_live, _prob)
except Exception:
    pass  # never let alert failures break page routing

pg.run()
