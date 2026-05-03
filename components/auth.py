"""
components/auth.py
===================
Email/password authentication via Supabase Auth.

Usage in app.py:
    from components.auth import require_auth, render_logout_button
    require_auth()   # call before any page content — stops if not logged in
"""

from __future__ import annotations

import streamlit as st

from components.supabase_client import get_client
from components.pulse360_theme import (
    BLUE, BORDER, CARD_BG, FG_MUTED, FG_PRIMARY, FG_SEC, PAGE_BG, TEXT_PRI, TEXT_SEC,
)

_SESSION_KEY = "sb_user"


def get_session_user() -> dict | None:
    return st.session_state.get(_SESSION_KEY)


def get_session_email() -> str | None:
    u = get_session_user()
    return u["email"] if u else None


def require_auth() -> dict:
    """
    Call once at the top of app.py (before any page rendering).
    Returns the user dict if authenticated; shows login form and stops if not.
    """
    user = get_session_user()
    if user:
        return user
    _render_login_page()
    st.stop()


def logout() -> None:
    try:
        get_client().auth.sign_out()
    except Exception:
        pass
    st.session_state.pop(_SESSION_KEY, None)
    st.rerun()


def render_logout_button() -> None:
    """Render a compact logout row for the sidebar."""
    user = get_session_user()
    if not user:
        return
    col_email, col_btn = st.columns([3, 1])
    with col_email:
        st.markdown(
            f'<div style="font-size:0.72rem;color:{FG_MUTED};font-family:\'Geist Mono\','
            f'monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
            f'padding-top:6px;">{user["email"]}</div>',
            unsafe_allow_html=True,
        )
    with col_btn:
        if st.button("Sign out", key="logout_btn", use_container_width=True):
            logout()


# ── Private helpers ────────────────────────────────────────────────────────────

def _render_login_page() -> None:
    st.set_page_config(
        page_title="Pulse360 — Sign in",
        page_icon="📊",
        layout="centered",
    )
    st.markdown(f"""
<style>
  .stApp {{ background: {PAGE_BG}; }}
  .auth-card {{
    max-width: 420px;
    margin: 60px auto 0 auto;
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 36px 36px 28px 36px;
  }}
  .auth-logo {{
    text-align: center;
    margin-bottom: 24px;
  }}
  .auth-logo-icon {{ font-size: 2.4rem; }}
  .auth-logo-name {{
    font-size: 1.5rem;
    font-weight: 800;
    color: {TEXT_PRI};
    letter-spacing: -0.03em;
    margin-top: 4px;
  }}
  .auth-logo-sub {{
    font-size: 0.78rem;
    color: {TEXT_SEC};
    margin-top: 2px;
  }}
  div[data-testid="stTabs"] button {{
    font-size: 0.88rem !important;
    font-weight: 600 !important;
  }}
</style>
""", unsafe_allow_html=True)

    st.markdown("""
<div class="auth-card">
  <div class="auth-logo">
    <div class="auth-logo-icon">📊</div>
    <div class="auth-logo-name">Pulse360</div>
    <div class="auth-logo-sub">AI-Powered Economic Cycle Dashboard</div>
  </div>
</div>
""", unsafe_allow_html=True)

    tab_in, tab_up = st.tabs(["Sign in", "Create account"])

    with tab_in:
        with st.form("login_form", clear_on_submit=False):
            email    = st.text_input("Email", placeholder="you@example.com", key="li_email")
            password = st.text_input("Password", type="password", key="li_pw")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            _do_sign_in(email.strip(), password)

    with tab_up:
        st.caption("Create your account — no credit card required.")
        with st.form("signup_form", clear_on_submit=False):
            email    = st.text_input("Email", placeholder="you@example.com", key="su_email")
            password = st.text_input(
                "Password", type="password", key="su_pw",
                help="Minimum 8 characters",
            )
            submitted = st.form_submit_button("Create account", type="primary", use_container_width=True)
        if submitted:
            _do_sign_up(email.strip(), password)


def _do_sign_in(email: str, password: str) -> None:
    if not email or not password:
        st.error("Please enter your email and password.")
        return
    try:
        resp = get_client().auth.sign_in_with_password({"email": email, "password": password})
        st.session_state[_SESSION_KEY] = {"email": resp.user.email, "id": str(resp.user.id)}
        st.rerun()
    except Exception as exc:
        msg = str(exc)
        if "Invalid login" in msg or "invalid_credentials" in msg:
            st.error("Incorrect email or password.")
        else:
            st.error(f"Sign in failed: {msg}")


def _do_sign_up(email: str, password: str) -> None:
    if not email or not password:
        st.error("Please enter an email and password.")
        return
    if len(password) < 8:
        st.error("Password must be at least 8 characters.")
        return
    try:
        resp = get_client().auth.sign_up({"email": email, "password": password})
        if resp.user:
            st.session_state[_SESSION_KEY] = {"email": resp.user.email, "id": str(resp.user.id)}
            st.rerun()
        else:
            st.info("Account created — check your email to confirm before signing in.")
    except Exception as exc:
        msg = str(exc)
        if "already registered" in msg or "already been registered" in msg:
            st.error("An account with this email already exists. Try signing in instead.")
        else:
            st.error(f"Sign up failed: {msg}")
