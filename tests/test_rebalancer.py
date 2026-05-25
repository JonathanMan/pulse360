"""
tests/test_rebalancer.py
========================
Unit tests for components/rebalancer.py

Run from the workspace root:
    python -m pytest Pulse360/tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# rebalancer.py imports pandas but not streamlit — safe to test standalone
from rebalancer import (
    CYCLE_PHASES,
    PHASE_RATIONALE,
    _action_tag,
    _equity_bucket,
    compute_plan,
    plan_to_dataframe,
    CYCLICAL_SECTORS,
    DEFENSIVE_SECTORS,
)


# ── _action_tag ───────────────────────────────────────────────────────────────

class TestActionTag:
    def test_strong_add(self):
        assert _action_tag(6.0) == "🟢 Add"

    def test_strong_trim(self):
        assert _action_tag(-6.0) == "🔴 Trim"

    def test_minor_add(self):
        assert _action_tag(3.0) == "🟡 Minor add"

    def test_minor_trim(self):
        assert _action_tag(-3.0) == "🟡 Minor trim"

    def test_hold_positive(self):
        assert _action_tag(1.0) == "⚪ Hold"

    def test_hold_zero(self):
        assert _action_tag(0.0) == "⚪ Hold"

    def test_hold_negative(self):
        assert _action_tag(-1.5) == "⚪ Hold"

    def test_exact_threshold_add(self):
        assert _action_tag(5.0) == "🟢 Add"

    def test_exact_threshold_trim(self):
        assert _action_tag(-5.0) == "🔴 Trim"


# ── _equity_bucket ────────────────────────────────────────────────────────────

class TestEquityBucket:
    def test_technology_is_cyclical(self):
        assert _equity_bucket("Technology") == "cyclical"

    def test_healthcare_is_defensive(self):
        assert _equity_bucket("Healthcare") == "defensive"

    def test_utilities_is_defensive(self):
        assert _equity_bucket("Utilities") == "defensive"

    def test_consumer_staples_is_defensive(self):
        assert _equity_bucket("Consumer Staples") == "defensive"

    def test_consumer_defensive_is_defensive(self):
        assert _equity_bucket("Consumer Defensive") == "defensive"

    def test_broad_equity_is_neutral(self):
        assert _equity_bucket("Broad Equity") == "neutral"

    def test_unknown_is_neutral(self):
        assert _equity_bucket("Unknown Sector XYZ") == "neutral"

    def test_industrials_is_cyclical(self):
        assert _equity_bucket("Industrials") == "cyclical"

    def test_energy_is_cyclical(self):
        assert _equity_bucket("Energy") == "cyclical"


# ── compute_plan ──────────────────────────────────────────────────────────────

def _simple_portfolio():
    """60% equity (cyclical), 30% bond, 10% cash — clean for testing."""
    weights = {"AAPL": 60.0, "TLT": 30.0, "BIL": 10.0}
    classifications = {
        "AAPL": {"sector": "Technology", "asset_class": "Equity"},
        "TLT":  {"sector": "Long-Term Bonds", "asset_class": "Bond"},
        "BIL":  {"sector": "Cash", "asset_class": "Cash"},
    }
    return weights, classifications


class TestComputePlan:
    def test_suggested_weights_sum_to_100(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Late / Peak")
        total = sum(p["suggested"] for p in plan.values())
        assert abs(total - 100.0) < 0.5, f"Suggested weights sum to {total}, expected ~100"

    def test_all_tickers_present(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Mid / Expansion")
        assert set(plan.keys()) == {"AAPL", "TLT", "BIL"}

    def test_late_peak_reduces_cyclicals(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Late / Peak")
        # AAPL (Technology = cyclical) should be trimmed
        assert plan["AAPL"]["delta"] < 0, "Cyclicals should be trimmed in Late/Peak"

    def test_late_peak_adds_bonds(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Late / Peak")
        assert plan["TLT"]["delta"] > 0, "Bonds should be added in Late/Peak"

    def test_contraction_sharply_reduces_cyclicals(self):
        weights, clfs = _simple_portfolio()
        plan_late = compute_plan(weights, clfs, "Late / Peak")
        plan_cont = compute_plan(weights, clfs, "Contraction")
        assert plan_cont["AAPL"]["delta"] < plan_late["AAPL"]["delta"], \
            "Contraction should reduce cyclicals more than Late/Peak"

    def test_early_recovery_adds_cyclicals(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Early / Recovery")
        assert plan["AAPL"]["delta"] > 0, "Cyclicals should be added in Early/Recovery"

    def test_unknown_cycle_phase_returns_unchanged(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Unknown Phase XYZ")
        for ticker, p in plan.items():
            assert p["delta"] == 0.0, f"{ticker} should be unchanged for unknown phase"

    def test_action_tags_assigned(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Contraction")
        for ticker, p in plan.items():
            assert "action" in p
            assert p["action"] in (
                "🟢 Add", "🔴 Trim", "🟡 Minor add", "🟡 Minor trim", "⚪ Hold"
            )

    def test_current_weights_preserved(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Late / Peak")
        for ticker, w in weights.items():
            assert plan[ticker]["current"] == round(w, 1)

    def test_delta_equals_suggested_minus_current(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Mid / Expansion")
        for ticker, p in plan.items():
            expected_delta = round(p["suggested"] - p["current"], 1)
            assert abs(p["delta"] - expected_delta) < 0.01, \
                f"{ticker}: delta={p['delta']}, expected={expected_delta}"

    def test_all_cycle_phases_run_without_error(self):
        weights, clfs = _simple_portfolio()
        for phase in CYCLE_PHASES:
            plan = compute_plan(weights, clfs, phase)
            total = sum(p["suggested"] for p in plan.values())
            assert abs(total - 100.0) < 0.5, f"Phase {phase}: sum={total}"

    def test_mixed_equity_portfolio(self):
        """Portfolio with both cyclical and defensive equities."""
        weights = {"NVDA": 40.0, "JNJ": 30.0, "AMZN": 30.0}
        clfs = {
            "NVDA": {"sector": "Technology",             "asset_class": "Equity"},
            "JNJ":  {"sector": "Healthcare",             "asset_class": "Equity"},
            "AMZN": {"sector": "Consumer Discretionary", "asset_class": "Equity"},
        }
        plan = compute_plan(weights, clfs, "Late / Peak")
        total = sum(p["suggested"] for p in plan.values())
        assert abs(total - 100.0) < 0.5
        # Defensives should gain relative to cyclicals
        assert plan["JNJ"]["delta"] > plan["NVDA"]["delta"], \
            "Healthcare (defensive) should outperform Tech (cyclical) in Late/Peak"

    def test_zero_weight_positions_excluded_from_normalisation(self):
        """Positions with 0 weight should stay at 0 suggested weight."""
        weights = {"AAPL": 100.0, "MSFT": 0.0}
        clfs = {
            "AAPL": {"sector": "Technology", "asset_class": "Equity"},
            "MSFT": {"sector": "Technology", "asset_class": "Equity"},
        }
        plan = compute_plan(weights, clfs, "Late / Peak")
        assert plan["MSFT"]["suggested"] == 0.0


# ── plan_to_dataframe ─────────────────────────────────────────────────────────

class TestPlanToDataframe:
    def test_returns_dataframe(self):
        import pandas as pd
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Late / Peak")
        df = plan_to_dataframe(plan)
        assert isinstance(df, pd.DataFrame)

    def test_has_required_columns(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Late / Peak")
        df = plan_to_dataframe(plan)
        for col in ("Ticker", "Sector", "Asset Class", "Current %", "Suggested %", "Δ", "Action"):
            assert col in df.columns, f"Missing column: {col}"

    def test_sorted_by_abs_delta_descending(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Contraction")
        df = plan_to_dataframe(plan)
        deltas = df["Δ"].abs().tolist()
        assert deltas == sorted(deltas, reverse=True), "Rows should be sorted by |Δ| descending"

    def test_row_count_matches_plan(self):
        weights, clfs = _simple_portfolio()
        plan = compute_plan(weights, clfs, "Late / Peak")
        df = plan_to_dataframe(plan)
        assert len(df) == len(plan)


# ── CYCLE_PHASES and PHASE_RATIONALE ──────────────────────────────────────────

class TestConstants:
    def test_four_cycle_phases(self):
        assert len(CYCLE_PHASES) == 4

    def test_all_phases_have_rationale(self):
        for phase in CYCLE_PHASES:
            assert phase in PHASE_RATIONALE, f"No rationale for phase: {phase}"
            assert len(PHASE_RATIONALE[phase]) > 50, f"Rationale too short for: {phase}"

    def test_cyclical_defensive_sets_disjoint(self):
        overlap = CYCLICAL_SECTORS & DEFENSIVE_SECTORS
        assert len(overlap) == 0, f"Sectors appear in both sets: {overlap}"
