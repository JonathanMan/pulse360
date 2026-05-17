"""
tests/test_watchlist_weights.py
================================
Unit tests for the portfolio-weight functions added to watchlist_store.py.

These functions read/write st.session_state directly (no st_javascript calls
in the pure-logic paths), so we can test them by providing a minimal
session_state dict mock.

Run from the workspace root:
    python -m pytest Pie360/tests/ -v
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest.mock as mock

# ── Streamlit stub ────────────────────────────────────────────────────────────
# Provide a minimal st stub so watchlist_store imports cleanly without a
# running Streamlit server.

_session_state: dict = {}

class _FakeSessionState(dict):
    """dict subclass that also supports attribute-style access."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)
    def __setattr__(self, key, value):
        self[key] = value
    def __delattr__(self, key):
        del self[key]

_session_state = _FakeSessionState()

streamlit_stub       = mock.MagicMock()
streamlit_stub.session_state = _session_state
streamlit_stub.cache_data    = lambda **kw: (lambda fn: fn)
streamlit_stub.warning       = lambda *a, **kw: None
sys.modules["streamlit"]             = streamlit_stub
sys.modules["streamlit_javascript"]  = mock.MagicMock()

# Import AFTER stubbing
from watchlist_store import (
    load_weights,
    save_weights,
    get_weight,
    clear_watchlist,
    remove_from_watchlist,
)


def _reset():
    """Clear session state between tests."""
    _session_state.clear()


# ── load_weights ──────────────────────────────────────────────────────────────

class TestLoadWeights:
    def setup_method(self):
        _reset()

    def test_returns_empty_dict_when_no_cache(self):
        # _js_read_weights returns None (mocked), so load_weights returns {}
        result = load_weights()
        assert result == {}

    def test_returns_from_session_state_cache(self):
        _session_state["_weights_cache"] = {"AAPL": 50.0, "MSFT": 50.0}
        result = load_weights()
        assert result == {"AAPL": 50.0, "MSFT": 50.0}

    def test_returns_copy_not_reference(self):
        _session_state["_weights_cache"] = {"AAPL": 50.0}
        result = load_weights()
        result["AAPL"] = 99.0
        assert _session_state["_weights_cache"]["AAPL"] == 50.0


# ── save_weights ──────────────────────────────────────────────────────────────

class TestSaveWeights:
    def setup_method(self):
        _reset()

    def test_saves_to_session_state(self):
        save_weights({"AAPL": 60.0, "TLT": 40.0})
        assert _session_state["_weights_cache"]["AAPL"] == 60.0
        assert _session_state["_weights_cache"]["TLT"] == 40.0

    def test_uppercases_tickers(self):
        save_weights({"aapl": 100.0})
        assert "AAPL" in _session_state["_weights_cache"]

    def test_filters_out_zero_weights(self):
        save_weights({"AAPL": 60.0, "MSFT": 0.0, "TLT": 40.0})
        assert "MSFT" not in _session_state["_weights_cache"]

    def test_rounds_to_two_decimals(self):
        save_weights({"AAPL": 33.333333})
        assert _session_state["_weights_cache"]["AAPL"] == 33.33

    def test_overwrites_existing_cache(self):
        _session_state["_weights_cache"] = {"MSFT": 100.0}
        save_weights({"AAPL": 100.0})
        assert "MSFT" not in _session_state["_weights_cache"]
        assert "AAPL" in _session_state["_weights_cache"]


# ── get_weight ────────────────────────────────────────────────────────────────

class TestGetWeight:
    def setup_method(self):
        _reset()

    def test_returns_zero_when_no_cache(self):
        assert get_weight("AAPL") == 0.0

    def test_returns_correct_weight(self):
        _session_state["_weights_cache"] = {"AAPL": 35.5}
        assert get_weight("AAPL") == 35.5

    def test_case_insensitive(self):
        _session_state["_weights_cache"] = {"AAPL": 25.0}
        assert get_weight("aapl") == 25.0

    def test_missing_ticker_returns_zero(self):
        _session_state["_weights_cache"] = {"AAPL": 50.0}
        assert get_weight("MSFT") == 0.0

    def test_returns_float(self):
        _session_state["_weights_cache"] = {"AAPL": 40}
        result = get_weight("AAPL")
        assert isinstance(result, float)


# ── remove_from_watchlist cleans up weights ───────────────────────────────────

class TestRemoveFromWatchlistCleansWeights:
    def setup_method(self):
        _reset()

    def test_removes_ticker_weight_from_cache(self):
        _session_state["_watchlist_cache"] = ["AAPL", "MSFT"]
        _session_state["_weights_cache"]   = {"AAPL": 60.0, "MSFT": 40.0}
        remove_from_watchlist("AAPL")
        assert "AAPL" not in _session_state.get("_weights_cache", {})
        assert "MSFT" in _session_state.get("_weights_cache", {})

    def test_remove_nonexistent_ticker_does_not_crash(self):
        _session_state["_watchlist_cache"] = ["AAPL"]
        _session_state["_weights_cache"]   = {"AAPL": 100.0}
        result = remove_from_watchlist("ZZZZ")
        assert result is False


# ── clear_watchlist clears weights ───────────────────────────────────────────

class TestClearWatchlistClearsWeights:
    def setup_method(self):
        _reset()

    def test_weights_cache_cleared(self):
        _session_state["_watchlist_cache"] = ["AAPL"]
        _session_state["_weights_cache"]   = {"AAPL": 100.0}
        clear_watchlist()
        assert _session_state.get("_weights_cache") == {}

    def test_watchlist_cache_cleared(self):
        _session_state["_watchlist_cache"] = ["AAPL", "MSFT"]
        clear_watchlist()
        assert _session_state.get("_watchlist_cache") == []


# ── round-trip ────────────────────────────────────────────────────────────────

class TestRoundTrip:
    def setup_method(self):
        _reset()

    def test_save_then_load(self):
        weights = {"AAPL": 40.0, "TLT": 35.0, "GLD": 25.0}
        save_weights(weights)
        loaded = load_weights()
        assert loaded == weights

    def test_save_then_get(self):
        save_weights({"NVDA": 55.5, "BIL": 44.5})
        assert get_weight("NVDA") == 55.5
        assert get_weight("BIL") == 44.5
