"""
components/profile_store.py
============================
Load and save per-user investor profile from/to Supabase.

Table (create once in Supabase SQL editor):
    create table user_profiles (
        user_email text primary key,
        profile    text not null default 'Beginner',
        updated_at timestamptz default now()
    );
"""

from __future__ import annotations

from components.supabase_client import get_client

_TABLE = "user_profiles"
_VALID = {"Beginner", "Investor", "Analyst"}


def load_profile(email: str) -> str | None:
    """Return the saved profile key for *email*, or None if not yet set."""
    try:
        resp = (
            get_client()
            .table(_TABLE)
            .select("profile")
            .eq("user_email", email)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            val = resp.data.get("profile")
            if val in _VALID:
                return val
    except Exception:
        pass
    return None


def save_profile(email: str, profile_key: str) -> None:
    """Upsert the profile for *email*. Silently ignores errors."""
    if profile_key not in _VALID:
        return
    try:
        get_client().table(_TABLE).upsert(
            {"user_email": email, "profile": profile_key, "updated_at": "now()"},
            on_conflict="user_email",
        ).execute()
    except Exception:
        pass
