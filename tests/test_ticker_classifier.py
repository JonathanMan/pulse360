"""
tests/test_ticker_classifier.py
================================
Unit tests for components/ticker_classifier.py

Run from the workspace root:
    python -m pytest Pie360/tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub out streamlit before importing ticker_classifier
import unittest.mock as mock
import sys

# Provide a minimal streamlit stub so ticker_classifier imports cleanly
streamlit_stub = mock.MagicMock()
streamlit_stub.cache_data = lambda **kw: (lambda fn: fn)  # passthrough decorator
streamlit_stub.secrets = {}
sys.modules["streamlit"] = streamlit_stub

from ticker_classifier import (
    TICKER_LOOKUP,
    SECTOR_TO_ASSET_CLASS,
    ASSET_CLASS_COLORS,
    classify_ticker,
    classify_all,
)


# ── TICKER_LOOKUP integrity ───────────────────────────────────────────────────

class TestTickerLookup:
    _VALID_ASSET_CLASSES = {"Equity", "Bond", "Commodity", "Cash", "Real Estate", "Crypto"}

    def test_all_entries_have_sector_and_asset_class(self):
        for ticker, info in TICKER_LOOKUP.items():
            assert "sector" in info, f"{ticker} missing 'sector'"
            assert "asset_class" in info, f"{ticker} missing 'asset_class'"

    def test_all_asset_classes_are_valid(self):
        for ticker, info in TICKER_LOOKUP.items():
            assert info["asset_class"] in self._VALID_ASSET_CLASSES, \
                f"{ticker} has invalid asset_class: {info['asset_class']}"

    def test_key_etfs_present(self):
        for ticker in ("SPY", "QQQ", "TLT", "GLD", "BIL"):
            assert ticker in TICKER_LOOKUP, f"{ticker} missing from TICKER_LOOKUP"

    def test_spy_is_broad_equity(self):
        assert TICKER_LOOKUP["SPY"]["asset_class"] == "Equity"

    def test_tlt_is_bond(self):
        assert TICKER_LOOKUP["TLT"]["asset_class"] == "Bond"

    def test_gld_is_commodity(self):
        assert TICKER_LOOKUP["GLD"]["asset_class"] == "Commodity"

    def test_bil_is_cash(self):
        assert TICKER_LOOKUP["BIL"]["asset_class"] == "Cash"

    def test_cqqq_is_equity(self):
        assert TICKER_LOOKUP["CQQQ"]["asset_class"] == "Equity"

    def test_qqq_sector_is_technology(self):
        assert TICKER_LOOKUP["QQQ"]["sector"] == "Technology"

    def test_all_tickers_uppercase(self):
        for ticker in TICKER_LOOKUP:
            assert ticker == ticker.upper(), f"Ticker not uppercase: {ticker}"


# ── SECTOR_TO_ASSET_CLASS ────────────────────────────────────────────────────

class TestSectorMapping:
    _VALID_ASSET_CLASSES = {"Equity", "Bond", "Commodity", "Cash", "Real Estate", "Crypto"}

    def test_all_values_valid(self):
        for sector, ac in SECTOR_TO_ASSET_CLASS.items():
            assert ac in self._VALID_ASSET_CLASSES, \
                f"Sector '{sector}' maps to invalid asset_class '{ac}'"

    def test_technology_maps_to_equity(self):
        assert SECTOR_TO_ASSET_CLASS["Technology"] == "Equity"

    def test_real_estate_maps_to_real_estate(self):
        assert SECTOR_TO_ASSET_CLASS["Real Estate"] == "Real Estate"

    def test_healthcare_maps_to_equity(self):
        assert SECTOR_TO_ASSET_CLASS["Healthcare"] == "Equity"


# ── ASSET_CLASS_COLORS ────────────────────────────────────────────────────────

class TestAssetClassColors:
    def test_all_six_classes_have_color(self):
        for ac in ("Equity", "Bond", "Commodity", "Cash", "Real Estate", "Crypto"):
            assert ac in ASSET_CLASS_COLORS, f"Missing color for {ac}"

    def test_colors_are_hex(self):
        for ac, color in ASSET_CLASS_COLORS.items():
            assert color.startswith("#"), f"{ac} color is not hex: {color}"
            assert len(color) == 7, f"{ac} color wrong length: {color}"


# ── classify_ticker ───────────────────────────────────────────────────────────

class TestClassifyTicker:
    def test_etf_from_lookup(self):
        result = classify_ticker("SPY")
        assert result["asset_class"] == "Equity"
        assert result["source"] == "lookup"

    def test_lookup_case_insensitive(self):
        result = classify_ticker("spy")
        assert result["source"] == "lookup"

    def test_bond_etf(self):
        result = classify_ticker("TLT")
        assert result["asset_class"] == "Bond"

    def test_commodity_etf(self):
        result = classify_ticker("GLD")
        assert result["asset_class"] == "Commodity"

    def test_cash_etf(self):
        result = classify_ticker("BIL")
        assert result["asset_class"] == "Cash"

    def test_scored_stock_uses_scorer_sector(self):
        result = classify_ticker("AAPL", sector_from_scorer="Technology")
        assert result["sector"] == "Technology"
        assert result["asset_class"] == "Equity"
        assert result["source"] == "scorer"

    def test_lookup_takes_priority_over_scorer(self):
        # SPY is in TICKER_LOOKUP — lookup should win even if scorer provides a sector
        result = classify_ticker("SPY", sector_from_scorer="Financials")
        assert result["source"] == "lookup"

    def test_result_has_required_keys(self):
        result = classify_ticker("QQQ")
        for key in ("sector", "asset_class", "source"):
            assert key in result, f"Missing key: {key}"

    def test_unknown_ticker_with_scorer_sector(self):
        result = classify_ticker("ZZZZ", sector_from_scorer="Healthcare")
        assert result["asset_class"] == "Equity"
        assert result["sector"] == "Healthcare"

    def test_dash_sector_falls_through_to_fallback(self):
        # sector "—" is the blank placeholder — should NOT be used as scorer data
        # With Claude mocked, it falls back to {"sector": "Unknown", "asset_class": "Equity", "source": "fallback"}
        result = classify_ticker("ZZZZ99", sector_from_scorer="—", company="Unknown Corp")
        assert result["source"] != "scorer"

    def test_empty_sector_falls_through(self):
        result = classify_ticker("ZZZZ98", sector_from_scorer="", company="Unknown Corp")
        assert result["source"] != "scorer"


# ── classify_all ─────────────────────────────────────────────────────────────

class TestClassifyAll:
    def _make_scored(self, tickers_sectors):
        return [
            {"Ticker": t, "Sector": s, "Company": t}
            for t, s in tickers_sectors
        ]

    def test_all_tickers_returned(self):
        scored = self._make_scored([("AAPL", "Technology"), ("MSFT", "Technology")])
        result = classify_all(scored, failed=[])
        assert "AAPL" in result
        assert "MSFT" in result

    def test_failed_etfs_included(self):
        result = classify_all(scored=[], failed=["SPY", "TLT"])
        assert "SPY" in result
        assert "TLT" in result

    def test_failed_etf_correct_asset_class(self):
        result = classify_all(scored=[], failed=["TLT"])
        assert result["TLT"]["asset_class"] == "Bond"

    def test_scored_and_failed_combined(self):
        scored = self._make_scored([("AAPL", "Technology")])
        result = classify_all(scored, failed=["SPY"])
        assert "AAPL" in result
        assert "SPY" in result

    def test_no_duplicate_tickers(self):
        scored = self._make_scored([("AAPL", "Technology")])
        result = classify_all(scored, failed=["AAPL"])  # AAPL in both
        # AAPL should appear exactly once
        assert "AAPL" in result

    def test_empty_inputs(self):
        result = classify_all(scored=[], failed=[])
        assert result == {}

    def test_result_values_have_required_keys(self):
        scored = self._make_scored([("NVDA", "Technology")])
        result = classify_all(scored, failed=["GLD"])
        for ticker, clf in result.items():
            for key in ("sector", "asset_class", "source"):
                assert key in clf, f"{ticker} missing key '{key}'"
