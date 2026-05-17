"""
components/forecaster_weights.py
=================================
Per-user forecaster credibility weights for Pie360.

Each authenticated user can assign a weight (0.0 – 3.0) to every forecaster.
The weighted values flow into compute_consensus() in forecasters.py, shifting
the consensus bar and verdict to reflect the user's personal credibility model.

Default weight is 1.0 for every forecaster (equal weighting).
Weight 0.0 = "ignore this forecaster entirely."
Weight 2.0 = "double conviction — I trust this forecaster twice as much."

Supabase table: user_forecaster_weights
  (user_id TEXT, forecaster_name TEXT, weight FLOAT, updated_at TIMESTAMPTZ)
  PRIMARY KEY (user_id, forecaster_name)

Run supabase_forecaster_weights.sql once to create the table.

Public API
----------
    from components.forecaster_weights import (
        load_weights, save_weights, reset_weights,
        DEFAULT_WEIGHT, MAX_WEIGHT,
    )
"""

from __future__ import annotations

import streamlit as st

from components.forecasters import FORECASTER_NAMES
from components.supabase_client import get_client

_TABLE        = "user_forecaster_weights"
DEFAULT_WEIGHT = 1.0
MAX_WEIGHT     = 3.0
_CACHE_KEY    = "_fw_cache"   # session_state key for this session's weights


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_user_id() -> str | None:
    """Return the current user's Supabase UUID, or None if unauthenticated."""
    try:
        from components.auth import get_session_user
        u = get_session_user()
        return u.get("id") if u else None
    except Exception:
        return None


def _default_weights() -> dict[str, float]:
    """Return equal weights (1.0) for all known forecasters."""
    return {name: DEFAULT_WEIGHT for name in FORECASTER_NAMES}


# ── Public API ────────────────────────────────────────────────────────────────

def load_weights() -> dict[str, float]:
    """
    Load this user's forecaster weights.
    Waterfall: session_state cache → Supabase → default equal weights.

    Returns {forecaster_name: weight_float} for all known forecasters.
    Missing entries (forecaster added after the user last saved) default to 1.0.
    """
    # Session-state cache
    if _CACHE_KEY in st.session_state:
        return dict(st.session_state[_CACHE_KEY])

    user_id = _get_user_id()
    if not user_id:
        return _default_weights()

    try:
        rows = (
            get_client()
            .table(_TABLE)
            .select("forecaster_name, weight")
            .eq("user_id", user_id)
            .execute()
        ).data or []

        loaded = {r["forecaster_name"]: float(r["weight"]) for r in rows}
        # Fill in any forecasters not yet in DB with default
        weights = {name: loaded.get(name, DEFAULT_WEIGHT) for name in FORECASTER_NAMES}
        st.session_state[_CACHE_KEY] = weights
        return dict(weights)
    except Exception:
        return _default_weights()


def save_weights(weights: dict[str, float]) -> bool:
    """
    Persist weights for the current user.
    Updates session_state cache immediately; writes to Supabase asynchronously.

    Args:
        weights: {forecaster_name: weight_float}  — must cover all FORECASTER_NAMES

    Returns:
        True on success, False on Supabase failure (cache still updated).
    """
    # Clamp and clean
    cleaned = {
        name: round(max(0.0, min(MAX_WEIGHT, float(weights.get(name, DEFAULT_WEIGHT)))), 2)
        for name in FORECASTER_NAMES
    }
    st.session_state[_CACHE_KEY] = cleaned

    user_id = _get_user_id()
    if not user_id:
        return False  # unauthenticated — session-only

    try:
        rows = [
            {"user_id": user_id, "forecaster_name": name, "weight": w}
            for name, w in cleaned.items()
        ]
        get_client().table(_TABLE).upsert(rows).execute()
        return True
    except Exception:
        return False


def reset_weights() -> dict[str, float]:
    """
    Reset all weights to 1.0 (equal weighting) and persist.
    Returns the reset weights dict.
    """
    defaults = _default_weights()
    save_weights(defaults)
    return defaults


def is_equal_weighted(weights: dict[str, float]) -> bool:
    """Return True if all weights are (approximately) equal."""
    vals = list(weights.values())
    if not vals:
        return True
    first = vals[0]
    return all(abs(v - first) < 0.01 for v in vals)
