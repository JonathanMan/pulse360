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
    "GoogleDrive-jonathancyman@gmail.com/My Drive/Business/Claude/Pie360/watchlist.json"
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

    Reads directly from session_state (never calls load_watchlist / _js_read) to
    avoid a StreamlitDuplicateElementKey error: the page-level load_watchlist()
    call already registered the 'wl_read' key; calling it again inside a form
    submission handler would try to register the same key a second time.
    """
    ticker = ticker.upper().strip()
    # Direct session_state access — bypasses _js_read() entirely
    current = st.session_state.get("_watchlist_cache")
    if not isinstance(current, list):
        current = []
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

    Same session_state-direct pattern as add_to_watchlist — avoids duplicate key.
    """
    ticker = ticker.upper().strip()
    current = st.session_state.get("_watchlist_cache")
    if not isinstance(current, list):
        return False
    if ticker not in current:
        return False
    updated = [t for t in current if t != ticker]
    st.session_state["_watchlist_cache"] = updated
    _js_write(updated)
    # Clean the removed ticker out of the weights cache (no JS write needed —
    # the weights will be reconciled against the live watchlist on next save)
    w_cache = st.session_state.get("_weights_cache")
    if isinstance(w_cache, dict) and ticker in w_cache:
        del w_cache[ticker]
        st.session_state["_weights_cache"] = w_cache
    return True


def in_watchlist(ticker: str) -> bool:
    """Return True if *ticker* is in the current watchlist.

    Reads session_state directly — never calls _js_read() — to stay safe
    inside form submission handlers where 'wl_read' is already registered.
    """
    current = st.session_state.get("_watchlist_cache")
    if not isinstance(current, list):
        return False
    return ticker.upper().strip() in current


def clear_watchlist() -> None:
    """Remove all tickers from the watchlist."""
    st.session_state["_watchlist_cache"] = []
    _js_write([])
    # Also clear weights
    st.session_state["_weights_cache"] = {}
    _js_write_weights({})


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio weights store
# ══════════════════════════════════════════════════════════════════════════════
# Stored separately in localStorage under 'pulse360_weights' as a JSON object:
#   {"AAPL": 12.5, "MSFT": 8.0, ...}
#
# Follows the exact same two-tier pattern as the watchlist store:
# - load_weights()  — only function that calls _js_read_weights(); reads once at page level
# - save_weights()  — updates session_state + writes to localStorage
# - get_weight()    — reads session_state directly; safe in form submission handlers
# ══════════════════════════════════════════════════════════════════════════════

_WEIGHTS_KEY = "pulse360_weights"


def _js_read_weights() -> dict[str, float] | None:
    """
    Read portfolio weights from localStorage.

    Returns:
        dict[str, float]  — weights keyed by uppercase ticker (may be {})
        None              — JS component hasn't mounted yet (first render cycle)
    """
    try:
        from streamlit_javascript import st_javascript  # type: ignore
    except ImportError:
        return None

    raw = st_javascript(
        f"JSON.parse(localStorage.getItem('{_WEIGHTS_KEY}') || '{{}}')",
        key="wl_weights_read",
    )
    if raw is None or raw == 0:
        return None
    if isinstance(raw, dict):
        # Coerce values to float, skip non-numeric entries
        return {
            str(k).upper().strip(): float(v)
            for k, v in raw.items()
            if k and isinstance(v, (int, float))
        }
    return {}


def _js_write_weights(weights: dict[str, float]) -> None:
    """
    Persist portfolio weights to localStorage.
    Also mirrors to st.session_state so the same render cycle sees the update.
    """
    try:
        from streamlit_javascript import st_javascript  # type: ignore
    except ImportError:
        return

    payload = json.dumps({k.upper(): round(float(v), 2) for k, v in weights.items()})
    safe_payload = payload.replace("'", "\\'")
    st_javascript(
        f"localStorage.setItem('{_WEIGHTS_KEY}', '{safe_payload}'); 1",
        key="wl_weights_write",
    )
    st.session_state["_weights_cache"] = weights.copy()


def load_weights() -> dict[str, float]:
    """
    Return the current portfolio weights as a dict of {TICKER: weight_pct}.

    Reads from st.session_state cache first, then falls back to localStorage.
    Returns {} if the JS component hasn't mounted yet (first render cycle).
    """
    if "_weights_cache" in st.session_state:
        return dict(st.session_state["_weights_cache"])

    weights = _js_read_weights()
    if weights is not None:
        st.session_state["_weights_cache"] = weights
        return weights
    return {}


def save_weights(weights: dict[str, float]) -> None:
    """
    Persist all portfolio weights at once.

    Call this once after a form submission — do NOT call set_weight()
    per-ticker in a loop, as each call would try to register a new
    'wl_weights_write' JS key in the same render cycle.

    Args:
        weights: dict mapping uppercase ticker → weight percentage (0–100)
    """
    cleaned = {k.upper().strip(): round(float(v), 2) for k, v in weights.items() if v > 0}
    st.session_state["_weights_cache"] = cleaned
    _js_write_weights(cleaned)


def get_weight(ticker: str) -> float:
    """
    Return the portfolio weight for *ticker* (default 0.0).

    Reads session_state directly — never calls _js_read_weights() — to stay
    safe inside form submission handlers where 'wl_weights_read' is already
    registered.
    """
    current = st.session_state.get("_weights_cache")
    if not isinstance(current, dict):
        return 0.0
    return float(current.get(ticker.upper().strip(), 0.0))
