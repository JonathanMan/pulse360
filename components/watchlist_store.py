"""
watchlist_store.py
==================
Dual-persistence watchlist + portfolio weights store.

  • Authenticated users  → Supabase (cross-device, cloud-synced)
  • Unauthenticated users → localStorage via streamlit-javascript (browser-only)

Supabase table: user_watchlists (user_id, ticker, weight_pct, created_at)
  One row per ticker per user.  weight_pct = 0.0 for un-weighted tickers.
  See supabase_watchlist_migration.sql for the CREATE TABLE statement.

Session-state keys (same contract as before — nothing in the UI layer changes):
  _watchlist_cache : list[str]         current tickers, uppercase
  _weights_cache   : dict[str, float]  current weights keyed by ticker
  _wl_user_id      : str | None        cached Supabase UUID for this session
  _wl_source       : "supabase" | "localstorage"

Public API (unchanged from the previous localStorage-only version):
  load_watchlist()           → list[str]
  add_to_watchlist(ticker)   → bool
  remove_from_watchlist(t)   → bool
  in_watchlist(ticker)       → bool
  clear_watchlist()          → None
  load_weights()             → dict[str, float]
  save_weights(weights)      → None
  get_weight(ticker)         → float

Important invariants (preserved from original):
  • Mutation functions (add / remove / save / clear) read st.session_state
    directly — they NEVER call load_watchlist() or _js_read().  This avoids
    StreamlitDuplicateElementKey errors when called inside form handlers.
  • Supabase writes happen after session_state is updated, so the same render
    cycle already sees the new data without waiting for the network call.
  • If Supabase is unavailable, writes silently fail (same as the old
    _sync_export pattern).  Reads fall back to an empty list with a warning.
"""

from __future__ import annotations

import json
import streamlit as st

_LS_KEY      = "pulse360_watchlist"
_WEIGHTS_KEY = "pulse360_weights"
_MAX_TICKERS = 50
_SB_TABLE    = "user_watchlists"


# ══════════════════════════════════════════════════════════════════════════════
# Private helpers — user identity
# ══════════════════════════════════════════════════════════════════════════════

def _get_user_id() -> str | None:
    """
    Return the Supabase user UUID for the current session, or None if the
    user is not authenticated.  Caches the result in session_state so
    subsequent calls within the same render cycle are free.
    """
    if "_wl_user_id" in st.session_state:
        return st.session_state["_wl_user_id"]
    try:
        from components.supabase_client import get_user_id
        uid = get_user_id()
        if uid:
            st.session_state["_wl_user_id"] = uid
            return uid
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Private helpers — Supabase
# ══════════════════════════════════════════════════════════════════════════════

def _sb_load(user_id: str) -> tuple[list[str], dict[str, float]]:
    """
    Fetch all watchlist rows for user_id in a single Supabase query.
    Returns (tickers, weights).  Both empty on any error — caller must
    decide whether to surface the failure.
    """
    try:
        from components.supabase_client import get_client
        rows = (
            get_client()
            .table(_SB_TABLE)
            .select("ticker, weight_pct")
            .eq("user_id", user_id)
            .execute()
        ).data or []
        tickers = [r["ticker"] for r in rows]
        weights = {
            r["ticker"]: float(r["weight_pct"])
            for r in rows
            if r.get("weight_pct", 0.0) > 0
        }
        return tickers, weights
    except Exception:
        return [], {}


def _sb_upsert(user_id: str, ticker: str, weight_pct: float = 0.0) -> None:
    """Upsert a single (user_id, ticker) row.  Silently swallows errors."""
    try:
        from components.supabase_client import get_client
        get_client().table(_SB_TABLE).upsert({
            "user_id":    user_id,
            "ticker":     ticker,
            "weight_pct": round(weight_pct, 2),
        }).execute()
    except Exception:
        pass


def _sb_upsert_many(user_id: str, rows: list[dict]) -> None:
    """Bulk upsert rows for a user.  Silently swallows errors."""
    if not rows:
        return
    try:
        from components.supabase_client import get_client
        get_client().table(_SB_TABLE).upsert(rows).execute()
    except Exception:
        pass


def _sb_delete(user_id: str, ticker: str) -> None:
    """Delete a single ticker row for the user.  Silently swallows errors."""
    try:
        from components.supabase_client import get_client
        get_client().table(_SB_TABLE).delete().eq("user_id", user_id).eq("ticker", ticker).execute()
    except Exception:
        pass


def _sb_clear(user_id: str) -> None:
    """Delete all watchlist rows for the user.  Silently swallows errors."""
    try:
        from components.supabase_client import get_client
        get_client().table(_SB_TABLE).delete().eq("user_id", user_id).execute()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Private helpers — localStorage (unauthenticated users only)
# ══════════════════════════════════════════════════════════════════════════════

def _js_read() -> list[str] | None:
    """
    Read the watchlist from localStorage.
    Returns None on first render (JS component not yet mounted).
    """
    try:
        from streamlit_javascript import st_javascript  # type: ignore
    except ImportError:
        return None
    raw = st_javascript(
        f"JSON.parse(localStorage.getItem('{_LS_KEY}') || '[]')",
        key="wl_read",
    )
    if raw is None or raw == 0:
        return None
    if isinstance(raw, list):
        return [str(t).upper().strip() for t in raw if t]
    return []


def _js_write(tickers: list[str]) -> None:
    """Persist the watchlist to localStorage."""
    try:
        from streamlit_javascript import st_javascript  # type: ignore
    except ImportError:
        return
    payload     = json.dumps([t.upper() for t in tickers])
    safe_payload = payload.replace("'", "\\'")
    st_javascript(
        f"localStorage.setItem('{_LS_KEY}', '{safe_payload}'); 1",
        key="wl_write",
    )


def _js_read_weights() -> dict[str, float] | None:
    """
    Read portfolio weights from localStorage.
    Returns None on first render (JS component not yet mounted).
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
        return {
            str(k).upper().strip(): float(v)
            for k, v in raw.items()
            if k and isinstance(v, (int, float))
        }
    return {}


def _js_write_weights(weights: dict[str, float]) -> None:
    """Persist portfolio weights to localStorage."""
    try:
        from streamlit_javascript import st_javascript  # type: ignore
    except ImportError:
        return
    payload     = json.dumps({k.upper(): round(float(v), 2) for k, v in weights.items()})
    safe_payload = payload.replace("'", "\\'")
    st_javascript(
        f"localStorage.setItem('{_WEIGHTS_KEY}', '{safe_payload}'); 1",
        key="wl_weights_write",
    )


# ══════════════════════════════════════════════════════════════════════════════
# Public API — watchlist
# ══════════════════════════════════════════════════════════════════════════════

def load_watchlist() -> list[str]:
    """
    Return the current watchlist as a list of uppercase ticker strings.

    Authenticated users  → one Supabase query that primes BOTH _watchlist_cache
                           and _weights_cache (zero extra round trips for weights).
    Unauthenticated users → localStorage via streamlit-javascript (unchanged).

    Result is cached in st.session_state["_watchlist_cache"] for the render cycle.
    On first render the JS component may not be mounted yet; returns [] without
    caching so the real data arrives on the next cycle.

    Source-mismatch detection: if the cached data came from localStorage but the
    user is now authenticated (or vice-versa), the cache is busted and re-fetched
    from the correct source.  This handles Streamlit session persistence across
    deploys and the common case where localStorage data was cached before auth
    resolved.
    """
    user_id       = _get_user_id()
    cached_source = st.session_state.get("_wl_source")

    if "_watchlist_cache" in st.session_state:
        # Determine whether the cached data came from the right source:
        #   • authenticated + cached from localStorage → bust, re-fetch Supabase
        #   • unauthenticated + cached from Supabase   → bust, re-fetch localStorage
        source_mismatch = (
            (user_id     and cached_source != "supabase") or
            (not user_id and cached_source == "supabase")
        )
        if not source_mismatch:
            return list(st.session_state["_watchlist_cache"])
        # Bust stale cache before re-fetching
        st.session_state.pop("_watchlist_cache", None)
        st.session_state.pop("_weights_cache",   None)

    if user_id:
        # ── Authenticated: load from Supabase ──────────────────────────────
        tickers, weights = _sb_load(user_id)
        st.session_state["_watchlist_cache"] = tickers
        st.session_state["_wl_source"]       = "supabase"
        # Prime weights cache so load_weights() skips a second round trip
        if "_weights_cache" not in st.session_state:
            st.session_state["_weights_cache"] = weights
        return tickers
    else:
        # ── Unauthenticated: fall back to localStorage ─────────────────────
        st.session_state["_wl_source"] = "localstorage"
        tickers = _js_read()
        if tickers is not None:
            st.session_state["_watchlist_cache"] = tickers
            return tickers
        return []  # JS not mounted yet — don't cache


def add_to_watchlist(ticker: str) -> bool:
    """
    Add *ticker* to the watchlist.  Returns True if added, False if already present.

    Reads/writes session_state directly — never calls load_watchlist() or
    _js_read() to avoid StreamlitDuplicateElementKey inside form handlers.
    """
    ticker  = ticker.upper().strip()
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

    user_id = st.session_state.get("_wl_user_id") or _get_user_id()
    if user_id:
        _sb_upsert(user_id, ticker, weight_pct=0.0)
    else:
        _js_write(updated)

    return True


def remove_from_watchlist(ticker: str) -> bool:
    """
    Remove *ticker* from the watchlist.  Returns True if removed, False if not found.

    Reads/writes session_state directly — same rationale as add_to_watchlist.
    """
    ticker  = ticker.upper().strip()
    current = st.session_state.get("_watchlist_cache")
    if not isinstance(current, list) or ticker not in current:
        return False

    updated = [t for t in current if t != ticker]
    st.session_state["_watchlist_cache"] = updated

    # Clean the ticker from the weights cache too
    w_cache = st.session_state.get("_weights_cache")
    if isinstance(w_cache, dict) and ticker in w_cache:
        del w_cache[ticker]
        st.session_state["_weights_cache"] = w_cache

    user_id = st.session_state.get("_wl_user_id") or _get_user_id()
    if user_id:
        _sb_delete(user_id, ticker)
    else:
        _js_write(updated)

    return True


def in_watchlist(ticker: str) -> bool:
    """
    Return True if *ticker* is in the current watchlist.
    Reads session_state directly — safe inside form submission handlers.
    """
    current = st.session_state.get("_watchlist_cache")
    if not isinstance(current, list):
        return False
    return ticker.upper().strip() in current


def clear_watchlist() -> None:
    """Remove all tickers and weights from the watchlist."""
    st.session_state["_watchlist_cache"] = []
    st.session_state["_weights_cache"]   = {}

    user_id = st.session_state.get("_wl_user_id") or _get_user_id()
    if user_id:
        _sb_clear(user_id)
    else:
        _js_write([])
        _js_write_weights({})


# ══════════════════════════════════════════════════════════════════════════════
# Public API — portfolio weights
# ══════════════════════════════════════════════════════════════════════════════

def load_weights() -> dict[str, float]:
    """
    Return the current portfolio weights as {TICKER: weight_pct}.

    For authenticated users: weights are loaded as part of load_watchlist()
    (same Supabase query, zero extra round trips).  If load_watchlist() hasn't
    been called yet, this function calls it now.

    For unauthenticated users: reads from localStorage.
    """
    if "_weights_cache" in st.session_state:
        return dict(st.session_state["_weights_cache"])

    user_id = _get_user_id()
    if user_id:
        # Weights come for free with the watchlist load — trigger it now
        load_watchlist()
        return dict(st.session_state.get("_weights_cache", {}))
    else:
        weights = _js_read_weights()
        if weights is not None:
            st.session_state["_weights_cache"] = weights
            return weights
        return {}


def save_weights(weights: dict[str, float]) -> None:
    """
    Persist all portfolio weights at once.

    Authenticated users  → bulk upserts every watchlist ticker with its weight.
                           Tickers not in *weights* are upserted with weight 0.
    Unauthenticated users → writes to localStorage.

    Call this once after a form submission — do NOT call per-ticker in a loop,
    as each call would try to register a new JS key in the same render cycle
    (unauthenticated path) or generate N separate Supabase calls (authenticated).
    """
    cleaned = {
        k.upper().strip(): round(float(v), 2)
        for k, v in weights.items()
        if v > 0
    }
    st.session_state["_weights_cache"] = cleaned

    user_id = st.session_state.get("_wl_user_id") or _get_user_id()
    if user_id:
        tickers = st.session_state.get("_watchlist_cache", [])
        rows = [
            {
                "user_id":    user_id,
                "ticker":     t,
                "weight_pct": cleaned.get(t, 0.0),
            }
            for t in tickers
        ]
        _sb_upsert_many(user_id, rows)
    else:
        _js_write_weights(cleaned)


def get_weight(ticker: str) -> float:
    """
    Return the portfolio weight for *ticker* (default 0.0).
    Reads session_state directly — safe inside form submission handlers.
    """
    current = st.session_state.get("_weights_cache")
    if not isinstance(current, dict):
        return 0.0
    return float(current.get(ticker.upper().strip(), 0.0))
