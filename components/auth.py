"""
components/auth.py
===================
Email/password + Google OAuth + Phone OTP authentication via Supabase Auth.

OAuth flow (implicit):
  1. User clicks "Continue with Google"
  2. Browser redirects to Google via Supabase OAuth URL
  3. Google authenticates and Supabase redirects back with #access_token=... in URL fragment
  4. JavaScript extracts the token from the fragment and returns it to Python
  5. Python validates the token with Supabase and stores the user in session_state

Phone OTP flow:
  1. User enters phone number (country code + number)
  2. Supabase sends a 6-digit SMS OTP via configured SMS provider (Twilio etc.)
  3. User enters OTP code
  4. Supabase verifies and returns session
  5. Python stores user in session_state
"""

from __future__ import annotations

from urllib.parse import urlencode

import streamlit as st

from components.supabase_client import get_client
from components.pulse360_theme import (
    BLUE, BORDER, CARD_BG, FG_MUTED, FG_PRIMARY, FG_SEC, PAGE_BG, TEXT_PRI, TEXT_SEC,
)

_SESSION_KEY      = "sb_user"
_REDIRECT_URL     = "https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app"

# Session state keys for phone OTP 2-step flow
_OTP_PHONE_KEY    = "_p360_otp_phone"   # stores E.164 number while waiting for OTP
_OTP_SENT_KEY     = "_p360_otp_sent"    # bool — True after send_otp succeeds

# Supported country codes
_COUNTRY_CODES = [
    ("+852", "🇭🇰 +852 (HK)"),
    ("+1",   "🇺🇸 +1   (US)"),
    ("+44",  "🇬🇧 +44  (UK)"),
]


# ── Phone link table helpers ───────────────────────────────────────────────────
# user_phone_links table maps phone numbers to canonical email accounts,
# enabling cross-method login (Google/email user adds phone, and vice versa).
# SQL to create (run once in Supabase SQL editor):
#   create table user_phone_links (
#     id         uuid default gen_random_uuid() primary key,
#     user_email text not null,
#     phone      text not null unique,
#     linked_at  timestamptz default now()
#   );

_LINKS_TABLE = "user_phone_links"


def get_canonical_email_for_phone(phone: str) -> str | None:
    """Return the canonical email linked to this phone number, or None."""
    try:
        resp = (
            get_client()
            .table(_LINKS_TABLE)
            .select("user_email")
            .eq("phone", phone)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            return resp.data.get("user_email")
    except Exception:
        pass
    return None


def get_linked_phone_for_email(email: str) -> str | None:
    """Return the linked phone number for this email account, or None."""
    try:
        resp = (
            get_client()
            .table(_LINKS_TABLE)
            .select("phone")
            .eq("user_email", email)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            return resp.data.get("phone")
    except Exception:
        pass
    return None


def save_phone_link(email: str, phone: str) -> bool:
    """Link a phone number to an email account. Returns True on success."""
    try:
        get_client().table(_LINKS_TABLE).upsert(
            {"user_email": email, "phone": phone},
            on_conflict="phone",
        ).execute()
        return True
    except Exception:
        return False


# ── Public API ─────────────────────────────────────────────────────────────────

def get_session_user() -> dict | None:
    return st.session_state.get(_SESSION_KEY)


def get_session_email() -> str | None:
    """Return email for the logged-in user. Phone-only users return phone number."""
    u = get_session_user()
    if not u:
        return None
    # Email users and Google OAuth users always have email
    if u.get("email"):
        return u["email"]
    # Phone-only users: return phone as the stable identifier
    return u.get("phone")


def get_session_phone() -> str | None:
    """Return phone number for the logged-in user, if they used phone login."""
    u = get_session_user()
    return u.get("phone") if u else None


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
    for key in (_SESSION_KEY, _OTP_PHONE_KEY, _OTP_SENT_KEY):
        st.session_state.pop(key, None)
    st.rerun()


def render_logout_button() -> None:
    user = get_session_user()
    if not user:
        return
    # Display email or phone number (whichever they used to log in)
    display_id = user.get("email") or user.get("phone") or "signed in"
    col_id, col_btn = st.columns([3, 1])
    with col_id:
        st.markdown(
            f'<div style="font-size:0.72rem;color:{FG_MUTED};font-family:\'Geist Mono\','
            f'monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
            f'padding-top:6px;">{display_id}</div>',
            unsafe_allow_html=True,
        )
    with col_btn:
        if st.button("Sign out", key="logout_btn", use_container_width=True):
            logout()


# ── OAuth callback handler ─────────────────────────────────────────────────────

def _handle_oauth_callback() -> None:
    """
    Handle the OAuth implicit-flow callback.

    Google redirects back with #access_token=... in the PARENT window's URL.
    st_javascript runs inside a same-origin iframe, so we must read
    window.parent.location.hash (not window.location.hash, which is the
    iframe's own — always empty).  The localStorage bridge survives the
    one Streamlit rerun that fires before Python reads the component value.
    """
    if get_session_user():
        return
    try:
        from streamlit_javascript import st_javascript
        token_data = st_javascript(
            """(() => {
                try {
                    var stored = localStorage.getItem('p360_oauth_token');
                    if (stored) {
                        localStorage.removeItem('p360_oauth_token');
                        return JSON.parse(stored);
                    }
                } catch(e) {}
                var hash = window.parent.location.hash;
                if (hash && hash.indexOf('access_token') !== -1) {
                    var p = new URLSearchParams(hash.substring(1));
                    var token = { access_token: p.get('access_token') };
                    try { localStorage.setItem('p360_oauth_token', JSON.stringify(token)); } catch(e) {}
                    window.parent.history.replaceState(
                        {}, document.title,
                        window.parent.location.pathname + window.parent.location.search
                    );
                    return token;
                }
                return null;
            })()""",
            key="oauth_cb",
        )
        if token_data and isinstance(token_data, dict) and token_data.get("access_token"):
            resp = get_client().auth.get_user(token_data["access_token"])
            if resp and resp.user:
                st.session_state[_SESSION_KEY] = {
                    "email": resp.user.email,
                    "id":    str(resp.user.id),
                    "phone": getattr(resp.user, "phone", None) or None,
                }
                try:
                    from components.analytics import log_login
                    log_login("google")
                except Exception:
                    pass
                st.rerun()
    except Exception:
        pass


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
  .otp-hint {{
    font-size: 0.75rem; color: {FG_MUTED}; margin-top: 6px; text-align: center;
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

    # ── Google SSO ────────────────────────────────────────────────────────────
    st.link_button(
        "   Continue with Google",
        _google_oauth_url(),
        use_container_width=True,
        icon="🔵",
    )
    st.caption("New to Pulse360? Google sign-in creates your account automatically.")

    st.markdown('<div class="auth-divider">or sign in with</div>', unsafe_allow_html=True)

    # ── Email / Phone tabs ────────────────────────────────────────────────────
    tab_email, tab_phone = st.tabs(["📧  Email", "📱  Phone"])

    with tab_email:
        _render_email_tab()

    with tab_phone:
        _render_phone_tab()


# ── Email tab ──────────────────────────────────────────────────────────────────

def _render_email_tab() -> None:
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


# ── Phone OTP tab ──────────────────────────────────────────────────────────────

def _render_phone_tab() -> None:
    """
    Two-step phone OTP flow:
      Step 1 — enter phone number → send OTP
      Step 2 — enter 6-digit code → verify
    """
    otp_sent  = st.session_state.get(_OTP_SENT_KEY, False)
    otp_phone = st.session_state.get(_OTP_PHONE_KEY, "")

    if not otp_sent:
        # ── Step 1: phone number entry ────────────────────────────────────────
        st.markdown(
            f'<p style="font-size:0.8rem;color:{FG_SEC};margin-bottom:8px;">'
            "We'll text you a 6-digit verification code."
            "</p>",
            unsafe_allow_html=True,
        )
        with st.form("phone_send_form", clear_on_submit=False):
            col_cc, col_num = st.columns([2, 3])
            with col_cc:
                country_display = [label for _, label in _COUNTRY_CODES]
                cc_idx = st.selectbox(
                    "Country",
                    options=range(len(_COUNTRY_CODES)),
                    format_func=lambda i: country_display[i],
                    key="ph_cc",
                    label_visibility="collapsed",
                )
            with col_num:
                phone_local = st.text_input(
                    "Phone number",
                    placeholder="07700 900123",
                    key="ph_num",
                    label_visibility="collapsed",
                )
            submitted = st.form_submit_button(
                "Send verification code", type="primary", use_container_width=True
            )

        if submitted:
            cc = _COUNTRY_CODES[cc_idx][0]
            _do_send_otp(cc, phone_local.strip())

    else:
        # ── Step 2: OTP code entry ────────────────────────────────────────────
        # Format phone for display: +14155552671 → +1 (415) 555-2671 (rough)
        display_phone = otp_phone
        st.markdown(
            f'<p style="font-size:0.8rem;color:{FG_SEC};margin-bottom:8px;">'
            f"Code sent to <strong>{display_phone}</strong>. "
            "Check your messages — it arrives within 60 seconds."
            "</p>",
            unsafe_allow_html=True,
        )

        with st.form("phone_verify_form", clear_on_submit=False):
            otp_code = st.text_input(
                "Verification code",
                placeholder="123456",
                max_chars=6,
                key="ph_otp",
                help="Enter the 6-digit code from your SMS",
            )
            submitted = st.form_submit_button(
                "Verify & sign in", type="primary", use_container_width=True
            )

        if submitted:
            _do_verify_otp(otp_phone, otp_code.strip())

        # Allow user to go back and re-enter their number
        st.markdown("")
        col_back, _ = st.columns([1, 2])
        with col_back:
            if st.button("← Change number", key="ph_back", use_container_width=True):
                st.session_state.pop(_OTP_SENT_KEY, None)
                st.session_state.pop(_OTP_PHONE_KEY, None)
                st.rerun()

        if st.button("Resend code", key="ph_resend", use_container_width=True):
            _do_send_otp_raw(otp_phone, resend=True)


# ── Auth actions ───────────────────────────────────────────────────────────────

def _do_sign_in(email: str, password: str) -> None:
    if not email or not password:
        st.error("Please enter your email and password.")
        return
    try:
        resp = get_client().auth.sign_in_with_password({"email": email, "password": password})
        st.session_state[_SESSION_KEY] = {
            "email": resp.user.email,
            "id":    str(resp.user.id),
            "phone": getattr(resp.user, "phone", None) or None,
        }
        try:
            from components.analytics import log_login
            log_login("email")
        except Exception:
            pass
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
            st.session_state[_SESSION_KEY] = {
                "email": resp.user.email,
                "id":    str(resp.user.id),
                "phone": None,
            }
            st.rerun()
        else:
            st.info("Account created — check your email to confirm before signing in.")
    except Exception as exc:
        msg = str(exc)
        if "already registered" in msg or "already been registered" in msg:
            st.error("An account with this email already exists. Try signing in instead.")
        else:
            st.error(f"Sign up failed: {msg}")


def _build_e164(country_code: str, local_number: str) -> str:
    """
    Combine country code + local number into E.164 format.
    Strips spaces, dashes, brackets, leading zeros.
    e.g. +44, 07700 900123 → +447700900123
    """
    import re
    # Strip all non-digit chars from local number
    digits = re.sub(r"\D", "", local_number)
    # Remove leading zero (common in UK/AU local format)
    digits = digits.lstrip("0")
    cc = country_code.strip()
    return f"{cc}{digits}"


def _do_send_otp(country_code: str, local_number: str) -> None:
    """Validate phone, build E.164, and call Supabase sign_in_with_otp."""
    if not local_number:
        st.error("Please enter your phone number.")
        return
    e164 = _build_e164(country_code, local_number)
    if len(e164) < 8:
        st.error("Phone number looks too short — please check and try again.")
        return
    _do_send_otp_raw(e164)


def _do_send_otp_raw(e164_phone: str, resend: bool = False) -> None:
    """Call Supabase to send (or resend) the SMS OTP."""
    try:
        get_client().auth.sign_in_with_otp({"phone": e164_phone})
        st.session_state[_OTP_PHONE_KEY] = e164_phone
        st.session_state[_OTP_SENT_KEY]  = True
        if resend:
            st.success("Code resent! Check your messages.")
        st.rerun()
    except Exception as exc:
        msg = str(exc)
        if "sms_send_failed" in msg or "SMS" in msg:
            st.error(
                "SMS could not be sent. Check the phone number is correct and your "
                "Supabase project has an SMS provider configured (Twilio etc.)."
            )
        elif "rate" in msg.lower():
            st.error("Too many attempts — please wait a moment before requesting another code.")
        else:
            st.error(f"Could not send code: {msg}")


def _do_verify_otp(e164_phone: str, otp_code: str) -> None:
    """
    Verify the SMS OTP code with Supabase.
    After verification, check user_phone_links to resolve a canonical email
    account — so phone users get merged with their Google/email identity.
    """
    if not otp_code or len(otp_code) != 6 or not otp_code.isdigit():
        st.error("Please enter the 6-digit code from your SMS.")
        return
    try:
        resp = get_client().auth.verify_otp(
            {"phone": e164_phone, "token": otp_code, "type": "sms"}
        )
        if resp and resp.user:
            user = resp.user
            # Check if this phone is linked to a canonical email account
            canonical_email = get_canonical_email_for_phone(e164_phone)
            st.session_state[_SESSION_KEY] = {
                "email": canonical_email or user.email or None,
                "id":    str(user.id),
                "phone": e164_phone,
            }
            # Clear OTP flow state
            st.session_state.pop(_OTP_PHONE_KEY, None)
            st.session_state.pop(_OTP_SENT_KEY, None)
            try:
                from components.analytics import log_login
                log_login("phone")
            except Exception:
                pass
            st.rerun()
        else:
            st.error("Verification failed — please try again.")
    except Exception as exc:
        msg = str(exc)
        if "invalid" in msg.lower() or "expired" in msg.lower() or "Token" in msg:
            st.error("Incorrect or expired code. Request a new one if needed.")
        elif "rate" in msg.lower():
            st.error("Too many attempts — please wait before trying again.")
        else:
            st.error(f"Verification failed: {msg}")
