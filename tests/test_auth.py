"""
tests/test_auth.py
===================
Unit tests for auth helpers that contain pure logic (no Supabase I/O).
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.auth import (
    _build_e164,
    get_session_user,
    get_session_email,
    get_session_phone,
    is_guest,
)
import streamlit as st


# ── _build_e164 ───────────────────────────────────────────────────────────────

class TestBuildE164:
    def test_uk_standard(self):
        assert _build_e164("+44", "07700 900123") == "+447700900123"

    def test_us_standard(self):
        assert _build_e164("+1", "4155552671") == "+14155552671"

    def test_hk_standard(self):
        assert _build_e164("+852", "69038453") == "+85269038453"

    def test_strips_dashes_and_spaces(self):
        assert _build_e164("+44", "077-00 900 123") == "+447700900123"

    def test_strips_brackets(self):
        assert _build_e164("+1", "(415) 555-2671") == "+14155552671"

    def test_strips_leading_zero(self):
        # UK local numbers start with 0; E.164 must not have it
        result = _build_e164("+44", "07700900123")
        assert not result.startswith("+440"), f"Leading zero not stripped: {result}"
        assert result == "+447700900123"

    def test_no_leading_zero_us(self):
        # US numbers don't start with 0, should be unchanged
        assert _build_e164("+1", "5551234567") == "+15551234567"


# ── Session helpers ────────────────────────────────────────────────────────────

class TestSessionHelpers:
    def test_get_session_user_none_when_empty(self):
        assert get_session_user() is None

    def test_get_session_user_returns_dict(self):
        st.session_state["sb_user"] = {"email": "a@b.com", "id": "123"}
        assert get_session_user() == {"email": "a@b.com", "id": "123"}

    def test_get_session_email_none_when_no_user(self):
        assert get_session_email() is None

    def test_get_session_email_returns_email(self):
        st.session_state["sb_user"] = {"email": "test@example.com", "id": "1"}
        assert get_session_email() == "test@example.com"

    def test_get_session_email_falls_back_to_phone(self):
        st.session_state["sb_user"] = {"email": None, "phone": "+85269038453", "id": "1"}
        assert get_session_email() == "+85269038453"

    def test_get_session_phone_none_when_no_user(self):
        assert get_session_phone() is None

    def test_get_session_phone_returns_phone(self):
        st.session_state["sb_user"] = {"email": None, "phone": "+85269038453", "id": "1"}
        assert get_session_phone() == "+85269038453"


# ── is_guest ──────────────────────────────────────────────────────────────────

class TestIsGuest:
    def test_guest_when_no_session(self):
        assert is_guest() is True

    def test_not_guest_when_logged_in(self):
        st.session_state["sb_user"] = {"email": "a@b.com", "id": "xyz"}
        assert is_guest() is False

    def test_guest_after_logout(self):
        st.session_state["sb_user"] = {"email": "a@b.com", "id": "xyz"}
        st.session_state.pop("sb_user")
        assert is_guest() is True
