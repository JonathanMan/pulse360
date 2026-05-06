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

import time
from urllib.parse import urlencode

import streamlit as st

from components.supabase_client import get_client
from components.pulse360_theme import (
    BLUE, BORDER, CARD_BG, FG_MUTED, FG_PRIMARY, FG_SEC, PAGE_BG, TEXT_PRI, TEXT_SEC,
)

_SESSION_KEY      = "sb_user"
_REDIRECT_URL     = "https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app"

# ── Feature flag: Google OAuth ─────────────────────────────────────────────────
# Set to False to hide all Google sign-in buttons across the app.
# The underlying OAuth callback handler (_handle_oauth_callback) still runs so
# that any in-flight sessions complete normally, but no new Google flows are
# initiated from the UI.
_GOOGLE_ENABLED = False

# Session state keys for phone OTP 2-step flow
_OTP_PHONE_KEY    = "_p360_otp_phone"   # stores E.164 number while waiting for OTP
_OTP_SENT_KEY     = "_p360_otp_sent"    # bool — True after send_otp succeeds
_OTP_RESEND_AT    = "_p360_otp_resend_at"  # float — time.time() of last send/resend

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

    After an OAuth link flow, redirects to the page stored in
    _post_auth_redirect (e.g. Settings) instead of staying on root.
    """
    _handle_oauth_callback()
    user = get_session_user()
    if user:
        redirect = st.session_state.pop("_post_auth_redirect", None)
        if redirect:
            st.switch_page(redirect)
        return user
    _render_login_page()
    st.stop()


def logout() -> None:
    try:
        get_client().auth.sign_out()
    except Exception:
        pass
    for key in (_SESSION_KEY, _OTP_PHONE_KEY, _OTP_SENT_KEY, _OTP_RESEND_AT):
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

    Popup mode (preferred):
      The Google button opens a small popup. When the popup receives the OAuth
      redirect it stores the token in localStorage and calls window.parent.close()
      to close itself. The parent page detects the popup closing (via its poll
      timer) and calls window.location.reload(), which then picks up the token
      from localStorage on the next load — keeping the user on the original page.

    If p360_link_mode is set in localStorage (placed there by the Settings
    "Link Google account" button before redirecting), we treat the returning
    token as a link operation rather than a new login — the Google email is
    saved to user_phone_links and the existing session is preserved.

    NOTE: the guard below skips this entirely for authenticated users. This is
    intentional — it prevents st_javascript from returning a stale cached token
    on subsequent reruns and creating an infinite loop. The link-mode flow is
    safe because Google's redirect always creates a fresh WebSocket session,
    so get_session_user() is None when we return from OAuth even for logged-in users.
    """
    if get_session_user():
        return
    try:
        from streamlit_javascript import st_javascript
        token_data = st_javascript(
            """(() => {
                // No popup mode — same-tab redirect flow only.

                // ── Check bridge cache (survives one extra rerun) ─────────────────
                try {
                    var stored = localStorage.getItem('p360_oauth_token');
                    if (stored) {
                        localStorage.removeItem('p360_oauth_token');
                        var parsed = JSON.parse(stored);
                        var lm = localStorage.getItem('p360_link_mode');
                        var lu = localStorage.getItem('p360_link_user');
                        if (lm) { localStorage.removeItem('p360_link_mode'); parsed.link_mode = true; }
                        if (lu) { localStorage.removeItem('p360_link_user'); parsed.link_user = lu; }
                        // Pick up the return-to page stored by the sign-in button
                        var rt = localStorage.getItem('p360_return_to');
                        if (rt) { localStorage.removeItem('p360_return_to'); parsed.return_to = rt; }
                        return parsed;
                    }
                } catch(e) {}
                // ── Read token from URL hash (same-tab redirect just landed) ─────
                var hash = window.parent.location.hash;
                if (hash && hash.indexOf('access_token') !== -1) {
                    var p    = new URLSearchParams(hash.substring(1));
                    var lm   = localStorage.getItem('p360_link_mode');
                    var lu   = localStorage.getItem('p360_link_user');
                    var rt   = localStorage.getItem('p360_return_to');
                    if (lm) localStorage.removeItem('p360_link_mode');
                    if (lu) localStorage.removeItem('p360_link_user');
                    if (rt) localStorage.removeItem('p360_return_to');
                    var token = {
                        access_token: p.get('access_token'),
                        link_mode:    lm === '1',
                        link_user:    lu || null,
                        return_to:    rt  || null
                    };
                    try { localStorage.setItem('p360_oauth_token', JSON.stringify(token)); } catch(e) {}
                    // Write for cross-tab detection: original tab's storage listener picks this up
                    try { localStorage.setItem('p360_auth_shared', JSON.stringify({
                        at: p.get('access_token'),
                        rt: p.get('refresh_token') || ''
                    })); } catch(e) {}
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
                google_email = resp.user.email
                link_mode    = bool(token_data.get("link_mode"))
                link_user    = token_data.get("link_user")  # phone/email of existing account

                if link_mode and link_user:
                    # ── Link mode: link_user is the existing account's phone ──
                    # link_user survived the redirect via localStorage (not session state)
                    save_phone_link(google_email, link_user)
                    # Create a merged session: email from Google + phone from link_user
                    st.session_state[_SESSION_KEY] = {
                        "email": google_email,
                        "id":    str(resp.user.id),
                        "phone": link_user,
                    }
                    st.session_state["_google_link_success"] = google_email
                    # Redirect back to Settings after rerun
                    st.session_state["_post_auth_redirect"] = "pages/10_Settings.py"
                    st.rerun()
                else:
                    # ── Normal login ──────────────────────────────────────────
                    st.session_state[_SESSION_KEY] = {
                        "email": google_email,
                        "id":    str(resp.user.id),
                        "phone": getattr(resp.user, "phone", None) or None,
                    }
                    try:
                        from components.analytics import log_login
                        log_login("google")
                    except Exception:
                        pass
                    # Return to the page the user was on before signing in
                    return_to = token_data.get("return_to")
                    if return_to:
                        st.session_state["_post_auth_redirect"] = return_to
                    st.rerun()
    except Exception:
        pass


# ── Login page ─────────────────────────────────────────────────────────────────

def _google_oauth_url() -> str:
    params = urlencode({"provider": "google", "redirect_to": _REDIRECT_URL})
    return f"{st.secrets['SUPABASE_URL']}/auth/v1/authorize?{params}"


def get_google_oauth_url() -> str:
    """Public accessor for the Google OAuth URL (used by Settings link button)."""
    return _google_oauth_url()


def _render_google_signin_button(oauth_url: str, btn_key: str = "default", return_page: str | None = None) -> None:
    """
    Render a Google sign-in button.

    Streamlit has NO mechanism to navigate the current tab to an external URL —
    every approach is blocked by the platform:
      • st.link_button:           hardcoded target="_blank"
      • st.markdown <a>:          React router intercepts external clicks → new tab
      • st.components.v1.html():  iframe sandbox blocks window.top navigation
      • st_javascript:            programmatic JS loses user-activation context

    We use st.link_button (opens new tab) and handle the cross-tab auth
    completion via a "Complete sign-in" button in render_login_gate().
    """
    st.link_button(
        "Continue with Google",
        oauth_url,
        use_container_width=True,
        icon="🔵",
    )


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

    # ── Google SSO (hidden while OAuth new-tab flow is under review) ─────────
    if _GOOGLE_ENABLED:
        _render_google_signin_button(_google_oauth_url(), btn_key="login_page")
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

        # Resend code — 60-second cooldown to prevent spam
        _RESEND_COOLDOWN = 60
        _last_resend = st.session_state.get(_OTP_RESEND_AT, 0)
        _elapsed = int(time.time() - _last_resend)
        _remaining = _RESEND_COOLDOWN - _elapsed
        if _remaining > 0:
            st.button(
                f"Resend code ({_remaining}s)",
                key="ph_resend",
                use_container_width=True,
                disabled=True,
            )
        else:
            if st.button("Resend code", key="ph_resend", use_container_width=True):
                st.session_state[_OTP_RESEND_AT] = time.time()
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
        st.session_state[_OTP_PHONE_KEY]  = e164_phone
        st.session_state[_OTP_SENT_KEY]   = True
        st.session_state[_OTP_RESEND_AT]  = time.time()  # start cooldown
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


# ── Guest mode helpers ─────────────────────────────────────────────────────────

def is_guest() -> bool:
    """Return True if the user is NOT logged in."""
    return get_session_user() is None


def render_login_gate(
    title: str = "Sign in to continue",
    body: str = "Create a free account — it only takes a moment.",
    feature_bullets: list | None = None,
    return_page: str | None = None,
) -> bool:
    """
    Render a polished inline sign-in card for pages that require authentication.
    Phone OTP is the primary method; Google SSO and email are secondary options.

    Returns True  — user is logged in, caller should proceed normally.
    Returns False — user is a guest; gate card rendered, caller should st.stop().
    """
    if not is_guest():
        return True

    from components.pulse360_theme import (
        BLUE, BORDER, CARD_BG, PAGE_BG, TEXT_PRI, TEXT_SEC, TEXT_MUT,
    )

    # Unique keys per gate so multiple gates can coexist on a page
    _k   = str(abs(hash(title)) % 99999)
    _otp_sent  = st.session_state.get(f"_gate_otp_sent_{_k}", False)
    _otp_phone = st.session_state.get(f"_gate_otp_phone_{_k}", "")
    _show_email = st.session_state.get(f"_gate_show_email_{_k}", False)

    # ── Shared CSS ─────────────────────────────────────────────────────────────
    st.markdown(f"""
<style>
/* Gate card wrapper */
.p360-gate-wrap {{
    max-width: 480px;
    margin: 2rem auto;
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 40px 40px 32px 40px;
}}
/* Header */
.p360-gate-eyebrow {{
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: {TEXT_MUT};
    margin-bottom: 10px;
}}
.p360-gate-heading {{
    font-size: 1.55rem;
    font-weight: 800;
    color: {TEXT_PRI};
    letter-spacing: -0.025em;
    line-height: 1.2;
    margin-bottom: 8px;
}}
.p360-gate-sub {{
    font-size: 0.86rem;
    color: {TEXT_SEC};
    line-height: 1.5;
    margin-bottom: 6px;
}}
/* Feature bullets */
.p360-gate-bullet {{
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 5px;
}}
.p360-gate-bullet-check {{
    color: #27ae60;
    font-size: 0.8rem;
    margin-top: 2px;
    flex-shrink: 0;
}}
.p360-gate-bullet-text {{
    font-size: 0.82rem;
    color: {TEXT_SEC};
    line-height: 1.4;
}}
/* Divider */
.p360-gate-divider {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 18px 0;
    color: {TEXT_MUT};
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}}
.p360-gate-divider::before, .p360-gate-divider::after {{
    content: "";
    flex: 1;
    height: 1px;
    background: {BORDER};
}}
/* Terms footer */
.p360-gate-terms {{
    font-size: 0.69rem;
    color: {TEXT_MUT};
    text-align: center;
    margin-top: 20px;
    line-height: 1.5;
}}
.p360-gate-terms a {{
    color: {TEXT_SEC};
    text-decoration: underline;
}}
/* Phone label */
.p360-phone-label {{
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: {TEXT_MUT};
    margin-bottom: 6px;
    margin-top: 16px;
}}
</style>
""", unsafe_allow_html=True)

    # ── Card header ────────────────────────────────────────────────────────────
    _l, mid, _r = st.columns([1, 8, 1])
    with mid:
        # Build bullets HTML
        bullets_html = ""
        if feature_bullets:
            bullets_html = "".join(
                f'<div class="p360-gate-bullet">'
                f'<span class="p360-gate-bullet-check">✓</span>'
                f'<span class="p360-gate-bullet-text">{b}</span>'
                f'</div>'
                for b in feature_bullets
            )

        st.markdown(f"""
<div class="p360-gate-wrap">
  <div class="p360-gate-eyebrow">Sign in</div>
  <div class="p360-gate-heading">{title}</div>
  <div class="p360-gate-sub">{body}</div>
  {f'<div style="margin: 14px 0 0 0;">{bullets_html}</div>' if bullets_html else ''}
</div>
""", unsafe_allow_html=True)

    # ── Form column ────────────────────────────────────────────────────────────
    _l2, form_col, _r2 = st.columns([1, 8, 1])
    with form_col:

        # ── Phone OTP (primary method) ─────────────────────────────────────────
        st.markdown('<div class="p360-phone-label">Phone number</div>', unsafe_allow_html=True)

        if not _otp_sent:
            # Step 1 — enter number
            with st.form(f"gate_phone_send_{_k}", clear_on_submit=False):
                _cc_col, _num_col = st.columns([2, 3])
                with _cc_col:
                    _cc_idx = st.selectbox(
                        "Country",
                        options=range(len(_COUNTRY_CODES)),
                        format_func=lambda i: _COUNTRY_CODES[i][1],
                        key=f"gate_cc_{_k}",
                        label_visibility="collapsed",
                    )
                with _num_col:
                    _local = st.text_input(
                        "Phone",
                        placeholder="(555) 000-0000",
                        key=f"gate_ph_{_k}",
                        label_visibility="collapsed",
                    )
                if st.form_submit_button("Send code", type="primary", use_container_width=True):
                    _cc = _COUNTRY_CODES[_cc_idx][0]
                    _e164 = _build_e164(_cc, _local.strip())
                    if len(_e164) >= 8:
                        try:
                            get_client().auth.sign_in_with_otp({"phone": _e164})
                            st.session_state[f"_gate_otp_phone_{_k}"]      = _e164
                            st.session_state[f"_gate_otp_sent_{_k}"]       = True
                            st.session_state[f"_gate_otp_resend_at_{_k}"]  = time.time()
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not send code: {exc}")
                    else:
                        st.error("Phone number looks too short.")
        else:
            # Step 2 — enter OTP
            st.markdown(
                f'<p style="font-size:0.82rem;color:{TEXT_SEC};margin-bottom:8px;">'
                f'Code sent to <strong>{_otp_phone}</strong>. Check your messages.</p>',
                unsafe_allow_html=True,
            )
            with st.form(f"gate_phone_verify_{_k}", clear_on_submit=False):
                _otp_code = st.text_input(
                    "Code", placeholder="123456", max_chars=6,
                    key=f"gate_otp_{_k}", label_visibility="collapsed",
                )
                if st.form_submit_button("Verify & sign in", type="primary", use_container_width=True):
                    _do_verify_otp(_otp_phone, _otp_code.strip())

            _bc, _rc, _ = st.columns([1, 1, 1])
            with _bc:
                if st.button("← Change number", key=f"gate_back_{_k}", use_container_width=True):
                    st.session_state.pop(f"_gate_otp_sent_{_k}", None)
                    st.session_state.pop(f"_gate_otp_resend_at_{_k}", None)
                    st.rerun()
            with _rc:
                _gate_last_resend = st.session_state.get(f"_gate_otp_resend_at_{_k}", 0)
                _gate_elapsed = int(time.time() - _gate_last_resend)
                _gate_remaining = 60 - _gate_elapsed
                if _gate_remaining > 0:
                    st.button(
                        f"Resend ({_gate_remaining}s)",
                        key=f"gate_resend_{_k}",
                        use_container_width=True,
                        disabled=True,
                    )
                else:
                    if st.button("Resend code", key=f"gate_resend_{_k}", use_container_width=True):
                        st.session_state[f"_gate_otp_resend_at_{_k}"] = time.time()
                        try:
                            get_client().auth.sign_in_with_otp({"phone": _otp_phone})
                            st.success("Code resent.")
                        except Exception as exc:
                            st.error(f"Could not resend: {exc}")
                    st.session_state.pop(f"_gate_otp_phone_{_k}", None)
                    st.rerun()

        # ── Google SSO (hidden while new-tab OAuth flow is under review) ────────
        if _GOOGLE_ENABLED:
            st.markdown('<div class="p360-gate-divider">or continue with</div>', unsafe_allow_html=True)
            _render_google_signin_button(_google_oauth_url(), btn_key=f"gate_{_k}")
            st.caption("After signing in with Google, come back here and click below.")
            _cg_key = f"_p360_cg_{_k}"
            if st.session_state.get(_cg_key):
                st.session_state.pop(_cg_key, None)
                try:
                    from streamlit_javascript import st_javascript as _stjs
                    import json as _json
                    _shared = _stjs(
                        "localStorage.getItem('p360_auth_shared') || ''",
                        key=f"_p360_cg_ls_{_k}",
                    )
                    if _shared and _shared != 0 and _shared != "":
                        try:
                            _stjs("localStorage.removeItem('p360_auth_shared'); 1;",
                                  key=f"_p360_cg_clr_{_k}")
                        except Exception:
                            pass
                        _td = _json.loads(_shared) if isinstance(_shared, str) else _shared
                        _at = (_td.get("at") or _td.get("access_token") or "") if isinstance(_td, dict) else ""
                        if _at:
                            _resp = get_client().auth.get_user(_at)
                            if _resp and _resp.user:
                                st.session_state[_SESSION_KEY] = {
                                    "email": _resp.user.email,
                                    "id":    str(_resp.user.id),
                                    "phone": getattr(_resp.user, "phone", None) or None,
                                }
                                try:
                                    from components.analytics import log_login
                                    log_login("google")
                                except Exception:
                                    pass
                                if return_page:
                                    st.session_state["_post_auth_redirect"] = return_page
                                st.rerun()
                            else:
                                st.error("Sign-in token invalid. Please try again.")
                        else:
                            st.warning("No Google sign-in found. Please complete the Google sign-in first.")
                    elif _shared == 0:
                        st.session_state[_cg_key] = True
                        st.rerun()
                    else:
                        st.warning("No Google sign-in found. Please complete the Google sign-in first.")
                except Exception:
                    st.warning("Could not check sign-in. Please try again.")
            else:
                if st.button(
                    "✓  I've signed in with Google",
                    key=f"_p360_cg_btn_{_k}",
                    use_container_width=True,
                ):
                    st.session_state[_cg_key] = True
                    st.rerun()

        # Email (collapsed by default — tertiary option)
        if not _show_email:
            if st.button(
                "Sign in with email / password",
                key=f"gate_toggle_email_{_k}",
                use_container_width=True,
            ):
                st.session_state[f"_gate_show_email_{_k}"] = True
                st.rerun()
        else:
            with st.form(f"gate_email_{_k}", clear_on_submit=False):
                _email = st.text_input(
                    "Email", placeholder="you@example.com",
                    label_visibility="collapsed", key=f"gate_em_{_k}",
                )
                _pw = st.text_input(
                    "Password", type="password", placeholder="Password",
                    label_visibility="collapsed", key=f"gate_pw_{_k}",
                )
                if st.form_submit_button("Sign in", type="primary", use_container_width=True):
                    _do_sign_in(_email.strip(), _pw)

        # Terms footer
        st.markdown(
            f'<div class="p360-gate-terms">'
            f'By continuing you agree to Pulse360\'s '
            f'<a href="https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app">Terms of Service</a>'
            f' and <a href="https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app">Privacy Policy</a>.'
            f'</div>',
            unsafe_allow_html=True,
        )

    return False
