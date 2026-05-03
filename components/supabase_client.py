"""
components/supabase_client.py
==============================
Shared Supabase client and user identity helper.

Reads SUPABASE_URL and SUPABASE_KEY from st.secrets (set in Streamlit Cloud
or .streamlit/secrets.toml locally).

get_user_email() returns the logged-in viewer's email on Streamlit Cloud,
or DEV_USER_EMAIL from secrets for local development.
"""

from __future__ import annotations

import streamlit as st
from supabase import Client, create_client


@st.cache_resource
def get_client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def get_user_email() -> str:
    """Return the authenticated user's email from the Supabase auth session."""
    from components.auth import get_session_email
    email = get_session_email()
    if email:
        return email
    return st.secrets.get("DEV_USER_EMAIL", "dev@localhost.com")
