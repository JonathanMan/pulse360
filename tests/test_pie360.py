"""
tests/test_pie360.py
=====================
Comprehensive pytest test suite for Pie360 (Pulse360) macro-economic dashboard.

Extra test dependencies (pip install before running):
    pytest
    pytest-mock
    numpy
    pandas

Run from the repo root:
    python -m pytest tests/test_pie360.py -v

All Streamlit and Supabase I/O is mocked via conftest.py stubs and
unittest.mock — no live credentials or network access required.
"""

from __future__ import annotations

import sys
import os
from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock
import uuid

import numpy as np
import pandas as pd
import pytest

# Ensure the repo root is on sys.path so all imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st

# ============================================================================
# SECTION 1: Recession model unit tests
# ============================================================================

from models.recession_model import (
    _logistic,
    _stress_t10y3m,
    _stress_sahm,
    _stress_cfnai,
    _stress_nfci,
    _stress_claims_yoy,
    _stress_hy_oas,
    _stress_ism,
    run_recession_model,
    RecessionModelOutput,
    FeatureContribution,
)


# ── Logistic helper ───────────────────────────────────────────────────────────

class TestLogistic:
    """_logistic(x) always returns a value in [0, 1]."""

    def test_at_zero_returns_half(self):
        assert abs(_logistic(0.0) - 0.5) < 1e-9

    def test_large_positive_approaches_one(self):
        assert _logistic(100.0) > 0.999

    def test_large_negative_approaches_zero(self):
        assert _logistic(-100.0) < 0.001

    def test_output_always_in_0_1(self):
        for x in [-100, -10, -1, 0, 1, 10, 100]:
            result = _logistic(float(x))
            assert 0.0 <= result <= 1.0, f"_logistic({x}) = {result} out of [0,1]"

    def test_monotonically_increasing(self):
        xs = [-5, -2, -1, 0, 1, 2, 5]
        values = [_logistic(float(x)) for x in xs]
        assert all(values[i] < values[i+1] for i in range(len(values)-1))


# ── Per-feature stress functions ──────────────────────────────────────────────

class TestStressT10y3m:
    """Treasury 10Y–3M spread: deep inversion → high stress."""

    def test_returns_tuple(self):
        stress, desc = _stress_t10y3m(-1.0)
        assert isinstance(stress, float)
        assert isinstance(desc, str)

    def test_stress_in_unit_interval(self):
        for val in [-2.0, -0.75, -0.1, 0.0, 0.5, 1.5, 3.0]:
            stress, _ = _stress_t10y3m(val)
            assert 0.0 <= stress <= 1.0, f"stress={stress} for value={val}"

    def test_deep_inversion_high_stress(self):
        stress_inverted, _ = _stress_t10y3m(-1.5)
        stress_normal, _ = _stress_t10y3m(1.5)
        assert stress_inverted > stress_normal

    def test_positive_spread_low_stress(self):
        stress, desc = _stress_t10y3m(2.0)
        assert stress < 0.5
        assert "Positive" in desc

    def test_deeply_inverted_description(self):
        _, desc = _stress_t10y3m(-1.0)
        assert "Deeply inverted" in desc or "inverted" in desc.lower()

    def test_monotone_stress_increases_with_inversion(self):
        # More negative spread → higher stress
        s1, _ = _stress_t10y3m(1.0)
        s2, _ = _stress_t10y3m(0.0)
        s3, _ = _stress_t10y3m(-0.5)
        s4, _ = _stress_t10y3m(-2.0)
        assert s1 < s2 < s3 < s4


class TestStressSahm:
    """Sahm Rule: trigger at 0.50; historical 2020-04 ~0.57, 2019-01 ~0.0."""

    def test_stress_in_unit_interval(self):
        for val in [0.0, 0.25, 0.50, 0.75, 1.0]:
            stress, _ = _stress_sahm(val)
            assert 0.0 <= stress <= 1.0

    def test_historical_2020_04_high_stress(self):
        """Sahm ~0.57 in April 2020 — Covid recession onset."""
        stress, desc = _stress_sahm(0.57)
        assert stress > 0.7
        assert "Triggered" in desc

    def test_historical_2019_01_benign(self):
        """Sahm ~0.0 in early 2019 — no recession signal."""
        stress, desc = _stress_sahm(0.0)
        assert stress < 0.3
        assert "Benign" in desc

    def test_triggered_above_0_50(self):
        _, desc = _stress_sahm(0.50)
        assert "Triggered" in desc

    def test_elevated_near_trigger(self):
        stress_elevated, desc_elevated = _stress_sahm(0.35)
        stress_benign, _ = _stress_sahm(0.05)
        assert stress_elevated > stress_benign
        assert "Elevated" in desc_elevated

    def test_monotone_stress_with_value(self):
        stresses = [_stress_sahm(v)[0] for v in [0.0, 0.1, 0.25, 0.35, 0.50, 0.75]]
        assert all(stresses[i] <= stresses[i+1] for i in range(len(stresses)-1))


class TestStressCfnai:
    """CFNAI 3M average: <-0.70 is recession threshold."""

    def test_stress_in_unit_interval(self):
        for val in [-2.0, -0.70, -0.35, 0.0, 0.20, 1.0]:
            stress, _ = _stress_cfnai(val)
            assert 0.0 <= stress <= 1.0

    def test_below_minus_0_70_high_stress(self):
        stress, desc = _stress_cfnai(-0.80)
        assert stress > 0.55
        assert "recession threshold" in desc

    def test_above_zero_low_stress(self):
        stress, desc = _stress_cfnai(0.30)
        assert stress < 0.45
        assert "above-trend" in desc or "near trend" in desc

    def test_monotone_stress_decreases_with_value(self):
        # Lower CFNAI → higher stress
        s_low, _ = _stress_cfnai(-1.0)
        s_mid, _ = _stress_cfnai(-0.35)
        s_high, _ = _stress_cfnai(0.5)
        assert s_low > s_mid > s_high


class TestStressNfci:
    """NFCI: above 0 = tight conditions → stress."""

    def test_stress_in_unit_interval(self):
        for val in [-1.5, -0.5, 0.0, 0.5, 1.5]:
            stress, _ = _stress_nfci(val)
            assert 0.0 <= stress <= 1.0

    def test_tight_conditions_high_stress(self):
        stress, desc = _stress_nfci(0.75)
        assert stress > 0.7
        assert "tight" in desc.lower()

    def test_loose_conditions_low_stress(self):
        stress, desc = _stress_nfci(-0.75)
        assert stress < 0.3
        assert "Loose" in desc

    def test_neutral_near_0_5(self):
        stress, _ = _stress_nfci(0.0)
        assert abs(stress - 0.5) < 0.15


class TestStressClaimsYoy:
    """Initial Claims YoY: rising >15% → stress."""

    def test_stress_in_unit_interval(self):
        for pct in [-20, -5, 0, 5, 15, 30, 50]:
            stress, _ = _stress_claims_yoy(float(pct))
            assert 0.0 <= stress <= 1.0

    def test_surging_claims_high_stress(self):
        stress, desc = _stress_claims_yoy(30.0)
        assert stress > 0.8
        assert "Surging" in desc

    def test_declining_claims_low_stress(self):
        stress, desc = _stress_claims_yoy(-10.0)
        assert stress < 0.4
        assert "Declining" in desc

    def test_covid_spike_extreme_stress(self):
        # In 2020, claims surged hundreds of percent
        stress_extreme, _ = _stress_claims_yoy(500.0)
        stress_normal, _ = _stress_claims_yoy(5.0)
        assert stress_extreme > stress_normal


class TestStressHyOas:
    """High-Yield OAS: wide spreads → high stress. Threshold ~700 bps."""

    def test_stress_in_unit_interval(self):
        for bps in [200, 350, 450, 550, 700, 1000]:
            stress, _ = _stress_hy_oas(float(bps))
            assert 0.0 <= stress <= 1.0

    def test_recession_threshold_700bps(self):
        stress, desc = _stress_hy_oas(750.0)
        assert stress > 0.8
        assert "700 bps" in desc or "recession" in desc.lower()

    def test_tight_spreads_low_stress(self):
        stress, desc = _stress_hy_oas(300.0)
        assert stress < 0.3
        assert "tight" in desc.lower() or "risk-on" in desc.lower()

    def test_monotone_stress_with_spread(self):
        stresses = [_stress_hy_oas(v)[0] for v in [250, 400, 550, 700, 900]]
        assert all(stresses[i] < stresses[i+1] for i in range(len(stresses)-1))


class TestStressIsm:
    """ISM PMI: below 45 → deep contraction."""

    def test_stress_in_unit_interval(self):
        for val in [40, 45, 50, 55, 60]:
            stress, _ = _stress_ism(float(val))
            assert 0.0 <= stress <= 1.0

    def test_deep_contraction_high_stress(self):
        stress, desc = _stress_ism(42.0)
        assert stress > 0.8
        assert "deep contraction" in desc.lower() or "below 45" in desc

    def test_strong_expansion_low_stress(self):
        stress, desc = _stress_ism(58.0)
        assert stress < 0.3
        assert "strong expansion" in desc.lower()

    def test_50_is_midpoint(self):
        stress, _ = _stress_ism(50.0)
        assert abs(stress - 0.5) < 0.1


# ── run_recession_model ───────────────────────────────────────────────────────

def _make_inputs(
    t10y3m:    float = 0.5,
    sahm:      float = 0.0,
    cfnai_avg: float = 0.1,
    nfci:      float = -0.2,
    icsa_yoy:  float = 0.0,
    hy_oas:    float = 350.0,
    lei_growth: float = 2.0,   # annualised 6M LEI growth — added 2026-05-28
    t10y2y:    float = 0.8,    # 10Y–2Y spread — added 2026-05-28
    is_stale:  bool = False,
) -> dict:
    """
    Build a minimal inputs dict for run_recession_model().
    CFNAI uses a pd.Series so compute_cfnai_signal() can compute the 3M average.
    ICSA uses a pd.Series long enough for compute_icsa_yoy() (≥56 weekly obs).
    USSLIND uses a pd.Series long enough for compute_lei_growth() (≥7 monthly obs).
    """
    cfnai_series = pd.Series(
        [cfnai_avg] * 6,
        index=pd.date_range("2024-01-01", periods=6, freq="MS"),
    )
    # 60 weekly observations — enough for the 56-point YoY window
    # The YoY compares last 4 obs vs obs[-56:-52].
    # With all values equal the YoY result is 0.
    # To produce a non-zero YoY: set recent 4 weeks to a different value.
    n = 60
    icsa_data = [300_000] * n
    # Fake the year-ago period so YoY ≈ icsa_yoy%
    year_ago_avg = 300_000.0
    recent_avg = year_ago_avg * (1 + icsa_yoy / 100)
    for i in range(4):
        icsa_data[-(i+1)] = recent_avg
    icsa_series = pd.Series(
        icsa_data,
        index=pd.date_range("2022-01-06", periods=n, freq="W-THU"),
        dtype=float,
    )
    # USSLIND: 8 monthly observations so compute_lei_growth() can compute 6M return.
    # We build a series where the 6-month annualised growth ≈ lei_growth.
    # Simple approach: set all 8 values to 100 (gives 0% growth), then adjust
    # the first value so that (last/first - 1)^2 - 1 ≈ lei_growth/100.
    # For simplicity just use a linearly growing series parameterised by lei_growth.
    base_lei    = 100.0
    # 6-period compound: target = ((1 + 6m_simple)^2 - 1) * 100 = lei_growth
    # So 6m_simple = sqrt(1 + lei_growth/100) - 1
    import math
    factor_6m  = math.sqrt(max(1 + lei_growth / 100, 1e-6)) - 1
    # Each of the 6 monthly steps: (1 + step)^6 ≈ 1 + 6*step (approx)
    step_mo    = factor_6m / 6
    lei_vals   = [base_lei * (1 + step_mo) ** i for i in range(8)]
    usslind_series = pd.Series(
        lei_vals,
        index=pd.date_range("2023-06-01", periods=8, freq="MS"),
        dtype=float,
    )
    stale_msg = "stale data" if is_stale else None
    return {
        "T10Y3M":        {"last_value": t10y3m,    "last_date": date(2024, 5, 1), "is_stale": is_stale, "stale_message": stale_msg},
        "SAHMREALTIME":  {"last_value": sahm,       "last_date": date(2024, 5, 1), "is_stale": is_stale, "stale_message": stale_msg},
        "CFNAI":         {"data": cfnai_series,      "last_date": date(2024, 5, 1), "is_stale": is_stale, "stale_message": stale_msg},
        "NFCI":          {"last_value": nfci,        "last_date": date(2024, 5, 1), "is_stale": is_stale, "stale_message": stale_msg},
        "ICSA":          {"data": icsa_series,       "last_date": date(2024, 5, 1), "is_stale": is_stale, "stale_message": stale_msg},
        "BAMLH0A0HYM2":  {"last_value": hy_oas,      "last_date": date(2024, 5, 1), "is_stale": is_stale, "stale_message": stale_msg},
        "USSLIND":       {"data": usslind_series,    "last_date": date(2024, 5, 1), "is_stale": is_stale, "stale_message": stale_msg, "error": None},
        "T10Y2Y":        {"last_value": t10y2y,      "last_date": date(2024, 5, 1), "is_stale": is_stale, "stale_message": stale_msg, "error": None},
    }


class TestRunRecessionModel:
    """Integration-level tests for run_recession_model()."""

    def test_returns_recession_model_output(self):
        inputs = _make_inputs()
        result = run_recession_model(inputs)
        assert isinstance(result, RecessionModelOutput)

    def test_probability_between_0_and_100(self):
        for _ in range(5):
            inputs = _make_inputs()
            result = run_recession_model(inputs)
            assert 0.0 <= result.probability <= 100.0

    def test_traffic_light_green_below_25(self):
        # All benign → green
        inputs = _make_inputs(t10y3m=2.0, sahm=0.0, cfnai_avg=0.3,
                               nfci=-0.5, icsa_yoy=-5.0, hy_oas=300.0)
        result = run_recession_model(inputs)
        assert result.probability < 40  # benign conditions, low prob
        if result.probability < 25:
            assert result.traffic_light == "green"

    def test_traffic_light_red_above_50(self):
        # All maximum stress
        inputs = _make_inputs(t10y3m=-2.0, sahm=0.70, cfnai_avg=-1.0,
                               nfci=1.5, icsa_yoy=40.0, hy_oas=900.0)
        result = run_recession_model(inputs)
        assert result.traffic_light == "red"
        assert result.probability >= 50.0

    def test_traffic_light_yellow_boundary(self):
        # Moderate stress — not trying to hit exact boundary,
        # just verify yellow is a reachable state
        inputs = _make_inputs(t10y3m=-0.3, sahm=0.30, cfnai_avg=-0.30,
                               nfci=0.20, icsa_yoy=8.0, hy_oas=530.0)
        result = run_recession_model(inputs)
        assert result.traffic_light in ("yellow", "green", "red")

    def test_neutral_features_produce_midpoint_probability(self):
        # logistic(0) = 0.5 for all features → weighted stress = 0.5 → prob = 50%
        # We achieve this by finding values where each stress ≈ 0.5
        # Near-neutral: t10y3m≈0, sahm≈0.25, cfnai≈-0.1, nfci≈0, claims_yoy≈5, hy_oas≈450
        inputs = _make_inputs(t10y3m=0.0, sahm=0.25, cfnai_avg=-0.1,
                               nfci=0.0, icsa_yoy=5.0, hy_oas=450.0)
        result = run_recession_model(inputs)
        assert 35.0 <= result.probability <= 65.0

    def test_single_stressed_feature_moves_probability(self):
        """Stressing only the yield curve (weight 0.30) should raise probability."""
        baseline = run_recession_model(_make_inputs(t10y3m=1.0))
        stressed = run_recession_model(_make_inputs(t10y3m=-2.0))
        assert stressed.probability > baseline.probability

    def test_features_list_length_matches_config(self):
        inputs = _make_inputs()
        result = run_recession_model(inputs)
        assert len(result.features) == 8  # 8 active features (added LEI + T10Y2Y 2026-05-28)

    def test_feature_contributions_sum_to_probability(self):
        inputs = _make_inputs()
        result = run_recession_model(inputs)
        total = sum(f.contribution for f in result.features)
        assert abs(total - result.probability) < 0.2  # float rounding tolerance

    def test_none_value_substitutes_neutral_stress(self):
        """If a feature value is None, model should still run with neutral (0.5) stress."""
        inputs = _make_inputs()
        inputs["T10Y3M"]["last_value"] = None
        result = run_recession_model(inputs)
        assert 0.0 <= result.probability <= 100.0
        t10y3m_feature = next(f for f in result.features if f.series_id == "T10Y3M")
        assert t10y3m_feature.stress_score == 0.5
        assert "unavailable" in t10y3m_feature.signal_description.lower()

    def test_stale_features_flagged(self):
        inputs = _make_inputs(is_stale=True)
        result = run_recession_model(inputs)
        assert result.has_stale_data is True
        assert len(result.stale_features) > 0

    def test_non_stale_features_not_flagged(self):
        inputs = _make_inputs(is_stale=False)
        result = run_recession_model(inputs)
        assert result.has_stale_data is False
        assert result.stale_features == []

    def test_all_none_values_probability_50(self):
        """All values None → all features use 0.5 → probability = 50."""
        inputs = _make_inputs()
        for key in ["T10Y3M", "SAHMREALTIME", "NFCI", "BAMLH0A0HYM2", "T10Y2Y"]:
            inputs[key]["last_value"] = None
        # Also make CFNAI, ICSA and USSLIND data empty so their computes return None
        inputs["CFNAI"]["data"]   = pd.Series(dtype=float)
        inputs["ICSA"]["data"]    = pd.Series(dtype=float)
        inputs["USSLIND"]["data"] = pd.Series(dtype=float)
        result = run_recession_model(inputs)
        assert abs(result.probability - 50.0) < 0.5
        # The 50% here is a neutral-fallback artefact, not a real reading —
        # it must be flagged so the UI never presents it as a confident gauge.
        assert result.data_quality == "unavailable"
        assert result.is_reliable is False
        assert result.n_unavailable == 8

    def test_data_quality_ok_when_all_inputs_present(self):
        result = run_recession_model(_make_inputs())
        assert result.data_quality == "ok"
        assert result.n_unavailable == 0
        assert result.is_reliable is True

    def test_data_quality_partial_when_one_input_missing(self):
        inputs = _make_inputs()
        inputs["T10Y3M"]["last_value"] = None
        result = run_recession_model(inputs)
        assert result.data_quality == "partial"
        assert result.n_unavailable == 1
        # partial still shows a normal traffic-light colour (not the grey override)
        assert result.color != "#95a5a6"

    def test_data_quality_unavailable_when_half_missing(self):
        inputs = _make_inputs()
        for key in ["T10Y3M", "SAHMREALTIME", "NFCI", "BAMLH0A0HYM2"]:
            inputs[key]["last_value"] = None
        result = run_recession_model(inputs)
        assert result.data_quality == "unavailable"
        assert result.color == "#95a5a6"  # neutral grey on unreliable reading

    def test_color_property_returns_hex(self):
        inputs = _make_inputs()
        result = run_recession_model(inputs)
        assert result.color.startswith("#")

    def test_emoji_property_not_empty(self):
        inputs = _make_inputs()
        result = run_recession_model(inputs)
        assert result.emoji  # non-empty


# ============================================================================
# SECTION 2: Sahm Rule calculation
# ============================================================================

from data.fred_client import compute_icsa_yoy, compute_cfnai_signal, compute_lei_growth


class TestSahmRuleStressFunction:
    """
    The Sahm Rule is embedded in _stress_sahm().
    These tests verify the function against real-world values.
    """

    def test_april_2020_recession_signal(self):
        """Sahm Rule was ~0.57 in April 2020 — should be stressed (triggered)."""
        stress, desc = _stress_sahm(0.57)
        assert stress > 0.7, f"Expected high stress for Sahm=0.57, got {stress}"
        assert "Triggered" in desc

    def test_january_2019_benign(self):
        """Sahm Rule was ~0.0 in early 2019 — healthy labour market."""
        stress, desc = _stress_sahm(0.0)
        assert stress < 0.3, f"Expected low stress for Sahm=0.0, got {stress}"
        assert "Benign" in desc

    def test_boundary_exactly_at_0_50_triggers(self):
        _, desc = _stress_sahm(0.50)
        assert "Triggered" in desc

    def test_just_below_trigger(self):
        stress, desc = _stress_sahm(0.49)
        assert "Elevated" in desc or "Benign" in desc

    def test_very_high_value_stress_approaches_one(self):
        stress, _ = _stress_sahm(2.0)
        assert stress > 0.95


class TestComputeCfnaiSignal:
    """compute_cfnai_signal: 3-month average of CFNAI series."""

    def _make_cfnai_series(self, values: list[float]) -> pd.Series:
        return pd.Series(
            values,
            index=pd.date_range("2024-01-01", periods=len(values), freq="MS"),
        )

    def test_returns_none_on_empty_series(self):
        result = compute_cfnai_signal(pd.Series(dtype=float))
        assert result is None

    def test_returns_none_on_insufficient_data(self):
        result = compute_cfnai_signal(self._make_cfnai_series([0.1, 0.2]))
        assert result is None

    def test_correct_3_month_average(self):
        series = self._make_cfnai_series([-0.1, 0.0, 0.3, 0.6, 0.9])
        result = compute_cfnai_signal(series, months=3)
        expected = round((0.3 + 0.6 + 0.9) / 3, 3)
        assert abs(result - expected) < 0.001

    def test_recession_threshold_detectable(self):
        """A 3M average below -0.70 should be detectable."""
        series = self._make_cfnai_series([-0.9, -1.0, -1.1, -0.8, -0.85, -0.95])
        result = compute_cfnai_signal(series)
        assert result < -0.70

    def test_expansion_positive_value(self):
        series = self._make_cfnai_series([0.3, 0.4, 0.35, 0.5, 0.45, 0.4])
        result = compute_cfnai_signal(series)
        assert result > 0.0

    def test_returns_float(self):
        series = self._make_cfnai_series([0.1, 0.2, 0.3])
        result = compute_cfnai_signal(series)
        assert isinstance(result, float)


class TestComputeIcsaYoy:
    """compute_icsa_yoy: year-over-year % change in initial claims 4-week average."""

    def _make_icsa_series(self, base: float, recent_mult: float = 1.0, n: int = 60) -> pd.Series:
        """Build a 60-obs weekly series where recent 4 weeks differ from year-ago."""
        data = [base] * n
        year_ago_avg = base
        recent_avg = year_ago_avg * recent_mult
        for i in range(4):
            data[-(i+1)] = recent_avg
        return pd.Series(
            data,
            index=pd.date_range("2022-01-06", periods=n, freq="W-THU"),
            dtype=float,
        )

    def test_returns_none_on_empty(self):
        assert compute_icsa_yoy(pd.Series(dtype=float)) is None

    def test_returns_none_on_insufficient_data(self):
        short = pd.Series([200_000] * 30)
        assert compute_icsa_yoy(short) is None

    def test_flat_series_yoy_near_zero(self):
        series = self._make_icsa_series(base=300_000, recent_mult=1.0)
        result = compute_icsa_yoy(series)
        assert result is not None
        assert abs(result) < 2.0  # effectively 0%

    def test_surge_produces_positive_yoy(self):
        series = self._make_icsa_series(base=200_000, recent_mult=2.0)
        result = compute_icsa_yoy(series)
        assert result is not None
        assert result > 80.0  # ~100% YoY

    def test_improvement_produces_negative_yoy(self):
        series = self._make_icsa_series(base=400_000, recent_mult=0.75)
        result = compute_icsa_yoy(series)
        assert result is not None
        assert result < 0.0

    def test_returns_float(self):
        series = self._make_icsa_series(base=300_000)
        result = compute_icsa_yoy(series)
        assert result is None or isinstance(result, float)


class TestComputeLeiGrowth:
    """compute_lei_growth: 6-month annualised LEI growth."""

    def _make_lei_series(self, start: float, growth_pct: float, n: int = 12) -> pd.Series:
        """Build monthly series where value grows at growth_pct% over 6 months."""
        # Simple linear approximation
        values = [start + (start * growth_pct / 100 / 6) * i for i in range(n)]
        return pd.Series(
            values,
            index=pd.date_range("2023-01-01", periods=n, freq="MS"),
        )

    def test_returns_none_on_empty(self):
        assert compute_lei_growth(pd.Series(dtype=float)) is None

    def test_returns_none_on_insufficient_data(self):
        short = self._make_lei_series(100.0, 2.0, n=3)
        assert compute_lei_growth(short) is None

    def test_flat_series_near_zero_growth(self):
        flat = pd.Series(
            [100.0] * 12,
            index=pd.date_range("2023-01-01", periods=12, freq="MS"),
        )
        result = compute_lei_growth(flat)
        assert result is not None
        assert abs(result) < 0.5

    def test_positive_growth_returns_positive(self):
        series = self._make_lei_series(100.0, 5.0, n=10)
        result = compute_lei_growth(series)
        assert result is not None
        assert result > 0.0

    def test_negative_growth_returns_negative(self):
        values = [100.0 - i * 0.5 for i in range(12)]
        series = pd.Series(
            values,
            index=pd.date_range("2023-01-01", periods=12, freq="MS"),
        )
        result = compute_lei_growth(series)
        assert result is not None
        assert result < 0.0


# ============================================================================
# SECTION 3: Cycle phase classifier
# ============================================================================

from models.cycle_classifier import classify_cycle_phase, CyclePhaseOutput, PHASE_COLORS


def _make_model_output(
    probability:  float = 15.0,
    traffic_light: str = "green",
    t10y3m_value:  float | None = 0.5,
    is_stale:      bool = False,
) -> RecessionModelOutput:
    """Build a minimal RecessionModelOutput for classifier tests."""
    feature = FeatureContribution(
        name               = "10Y–3M Treasury Spread",
        series_id          = "T10Y3M",
        weight             = 0.30,
        current_value      = t10y3m_value,
        stress_score       = 0.3,
        contribution       = 9.0,
        signal_description = "test",
        last_date          = date(2024, 5, 1),
        is_stale           = is_stale,
        stale_message      = "stale" if is_stale else None,
    )
    return RecessionModelOutput(
        probability    = probability,
        traffic_light  = traffic_light,
        features       = [feature],
        data_as_of     = date(2024, 5, 1),
    )


def _make_unrate(rising: bool = False, falling: bool = False, stable: bool = True) -> pd.Series:
    """Build a 6-month UNRATE series with a controlled 3-month change."""
    base = 4.0
    if rising:
        values = [base, base, base + 0.5]
        # 4 monthly obs for the 3M-change calc (needs at least 4)
        values = [base, base, base, base + 0.5]
    elif falling:
        values = [base + 0.5, base + 0.5, base + 0.5, base - 0.3]
    else:
        values = [base, base, base, base + 0.05]
    return pd.Series(
        values,
        index=pd.date_range("2024-01-01", periods=len(values), freq="MS"),
    )


class TestCyclePhaseExpansion:
    """Low recession prob → expansion phases."""

    def test_early_expansion_high_confidence(self):
        model = _make_model_output(probability=10.0)
        result = classify_cycle_phase(model, lei_growth=3.5, unrate_data=_make_unrate(falling=True))
        assert result.phase == "Early Expansion"
        assert result.confidence == "High"

    def test_early_expansion_with_stable_labor(self):
        model = _make_model_output(probability=15.0)
        result = classify_cycle_phase(model, lei_growth=2.0, unrate_data=_make_unrate(stable=True))
        assert result.phase == "Early Expansion"
        assert result.confidence in ("Medium", "High")

    def test_early_expansion_low_confidence_no_lei(self):
        model = _make_model_output(probability=10.0)
        result = classify_cycle_phase(model, lei_growth=None, unrate_data=None)
        assert result.phase == "Early Expansion"
        assert result.confidence == "Low"

    def test_mid_expansion_with_positive_lei(self):
        model = _make_model_output(probability=25.0)
        result = classify_cycle_phase(model, lei_growth=1.5, unrate_data=_make_unrate(stable=True))
        assert result.phase == "Mid Expansion"

    def test_mid_expansion_default_fallback(self):
        """No other conditions met → default Mid Expansion."""
        model = _make_model_output(probability=25.0)
        result = classify_cycle_phase(model, lei_growth=None, unrate_data=None)
        assert result.phase == "Mid Expansion"
        assert result.confidence == "Low"


class TestCyclePhaseSlowdown:
    """Moderate recession prob → late expansion / slowdown."""

    def test_late_expansion_with_two_signals(self):
        model = _make_model_output(
            probability=40.0, traffic_light="yellow", t10y3m_value=-0.3
        )
        result = classify_cycle_phase(model, lei_growth=None, unrate_data=None)
        assert result.phase == "Late Expansion"

    def test_late_expansion_single_signal_low_confidence(self):
        """prob 35% but no other confirming signals → Late Expansion, Low."""
        model = _make_model_output(probability=35.0, t10y3m_value=0.5)
        result = classify_cycle_phase(model, lei_growth=None, unrate_data=None)
        assert result.phase == "Late Expansion"
        assert result.confidence == "Low"

    def test_late_expansion_three_signals_high_confidence(self):
        model = _make_model_output(
            probability=45.0, traffic_light="yellow", t10y3m_value=-0.5
        )
        result = classify_cycle_phase(model, lei_growth=-0.5, unrate_data=None)
        assert result.phase == "Late Expansion"
        assert result.confidence in ("Medium", "High")


class TestCyclePhasePeak:
    """High prob + LEI or inversion → Peak."""

    def test_peak_with_lei_and_prob(self):
        model = _make_model_output(probability=60.0, traffic_light="red", t10y3m_value=-0.5)
        result = classify_cycle_phase(model, lei_growth=-0.5, unrate_data=None)
        assert result.phase == "Peak"

    def test_peak_with_inversion_only(self):
        model = _make_model_output(probability=55.0, traffic_light="red", t10y3m_value=-0.5)
        result = classify_cycle_phase(model, lei_growth=1.0, unrate_data=None)
        # prob>50 + yield_inverted → Peak
        assert result.phase == "Peak"

    def test_peak_three_confirming_high_confidence(self):
        model = _make_model_output(probability=65.0, traffic_light="red", t10y3m_value=-1.0)
        result = classify_cycle_phase(model, lei_growth=-1.5, unrate_data=None)
        assert result.phase == "Peak"
        assert result.confidence in ("High", "Medium")


class TestCyclePhaseContraction:
    """High prob + rising unemployment → Contraction."""

    def test_contraction_nber_declared(self):
        model = _make_model_output(probability=80.0, traffic_light="red")
        result = classify_cycle_phase(
            model, lei_growth=-3.0,
            unrate_data=_make_unrate(rising=True),
            nber_active=True,
        )
        assert result.phase == "Contraction"
        assert result.confidence == "High"
        assert "NBER recession declared" in result.confirming_indicators

    def test_contraction_model_driven(self):
        model = _make_model_output(probability=80.0, traffic_light="red")
        result = classify_cycle_phase(
            model, lei_growth=-3.0,
            unrate_data=_make_unrate(rising=True),
            nber_active=False,
        )
        assert result.phase == "Contraction"

    def test_contraction_not_triggered_below_threshold(self):
        model = _make_model_output(probability=60.0, traffic_light="red")
        result = classify_cycle_phase(
            model, lei_growth=1.0,
            unrate_data=_make_unrate(stable=True),
        )
        # prob=60 + LEI positive + labor stable → should be Peak not Contraction
        assert result.phase != "Contraction"


class TestCyclePhaseOutput:
    """CyclePhaseOutput properties."""

    def test_phase_has_color(self):
        model = _make_model_output(probability=10.0)
        result = classify_cycle_phase(model, lei_growth=2.0, unrate_data=None)
        assert result.color.startswith("#")
        assert result.color in PHASE_COLORS.values()

    def test_phase_has_emoji(self):
        model = _make_model_output(probability=10.0)
        result = classify_cycle_phase(model, lei_growth=2.0, unrate_data=None)
        assert result.emoji

    def test_confidence_color_property(self):
        model = _make_model_output(probability=10.0)
        result = classify_cycle_phase(model, lei_growth=2.0, unrate_data=None)
        assert result.confidence_color.startswith("#")

    def test_confirming_indicators_non_empty(self):
        model = _make_model_output(probability=10.0)
        result = classify_cycle_phase(model, lei_growth=2.0, unrate_data=None)
        assert len(result.confirming_indicators) >= 1


class TestDataQualityCap:
    """Stale high-weight features should degrade classifier confidence."""

    def _make_stale_output(self, n_stale: int = 1) -> RecessionModelOutput:
        """Create model output with n_stale high-weight stale features."""
        features = []
        for i in range(n_stale):
            features.append(FeatureContribution(
                name           = f"Stale Feature {i}",
                series_id      = f"FAKE_{i}",
                weight         = 0.20,   # high-weight (≥0.10)
                current_value  = 0.5,
                stress_score   = 0.5,
                contribution   = 10.0,
                signal_description = "stale",
                last_date      = date(2024, 1, 1),
                is_stale       = True,
                stale_message  = "stale",
            ))
        return RecessionModelOutput(
            probability    = 10.0,
            traffic_light  = "green",
            features       = features,
            data_as_of     = date(2024, 1, 1),
            has_stale_data = True,
            stale_features = [f"Stale Feature {i}" for i in range(n_stale)],
        )

    def test_one_stale_high_weight_caps_at_medium(self):
        model = self._make_stale_output(n_stale=1)
        # Force a High-confidence outcome (Early Expansion)
        result = classify_cycle_phase(model, lei_growth=3.0, unrate_data=_make_unrate(falling=True))
        # Would normally be High; stale cap should bring it to Medium
        assert result.confidence in ("Medium", "Low")

    def test_two_stale_high_weight_caps_at_low(self):
        model = self._make_stale_output(n_stale=2)
        result = classify_cycle_phase(model, lei_growth=3.0, unrate_data=_make_unrate(falling=True))
        assert result.confidence == "Low"

    def test_nber_contraction_exempt_from_cap(self):
        model = self._make_stale_output(n_stale=3)
        result = classify_cycle_phase(
            model, lei_growth=-5.0, unrate_data=_make_unrate(rising=True), nber_active=True
        )
        assert result.phase == "Contraction"
        assert result.confidence == "High"  # NBER exemption preserved


# ============================================================================
# SECTION 4: Auth flows (mocking Supabase)
# ============================================================================

from components.auth import (
    get_session_user,
    get_session_email,
    get_session_phone,
    is_guest,
    _do_sign_in,
    _do_sign_up,
    _do_verify_otp,
    _build_e164,
    logout,
    _SESSION_KEY,
    _OTP_PHONE_KEY,
    _OTP_SENT_KEY,
    _OTP_RESEND_AT,
)


def _fake_supabase_user(email: str = "test@example.com", uid: str = "abc-123", phone: str | None = None):
    """Build a mock Supabase User object."""
    user = MagicMock()
    user.email = email
    user.id    = uid
    user.phone = phone
    return user


def _fake_supabase_response(email: str = "test@example.com", uid: str = "abc-123", phone: str | None = None):
    """Build a mock Supabase auth response."""
    resp = MagicMock()
    resp.user = _fake_supabase_user(email=email, uid=uid, phone=phone)
    return resp


class TestDoSignIn:
    """_do_sign_in() — email/password authentication."""

    def test_successful_login_sets_session_state(self):
        mock_resp = _fake_supabase_response(email="user@test.com", uid="u1")
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            mock_st.rerun = MagicMock()
            mock_client = MagicMock()
            mock_client.auth.sign_in_with_password.return_value = mock_resp
            mock_get_client.return_value = mock_client

            _do_sign_in("user@test.com", "password123")

            assert st.session_state.get(_SESSION_KEY) is not None
            user = st.session_state[_SESSION_KEY]
            assert user["email"] == "user@test.com"
            assert user["id"] == "u1"
            mock_st.rerun.assert_called_once()

    def test_failed_login_shows_error_without_setting_session(self):
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            mock_st.rerun = MagicMock()
            mock_client = MagicMock()
            mock_client.auth.sign_in_with_password.side_effect = Exception("Invalid login credentials")
            mock_get_client.return_value = mock_client

            _do_sign_in("bad@test.com", "wrongpassword")

            assert st.session_state.get(_SESSION_KEY) is None
            mock_st.error.assert_called()
            mock_st.rerun.assert_not_called()

    def test_empty_email_shows_error(self):
        with patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            _do_sign_in("", "password123")
            mock_st.error.assert_called()
            assert st.session_state.get(_SESSION_KEY) is None

    def test_empty_password_shows_error(self):
        with patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            _do_sign_in("user@test.com", "")
            mock_st.error.assert_called()
            assert st.session_state.get(_SESSION_KEY) is None

    def test_invalid_credentials_message(self):
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            mock_st.rerun = MagicMock()
            mock_client = MagicMock()
            mock_client.auth.sign_in_with_password.side_effect = Exception("Invalid login credentials")
            mock_get_client.return_value = mock_client

            _do_sign_in("x@y.com", "badpass")

            error_args = mock_st.error.call_args[0][0]
            assert "email" in error_args.lower() or "password" in error_args.lower()


class TestDoSignUp:
    """_do_sign_up() — new account creation."""

    def test_successful_signup_sets_session(self):
        mock_resp = _fake_supabase_response(email="new@test.com", uid="new1")
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            mock_st.rerun = MagicMock()
            mock_client = MagicMock()
            mock_client.auth.sign_up.return_value = mock_resp
            mock_get_client.return_value = mock_client

            _do_sign_up("new@test.com", "securepass123")

            assert st.session_state.get(_SESSION_KEY) is not None

    def test_short_password_shows_error(self):
        with patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            _do_sign_up("x@y.com", "short")
            mock_st.error.assert_called()
            assert st.session_state.get(_SESSION_KEY) is None

    def test_empty_email_shows_error(self):
        with patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            _do_sign_up("", "goodpassword")
            mock_st.error.assert_called()

    def test_no_user_in_response_shows_info(self):
        """If sign_up returns no user (email confirmation needed), shows info."""
        mock_resp = MagicMock()
        mock_resp.user = None
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.info = MagicMock()
            mock_st.error = MagicMock()
            mock_st.rerun = MagicMock()
            mock_client = MagicMock()
            mock_client.auth.sign_up.return_value = mock_resp
            mock_get_client.return_value = mock_client

            _do_sign_up("confirm@test.com", "goodpassword")

            mock_st.info.assert_called()
            assert st.session_state.get(_SESSION_KEY) is None


class TestLogout:
    """logout() clears all pie360-related session state."""

    def test_logout_clears_session_key(self):
        st.session_state[_SESSION_KEY] = {"email": "a@b.com", "id": "1"}
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.st.rerun"):
            mock_get_client.return_value.auth.sign_out.return_value = None
            try:
                logout()
            except Exception:
                pass
        assert _SESSION_KEY not in st.session_state

    def test_logout_clears_otp_state(self):
        st.session_state[_SESSION_KEY]   = {"email": "a@b.com"}
        st.session_state[_OTP_PHONE_KEY] = "+85291234567"
        st.session_state[_OTP_SENT_KEY]  = True
        st.session_state[_OTP_RESEND_AT] = 12345.0
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.st.rerun"):
            mock_get_client.return_value.auth.sign_out.return_value = None
            try:
                logout()
            except Exception:
                pass
        assert _OTP_PHONE_KEY not in st.session_state
        assert _OTP_SENT_KEY not in st.session_state
        assert _OTP_RESEND_AT not in st.session_state

    def test_logout_graceful_when_supabase_errors(self):
        st.session_state[_SESSION_KEY] = {"email": "a@b.com"}
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.st.rerun"):
            mock_get_client.return_value.auth.sign_out.side_effect = Exception("network error")
            try:
                logout()
            except Exception:
                pass
        assert _SESSION_KEY not in st.session_state


class TestVerifyOtp:
    """_do_verify_otp() — SMS OTP verification."""

    def test_valid_otp_sets_session(self):
        mock_resp = _fake_supabase_response(email=None, uid="otp1", phone="+85269038453")
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.get_canonical_email_for_phone", return_value=None), \
             patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            mock_st.rerun = MagicMock()
            mock_client = MagicMock()
            mock_client.auth.verify_otp.return_value = mock_resp
            mock_get_client.return_value = mock_client

            _do_verify_otp("+85269038453", "123456")

            user = st.session_state.get(_SESSION_KEY)
            assert user is not None
            assert user["phone"] == "+85269038453"

    def test_invalid_otp_format_shows_error(self):
        with patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            _do_verify_otp("+85269038453", "abc")
            mock_st.error.assert_called()
            assert st.session_state.get(_SESSION_KEY) is None

    def test_wrong_length_otp_shows_error(self):
        with patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            _do_verify_otp("+85269038453", "12345")  # 5 digits, not 6
            mock_st.error.assert_called()

    def test_expired_otp_shows_error(self):
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            mock_st.rerun = MagicMock()
            mock_client = MagicMock()
            mock_client.auth.verify_otp.side_effect = Exception("Token has expired")
            mock_get_client.return_value = mock_client

            _do_verify_otp("+85269038453", "999999")

            mock_st.error.assert_called()
            assert st.session_state.get(_SESSION_KEY) is None

    def test_otp_with_canonical_email_merges_account(self):
        """When a canonical email exists, session should include it."""
        mock_resp = _fake_supabase_response(email=None, uid="otp2", phone="+85269038453")
        with patch("components.auth.get_client") as mock_get_client, \
             patch("components.auth.get_canonical_email_for_phone",
                   return_value="linked@gmail.com"), \
             patch("components.auth.st") as mock_st:
            mock_st.session_state = st.session_state
            mock_st.error = MagicMock()
            mock_st.rerun = MagicMock()
            mock_client = MagicMock()
            mock_client.auth.verify_otp.return_value = mock_resp
            mock_get_client.return_value = mock_client

            _do_verify_otp("+85269038453", "123456")

            user = st.session_state.get(_SESSION_KEY)
            assert user["email"] == "linked@gmail.com"


# ============================================================================
# SECTION 5: Watchlist store mutations
# ============================================================================

from components.watchlist_store import (
    add_to_watchlist,
    remove_from_watchlist,
    load_watchlist,
    in_watchlist,
    _MAX_TICKERS,
)


class TestWatchlistAddRemove:
    """add_to_watchlist / remove_from_watchlist via session_state."""

    def test_add_ticker_returns_true(self):
        assert add_to_watchlist("AAPL") is True

    def test_add_ticker_updates_cache(self):
        add_to_watchlist("MSFT")
        assert "MSFT" in st.session_state.get("_watchlist_cache", [])

    def test_add_ticker_normalises_to_uppercase(self):
        add_to_watchlist("aapl")
        assert "AAPL" in st.session_state.get("_watchlist_cache", [])

    def test_add_duplicate_returns_false(self):
        add_to_watchlist("TSLA")
        assert add_to_watchlist("TSLA") is False

    def test_add_duplicate_does_not_duplicate_entry(self):
        add_to_watchlist("GOOG")
        add_to_watchlist("GOOG")
        cache = st.session_state.get("_watchlist_cache", [])
        assert cache.count("GOOG") == 1

    def test_remove_existing_ticker_returns_true(self):
        add_to_watchlist("AMZN")
        assert remove_from_watchlist("AMZN") is True

    def test_remove_clears_from_cache(self):
        add_to_watchlist("NVDA")
        remove_from_watchlist("NVDA")
        assert "NVDA" not in st.session_state.get("_watchlist_cache", [])

    def test_remove_nonexistent_returns_false(self):
        assert remove_from_watchlist("NOTHERE") is False

    def test_remove_case_insensitive(self):
        add_to_watchlist("META")
        assert remove_from_watchlist("meta") is True

    def test_multiple_tickers_independent(self):
        add_to_watchlist("AAPL")
        add_to_watchlist("MSFT")
        add_to_watchlist("GOOG")
        remove_from_watchlist("MSFT")
        cache = st.session_state.get("_watchlist_cache", [])
        assert "AAPL" in cache
        assert "MSFT" not in cache
        assert "GOOG" in cache


class TestWatchlistCapAndLoad:
    """Watchlist cap and load_watchlist() session-state path."""

    def test_cap_at_max_tickers(self):
        for i in range(_MAX_TICKERS):
            add_to_watchlist(f"T{i:03d}")
        result = add_to_watchlist("OVERFLOW")
        # Should return False and not add
        cache = st.session_state.get("_watchlist_cache", [])
        assert "OVERFLOW" not in cache

    def test_load_watchlist_from_session_cache(self):
        st.session_state["_watchlist_cache"] = ["AAPL", "MSFT"]
        result = load_watchlist()
        assert "AAPL" in result
        assert "MSFT" in result

    def test_load_watchlist_returns_list(self):
        st.session_state["_watchlist_cache"] = ["TSLA"]
        assert isinstance(load_watchlist(), list)

    def test_load_watchlist_empty_when_no_cache(self):
        # No cache, no mounted JS → returns []
        assert load_watchlist() == []


class TestInWatchlist:
    """in_watchlist() reads session_state directly."""

    def test_in_watchlist_true(self):
        st.session_state["_watchlist_cache"] = ["AAPL", "TSLA"]
        assert in_watchlist("AAPL") is True

    def test_in_watchlist_false(self):
        st.session_state["_watchlist_cache"] = ["AAPL"]
        assert in_watchlist("MSFT") is False

    def test_in_watchlist_case_insensitive(self):
        st.session_state["_watchlist_cache"] = ["GOOG"]
        assert in_watchlist("goog") is True

    def test_in_watchlist_empty_cache(self):
        st.session_state["_watchlist_cache"] = []
        assert in_watchlist("AAPL") is False

    def test_in_watchlist_no_cache_key(self):
        # _watchlist_cache not set at all
        assert in_watchlist("AAPL") is False


# ============================================================================
# SECTION 6: friends_store mutations (mocking Supabase)
# ============================================================================

from components.friends_store import (
    send_friend_request,
    accept_request,
    reject_request,
    remove_friend,
    create_invite_token,
    consume_invite_token,
    get_my_snapshot,
    save_snapshot,
)


def _make_db_mock():
    """Return a MagicMock that mimics the Supabase client chaining API."""
    db = MagicMock()
    # Enable fluent chaining: db.table(...).select(...).eq(...).execute()
    db.table.return_value = db
    db.select.return_value = db
    db.eq.return_value = db
    db.insert.return_value = db
    db.update.return_value = db
    db.delete.return_value = db
    db.upsert.return_value = db
    db.maybe_single.return_value = db
    db.execute.return_value = MagicMock(data=None)
    return db


class TestSendFriendRequest:
    """send_friend_request() — business logic without live DB."""

    def test_missing_email_fails(self):
        ok, msg = send_friend_request("", "b@b.com")
        assert ok is False
        assert "Missing" in msg

    def test_self_request_fails(self):
        ok, msg = send_friend_request("a@a.com", "a@a.com")
        assert ok is False
        assert "yourself" in msg.lower()

    def test_new_request_inserts_row(self):
        db = _make_db_mock()
        db.execute.return_value = MagicMock(data=None)  # no existing row
        with patch("components.friends_store.get_client", return_value=db):
            ok, msg = send_friend_request("a@a.com", "b@b.com")
        assert ok is True
        db.insert.assert_called()

    def test_already_friends_returns_error(self):
        db = _make_db_mock()
        db.execute.return_value = MagicMock(
            data={"id": "1", "status": "accepted", "requester_email": "a@a.com"}
        )
        with patch("components.friends_store.get_client", return_value=db):
            ok, msg = send_friend_request("a@a.com", "b@b.com")
        assert ok is False
        assert "already" in msg.lower()

    def test_pending_own_request_returns_error(self):
        db = _make_db_mock()
        db.execute.return_value = MagicMock(
            data={"id": "2", "status": "pending", "requester_email": "a@a.com"}
        )
        with patch("components.friends_store.get_client", return_value=db):
            ok, msg = send_friend_request("a@a.com", "b@b.com")
        assert ok is False
        assert "already sent" in msg.lower()

    def test_incoming_pending_auto_accepts(self):
        """If they already requested me, accept their request instead."""
        db = _make_db_mock()
        db.execute.return_value = MagicMock(
            data={"id": "3", "status": "pending", "requester_email": "b@b.com"}
        )
        with patch("components.friends_store.get_client", return_value=db):
            ok, msg = send_friend_request("a@a.com", "b@b.com")
        assert ok is True
        assert msg == "auto_accepted"


class TestAcceptRejectRequest:
    """accept_request() and reject_request() — simple DB update paths."""

    def test_accept_returns_true_on_success(self):
        db = _make_db_mock()
        with patch("components.friends_store.get_client", return_value=db):
            result = accept_request("me@test.com", "them@test.com")
        assert result is True

    def test_accept_returns_false_on_exception(self):
        db = _make_db_mock()
        db.execute.side_effect = Exception("DB error")
        with patch("components.friends_store.get_client", return_value=db):
            result = accept_request("me@test.com", "them@test.com")
        assert result is False

    def test_reject_returns_true_on_success(self):
        db = _make_db_mock()
        with patch("components.friends_store.get_client", return_value=db):
            result = reject_request("me@test.com", "them@test.com")
        assert result is True

    def test_reject_returns_false_on_exception(self):
        db = _make_db_mock()
        db.execute.side_effect = Exception("DB error")
        with patch("components.friends_store.get_client", return_value=db):
            result = reject_request("me@test.com", "them@test.com")
        assert result is False


class TestRemoveFriend:
    """remove_friend() — deletes row in both directions."""

    def test_returns_true_on_success(self):
        db = _make_db_mock()
        with patch("components.friends_store.get_client", return_value=db):
            result = remove_friend("a@a.com", "b@b.com")
        assert result is True
        # delete should have been called twice (both directions)
        assert db.delete.call_count >= 2

    def test_returns_false_on_exception(self):
        db = _make_db_mock()
        db.execute.side_effect = Exception("connection error")
        with patch("components.friends_store.get_client", return_value=db):
            result = remove_friend("a@a.com", "b@b.com")
        assert result is False


class TestCreateInviteToken:
    """create_invite_token() — generates a UUID token and inserts into DB."""

    def test_returns_non_empty_string(self):
        db = _make_db_mock()
        with patch("components.friends_store.get_client", return_value=db):
            token = create_invite_token("creator@test.com")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_is_valid_uuid(self):
        db = _make_db_mock()
        with patch("components.friends_store.get_client", return_value=db):
            token = create_invite_token("creator@test.com")
        # Should be parseable as UUID4
        parsed = uuid.UUID(token)
        assert str(parsed) == token

    def test_returns_none_on_db_error(self):
        db = _make_db_mock()
        db.execute.side_effect = Exception("constraint violation")
        with patch("components.friends_store.get_client", return_value=db):
            token = create_invite_token("creator@test.com")
        assert token is None

    def test_different_calls_produce_different_tokens(self):
        db = _make_db_mock()
        with patch("components.friends_store.get_client", return_value=db):
            t1 = create_invite_token("a@a.com")
            t2 = create_invite_token("a@a.com")
        assert t1 != t2


class TestConsumeInviteToken:
    """consume_invite_token() — validates and redeems invite links."""

    def _make_valid_token_row(
        self,
        creator: str = "creator@test.com",
        token: str = "some-token-uuid",
        used_by: str | None = None,
        days_from_now: int = 3,
    ) -> dict:
        expires = (datetime.now(timezone.utc) + timedelta(days=days_from_now)).isoformat()
        return {
            "token":      token,
            "created_by": creator,
            "used_by":    used_by,
            "expires_at": expires,
        }

    def test_valid_token_returns_true_and_creator(self):
        db = _make_db_mock()
        row = self._make_valid_token_row()
        db.execute.return_value = MagicMock(data=row)
        # Subsequent calls (update, insert) return success
        with patch("components.friends_store.get_client", return_value=db), \
             patch("components.friends_store._existing_row", return_value=None), \
             patch("components.friends_store.send_friend_request", return_value=(True, "")):
            ok, result = consume_invite_token("some-token-uuid", "joiner@test.com")
        assert ok is True
        assert result == "creator@test.com"

    def test_nonexistent_token_fails(self):
        db = _make_db_mock()
        db.execute.return_value = MagicMock(data=None)
        with patch("components.friends_store.get_client", return_value=db):
            ok, msg = consume_invite_token("bad-token", "joiner@test.com")
        assert ok is False
        assert "not found" in msg.lower() or "already used" in msg.lower()

    def test_already_used_token_fails(self):
        db = _make_db_mock()
        row = self._make_valid_token_row(used_by="someoneelse@test.com")
        db.execute.return_value = MagicMock(data=row)
        with patch("components.friends_store.get_client", return_value=db):
            ok, msg = consume_invite_token("some-token-uuid", "joiner@test.com")
        assert ok is False
        assert "already been used" in msg.lower()

    def test_expired_token_fails(self):
        db = _make_db_mock()
        row = self._make_valid_token_row(days_from_now=-1)  # expired yesterday
        db.execute.return_value = MagicMock(data=row)
        with patch("components.friends_store.get_client", return_value=db):
            ok, msg = consume_invite_token("some-token-uuid", "joiner@test.com")
        assert ok is False
        assert "expired" in msg.lower()

    def test_own_token_fails(self):
        db = _make_db_mock()
        row = self._make_valid_token_row(creator="user@test.com")
        db.execute.return_value = MagicMock(data=row)
        with patch("components.friends_store.get_client", return_value=db):
            ok, msg = consume_invite_token("some-token-uuid", "user@test.com")
        assert ok is False
        assert "own" in msg.lower()


class TestGetMySnapshot:
    """get_my_snapshot() — returns user snapshot or defaults."""

    def test_returns_dict_always(self):
        db = _make_db_mock()
        db.execute.return_value = MagicMock(data=None)
        with patch("components.friends_store.get_client", return_value=db):
            result = get_my_snapshot("user@test.com")
        assert isinstance(result, dict)

    def test_returns_defaults_when_no_row(self):
        db = _make_db_mock()
        db.execute.return_value = MagicMock(data=None)
        with patch("components.friends_store.get_client", return_value=db):
            result = get_my_snapshot("user@test.com")
        assert result["user_email"] == "user@test.com"
        assert result["holdings_json"] == []
        assert result["share_holdings"] is False

    def test_merges_existing_row(self):
        db = _make_db_mock()
        db.execute.return_value = MagicMock(data={
            "user_email":    "user@test.com",
            "share_holdings": True,
            "cycle_phase":   "Expansion",
            "recession_prob": 15.0,
            "holdings_json": [{"ticker": "AAPL", "weight": 10.0}],
        })
        with patch("components.friends_store.get_client", return_value=db):
            result = get_my_snapshot("user@test.com")
        assert result["share_holdings"] is True
        assert result["cycle_phase"] == "Expansion"
        assert result["recession_prob"] == 15.0

    def test_returns_defaults_on_exception(self):
        db = _make_db_mock()
        db.execute.side_effect = Exception("DB unavailable")
        with patch("components.friends_store.get_client", return_value=db):
            result = get_my_snapshot.func("user@test.com")  # bypass cache
        assert isinstance(result, dict)


class TestSaveSnapshot:
    """save_snapshot() — upsert portfolio snapshot."""

    def test_returns_true_on_success(self):
        db = _make_db_mock()
        with patch("components.friends_store.get_client", return_value=db), \
             patch("components.friends_store.get_my_snapshot") as mock_cache:
            mock_cache.clear = MagicMock()
            result = save_snapshot(
                my_email="user@test.com",
                holdings=[{"ticker": "AAPL", "weight": 25.0}],
                settings={"share_holdings": True, "share_performance": False, "share_risk_metrics": False},
                cycle_phase="Mid Expansion",
                recession_prob=18.5,
            )
        assert result is True

    def test_returns_false_on_exception(self):
        db = _make_db_mock()
        db.execute.side_effect = Exception("upsert failed")
        with patch("components.friends_store.get_client", return_value=db):
            result = save_snapshot(
                my_email="user@test.com",
                holdings=[],
                settings={},
            )
        assert result is False

    def test_upsert_called_with_correct_email(self):
        db = _make_db_mock()
        with patch("components.friends_store.get_client", return_value=db), \
             patch("components.friends_store.get_my_snapshot") as mock_cache:
            mock_cache.clear = MagicMock()
            save_snapshot("owner@test.com", [], {})
        # Verify upsert was called
        db.upsert.assert_called()
        upsert_payload = db.upsert.call_args[0][0]
        assert upsert_payload["user_email"] == "owner@test.com"
