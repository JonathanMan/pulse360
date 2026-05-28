"""
tests/test_fred_client.py
==========================
Tests for data/fred_client.py — mocked fredapi calls so no live API key needed.

Covers:
  - fetch_series() happy path, empty response, and API error
  - compute_lei_growth(), compute_cfnai_signal(), compute_icsa_yoy() helpers
  - fetch_model_inputs() shape and key completeness
  - safe_get_series() compatibility wrapper
"""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

# conftest.py stubs out streamlit and fredapi globally — these imports work
# without a real API key because _get_fred() is mocked below.
from data.fred_client import (
    fetch_series,
    compute_lei_growth,
    compute_cfnai_signal,
    compute_icsa_yoy,
    fetch_model_inputs,
    safe_get_series,
    SERIES_META,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _daily_series(n: int = 500, start: str = "2000-01-01", value: float = 1.0) -> pd.Series:
    """Build a synthetic daily pd.Series for use in mock returns."""
    idx = pd.date_range(start=start, periods=n, freq="D")
    return pd.Series(np.full(n, value, dtype=float), index=idx)


def _monthly_series(n: int = 60, value: float = 100.0) -> pd.Series:
    idx = pd.date_range(start="2019-01-01", periods=n, freq="MS")
    # Slight upward slope so LEI growth tests produce non-zero values
    values = np.linspace(value, value * 1.05, n)
    return pd.Series(values, index=idx)


# ── Series metadata ────────────────────────────────────────────────────────────

class TestSeriesMeta:
    def test_model_series_registered(self):
        """All recession model series IDs must be in SERIES_META."""
        model_ids = ["T10Y3M", "T10Y2Y", "USSLIND", "SAHMREALTIME",
                     "CFNAI", "NFCI", "ICSA", "BAMLH0A0HYM2"]
        for sid in model_ids:
            assert sid in SERIES_META, f"{sid} missing from SERIES_META"

    def test_meta_tuple_structure(self):
        """Each entry must be a 3-tuple: (description, frequency, stale_days)."""
        for sid, meta in SERIES_META.items():
            assert isinstance(meta, tuple) and len(meta) == 3, \
                f"{sid}: expected 3-tuple, got {meta!r}"
            desc, freq, stale = meta
            assert isinstance(desc, str) and desc, f"{sid}: empty description"
            assert isinstance(stale, int) and stale > 0, f"{sid}: bad stale threshold"

    def test_daily_stale_threshold_sensible(self):
        """Daily series should go stale after ≤ 10 days, monthly after ≤ 220 days."""
        for sid, (_, freq, stale) in SERIES_META.items():
            if freq == "daily":
                assert stale <= 10, f"{sid}: daily series stale threshold {stale} too high"
            if freq == "monthly":
                assert stale <= 220, f"{sid}: monthly series stale threshold {stale} too high"


# ── fetch_series() ─────────────────────────────────────────────────────────────

class TestFetchSeries:
    def _mock_fred(self, return_value: pd.Series):
        """Patch _get_fred() to return a mock Fred object."""
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = return_value
        return patch("data.fred_client._get_fred", return_value=mock_fred)

    def test_happy_path_returns_dict_shape(self):
        data = _daily_series(300)
        with self._mock_fred(data):
            # Bypass st.cache_data by calling the underlying function directly
            result = fetch_series("T10Y3M", "2000-01-01")
        assert isinstance(result, dict)
        expected_keys = {
            "series_id", "description", "data", "last_date",
            "last_value", "is_stale", "stale_message", "error",
        }
        assert expected_keys.issubset(result.keys())

    def test_happy_path_populates_values(self):
        data = _daily_series(300, value=2.5)
        with self._mock_fred(data):
            result = fetch_series("T10Y3M", "2000-01-01")
        assert result["error"] is None
        assert result["last_value"] == pytest.approx(2.5)
        assert isinstance(result["last_date"], date)
        assert result["series_id"] == "T10Y3M"

    def test_description_filled_from_meta(self):
        data = _daily_series(100)
        with self._mock_fred(data):
            result = fetch_series("VIXCLS", "2000-01-01")
        assert "VIX" in result["description"]

    def test_unknown_series_id_uses_id_as_description(self):
        data = _daily_series(50)
        with self._mock_fred(data):
            result = fetch_series("UNKN_XYZ", "2000-01-01")
        assert result["description"] == "UNKN_XYZ"

    def test_empty_data_sets_error(self):
        with self._mock_fred(pd.Series(dtype=float)):
            result = fetch_series("T10Y3M", "2000-01-01")
        assert result["error"] is not None
        assert result["data"].empty

    def test_api_exception_does_not_raise(self):
        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = RuntimeError("FRED down")
        with patch("data.fred_client._get_fred", return_value=mock_fred):
            result = fetch_series("T10Y3M", "2000-01-01")
        assert result["error"] is not None
        assert "FRED down" in result["error"]
        assert result["data"].empty

    def test_stale_flag_set_when_old(self):
        # Create data whose last date is well past any stale threshold
        old_idx = pd.date_range(start="2010-01-01", periods=100, freq="D")
        old_data = pd.Series(np.ones(100), index=old_idx)
        with self._mock_fred(old_data):
            result = fetch_series("T10Y3M", "2000-01-01")
        assert result["is_stale"] is True
        assert result["stale_message"] is not None

    def test_fresh_data_not_stale(self):
        # Data ending today — should not be stale for daily series (threshold = 5)
        n = 100
        idx = pd.date_range(end=date.today(), periods=n, freq="D")
        fresh_data = pd.Series(np.ones(n), index=idx)
        with self._mock_fred(fresh_data):
            result = fetch_series("T10Y3M", "2000-01-01")
        assert result["is_stale"] is False

    def test_nan_values_dropped(self):
        idx = pd.date_range(start="2020-01-01", periods=10, freq="D")
        data_with_nan = pd.Series([1.0, np.nan, 2.0, np.nan, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], index=idx)
        with self._mock_fred(data_with_nan):
            result = fetch_series("T10Y3M", "2000-01-01")
        assert result["error"] is None
        assert not result["data"].isna().any()


# ── Derived calculation helpers ────────────────────────────────────────────────

class TestComputeLeiGrowth:
    def test_positive_growth(self):
        # 13 monthly values with a 5% gain over 6 months
        idx = pd.date_range(start="2023-01-01", periods=13, freq="MS")
        base = 100.0
        vals = [base] * 7 + [base * 1.05] * 6  # step up at month 7
        s = pd.Series(vals, index=idx)
        result = compute_lei_growth(s)
        assert result is not None
        assert result > 0

    def test_negative_growth(self):
        idx = pd.date_range(start="2023-01-01", periods=13, freq="MS")
        vals = [100.0] * 7 + [95.0] * 6   # step down
        s = pd.Series(vals, index=idx)
        result = compute_lei_growth(s)
        assert result is not None
        assert result < 0

    def test_returns_none_on_empty(self):
        assert compute_lei_growth(pd.Series(dtype=float)) is None

    def test_returns_none_on_insufficient_data(self):
        idx = pd.date_range(start="2023-01-01", periods=4, freq="MS")
        s = pd.Series([100.0] * 4, index=idx)
        assert compute_lei_growth(s, months=6) is None

    def test_returns_none_when_base_is_zero(self):
        idx = pd.date_range(start="2023-01-01", periods=13, freq="MS")
        s = pd.Series([0.0] * 13, index=idx)
        assert compute_lei_growth(s) is None

    def test_custom_months_parameter(self):
        idx = pd.date_range(start="2023-01-01", periods=25, freq="MS")
        s = pd.Series(np.linspace(100, 110, 25), index=idx)
        result_6 = compute_lei_growth(s, months=6)
        result_12 = compute_lei_growth(s, months=12)
        assert result_6 is not None
        assert result_12 is not None
        # 6-month growth should be roughly half the 12-month growth (linear growth)
        assert abs(result_6) < abs(result_12) + 5   # generous tolerance for annualisation


class TestComputeCfnaiSignal:
    def test_positive_value_above_trend(self):
        idx = pd.date_range(start="2023-01-01", periods=6, freq="MS")
        s = pd.Series([0.5, 0.6, 0.7, 0.8, 0.9, 1.0], index=idx)
        result = compute_cfnai_signal(s)
        assert result is not None
        assert result > 0

    def test_negative_value_contraction(self):
        idx = pd.date_range(start="2023-01-01", periods=6, freq="MS")
        s = pd.Series([-0.8, -0.9, -1.0, -0.7, -0.6, -0.8], index=idx)
        result = compute_cfnai_signal(s)
        assert result is not None
        assert result < -0.7   # recession signal threshold

    def test_trailing_months_parameter(self):
        idx = pd.date_range(start="2023-01-01", periods=10, freq="MS")
        # First 7 months positive, last 3 months strongly negative
        vals = [0.8] * 7 + [-2.0, -2.0, -2.0]
        s = pd.Series(vals, index=idx)
        result_3 = compute_cfnai_signal(s, months=3)
        result_6 = compute_cfnai_signal(s, months=6)
        # 3-month average should be more negative than 6-month
        assert result_3 < result_6

    def test_returns_none_on_empty(self):
        assert compute_cfnai_signal(pd.Series(dtype=float)) is None

    def test_returns_none_on_insufficient_data(self):
        idx = pd.date_range(start="2023-01-01", periods=2, freq="MS")
        s = pd.Series([0.5, 0.6], index=idx)
        assert compute_cfnai_signal(s, months=3) is None

    def test_result_is_rounded(self):
        idx = pd.date_range(start="2023-01-01", periods=6, freq="MS")
        s = pd.Series([0.123456789] * 6, index=idx)
        result = compute_cfnai_signal(s)
        # Should round to 3 decimal places
        assert result == round(result, 3)


class TestComputeIcsaYoy:
    def _weekly_claims(self, n_weeks: int = 60, current: float = 220_000,
                       year_ago: float = 200_000) -> pd.Series:
        """Build weekly claims where the last 4 avg ~current and year-ago 4 avg ~year_ago."""
        idx = pd.date_range(start="2023-01-01", periods=n_weeks, freq="W")
        vals = [year_ago] * (n_weeks - 8) + [year_ago] * 4 + [current] * 4
        return pd.Series(vals[:n_weeks], index=idx)

    def test_rising_claims_positive_yoy(self):
        s = self._weekly_claims(current=260_000, year_ago=220_000)
        result = compute_icsa_yoy(s)
        assert result is not None
        assert result > 0

    def test_falling_claims_negative_yoy(self):
        s = self._weekly_claims(current=180_000, year_ago=220_000)
        result = compute_icsa_yoy(s)
        assert result is not None
        assert result < 0

    def test_returns_none_on_empty(self):
        assert compute_icsa_yoy(pd.Series(dtype=float)) is None

    def test_returns_none_on_insufficient_data(self):
        idx = pd.date_range(start="2023-01-01", periods=10, freq="W")
        s = pd.Series([200_000.0] * 10, index=idx)
        # Need at least 56 observations for YoY comparison
        assert compute_icsa_yoy(s) is None

    def test_returns_none_when_year_ago_is_zero(self):
        idx = pd.date_range(start="2020-01-01", periods=60, freq="W")
        vals = [0.0] * 60
        s = pd.Series(vals, index=idx)
        assert compute_icsa_yoy(s) is None


# ── fetch_model_inputs() ───────────────────────────────────────────────────────

class TestFetchModelInputs:
    def _mock_fetch(self, last_value: float = 1.0):
        """Patch fetch_series to return a minimal success result."""
        def _fake_fetch(sid, start_date="1990-01-01", end_date=None):
            idx = pd.date_range(end=date.today(), periods=100, freq="D")
            return {
                "series_id": sid,
                "description": sid,
                "data": pd.Series(np.full(100, last_value), index=idx),
                "last_date": date.today(),
                "last_value": last_value,
                "is_stale": False,
                "stale_message": None,
                "error": None,
            }
        return patch("data.fred_client.fetch_series", side_effect=_fake_fetch)

    def test_returns_all_8_model_ids(self):
        with self._mock_fetch():
            results = fetch_model_inputs()
        expected = {"T10Y3M", "T10Y2Y", "USSLIND", "SAHMREALTIME",
                    "CFNAI", "NFCI", "ICSA", "BAMLH0A0HYM2"}
        assert set(results.keys()) == expected

    def test_each_result_has_required_keys(self):
        with self._mock_fetch():
            results = fetch_model_inputs()
        for sid, r in results.items():
            assert "data" in r, f"{sid} missing 'data' key"
            assert "last_value" in r, f"{sid} missing 'last_value' key"
            assert "error" in r, f"{sid} missing 'error' key"

    def test_propagates_error_when_series_fails(self):
        def _fail_nfci(sid, start_date="1990-01-01", end_date=None):
            return {
                "series_id": sid,
                "description": sid,
                "data": pd.Series(dtype=float),
                "last_date": None,
                "last_value": None,
                "is_stale": False,
                "stale_message": None,
                "error": "NFCI fetch failed" if sid == "NFCI" else None,
            }
        with patch("data.fred_client.fetch_series", side_effect=_fail_nfci):
            results = fetch_model_inputs()
        assert results["NFCI"]["error"] is not None
        assert results["T10Y3M"]["error"] is None


# ── safe_get_series() compatibility wrapper ────────────────────────────────────

class TestSafeGetSeries:
    def _mock_fetch_ok(self):
        idx = pd.date_range(end=date.today(), periods=50, freq="D")
        s = pd.Series(np.linspace(2.0, 3.0, 50), index=idx)
        ok_result = {
            "series_id": "T10Y3M", "description": "Spread",
            "data": s, "last_date": date.today(), "last_value": 3.0,
            "is_stale": False, "stale_message": None, "error": None,
        }
        return patch("data.fred_client.fetch_series", return_value=ok_result)

    def test_returns_series_on_success(self):
        idx = pd.date_range(end=date.today(), periods=50, freq="D")
        s = pd.Series(np.linspace(2.0, 3.0, 50), index=idx)
        ok_result = {
            "series_id": "T10Y3M", "description": "Spread",
            "data": s, "last_date": date.today(), "last_value": 3.0,
            "is_stale": False, "stale_message": None, "error": None,
        }
        with patch("data.fred_client.fetch_series", return_value=ok_result):
            result = safe_get_series("T10Y3M")
        assert isinstance(result, pd.Series)
        assert len(result) == 50

    def test_returns_empty_series_on_error(self):
        err_result = {
            "series_id": "T10Y3M", "description": "Spread",
            "data": pd.Series(dtype=float), "last_date": None, "last_value": None,
            "is_stale": False, "stale_message": None, "error": "fetch failed",
        }
        with patch("data.fred_client.fetch_series", return_value=err_result):
            result = safe_get_series("T10Y3M", warn=False)
        assert isinstance(result, pd.Series)
        assert result.empty

    def test_accepts_fred_key_kwarg_without_error(self):
        """fred_key is accepted for compat but silently ignored."""
        err_result = {
            "series_id": "T10Y3M", "description": "",
            "data": pd.Series(dtype=float), "last_date": None,
            "last_value": None, "is_stale": False,
            "stale_message": None, "error": None,
        }
        with patch("data.fred_client.fetch_series", return_value=err_result):
            # Should not raise TypeError
            safe_get_series("T10Y3M", fred_key="irrelevant", warn=False)
