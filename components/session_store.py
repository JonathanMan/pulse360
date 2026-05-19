"""
components/session_store.py
============================
Single source of truth for every ``st.session_state`` key used across Pie360.

Import the constant instead of using a bare string literal so typos become
AttributeErrors at import time rather than silent state misses at runtime.

Usage
-----
    from components.session_store import S
    st.session_state[S.PROFILE]         # read
    st.session_state[S.PROFILE] = "Analyst"  # write
    st.session_state.pop(S.PORTFOLIO_SCORED, None)
"""

from __future__ import annotations


class _Keys:
    # ── Profile & onboarding ──────────────────────────────────────────────────
    PROFILE              = "pulse360_profile"
    ONBOARDING_CHOICE    = "onboarding_choice"
    LS_CHECKED           = "_p360_ls_checked"   # set True once localStorage confirmed empty
    LS_READ              = "_p360_ls_read"       # st_javascript widget key (must be stable)
    SAVE_CTR             = "_p360_save_ctr"      # counter for unique st_javascript keys

    # ── Alert engine ─────────────────────────────────────────────────────────
    ALERTS_LAST_TS       = "_alerts_last_checked"  # unix timestamp of last alert check

    # ── Live data (populated by Dashboard page) ───────────────────────────────
    LIVE_VALUES          = "pulse360_live_values"
    RECESSION_PROB       = "pulse360_recession_prob"

    # ── Portfolio / heatmap (cleared on profile switch) ───────────────────────
    PORTFOLIO_SCORED     = "portfolio_scored"
    HEATMAP_PREFILL      = "heatmap_prefill"
    HEATMAP_EXTRACT_MSG  = "heatmap_extract_msg"

    # ── Auth ──────────────────────────────────────────────────────────────────
    POST_AUTH_REDIRECT   = "_post_auth_redirect"

    # ── Sidebar ───────────────────────────────────────────────────────────────
    SIDEBAR_PROFILE_SWITCH = "sidebar_profile_switch"

    # ── Macro Playbook (cache key prefix — append phase_conf_profile) ─────────
    PFX_PLAYBOOK         = "_pb_"
    PB_LAST_ERROR        = "_pb_last_error"

    # ── Simulator slider debounce ─────────────────────────────────────────────
    SIMULATOR_LAST_RUN   = "_sim_last_run"


#: Singleton — import this everywhere instead of using bare string literals.
S = _Keys()

__all__ = ["S"]
