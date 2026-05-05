"""
components/watchlist_store.py
==============================
Browser-persistent watchlist using localStorage via streamlit-javascript.

The watchlist is stored in the browser's localStorage under the key
'pulse360_watchlist' as a JSON array of uppercase ticker strings:
  ["AAPL", "MSFT", "GOOGL"]

Persistence model
-----------------
- Survives page refreshes and new tabs on the same device/browser
- Private to the user's browser — no server-side storage required
- Lost if the user clears browser data or switches to a different browser

Usage
-----
    from components.watchlist_store import (
        load_watchlist,
        add_to_watchlist,
        remove_from_watchlist,
        in_watchlist,
    )

    tickers = load_watchlist()          # list[str] — may be [] on first render
    add_to_watchlist("AAPL")
    remove_from_watchlist("AAPL")
    in_watchlist("AAPL")               # bool

Important: st_javascript renders as an invisible component and its return
value is 0 (int) on the very first render cycle before the JS executes.
Always guard with:  `if tickers and tickers != 0`
"""

from __future__ import annotations

import json
import streamlit as st

_LS_KEY = "pulse360_watchlist"
_MAX_TICKERS = 50

# Path where the scheduled briefing agent reads the watchlist
_EXPORT_PATH = (
    "/Users/jonathanman/Library/CloudStorage/"
    "GoogleDrive-jonathancyman@gmail.com/My Drive/Business/Claude/Pulse360/watchlist.json"
)


def _js_read() -> list[str] | None:
    """
    Read the watchlist from localStorage.

    Returns:
        list[str]  — the tickers stored in localStorage (may be [])
        None       — JS component hasn't mounted yet (first render cycle);
                     callers must NOT cache this result.
    """
    try:
        from streamlit_javascript import st_javascript  # type: ignore
    except ImportError:
        return None

    raw = st_javascript(
        f"JSON.parse(localStorage.getItem('{_LS_KEY}') || '[]')",
        key="wl_read",
    )
    # st_javascript returns 0 (int) before the component mounts on the first render.
    # Return None so callers can distinguish "not ready" from "genuinely empty".
    if raw is None or raw == 0:
        return None
    if isinstance(raw, list):
        return [str(t).upper().strip() for t in raw if t]
    return []


def _js_write(tickers: list[str]) -> None:
    """
    Persist the watchlist to localStorage.
    Also mirrors to st.session_state so the same render cycle sees the update.
    """
    try:
        from streamlit_javascript import st_javascript  # type: ignore
    except ImportError:
        return

    payload = json.dumps([t.upper() for t in tickers])
    # Escape single quotes inside the JSON string for safety
    safe_payload = payload.replace("'", "\\'")
    # Note: payload is already valid JSON so we store it directly,
    # not JSON.stringify again (that would double-encode).
    st_javascript(
        f"localStorage.setItem('{_LS_KEY}', '{safe_payload}'); 1",
        key="wl_write",
    )
    st.session_state["_watchlist_cache"] = tickers
    _sync_export(tickers)


def _sync_export(tickers: list[str]) -> None:
    """
    Write the watchlist to a JSON file so the scheduled briefing agent
    can read it without needing browser localStorage access.
    Silently swallows errors — export failure must never break the UI.
    """
    try:
        import os
        os.makedirs(os.path.dirname(_EXPORT_PATH), exist_ok=True)
        with open(_EXPORT_PATH, "w") as fh:
            json.dump(tickers, fh)
    except Exception:
        pass


def load_watchlist() -> list[str]:
    """
    Return the current watchlist as a list of uppercase ticker strings.

    Reads from st.session_state cache first (populated by add/remove),
    then falls back to localStorage via st_javascript.

    IMPORTANT: only caches the result when _js_read() returns a real value
    (list, including []).  If _js_read() returns None it means the JS
    component hasn't mounted yet — caching [] at that point would permanently
    mask the real localStorage data on the next render cycle.
    """
    if "_watchlist_cache" in st.session_state:
        return list(st.session_state["_watchlist_cache"])

    tickers = _js_read()
    if tickers is not None:           # real value ([] counts as valid empty list)
        st.session_state["_watchlist_cache"] = tickers
        return tickers
    return []                         # not mounted yet — return [] without caching


def add_to_watchlist(ticker: str) -> bool:
    """
    Add *ticker* to the watchlist.  Returns True if added, False if already present.
    Caps the list at _MAX_TICKERS.
    """
    ticker = ticker.upper().strip()
    current = load_watchlist()
    if ticker in current:
        return False
    if len(current) >= _MAX_TICKERS:
        st.warning(f"Watchlist is full ({_MAX_TICKERS} tickers max). Remove one first.")
        return False
    updated = current + [ticker]
    st.session_state["_watchlist_cache"] = updated
    _js_write(updated)
    return True


def remove_from_watchlist(ticker: str) -> bool:
    """
    Remove *ticker* from the watchlist.  Returns True if removed, False if not found.
    """
    ticker = ticker.upper().strip()
    current = load_watchlist()
    if ticker not in current:
        return False
    updated = [t for t in current if t != ticker]
    st.session_state["_watchlist_cache"] = updated
    _js_write(updated)
    return True


def in_watchlist(ticker: str) -> bool:
    """Return True if *ticker* is in the current watchlist."""
    return ticker.upper().strip() in load_watchlist()


def clear_watchlist() -> None:
    """Remove all tickers from the watchlist."""
    st.session_state["_watchlist_cache"] = []
    _js_write([])
