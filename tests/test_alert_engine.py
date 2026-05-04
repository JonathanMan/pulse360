"""
tests/test_alert_engine.py
===========================
Tests for alert rule evaluation logic — the most mission-critical pure-logic
function in the app (wrong evaluations = wrong user alerts).
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.alert_engine import evaluate_rule


def _rule(op, threshold, last_value=None):
    return {"operator": op, "threshold": threshold, "last_value": last_value}


class TestEvaluateRuleSimpleComparisons:
    def test_greater_than_fires(self):
        assert evaluate_rule(_rule(">", 25), 30) is True

    def test_greater_than_no_fire_at_threshold(self):
        assert evaluate_rule(_rule(">", 25), 25) is False

    def test_less_than_fires(self):
        assert evaluate_rule(_rule("<", 25), 20) is True

    def test_less_than_no_fire_at_threshold(self):
        assert evaluate_rule(_rule("<", 25), 25) is False

    def test_gte_fires_at_threshold(self):
        assert evaluate_rule(_rule(">=", 25), 25) is True

    def test_lte_fires_at_threshold(self):
        assert evaluate_rule(_rule("<=", 25), 25) is True

    def test_gte_fires_above(self):
        assert evaluate_rule(_rule(">=", 25), 26) is True

    def test_lte_fires_below(self):
        assert evaluate_rule(_rule("<=", 25), 24) is True


class TestEvaluateRuleCrossing:
    # crosses_above: last <= threshold < current
    def test_crosses_above_fires(self):
        assert evaluate_rule(_rule("crosses_above", 25, last_value=24), 26) is True

    def test_crosses_above_fires_last_equals_threshold(self):
        assert evaluate_rule(_rule("crosses_above", 25, last_value=25), 26) is True

    def test_crosses_above_no_fire_stays_above(self):
        # Was already above — not a new crossing
        assert evaluate_rule(_rule("crosses_above", 25, last_value=27), 28) is False

    def test_crosses_above_no_fire_no_last(self):
        assert evaluate_rule(_rule("crosses_above", 25, last_value=None), 26) is False

    def test_crosses_above_no_fire_current_at_threshold(self):
        # current must be ABOVE threshold, not equal
        assert evaluate_rule(_rule("crosses_above", 25, last_value=24), 25) is False

    # crosses_below: last >= threshold > current
    def test_crosses_below_fires(self):
        assert evaluate_rule(_rule("crosses_below", 25, last_value=26), 24) is True

    def test_crosses_below_fires_last_equals_threshold(self):
        assert evaluate_rule(_rule("crosses_below", 25, last_value=25), 24) is True

    def test_crosses_below_no_fire_stays_below(self):
        assert evaluate_rule(_rule("crosses_below", 25, last_value=22), 21) is False

    def test_crosses_below_no_fire_no_last(self):
        assert evaluate_rule(_rule("crosses_below", 25, last_value=None), 24) is False


class TestEvaluateRuleEdgeCases:
    def test_unknown_operator_returns_false(self):
        assert evaluate_rule(_rule("INVALID", 25), 30) is False

    def test_threshold_as_string_is_cast(self):
        # threshold stored as string from form input
        rule = {"operator": ">", "threshold": "25.0", "last_value": None}
        assert evaluate_rule(rule, 30) is True

    def test_zero_threshold(self):
        assert evaluate_rule(_rule(">", 0), 0.01) is True
        assert evaluate_rule(_rule(">", 0), 0) is False

    def test_negative_threshold(self):
        assert evaluate_rule(_rule("<", -1), -2) is True
        assert evaluate_rule(_rule("<", -1), -1) is False
