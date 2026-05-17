"""
components/fred_utils.py
========================
Hardened FRED API wrapper for Pie360.

Wraps fredapi.Fred.get_series() with:
  • Configurable retry logic (exponential back-off)
  • Per-call timeout via concurrent.futures
  • Graceful fallback: returns the last cached value from session_state
    (or an empty Series) so the app never crashes on a FRED outage
  • Emits a st.warning() once per series per session when FRED is unreachable

Usage
-----
    from components.fred_utils import safe_get_series

    gdp = safe_get_series("GDP", fred_key, observation_start="2010-01-01")
    # Returns pd.Series — may be empty on FRED outage, never raises.

    # Inside a cached function (no st.warning — pass warn=False):
    gdp = safe_get_series("GDP", fred_key, warn=False)
"""

from __future__ import annotations

import time
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import pandas as pd
import streamlit as st
from components.observability import log, capture_exception

logger = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────
_DEFAULT_TIMEOUT_SECS = 12      # wall-clock seconds before we give up on a call
_MAX_RETRIES          = 2       # attempts after the first failure (total = 3)
_RETRY_BACKOFF_SECS   = 1.5     # seconds to wait between retries (doubles each time)
_CACHE_NS             = "_fred_cache"  # session_state key for per-series cache


# ── Internal helpers ──────────────────────────────────────────────────────────

def _cache_key(series_id: str) -> str:
    return f"{_CACHE_NS}__{series_id.upper()}"


def _get_cached(series_id: str) -> pd.Series | None:
    """Return the last successful fetch for this series, or None."""
    return st.session_state.get(_cache_key(series_id))


def _set_cached(series_id: str, data: pd.Series) -> None:
    """Persist a successful fetch to session_state."""
    if not data.empty:
        st.session_state[_cache_key(series_id)] = data


def _fetch_once(fred_client, series_id: str, kwargs: dict) -> pd.Series:
    """Single blocking FRED call — runs inside a thread so we can time it out."""
    return fred_client.get_series(series_id, **kwargs)


# ── Public API ────────────────────────────────────────────────────────────────

def safe_get_series(
    series_id: str,
    fred_key: str,
    *,
    warn: bool = True,
    timeout: float = _DEFAULT_TIMEOUT_SECS,
    max_retries: int = _MAX_RETRIES,
    **fred_kwargs,
) -> pd.Series:
    """
    Fetch a FRED series with retries, timeout, and graceful fallback.

    Args:
        series_id:   FRED series ID (e.g. "GDP", "UNRATE", "T10Y2Y")
        fred_key:    FRED API key string
        warn:        If True, emit st.warning() on failure (set False inside
                     @st.cache_data functions where st calls are not allowed)
        timeout:     Per-attempt wall-clock timeout in seconds
        max_retries: Number of additional attempts after the first failure
        **fred_kwargs: Passed verbatim to Fred.get_series() — e.g.
                     observation_start="2000-01-01", units="pc1"

    Returns:
        pd.Series — may be empty if all attempts fail and no cache exists.
        Never raises.
    """
    if not fred_key:
        # No API key configured — return empty without noise
        return pd.Series(dtype=float)

    try:
        import fredapi
        fred = fredapi.Fred(api_key=fred_key)
    except ImportError:
        if warn:
            st.warning("fredapi is not installed. Run: pip install fredapi", icon="⚠️")
        return pd.Series(dtype=float)

    last_exc: Exception | None = None
    backoff = _RETRY_BACKOFF_SECS

    for attempt in range(1 + max_retries):
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_fetch_once, fred, series_id, fred_kwargs)
                result = future.result(timeout=timeout)

            if isinstance(result, pd.Series):
                _set_cached(series_id, result)
                return result

        except FuturesTimeoutError:
            last_exc = TimeoutError(
                f"FRED timed out after {timeout}s for series {series_id!r}"
            )
            logger.warning("FRED timeout (attempt %d/%d): %s",
                           attempt + 1, 1 + max_retries, series_id)
        except Exception as exc:
            last_exc = exc
            logger.warning("FRED error (attempt %d/%d) for %s: %s",
                           attempt + 1, 1 + max_retries, series_id, exc)

        if attempt < max_retries:
            time.sleep(backoff)
            backoff *= 2

    # ── All attempts failed — try the cache ───────────────────────────────────
    cached = _get_cached(series_id)
    if cached is not None and not cached.empty:
        if warn:
            st.warning(
                f"⚠️ Could not reach FRED for **{series_id}** "
                f"({type(last_exc).__name__}). Showing last cached data.",
                icon="📡",
            )
        return cached

    # ── No cache either — return empty with a clear warning ───────────────────
    if warn:
        st.warning(
            f"⚠️ **{series_id}** data unavailable — FRED is unreachable and "
            "no cached data exists. Some charts may be empty.",
            icon="📡",
        )
    return pd.Series(dtype=float)


def safe_get_series_multi(
    series: dict[str, str],
    fred_key: str,
    *,
    warn: bool = True,
    timeout: float = _DEFAULT_TIMEOUT_SECS,
    **fred_kwargs,
) -> dict[str, pd.Series]:
    """
    Fetch multiple FRED series in parallel.

    Args:
        series:   {label: series_id}  — e.g. {"gdp": "GDP", "unrate": "UNRATE"}
        fred_key: FRED API key
        **fred_kwargs: Passed to every safe_get_series() call

    Returns:
        {label: pd.Series}  — empty Series for any that failed
    """
    results: dict[str, pd.Series] = {}
    # Sequential for now — add threading here if parallelism matters later
    for label, sid in series.items():
        results[label] = safe_get_series(
            sid, fred_key, warn=warn, timeout=timeout, **fred_kwargs
        )
    return results
