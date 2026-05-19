"""
components/onboarding.py
========================
Full-page first-visit onboarding screen for Pie360.

Extracted from app.py to keep the router thin.

Public API
----------
    from components.onboarding import render_onboarding
    render_onboarding(save_profile_fn=_save_profile)
"""

from __future__ import annotations

from typing import Callable

import streamlit as st

from components.pulse360_theme import (
    BLUE, BORDER, CARD_BG, PAGE_BG,
    TEXT_MUT, TEXT_PRI, TEXT_SEC,
)
from components.user_profile import PROFILES


# ── Full nav structure: (icon, label, min_level, section) ─────────────────────
_NAV_ITEMS: list[tuple[str, str, int, str]] = [
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

# Keys cleared when user commits a profile choice
_PROFILE_CLEARED_KEYS = ("portfolio_scored", "heatmap_prefill", "heatmap_extract_msg")


def render_onboarding(*, save_profile_fn: Callable[[str], None]) -> None:
    """
    Render the full-page onboarding flow.

    Left column  — profile radio + feature preview card + Get Started button.
    Right column — live nav preview that updates as the user picks a profile.

    The caller must set up ``st.navigation()`` *before* calling this function.
    When the user clicks "Get Started", this function writes the profile to
    session_state and calls *save_profile_fn* for persistence, then returns
    normally — the caller should *not* call ``pg.run()`` afterwards for this
    render cycle (both the onboarding guard and the button's ``st.rerun()``
    handle that).
    """
    # ── Per-page CSS ──────────────────────────────────────────────────────────
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

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown(f"""
<div style="text-align:center; padding: 2rem 0 1.2rem 0;">
  <div style="font-size:2.8rem; margin-bottom:0.3rem;">📊</div>
  <h1 style="font-size:2.2rem; font-weight:800; color:{TEXT_PRI}; margin:0;">
    Welcome to Pie360
  </h1>
  <p style="font-size:1.1rem; font-weight:600; color:{TEXT_PRI};
            margin-top:0.4rem; margin-bottom:0.2rem; letter-spacing:0.02em;">
    Slice through the noise
  </p>
  <p style="color:{TEXT_SEC}; font-size:1rem; margin-top:0.3rem;">
    AI-Powered Economic Cycle Dashboard &nbsp;·&nbsp; Real-time Business Cycle Monitoring
  </p>
</div>
""", unsafe_allow_html=True)

    st.markdown("---")

    left_col, right_col = st.columns([1, 1], gap="large")

    # ── Left: profile question ────────────────────────────────────────────────
    with left_col:
        st.markdown("#### How would you describe yourself as an investor?")
        st.caption("Pie360 adapts to your level. You can change this any time from ⚙️ Settings.")

        chosen = st.radio(
            "Profile",
            options=list(PROFILES.keys()),
            format_func=lambda k: f"{PROFILES[k]['icon']}  {PROFILES[k]['label']}",
            label_visibility="collapsed",
            key="onboarding_choice",
        )

        p = PROFILES[chosen]
        _profile_colours = {
            "Beginner": ("#2ecc71", "#0e2a1a"),
            "Investor": ("#3498db", "#0a1e2e"),
            "Analyst":  ("#9b59b6", "#1a0e2a"),
        }
        fg, bg = _profile_colours.get(chosen, ("#888", "#111"))

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

        if st.button("Get Started →", type="primary", width='stretch'):
            st.session_state["pulse360_profile"] = chosen
            save_profile_fn(chosen)
            for key in _PROFILE_CLEARED_KEYS:
                st.session_state.pop(key, None)
            st.rerun()

    # ── Right: live nav preview ───────────────────────────────────────────────
    with right_col:
        level = PROFILES[chosen]["level"]

        sections_seen: set[str] = set()
        nav_html = ""
        for icon, label, min_lvl, section in _NAV_ITEMS:
            if section not in sections_seen:
                sections_seen.add(section)
                if section:
                    nav_html += f'<div class="ob-nav-header">{section}</div>'

            available = level >= min_lvl
            css_cls  = "available" if available else "locked"
            lock_tag = "" if available else '<span class="ob-lock">🔒</span>'
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
    <span style="float:right;font-weight:400;color:{TEXT_MUT};
                 text-transform:none;letter-spacing:0;">{unlocked} of {total} pages</span>
  </div>
  {nav_html}
</div>
""", unsafe_allow_html=True)
