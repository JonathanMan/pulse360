"""
tests/test_user_profile.py
============================
Tests for the profile / feature-visibility system.
Wrong feature gating = users see features they shouldn't (or can't see ones they paid for).
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from components.user_profile import (
    PROFILES,
    feature_visible,
    get_profile,
    get_profile_key,
    get_nav_pages,
)


class TestProfileKeys:
    def test_three_profiles_exist(self):
        assert set(PROFILES.keys()) == {"Beginner", "Investor", "Analyst"}

    def test_each_profile_has_required_fields(self):
        for key, p in PROFILES.items():
            assert "level" in p,       f"{key} missing level"
            assert "label" in p,       f"{key} missing label"
            assert "features" in p,    f"{key} missing features"
            assert "hidden" in p,      f"{key} missing hidden"

    def test_levels_are_0_1_2(self):
        levels = sorted(p["level"] for p in PROFILES.values())
        assert levels == [0, 1, 2]

    def test_analyst_has_no_hidden_features(self):
        assert PROFILES["Analyst"]["hidden"] == []


class TestGetProfileKey:
    def test_defaults_to_beginner(self):
        assert get_profile_key() == "Beginner"

    def test_returns_set_profile(self):
        st.session_state["pulse360_profile"] = "Investor"
        assert get_profile_key() == "Investor"

    def test_returns_analyst(self):
        st.session_state["pulse360_profile"] = "Analyst"
        assert get_profile_key() == "Analyst"


class TestFeatureVisible:
    def test_beginner_sees_dashboard(self):
        st.session_state["pulse360_profile"] = "Beginner"
        assert feature_visible("dashboard_all_tabs") is True

    def test_beginner_cannot_see_dcf(self):
        st.session_state["pulse360_profile"] = "Beginner"
        assert feature_visible("buffett_dcf_tab") is False

    def test_investor_sees_dcf(self):
        st.session_state["pulse360_profile"] = "Investor"
        assert feature_visible("buffett_dcf_tab") is True

    def test_investor_cannot_see_sbc_toggle(self):
        st.session_state["pulse360_profile"] = "Investor"
        assert feature_visible("buffett_sbc_toggle") is False

    def test_analyst_sees_everything(self):
        st.session_state["pulse360_profile"] = "Analyst"
        from components.user_profile import _FEATURE_LEVELS
        for key in _FEATURE_LEVELS:
            assert feature_visible(key) is True, f"Analyst can't see: {key}"

    def test_unknown_feature_defaults_visible(self):
        # Unknown features default to level 0 — visible to all
        st.session_state["pulse360_profile"] = "Beginner"
        assert feature_visible("nonexistent_feature_xyz") is True


class TestGetNavPages:
    def test_beginner_nav_has_all_sections(self):
        st.session_state["pulse360_profile"] = "Beginner"
        nav = get_nav_pages()
        assert "Macro Context" in nav
        assert "My Portfolio" in nav
        assert "Research"      in nav
        assert "Analysis"      in nav
        assert "Account"       in nav

    def test_beginner_nav_no_screener(self):
        st.session_state["pulse360_profile"] = "Beginner"
        nav = get_nav_pages()
        portfolio_titles = [p.title for p in nav["My Portfolio"]]
        assert "Stock Screener" not in portfolio_titles

    def test_investor_nav_has_screener(self):
        st.session_state["pulse360_profile"] = "Investor"
        nav = get_nav_pages()
        portfolio_titles = [p.title for p in nav["My Portfolio"]]
        assert "Stock Screener" in portfolio_titles

    def test_investor_nav_has_heatmap(self):
        st.session_state["pulse360_profile"] = "Investor"
        nav = get_nav_pages()
        portfolio_titles = [p.title for p in nav["My Portfolio"]]
        assert "Portfolio Heatmap" in portfolio_titles

    def test_analyst_nav_has_backtest(self):
        st.session_state["pulse360_profile"] = "Analyst"
        nav = get_nav_pages()
        analysis_titles = [p.title for p in nav["Analysis"]]
        assert "Model Track Record" in analysis_titles

    def test_beginner_nav_no_backtest(self):
        st.session_state["pulse360_profile"] = "Beginner"
        nav = get_nav_pages()
        analysis_titles = [p.title for p in nav["Analysis"]]
        assert "Model Track Record" not in analysis_titles

    def test_macro_pulse_visible_to_all(self):
        for profile in PROFILES:
            st.session_state["pulse360_profile"] = profile
            nav = get_nav_pages(profile)
            macro_titles = [p.title for p in nav["Macro Context"]]
            assert "Macro Pulse" in macro_titles, f"Macro Pulse missing for {profile}"
