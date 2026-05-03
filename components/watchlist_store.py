"""
components/watchlist_store.py
==============================
Per-user watchlist backed by Supabase (watchlist_items table).

Each row: user_email | ticker | added_at
Unique constraint on (user_email, ticker) prevents duplicates.

Session-state cache avoids a round-trip on every rerun within the same
browser session. Cache is invalidated on add/remove/clear.
"""

from __future__ import annotations

import streamlit as st

from components.supabase_client import get_client, get_user_email

_MAX_TICKERS = 50


def _cache_key() -> str:
    return f"_watchlist_{get_user_email()}"


def load_watchlist() -> list[str]:
    key = _cache_key()
    if key in st.session_state:
        return list(st.session_state[key])
    try:
        rows = (
            get_client()
            .table("watchlist_items")
            .select("ticker")
            .eq("user_email", get_user_email())
            .order("added_at")
            .execute()
        )
        tickers = [r["ticker"] for r in rows.data]
    except Exception:
        tickers = []
    st.session_state[key] = tickers
    return tickers


def add_to_watchlist(ticker: str) -> bool:
    ticker = ticker.upper().strip()
    current = load_watchlist()
    if ticker in current:
        return False
    if len(current) >= _MAX_TICKERS:
        st.warning(f"Watchlist is full ({_MAX_TICKERS} tickers max). Remove one first.")
        return False
    try:
        get_client().table("watchlist_items").insert(
            {"user_email": get_user_email(), "ticker": ticker}
        ).execute()
        st.session_state[_cache_key()] = current + [ticker]
        return True
    except Exception:
        return False


def remove_from_watchlist(ticker: str) -> bool:
    ticker = ticker.upper().strip()
    current = load_watchlist()
    if ticker not in current:
        return False
    try:
        get_client().table("watchlist_items").delete().eq(
            "user_email", get_user_email()
        ).eq("ticker", ticker).execute()
        st.session_state[_cache_key()] = [t for t in current if t != ticker]
        return True
    except Exception:
        return False


def in_watchlist(ticker: str) -> bool:
    return ticker.upper().strip() in load_watchlist()


def clear_watchlist() -> None:
    try:
        get_client().table("watchlist_items").delete().eq(
            "user_email", get_user_email()
        ).execute()
    except Exception:
        pass
    st.session_state[_cache_key()] = []
