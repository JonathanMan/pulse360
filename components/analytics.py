"""
components/analytics.py
========================
Lightweight event logging to Supabase.

Events logged:
  page_view  — every time a user navigates to a page
  login      — on successful auth (email or google)

Admin view: pages/13_Admin.py (restricted to ADMIN_EMAILS in secrets).
"""

from __future__ import annotations

import streamlit as st

from components.supabase_client import get_client, get_user_email

_TABLE = "usage_events"


def is_admin() -> bool:
    """True if the current user's email is in the ADMIN_EMAILS secret."""
    try:
        raw = st.secrets.get("ADMIN_EMAILS", "")
        admins = [e.strip().lower() for e in raw.split(",") if e.strip()]
        return bool(admins) and get_user_email().lower() in admins
    except Exception:
        return False


def log_event(
    event_type: str,
    page: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Insert a usage event. Fire-and-forget — never raises."""
    try:
        row: dict = {
            "user_email": get_user_email(),
            "event_type": event_type,
        }
        if page:
            row["page"] = page
        if metadata:
            row["metadata"] = metadata
        get_client().table(_TABLE).insert(row).execute()
    except Exception:
        pass


def log_page_view(page_title: str) -> None:
    """Log a page view once per navigation (deduped via session_state)."""
    key = "_analytics_last_page"
    if st.session_state.get(key) == page_title:
        return
    st.session_state[key] = page_title
    log_event("page_view", page=page_title)


def log_login(method: str) -> None:
    """Log a successful login with the auth method used."""
    log_event("login", metadata={"method": method})
