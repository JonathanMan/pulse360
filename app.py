"""
Pulse360 — Navigation Router
==============================
Entry point for Streamlit Cloud. Defines all pages explicitly via
st.navigation() so page discovery works regardless of repo layout.

Run locally:  streamlit run app.py
Deploy:       push to GitHub → connect to Streamlit Cloud → add secrets
"""

import streamlit as st
from components.pulse360_theme import inject_theme, BLUE, BORDER, TEXT_PRI, TEXT_SEC, TEXT_MUT, CARD_BG, PAGE_BG

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
        # Macro Context
        ("📊", "Dashboard",           0, "Macro Context"),
        ("🌐", "Macro Pulse",         0, "Macro Context"),
        # My Portfolio
        ("🗂️", "Investment Analyser", 0, "My Portfolio"),
        ("⭐", "Watchlist",           0, "My Portfolio"),
        ("🏆", "Stock Screener",      1, "My Portfolio"),
        ("📋", "Portfolio Heatmap",   1, "My Portfolio"),
        # Research
        ("🔍", "Stock Research",      0, "Research"),
        ("🔬", "AI Research Desk",    0, "Research"),
        ("⚖️", "Market Valuation",    0, "Research"),
        # Analysis
        ("📈", "What to Own & When",  0, "Analysis"),
        ("🎛️", "Stress Test",         1, "Analysis"),
        ("📉", "Model Track Record",  2, "Analysis"),
        # Account
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

    # Do NOT call st.stop() here — navigation must already be set up above.
    # We just return; pg.run() is never reached so the page stays blank.
    return


# ── Build navigation FIRST — must happen before any st.stop() ─────────────────
# st.navigation() must be called before onboarding's early-return, otherwise
# Streamlit falls back to auto-discovery and shows a flat unsectioned sidebar.
from components.user_profile import get_nav_pages, get_profile, PROFILES  # noqa: E402

nav_sections = get_nav_pages()
pg = st.navigation(nav_sections)

# ── Run onboarding if no profile set (returns early, pg.run() is skipped) ─────
if "pulse360_profile" not in st.session_state:
    _render_onboarding()
    # _render_onboarding() returns here; pg.run() below is never reached.

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    profile = get_profile()
    profile_key = st.session_state.get("pulse360_profile", "Beginner")

    # Profile badge + switcher
    st.markdown(f"""
<style>
  .pb-wrap {{
    margin-bottom: 0.8rem;
    padding: 10px 12px;
    border-radius: 8px;
    background: {CARD_BG};
    border: 1px solid {BORDER};
  }}
  .pb-label {{
    font-size: 0.68rem;
    color: {TEXT_MUT};
    text-transform: uppercase;
    letter-spacing: .05em;
    margin-bottom: 4px;
  }}
  .pb-name {{
    font-size: 0.88rem;
    font-weight: 700;
    color: {profile["colour"]};
  }}
  .pb-desc {{
    font-size: 0.75rem;
    color: {TEXT_SEC};
    margin-top: 3px;
    line-height: 1.3;
  }}
</style>
<div class="pb-wrap">
  <div class="pb-label">Your profile</div>
  <div class="pb-name">{profile["icon"]}  {profile["label"]}</div>
  <div class="pb-desc">{profile["description"]}</div>
</div>
""", unsafe_allow_html=True)

    # Profile switcher (compact selectbox)
    new_profile = st.selectbox(
        "Switch profile",
        options=list(PROFILES.keys()),
        format_func=lambda k: f"{PROFILES[k]['icon']} {PROFILES[k]['label']}",
        index=list(PROFILES.keys()).index(profile_key),
        label_visibility="collapsed",
        key="sidebar_profile_switch",
    )
    if new_profile != profile_key:
        st.session_state["pulse360_profile"] = new_profile
        for key in ["portfolio_scored", "heatmap_prefill", "heatmap_extract_msg"]:
            st.session_state.pop(key, None)
        st.rerun()

    # Nav guide (only show entries relevant to current profile)
    level = profile["level"]

    guide_items = [
        ("📊", "Dashboard",          "Live recession risk, cycle phase & macro deep-dive.", 0),
        ("🗂️", "Investment Analyser", "Upload your portfolio or a fund brochure for a macro-aware breakdown.", 0),
        ("🔬", "AI Research Desk",    "On-demand AI research — macro snapshot, M&A, short squeezes & more.", 0),
        ("🔍", "Buffett Score",       "Is a stock high quality and fairly priced? Buffett/Munger framework.", 0),
        ("🏆", "Stock Screener",      "Rank ~80 large-caps by Buffett score. Apply a macro cycle overlay.", 1),
        ("📋", "Portfolio Heatmap",   "Paste your tickers — stress-test across 5 macro regimes instantly.", 1),
        ("⚖️", "Buffett Indicator",   "Is the overall stock market cheap or expensive vs the economy?", 0),
    ]
    analysis_items = [
        ("📈", "What to Own & When",  "Stocks, bonds, gold, oil — what performs best in each cycle phase?", 0),
        ("🎛️", "Stress Test",         "Dial up a 'what if' scenario and see how recession risk changes.", 1),
        ("📉", "Model Track Record",  "Did this model catch 2001, 2008, and 2020 in time?", 2),
    ]

    items_html = ""
    for icon, title, desc, min_level in guide_items:
        if level >= min_level:
            items_html += f"""
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">{icon} {title}</div>
      <div class="nav-guide-desc">{desc}</div>
    </div>
  </div>"""

    items_html += '<div class="nav-guide-section">Analysis</div>'
    for icon, title, desc, min_level in analysis_items:
        if level >= min_level:
            items_html += f"""
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">{icon} {title}</div>
      <div class="nav-guide-desc">{desc}</div>
    </div>
  </div>"""

    # Locked items hint
    locked = (
        [t for _, t, _, ml in guide_items if ml > level]
        + [t for _, t, _, ml in analysis_items if ml > level]
    )
    locked_html = ""
    if locked:
        locked_html = f"""
<div style="margin-top:14px; padding:8px 10px; border-radius:6px;
            background:{PAGE_BG}; border:1px dashed {BORDER};">
  <div style="font-size:0.7rem; color:{TEXT_SEC}; margin-bottom:4px;">
    Unlock more by switching profile:
  </div>
  <div style="font-size:0.72rem; color:{TEXT_MUT};">
    {'  ·  '.join(locked)}
  </div>
</div>"""

    st.markdown(f"""
<style>
  .nav-guide {{ margin-top:1rem; padding-top:0.8rem; border-top:1px solid {BORDER}; }}
  .nav-guide-item {{ display:flex; gap:8px; margin-bottom:10px; align-items:flex-start; }}
  .nav-guide-text {{ line-height:1.35; }}
  .nav-guide-title {{ font-size:0.82rem; font-weight:600; color:{TEXT_PRI}; }}
  .nav-guide-desc {{
    font-size:0.78rem; color:{TEXT_SEC};
    border-left:2px solid {BORDER};
    padding-left:7px; margin-top:3px; font-style:italic;
  }}
  .nav-guide-section {{
    font-size:0.72rem; font-weight:700; color:{TEXT_SEC};
    text-transform:uppercase; letter-spacing:.05em; margin:12px 0 6px 0;
  }}
</style>
<div class="nav-guide">
{items_html}
</div>
{locked_html}
""", unsafe_allow_html=True)

    # ── Watchlist mini-preview ─────────────────────────────────────────────────
    st.markdown("---")
    try:
        from components.watchlist_store import load_watchlist as _load_wl
        _wl = _load_wl()
        _wl_count = len(_wl) if _wl and _wl != 0 else 0
    except Exception:
        _wl_count = 0
        _wl = []

    if _wl_count > 0:
        st.markdown(
            f'<div style="font-size:0.7rem;font-weight:700;color:{TEXT_SEC};'
            f'text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">'
            f'⭐ Watchlist ({_wl_count})</div>',
            unsafe_allow_html=True,
        )
        # Show up to 5 tickers as compact pills
        preview_tickers = _wl[:5]
        pills_html = "".join(
            f'<span style="display:inline-block;background:#e8f1fb;border:1px solid {BORDER};'
            f'border-radius:6px;padding:2px 8px;font-size:0.72rem;color:{BLUE};'
            f'font-weight:600;margin:2px 3px 2px 0;">{t}</span>'
            for t in preview_tickers
        )
        if _wl_count > 5:
            pills_html += (
                f'<span style="font-size:0.7rem;color:{TEXT_MUT};"> +{_wl_count - 5} more</span>'
            )
        st.markdown(pills_html, unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div style="font-size:0.75rem;color:{TEXT_MUT};">⭐ Watchlist empty</div>',
            unsafe_allow_html=True,
        )


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
