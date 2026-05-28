"""
tests/test_recession_model.py
==============================
Comprehensive tests for the Pie360 recession probability model and its
supporting FRED data-layer helpers.

Covers:
  - models/recession_model.py  — all 8 stress functions, run_recession_model(),
                                  traffic light thresholds, graceful None handling
  - data/fred_client.py        — compute_lei_growth(), compute_cfnai_signal(),
                                  compute_icsa_yoy()
  - components/cycle_engine.py — individual indicator scoring functions,
                                  confidence arithmetic, empty-series fallbacks

No live FRED calls are made. All data is synthetic pd.Series / dict fixtures.
"""

import sys
import os
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 1 — models/recession_model.py
# ──────────────────────────────────────────────────────────────────────────────

from models.recession_model import (
    _logistic,
    _stress_t10y3m,
    _stress_t10y2y,
    _stress_lei_growth,
    _stress_sahm,
    _stress_cfnai,
    _stress_nfci,
    _stress_claims_yoy,
    _stress_hy_oas,
    _FEATURES,
    run_recession_model,
    RecessionModelOutput,
    FeatureContribution,
)


# ── 1.1 _logistic ─────────────────────────────────────────────────────────────

class TestLogistic:
    def test_zero_input_returns_half(self):
        assert abs(_logistic(0.0) - 0.5) < 1e-9

    def test_large_positive_approaches_one(self):
        assert _logistic(100.0) > 0.999

    def test_large_negative_approaches_zero(self):
        assert _logistic(-100.0) < 0.001

    def test_output_in_unit_interval(self):
        for x in [-10, -1, -0.5, 0, 0.5, 1, 10]:
            v = _logistic(x)
            assert 0.0 < v < 1.0, f"logistic({x}) = {v} out of (0, 1)"

    def test_monotonically_increasing(self):
        xs = [-5, -2, -1, 0, 1, 2, 5]
        vals = [_logistic(x) for x in xs]
        assert vals == sorted(vals)

    def test_symmetry(self):
        assert abs(_logistic(2.0) + _logistic(-2.0) - 1.0) < 1e-9


# ── 1.2 Stress function contracts ─────────────────────────────────────────────

class TestStressFunctionContracts:
    """Every stress function must return (float in [0,1], non-empty str)."""

    def _check(self, fn, value):
        stress, desc = fn(value)
        assert 0.0 <= stress <= 1.0, f"{fn.__name__}({value}) stress={stress} out of range"
        assert isinstance(desc, str) and desc, f"{fn.__name__}({value}) empty description"
        return stress, desc

    def test_t10y3m_range(self):
        for v in [-2.0, -1.0, -0.5, -0.25, 0.0, 0.5, 1.5, 3.0]:
            self._check(_stress_t10y3m, v)

    def test_t10y2y_range(self):
        for v in [-2.0, -0.75, -0.5, -0.25, 0.0, 0.5, 1.0]:
            self._check(_stress_t10y2y, v)

    def test_lei_growth_range(self):
        for v in [-5.0, -2.0, -1.0, 0.0, 1.0, 2.0, 5.0, 10.0]:
            self._check(_stress_lei_growth, v)

    def test_sahm_range(self):
        for v in [0.0, 0.1, 0.25, 0.35, 0.50, 0.70, 1.0]:
            self._check(_stress_sahm, v)

    def test_cfnai_range(self):
        for v in [-1.5, -0.70, -0.35, 0.0, 0.20, 0.50, 1.0]:
            self._check(_stress_cfnai, v)

    def test_nfci_range(self):
        for v in [-1.5, -0.5, 0.0, 0.25, 0.50, 1.0]:
            self._check(_stress_nfci, v)

    def test_claims_yoy_range(self):
        for v in [-20.0, -5.0, 0.0, 5.0, 10.0, 20.0, 40.0]:
            self._check(_stress_claims_yoy, v)

    def test_hy_oas_range(self):
        for v in [200.0, 350.0, 450.0, 550.0, 700.0, 900.0]:
            self._check(_stress_hy_oas, v)


# ── 1.3 Stress function monotonicity ─────────────────────────────────────────

class TestStressMonotonicity:
    """Stress must be monotonically increasing with recession severity."""

    def test_t10y3m_more_inverted_more_stress(self):
        s_steep, _ = _stress_t10y3m(2.0)   # steep positive (low stress)
        s_flat, _  = _stress_t10y3m(0.0)
        s_inv, _   = _stress_t10y3m(-1.0)  # deeply inverted (high stress)
        assert s_steep < s_flat < s_inv

    def test_t10y2y_more_inverted_more_stress(self):
        s_pos, _ = _stress_t10y2y(1.0)
        s_neg, _ = _stress_t10y2y(-1.0)
        assert s_pos < s_neg

    def test_lei_growth_lower_growth_higher_stress(self):
        s_high, _ = _stress_lei_growth(5.0)
        s_zero, _ = _stress_lei_growth(0.0)
        s_neg, _  = _stress_lei_growth(-3.0)
        assert s_high < s_zero < s_neg

    def test_sahm_higher_value_higher_stress(self):
        s_low, _  = _stress_sahm(0.0)
        s_mid, _  = _stress_sahm(0.30)
        s_high, _ = _stress_sahm(0.60)
        assert s_low < s_mid < s_high

    def test_cfnai_lower_value_higher_stress(self):
        s_strong, _ = _stress_cfnai(0.5)
        s_weak, _   = _stress_cfnai(-0.5)
        s_reces, _  = _stress_cfnai(-1.0)
        assert s_strong < s_weak < s_reces

    def test_nfci_tighter_higher_stress(self):
        s_loose, _ = _stress_nfci(-1.0)
        s_neut, _  = _stress_nfci(0.0)
        s_tight, _ = _stress_nfci(1.0)
        assert s_loose < s_neut < s_tight

    def test_claims_yoy_rising_higher_stress(self):
        s_fall, _ = _stress_claims_yoy(-10.0)
        s_flat, _ = _stress_claims_yoy(0.0)
        s_rise, _ = _stress_claims_yoy(25.0)
        assert s_fall < s_flat < s_rise

    def test_hy_oas_wider_higher_stress(self):
        s_tight, _ = _stress_hy_oas(250.0)
        s_norm, _  = _stress_hy_oas(450.0)
        s_wide, _  = _stress_hy_oas(800.0)
        assert s_tight < s_norm < s_wide


# ── 1.4 Stress function calibration checkpoints ───────────────────────────────

class TestStressCalibration:
    """Spot-check known calibration points documented in the model docstrings."""

    def test_t10y3m_breakeven_at_minus_025(self):
        stress, _ = _stress_t10y3m(-0.25)
        assert abs(stress - 0.5) < 0.01, f"Expected ≈0.50, got {stress}"

    def test_t10y3m_flat_curve_low_stress(self):
        stress, _ = _stress_t10y3m(0.0)
        assert stress < 0.20, f"Flat curve stress={stress}, expected < 0.20"

    def test_t10y2y_breakeven_at_minus_025(self):
        stress, _ = _stress_t10y2y(-0.25)
        assert abs(stress - 0.5) < 0.01

    def test_lei_midpoint_at_plus_1pct(self):
        stress, _ = _stress_lei_growth(1.0)
        assert abs(stress - 0.5) < 0.01, f"Expected ≈0.50, got {stress}"

    def test_lei_zero_growth_slightly_above_half(self):
        stress, _ = _stress_lei_growth(0.0)
        assert stress > 0.50, f"Zero LEI growth should be > 0.50"

    def test_lei_neg2_high_stress(self):
        stress, _ = _stress_lei_growth(-2.0)
        assert stress > 0.85, f"LEI -2% 6M should produce stress > 0.85, got {stress}"

    def test_sahm_trigger_at_050(self):
        stress, _ = _stress_sahm(0.50)
        # Logistic midpoint at 0.25 with scale 0.12 → value at 0.50 ≈ 0.88
        assert stress > 0.85, f"Sahm at trigger (0.50) should be > 0.85, got {stress}"

    def test_hy_oas_midpoint_around_450(self):
        stress, _ = _stress_hy_oas(450.0)
        assert 0.40 < stress < 0.60, f"HY OAS 450bps stress={stress}, expected ≈0.50"


# ── 1.5 Feature weights integrity ────────────────────────────────────────────

class TestFeatureWeights:
    def test_weights_sum_to_one(self):
        total = sum(f["weight"] for f in _FEATURES)
        assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, expected 1.0"

    def test_eight_features_present(self):
        assert len(_FEATURES) == 8

    def test_all_weights_positive(self):
        for f in _FEATURES:
            assert f["weight"] > 0, f"Feature {f['name']} has non-positive weight"

    def test_t10y3m_has_highest_weight(self):
        weights = {f["series_id"]: f["weight"] for f in _FEATURES}
        assert weights["T10Y3M"] == max(weights.values())

    def test_t10y2y_has_lowest_weight(self):
        weights = {f["series_id"]: f["weight"] for f in _FEATURES}
        assert weights["T10Y2Y"] == min(weights.values())


# ── 1.6 run_recession_model() — traffic light thresholds ─────────────────────

def _mock_series(value: float, days_old: int = 1) -> pd.Series:
    """Return a minimal pd.Series suitable for model input."""
    idx = pd.date_range(end=date.today() - timedelta(days=days_old), periods=60, freq="MS")
    return pd.Series([value] * 60, index=idx, dtype=float)


def _build_inputs(
    t10y3m: float = 1.5,
    t10y2y: float = 1.5,
    sahmrealtime: float = 0.0,
    cfnai: float = 0.3,
    nfci: float = -0.3,
    icsa_yoy: float = -5.0,   # claims falling = healthy
    hy_oas: float = 300.0,
    lei_growth_6m: float = 3.0,
) -> dict:
    """
    Build a synthetic model inputs dict.

    ICSA is given as a pre-calculated YoY % — we build a Series where the
    last 4 vs prior-year 4 produce approximately the requested YoY %.
    USSLIND is built so compute_lei_growth() returns lei_growth_6m.
    CFNAI is built so compute_cfnai_signal() returns cfnai.
    """
    today = date.today()

    def _daily_series(v, days=400):
        idx = pd.date_range(end=today, periods=days, freq="D")
        return pd.Series([v] * days, index=idx, dtype=float)

    def _monthly_series(v, months=36):
        idx = pd.date_range(end=today, periods=months, freq="MS")
        return pd.Series([v] * months, index=idx, dtype=float)

    def _weekly_series(v, weeks=60):
        idx = pd.date_range(end=today, periods=weeks, freq="W")
        return pd.Series([v] * weeks, index=idx, dtype=float)

    # Build ICSA weekly series so that 4-week avg YoY ≈ icsa_yoy %
    # current_avg = 220_000; year_ago_avg = current_avg / (1 + icsa_yoy/100)
    current_claims = 220_000.0
    year_ago_claims = current_claims / (1 + icsa_yoy / 100) if icsa_yoy != -100 else current_claims
    # 60 weeks: first 4 are "year ago" (weeks 52-56), last 4 are "current"
    icsa_vals = [year_ago_claims] * 56 + [current_claims] * 4
    icsa_idx = pd.date_range(end=today, periods=60, freq="W")
    icsa_series = pd.Series(icsa_vals, index=icsa_idx, dtype=float)

    # Build USSLIND monthly series so compute_lei_growth() returns ≈ lei_growth_6m
    # annualised = ((current/past)^2 - 1)*100 ≈ lei_growth_6m
    # => current/past = sqrt(1 + lei_growth_6m/100) (approximately)
    ratio = math.sqrt(1 + lei_growth_6m / 100) if lei_growth_6m > -100 else 0.5
    lei_past = 100.0
    lei_current = lei_past * ratio
    lei_vals = [lei_past] * 7 + [lei_current]   # 8 months: index [-7] = past, [-1] = current
    lei_idx = pd.date_range(end=today, periods=8, freq="MS")
    lei_series = pd.Series(lei_vals, index=lei_idx, dtype=float)

    # Build CFNAI monthly series so trailing 3-month avg ≈ cfnai
    cfnai_series = _monthly_series(cfnai, months=12)

    def _result(series_id, series, last_value, is_stale=False):
        return {
            "series_id":    series_id,
            "description":  series_id,
            "data":         series,
            "last_date":    today - timedelta(days=1),
            "last_value":   last_value,
            "is_stale":     is_stale,
            "stale_message": None,
            "error":        None,
        }

    return {
        "T10Y3M":      _result("T10Y3M",      _daily_series(t10y3m),   t10y3m),
        "T10Y2Y":      _result("T10Y2Y",      _daily_series(t10y2y),   t10y2y),
        "SAHMREALTIME":_result("SAHMREALTIME",_monthly_series(sahmrealtime), sahmrealtime),
        "CFNAI":       _result("CFNAI",       cfnai_series,             cfnai),
        "NFCI":        _result("NFCI",        _weekly_series(nfci),     nfci),
        "ICSA":        _result("ICSA",        icsa_series,              current_claims),
        "BAMLH0A0HYM2":_result("BAMLH0A0HYM2",_daily_series(hy_oas),   hy_oas),
        "USSLIND":     _result("USSLIND",     lei_series,               lei_current),
    }


class TestRunRecessionModelTrafficLights:
    """run_recession_model() traffic lights depend solely on the probability threshold."""

    def test_benign_environment_green(self):
        # All signals healthy → probability should be < 25
        inputs = _build_inputs(
            t10y3m=2.0, t10y2y=1.5, sahmrealtime=0.0,
            cfnai=0.5, nfci=-0.5, icsa_yoy=-10.0,
            hy_oas=280.0, lei_growth_6m=5.0,
        )
        out = run_recession_model(inputs)
        assert out.traffic_light == "green", (
            f"Benign env → expected green, got {out.traffic_light} (prob={out.probability})"
        )

    def test_stressed_environment_red(self):
        # All signals recessionary → probability should be ≥ 50
        inputs = _build_inputs(
            t10y3m=-1.5, t10y2y=-1.0, sahmrealtime=0.7,
            cfnai=-1.0, nfci=1.0, icsa_yoy=30.0,
            hy_oas=850.0, lei_growth_6m=-4.0,
        )
        out = run_recession_model(inputs)
        assert out.traffic_light == "red", (
            f"Stressed env → expected red, got {out.traffic_light} (prob={out.probability})"
        )

    def test_mixed_environment_yellow(self):
        # Moderate stress
        inputs = _build_inputs(
            t10y3m=-0.4, t10y2y=-0.3, sahmrealtime=0.25,
            cfnai=-0.2, nfci=0.1, icsa_yoy=8.0,
            hy_oas=420.0, lei_growth_6m=0.5,
        )
        out = run_recession_model(inputs)
        assert out.traffic_light in ("yellow", "red"), (
            f"Mixed signals produced unexpected light: {out.traffic_light} (prob={out.probability})"
        )

    def test_probability_in_valid_range(self):
        inputs = _build_inputs()
        out = run_recession_model(inputs)
        assert 0.0 <= out.probability <= 100.0

    def test_green_threshold_exactly_25(self):
        # Force a model output probability < 25 → green
        inputs = _build_inputs(
            t10y3m=3.0, t10y2y=2.0, sahmrealtime=0.0,
            cfnai=1.0, nfci=-1.0, icsa_yoy=-20.0,
            hy_oas=200.0, lei_growth_6m=8.0,
        )
        out = run_recession_model(inputs)
        assert out.probability < 25.0 and out.traffic_light == "green"

    def test_red_threshold_exactly_50(self):
        inputs = _build_inputs(
            t10y3m=-2.0, t10y2y=-1.5, sahmrealtime=0.8,
            cfnai=-1.5, nfci=1.5, icsa_yoy=40.0,
            hy_oas=900.0, lei_growth_6m=-5.0,
        )
        out = run_recession_model(inputs)
        assert out.probability >= 50.0 and out.traffic_light == "red"


class TestRunRecessionModelOutput:
    """Structural checks on RecessionModelOutput."""

    def test_returns_correct_type(self):
        out = run_recession_model(_build_inputs())
        assert isinstance(out, RecessionModelOutput)

    def test_eight_features_in_output(self):
        out = run_recession_model(_build_inputs())
        assert len(out.features) == 8

    def test_feature_contributions_sum_to_probability(self):
        out = run_recession_model(_build_inputs())
        total_contrib = sum(f.contribution for f in out.features)
        assert abs(total_contrib - out.probability) < 0.1, (
            f"Sum of contributions {total_contrib} != probability {out.probability}"
        )

    def test_feature_weights_match_config(self):
        out = run_recession_model(_build_inputs())
        config_weights = {f["series_id"]: f["weight"] for f in _FEATURES}
        for feat in out.features:
            expected = config_weights[feat.series_id]
            assert abs(feat.weight - expected) < 1e-9

    def test_stress_scores_in_unit_interval(self):
        out = run_recession_model(_build_inputs())
        for feat in out.features:
            assert 0.0 <= feat.stress_score <= 1.0, (
                f"{feat.name} stress_score={feat.stress_score}"
            )

    def test_data_as_of_is_set(self):
        out = run_recession_model(_build_inputs())
        assert out.data_as_of is not None

    def test_color_property(self):
        out = run_recession_model(_build_inputs())
        assert out.color.startswith("#")

    def test_emoji_property(self):
        out = run_recession_model(_build_inputs())
        assert out.emoji in ("🟢", "🟡", "🔴")


class TestRunRecessionModelGracefulDegradation:
    """Model must handle None values and missing optional series gracefully."""

    def test_none_usslind_falls_back_to_neutral(self):
        inputs = _build_inputs()
        # Remove USSLIND entirely to simulate fetch failure
        del inputs["USSLIND"]
        out = run_recession_model(inputs)
        assert isinstance(out, RecessionModelOutput)
        # LEI feature should show neutral stress (0.5)
        lei_feat = next(f for f in out.features if f.series_id == "USSLIND")
        assert abs(lei_feat.stress_score - 0.5) < 1e-9

    def test_none_t10y2y_falls_back_to_neutral(self):
        inputs = _build_inputs()
        del inputs["T10Y2Y"]
        out = run_recession_model(inputs)
        assert isinstance(out, RecessionModelOutput)
        t10y2y_feat = next(f for f in out.features if f.series_id == "T10Y2Y")
        assert abs(t10y2y_feat.stress_score - 0.5) < 1e-9

    def test_stale_data_flagged(self):
        inputs = _build_inputs()
        inputs["T10Y3M"]["is_stale"] = True
        inputs["T10Y3M"]["stale_message"] = "Last valid: 2026-01-01 (100d ago)"
        out = run_recession_model(inputs)
        assert out.has_stale_data
        assert "10Y–3M Treasury Spread" in out.stale_features

    def test_cfnai_empty_series_uses_neutral(self):
        inputs = _build_inputs()
        inputs["CFNAI"]["data"] = pd.Series(dtype=float)
        out = run_recession_model(inputs)
        cfnai_feat = next(f for f in out.features if f.series_id == "CFNAI")
        assert abs(cfnai_feat.stress_score - 0.5) < 1e-9

    def test_icsa_short_series_uses_neutral(self):
        inputs = _build_inputs()
        # Fewer than 56 weeks — compute_icsa_yoy returns None
        inputs["ICSA"]["data"] = pd.Series([220_000.0] * 10, dtype=float)
        out = run_recession_model(inputs)
        icsa_feat = next(f for f in out.features if f.series_id == "ICSA")
        assert abs(icsa_feat.stress_score - 0.5) < 1e-9


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 2 — data/fred_client.py derived calculations
# ──────────────────────────────────────────────────────────────────────────────

from data.fred_client import compute_lei_growth, compute_cfnai_signal, compute_icsa_yoy


class TestComputeLeiGrowth:
    """compute_lei_growth(series, months=6) → annualised % or None."""

    def _series(self, values):
        idx = pd.date_range(end=date.today(), periods=len(values), freq="MS")
        return pd.Series(values, index=idx, dtype=float)

    def test_flat_lei_returns_near_zero(self):
        s = self._series([100.0] * 12)
        result = compute_lei_growth(s)
        assert result is not None
        assert abs(result) < 0.5, f"Flat LEI should give ~0% growth, got {result}"

    def test_growing_lei_positive(self):
        # 3% over 6 months → annualised ≈ 6%
        vals = [100.0] * 6 + [103.0] * 6
        s = self._series(vals)
        result = compute_lei_growth(s)
        assert result is not None and result > 0

    def test_shrinking_lei_negative(self):
        vals = [100.0] * 6 + [97.0] * 6
        s = self._series(vals)
        result = compute_lei_growth(s)
        assert result is not None and result < 0

    def test_none_on_empty_series(self):
        assert compute_lei_growth(pd.Series(dtype=float)) is None

    def test_none_on_none_input(self):
        assert compute_lei_growth(None) is None

    def test_none_on_insufficient_data(self):
        # Needs at least months+1 monthly observations
        s = self._series([100.0] * 5)
        assert compute_lei_growth(s, months=6) is None

    def test_returns_float(self):
        s = self._series([100.0] * 12)
        result = compute_lei_growth(s)
        assert isinstance(result, float)

    def test_zero_past_value_returns_none(self):
        vals = [0.0] * 7 + [100.0]
        s = self._series(vals)
        # past value is 0 → division by zero guard → None
        assert compute_lei_growth(s) is None


class TestComputeCfnaiSignal:
    """compute_cfnai_signal(series, months=3) → trailing 3-month avg or None."""

    def _series(self, values):
        idx = pd.date_range(end=date.today(), periods=len(values), freq="MS")
        return pd.Series(values, index=idx, dtype=float)

    def test_positive_values_return_positive_avg(self):
        s = self._series([0.5, 0.4, 0.6])
        result = compute_cfnai_signal(s)
        assert result is not None and result > 0

    def test_negative_values_return_negative_avg(self):
        s = self._series([-0.8, -0.6, -0.7])
        result = compute_cfnai_signal(s)
        assert result is not None and result < 0

    def test_exact_average_correct(self):
        s = self._series([0.3, 0.6, 0.9])
        result = compute_cfnai_signal(s, months=3)
        assert result is not None
        assert abs(result - 0.6) < 0.01

    def test_none_on_empty_series(self):
        assert compute_cfnai_signal(pd.Series(dtype=float)) is None

    def test_none_on_none_input(self):
        assert compute_cfnai_signal(None) is None

    def test_none_on_insufficient_data(self):
        s = self._series([0.5, 0.5])   # 2 values, need 3
        assert compute_cfnai_signal(s, months=3) is None

    def test_returns_rounded_float(self):
        s = self._series([0.123456, 0.234567, 0.345678])
        result = compute_cfnai_signal(s)
        assert isinstance(result, float)
        # Should be rounded to 3dp
        assert result == round(result, 3)


class TestComputeIcsaYoy:
    """compute_icsa_yoy(series) → 4-wk avg YoY % or None."""

    def _weekly_series(self, current_avg, year_ago_avg, n_weeks=60):
        """60 weekly observations: first 56 at year_ago_avg, last 4 at current_avg."""
        vals = [year_ago_avg] * 56 + [current_avg] * 4
        idx = pd.date_range(end=date.today(), periods=n_weeks, freq="W")
        return pd.Series(vals[:n_weeks], index=idx, dtype=float)

    def test_rising_claims_positive_yoy(self):
        s = self._weekly_series(current_avg=300_000, year_ago_avg=220_000)
        result = compute_icsa_yoy(s)
        assert result is not None and result > 0

    def test_falling_claims_negative_yoy(self):
        s = self._weekly_series(current_avg=180_000, year_ago_avg=220_000)
        result = compute_icsa_yoy(s)
        assert result is not None and result < 0

    def test_flat_claims_near_zero(self):
        s = self._weekly_series(current_avg=220_000, year_ago_avg=220_000)
        result = compute_icsa_yoy(s)
        assert result is not None and abs(result) < 0.1

    def test_none_on_short_series(self):
        idx = pd.date_range(end=date.today(), periods=20, freq="W")
        s = pd.Series([220_000.0] * 20, index=idx)
        assert compute_icsa_yoy(s) is None

    def test_none_on_empty_series(self):
        assert compute_icsa_yoy(pd.Series(dtype=float)) is None

    def test_returns_float(self):
        s = self._weekly_series(220_000, 200_000)
        result = compute_icsa_yoy(s)
        assert isinstance(result, float)

    def test_yoy_magnitude_sensible(self):
        # 10% jump: current 242k vs prior 220k
        s = self._weekly_series(242_000, 220_000)
        result = compute_icsa_yoy(s)
        assert result is not None
        assert 8.0 < result < 12.0, f"Expected ~10% YoY, got {result}"


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 3 — components/cycle_engine.py (pure scoring functions)
# ──────────────────────────────────────────────────────────────────────────────

from components.cycle_engine import (
    _score_yield_curve,
    _score_unemployment,
    _score_industrial_production,
    _score_cpi,
    _score_initial_claims,
    _confidence_label,
    PHASES,
)


def _make_daily(value, days=400):
    idx = pd.date_range(end=date.today(), periods=days, freq="D")
    return pd.Series([value] * days, index=idx, dtype=float)


def _make_monthly(value, months=36):
    idx = pd.date_range(end=date.today(), periods=months, freq="MS")
    return pd.Series([value] * months, index=idx, dtype=float)


def _make_weekly(value, weeks=60):
    idx = pd.date_range(end=date.today(), periods=weeks, freq="W")
    return pd.Series([value] * weeks, index=idx, dtype=float)


class TestCycleEngineContracts:
    """Every scoring function must return a SignalReading with correct structure."""

    def _check_reading(self, reading):
        assert reading.value is not None or reading.value is None  # type existence
        assert isinstance(reading.formatted, str)
        assert isinstance(reading.trend, str)
        assert isinstance(reading.scores, dict)
        assert set(reading.scores.keys()) == set(PHASES)
        for v in reading.scores.values():
            assert v >= 0.0, f"Negative score: {v}"

    def test_yield_curve_contract(self):
        self._check_reading(_score_yield_curve(_make_daily(0.5)))

    def test_unemployment_contract(self):
        self._check_reading(_score_unemployment(_make_monthly(4.0)))

    def test_industrial_production_contract(self):
        self._check_reading(_score_industrial_production(_make_monthly(105.0)))

    def test_cpi_contract(self):
        self._check_reading(_score_cpi(_make_monthly(315.0)))

    def test_initial_claims_contract(self):
        self._check_reading(_score_initial_claims(_make_weekly(210_000)))

    def test_empty_series_returns_safe_fallback(self):
        empty = pd.Series(dtype=float)
        for fn in [_score_yield_curve, _score_unemployment,
                   _score_industrial_production, _score_cpi, _score_initial_claims]:
            r = fn(empty)
            assert r.value is None
            assert r.formatted == "N/A"
            assert all(v == 0.0 for v in r.scores.values())


class TestScoreYieldCurve:
    def test_deep_inversion_signals_contraction(self):
        r = _score_yield_curve(_make_daily(-1.5))
        assert r.implied_phase == "Contraction"
        assert r.scores["Contraction"] > r.scores["Mid / Expansion"]

    def test_steep_positive_signals_early_recovery(self):
        r = _score_yield_curve(_make_daily(2.0))
        assert r.implied_phase == "Early / Recovery"
        assert r.scores["Early / Recovery"] > 0

    def test_mildly_positive_signals_mid_expansion(self):
        r = _score_yield_curve(_make_daily(0.6))
        assert r.implied_phase == "Mid / Expansion"

    def test_formatted_includes_percent(self):
        r = _score_yield_curve(_make_daily(0.5))
        assert "%" in r.formatted


class TestScoreUnemployment:
    def test_rapidly_rising_unemployment_contraction(self):
        # Build a series where unemployment rises 1.5pp over 6 months
        idx = pd.date_range(end=date.today(), periods=24, freq="MS")
        vals = [4.0] * 18 + [5.5] * 6   # +1.5pp in 6 months
        s = pd.Series(vals, index=idx)
        r = _score_unemployment(s)
        assert r.implied_phase == "Contraction"

    def test_stable_low_unemployment_mid_expansion(self):
        s = _make_monthly(3.8, months=30)
        r = _score_unemployment(s)
        assert r.implied_phase in ("Mid / Expansion", "Late / Peak")

    def test_formatted_includes_percent(self):
        r = _score_unemployment(_make_monthly(4.5))
        assert "%" in r.formatted


class TestScoreIndustrialProduction:
    def test_negative_yoy_contraction_signal(self):
        # Falling IP: last 12 months declining from 110 to 105
        idx = pd.date_range(end=date.today(), periods=36, freq="MS")
        vals = [110.0] * 23 + [105.0] * 13
        s = pd.Series(vals, index=idx)
        r = _score_industrial_production(s)
        assert r.implied_phase in ("Contraction", "Late / Peak")

    def test_strong_positive_yoy_mid_expansion(self):
        idx = pd.date_range(end=date.today(), periods=24, freq="MS")
        vals = [100.0] * 12 + [106.0] * 12   # +6% YoY
        s = pd.Series(vals, index=idx)
        r = _score_industrial_production(s)
        assert r.implied_phase == "Mid / Expansion"


class TestScoreCpi:
    def test_high_rising_inflation_late_peak(self):
        idx = pd.date_range(end=date.today(), periods=24, freq="MS")
        # Rising from 300 to 325 = > 5% YoY
        vals = [300.0] * 12 + [325.0] * 12
        s = pd.Series(vals, index=idx)
        r = _score_cpi(s)
        assert r.implied_phase == "Late / Peak"

    def test_moderate_inflation_mid_expansion(self):
        idx = pd.date_range(end=date.today(), periods=24, freq="MS")
        # ~3% YoY
        vals = [300.0] * 12 + [309.0] * 12
        s = pd.Series(vals, index=idx)
        r = _score_cpi(s)
        assert r.implied_phase in ("Mid / Expansion", "Late / Peak")


class TestScoreInitialClaims:
    def test_very_high_claims_contraction(self):
        r = _score_initial_claims(_make_weekly(400_000))
        assert r.implied_phase == "Contraction"

    def test_low_stable_claims_mid_expansion(self):
        r = _score_initial_claims(_make_weekly(200_000))
        assert r.implied_phase == "Mid / Expansion"

    def test_formatted_has_comma_separator(self):
        r = _score_initial_claims(_make_weekly(210_000))
        assert "," in r.formatted   # e.g. "210,000"


class TestConfidenceLabel:
    def test_high_confidence_75_plus(self):
        assert _confidence_label(75) == "High"
        assert _confidence_label(100) == "High"

    def test_moderate_confidence_50_to_74(self):
        assert _confidence_label(50) == "Moderate"
        assert _confidence_label(74) == "Moderate"

    def test_low_confidence_30_to_49(self):
        assert _confidence_label(30) == "Low"
        assert _confidence_label(49) == "Low"

    def test_uncertain_below_30(self):
        assert _confidence_label(0) == "Uncertain"
        assert _confidence_label(29) == "Uncertain"
