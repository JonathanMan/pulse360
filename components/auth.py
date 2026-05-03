"""
components/auth.py
===================
Email/password + Google OAuth authentication via Supabase Auth.

OAuth flow (implicit):
  1. User clicks "Continue with Google"
  2. Browser redirects to Google via Supabase OAuth URL
  3. Google authenticates and Supabase redirects back with #access_token=... in URL fragment
  4. JavaScript extracts the token from the fragment and returns it to Python
  5. Python validates the token with Supabase and stores the user in session_state
"""

from __future__ import annotations

from urllib.parse import urlencode

import streamlit as st
import streamlit.components.v1 as _components

from components.supabase_client import get_client
from components.pulse360_theme import (
    BLUE, BORDER, CARD_BG, FG_MUTED, FG_PRIMARY, FG_SEC, PAGE_BG, TEXT_PRI, TEXT_SEC,
)

_SESSION_KEY  = "sb_user"
_REDIRECT_URL = "https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app"


# ── Public API ─────────────────────────────────────────────────────────────────

def get_session_user() -> dict | None:
    return st.session_state.get(_SESSION_KEY)


def get_session_email() -> str | None:
    u = get_session_user()
    return u["email"] if u else None


def require_auth() -> dict:
    """
    Call once at the top of app.py. Handles OAuth callbacks, shows login
    form if not authenticated, and returns the user dict when authenticated.
    """
    _handle_oauth_callback()
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


# ── OAuth callback handler ─────────────────────────────────────────────────────

def _handle_oauth_callback() -> None:
    """
    Handle the OAuth implicit-flow callback.

    Google redirects back with #access_token=... in the URL fragment.
    Fragments are invisible to Python, so a zero-height JS component
    extracts the token and immediately redirects the parent page to
    ?p360_tk=<token> — a normal query param that Python can read.
    On the next render Python validates the token and sets the session.
    """
    if get_session_user():
        return

    # ── Step 1: read token from query param (set by our JS redirect) ──────────
    token = st.query_params.get("p360_tk")
    if token:
        try:
            resp = get_client().auth.get_user(token)
            if resp and resp.user:
                st.session_state[_SESSION_KEY] = {
                    "email": resp.user.email,
                    "id":    str(resp.user.id),
                }
        except Exception:
            pass
        st.query_params.clear()
        st.rerun()

    # ── Step 2: inject JS to detect fragment and redirect with token as QP ────
    _components.html(
        """<script>
        (function () {
            var hash = window.parent.location.hash;
            if (hash && hash.indexOf('access_token') !== -1) {
                var p = new URLSearchParams(hash.substring(1));
                var tk = p.get('access_token');
                if (tk) {
                    window.parent.location.replace(
                        window.parent.location.pathname +
                        '?p360_tk=' + encodeURIComponent(tk)
                    );
                }
            }
        })();
        </script>""",
        height=0,
    )


# ── Login page ─────────────────────────────────────────────────────────────────

def _google_oauth_url() -> str:
    params = urlencode({"provider": "google", "redirect_to": _REDIRECT_URL})
    return f"{st.secrets['SUPABASE_URL']}/auth/v1/authorize?{params}"


def _render_login_page() -> None:
    st.markdown(f"""
<style>
  .stApp {{ background: {PAGE_BG}; }}
  .auth-wrap {{
    max-width: 400px;
    margin: 48px auto 0 auto;
  }}
  .auth-header {{
    text-align: center;
    margin-bottom: 28px;
  }}
  .auth-icon  {{ font-size: 2.2rem; }}
  .auth-name  {{
    font-size: 1.45rem; font-weight: 800;
    color: {TEXT_PRI}; letter-spacing: -0.03em; margin-top: 4px;
  }}
  .auth-sub   {{ font-size: 0.78rem; color: {TEXT_SEC}; margin-top: 2px; }}
  .auth-card  {{
    background: {CARD_BG}; border: 1px solid {BORDER};
    border-radius: 12px; padding: 28px 28px 22px 28px;
  }}
  .auth-divider {{
    display: flex; align-items: center; gap: 10px;
    margin: 14px 0; color: {FG_MUTED}; font-size: 0.75rem;
  }}
  .auth-divider::before, .auth-divider::after {{
    content: ""; flex: 1; height: 1px; background: {BORDER};
  }}
</style>
<div class="auth-wrap">
  <div class="auth-header">
    <div class="auth-icon">📊</div>
    <div class="auth-name">Pulse360</div>
    <div class="auth-sub">AI-Powered Economic Cycle Dashboard</div>
  </div>
  <div class="auth-card">
</div>
""", unsafe_allow_html=True)

    # Google button — handles both new and returning users automatically
    st.link_button(
        "   Continue with Google",
        _google_oauth_url(),
        use_container_width=True,
        icon="🔵",
    )
    st.caption("New to Pulse360? Google sign-in creates your account automatically.")

    st.markdown('<div class="auth-divider">or sign in with email</div>', unsafe_allow_html=True)

    tab_in, tab_up = st.tabs(["Sign in", "Create account"])

    with tab_in:
        with st.form("login_form", clear_on_submit=False):
            email    = st.text_input("Email", placeholder="you@example.com", key="li_email")
            password = st.text_input("Password", type="password", key="li_pw")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            _do_sign_in(email.strip(), password)

    with tab_up:
        st.caption("Create your account — free.")
        with st.form("signup_form", clear_on_submit=False):
            email    = st.text_input("Email", placeholder="you@example.com", key="su_email")
            password = st.text_input("Password", type="password", key="su_pw",
                                     help="Minimum 8 characters")
            submitted = st.form_submit_button("Create account", type="primary", use_container_width=True)
        if submitted:
            _do_sign_up(email.strip(), password)


# ── Auth actions ───────────────────────────────────────────────────────────────

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
