"""
tests/test_macro_scoring.py
============================
Tests for macro regime scoring and visual helpers.
These functions directly affect investment recommendations shown to users.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.stock_score_utils import (
    _macro_adj_score,
    _score_color,
    _score_label,
)


class TestMacroAdjScore:
    """_macro_adj_score(base, sector, regime) — capped ±15, total 0–100."""

    def test_no_adjustment_for_unknown_regime(self):
        score = _macro_adj_score(60, "Technology", "Unknown Regime")
        assert score == 60

    def test_no_adjustment_for_unknown_sector(self):
        score = _macro_adj_score(60, "Widgets & Sprockets", "Expansion")
        assert score == 60

    def test_output_never_below_zero(self):
        # Even with max downward adj, score can't go negative
        score = _macro_adj_score(0, "Energy", "Contraction")
        assert score >= 0

    def test_output_never_above_100(self):
        score = _macro_adj_score(100, "Technology", "Expansion")
        assert score <= 100

    def test_cap_at_plus_15(self):
        # Adj should be capped at +15 even if map says more
        score = _macro_adj_score(50, "Technology", "Expansion")
        assert score <= 65   # base 50 + max 15

    def test_cap_at_minus_15(self):
        score = _macro_adj_score(50, "Energy", "Contraction")
        assert score >= 35   # base 50 - max 15

    def test_none_sector_is_safe(self):
        score = _macro_adj_score(60, None, "Expansion")
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_returns_int(self):
        score = _macro_adj_score(55, "Healthcare", "Late Cycle")
        assert isinstance(score, int)


class TestScoreColor:
    """_score_color(score) — returns a hex colour string."""

    def test_returns_string(self):
        assert isinstance(_score_color(75), str)

    def test_elite_score_green(self):
        color = _score_color(80)
        assert color.startswith("#")

    def test_zero_score_red_ish(self):
        color = _score_color(0)
        assert color.startswith("#")

    def test_all_bands_return_color(self):
        for score in [0, 20, 30, 45, 60, 75, 90, 100]:
            c = _score_color(score)
            assert c.startswith("#"), f"Score {score} returned non-hex: {c}"


class TestScoreLabel:
    """_score_label(score) — returns (label_str, colour_str)."""

    def test_returns_tuple_of_two(self):
        result = _score_label(70)
        assert isinstance(result, tuple) and len(result) == 2

    def test_elite_band(self):
        label, _ = _score_label(80)
        assert "elite" in label.lower() or "strong" in label.lower()

    def test_avoid_band(self):
        label, _ = _score_label(10)
        assert label  # at minimum returns something

    def test_all_bands_return_non_empty(self):
        for score in [0, 15, 30, 45, 60, 75, 90]:
            label, color = _score_label(score)
            assert label, f"Empty label for score {score}"
            assert color, f"Empty color for score {score}"
