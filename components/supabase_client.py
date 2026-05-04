"""
components/supabase_client.py
==============================
Shared Supabase client and user identity helper.

Reads SUPABASE_URL and SUPABASE_KEY from st.secrets (set in Streamlit Cloud
or .streamlit/secrets.toml locally).

get_user_email() returns the logged-in viewer's email, or their phone number
for phone-only accounts (used as a stable per-user identifier in Supabase
tables such as watchlist_items and alerts).

For local development, falls back to DEV_USER_EMAIL from secrets.
"""

from __future__ import annotations

import streamlit as st
from supabase import Client, create_client


@st.cache_resource
def get_client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def get_user_email() -> str:
    """
    Return a stable string identifier for the authenticated user.

    Priority:
      1. Email address (email/password or Google OAuth users)
      2. Phone number (phone OTP users — stored as E.164 e.g. +447700900123)
      3. DEV_USER_EMAIL secret (local development fallback)
    """
    from components.auth import get_session_email
    identifier = get_session_email()   # returns email, or phone for phone-only users
    if identifier:
        return identifier
    return st.secrets.get("DEV_USER_EMAIL", "dev@localhost.com")


def get_user_id() -> str | None:
    """Return the Supabase user UUID for the authenticated user, if available."""
    from components.auth import get_session_user
    u = get_session_user()
    return u.get("id") if u else None
