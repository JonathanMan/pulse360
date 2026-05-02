"""
components/user_profile.py
============================
Investor profiling system for Pulse360.

Three tiers:
  Beginner  — new to investing, wants macro context without jargon
  Investor  — self-directed, manages own portfolio, comfortable with stock research
  Analyst   — professional/sophisticated, wants every tool and technical detail

Usage in any page:
    from components.user_profile import feature_visible

    if feature_visible("buffett_dcf"):
        # show DCF tab
"""

from __future__ import annotations
import streamlit as st

# ── Profile definitions ────────────────────────────────────────────────────────
PROFILES: dict[str, dict] = {
    "Beginner": {
        "label":       "Curious Learner",
        "icon":        "🌱",
        "level":       0,
        "colour":      "#00a35a",
        "description": (
            "Macro concepts explained clearly. "
            "Stock quality at a glance. No jargon."
        ),
        "features": [
            "Economy dashboard",
            "Stock quality scores (simplified)",
            "What to own in each cycle phase",
            "Is the market cheap or expensive?",
            "AI portfolio & fund analyser",
        ],
        "hidden": [
            "Stock Screener",
            "Portfolio Heatmap",
            "Stress Test",
            "Model Track Record",
            "DCF / Owner Earnings",
            "Altman Z-Score detail",
            "Macro Beta column",
        ],
    },
    "Investor": {
        "label":       "Active Investor",
        "icon":        "📊",
        "level":       1,
        "colour":      "#3498db",
        "description": (
            "Full stock research toolkit, portfolio stress-testing, "
            "macro overlays, and action alerts."
        ),
        "features": [
            "Everything in Curious Learner, plus:",
            "Stock Screener with macro overlay",
            "Portfolio Macro Heatmap + Action Alerts",
            "Full Buffett Score (DCF, Altman Z)",
            "Scenario Stress Test",
        ],
        "hidden": [
            "Model Track Record",
            "SBC deduction toggle (DCF)",
            "Conviction threshold slider",
        ],
    },
    "Analyst": {
        "label":       "Pro / Analyst",
        "icon":        "🏦",
        "level":       2,
        "colour":      "#9b59b6",
        "description": (
            "Every feature, every dial. "
            "Technical models, backtest, full parameter control."
        ),
        "features": [
            "Everything in Active Investor, plus:",
            "Model Track Record & backtest",
            "SBC deduction toggle in DCF",
            "Conviction threshold calibration",
            "Macro Beta column in Screener",
        ],
        "hidden": [],
    },
}

_LEVEL = {k: v["level"] for k, v in PROFILES.items()}

# ── Feature → minimum level required ──────────────────────────────────────────
_FEATURE_LEVELS: dict[str, int] = {
    # Dashboard
    "dashboard_all_tabs":        0,   # all profiles
    # Buffett Score
    "buffett_dcf_tab":           1,   # Investor+
    "buffett_altman_detail":     1,   # Investor+
    "buffett_piotroski_detail":  1,   # Investor+
    "buffett_sbc_toggle":        2,   # Analyst only
    # Screener
    "screener_macro_beta_col":   2,   # Analyst only
    "screener_presets":          0,   # all profiles
    # Portfolio Heatmap
    "heatmap_action_engine":     1,   # Investor+
    "heatmap_conviction_slider": 2,   # Analyst only
    "heatmap_macro_beta_expander": 1, # Investor+
    # Analysis pages
    "page_stress_test":          1,   # Investor+
    "page_backtest":             2,   # Analyst only
    # Navigation pages
    "page_screener":             1,   # Investor+
    "page_heatmap":              1,   # Investor+
}


def get_profile_key() -> str:
    """Return the current profile key, defaulting to 'Beginner'."""
    return st.session_state.get("pulse360_profile", "Beginner")


def get_profile() -> dict:
    """Return the current profile dict."""
    return PROFILES.get(get_profile_key(), PROFILES["Beginner"])


def feature_visible(feature_key: str) -> bool:
    """
    Return True if the feature should be shown for the current profile.

    Usage:
        if feature_visible("buffett_dcf_tab"):
            with tab_dcf:
                ...
    """
    current_level = get_profile()["level"]
    required_level = _FEATURE_LEVELS.get(feature_key, 0)
    return current_level >= required_level


def get_nav_pages(profile_key: str | None = None) -> dict[str, list]:
    """
    Return the st.Page lists for the given profile, ready to pass to
    st.navigation().  Keys are section headers.
    """
    if profile_key is None:
        profile_key = get_profile_key()
    level = _LEVEL.get(profile_key, 0)

    main_pages = [
        st.Page("pages/0_Dashboard.py",   title="Dashboard",           icon="📊", default=True),
        st.Page("pages/4_Portfolio.py",   title="Investment Analyser",  icon="🗂️"),
        st.Page("pages/5_Briefing.py",    title="AI Research Desk",     icon="🔬"),
        st.Page("pages/7_Stock_Score.py", title="Buffett Score",         icon="🔍"),
        st.Page("pages/11_Watchlist.py",  title="Watchlist",             icon="⭐"),
    ]
    if level >= 1:
        main_pages.append(st.Page("pages/8_Screener.py", title="Stock Screener",   icon="🏆"))
        main_pages.append(st.Page("pages/9_Heatmap.py",  title="Portfolio Heatmap", icon="📋"))
    main_pages.append(st.Page("pages/6_Buffett.py", title="Buffett Indicator", icon="⚖️"))

    analysis_pages = [
        st.Page("pages/2_Phase_Returns.py", title="What to Own & When", icon="📈"),
    ]
    if level >= 1:
        analysis_pages.append(st.Page("pages/3_Simulator.py", title="Stress Test", icon="🎛️"))
    if level >= 2:
        analysis_pages.append(st.Page("pages/1_Backtest.py", title="Model Track Record", icon="📉"))

    settings_pages = [
        st.Page("pages/12_Alerts.py",   title="Alerts",   icon="🔔"),
        st.Page("pages/10_Settings.py", title="Settings", icon="⚙️"),
    ]

    return {"": main_pages, "Analysis": analysis_pages, "Account": settings_pages}
