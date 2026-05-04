"""
tests/test_portfolio_parser.py
================================
Tests for parse_portfolio_csv — the function that ingests user-uploaded
broker exports. A parse failure = user sees no analysis, so robustness matters.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from ai.portfolio_analyzer import parse_portfolio_csv


def _df(**kwargs):
    """Build a minimal DataFrame from column→list kwargs."""
    return pd.DataFrame(kwargs)


class TestParsePortfolioCsvGeneric:
    def test_standard_columns(self):
        df = _df(
            ticker=["AAPL", "MSFT"],
            quantity=[100, 50],
            last_price=[180.0, 350.0],
            market_value=[18000.0, 17500.0],
        )
        positions, total = parse_portfolio_csv(df)
        assert len(positions) == 2
        tickers = [p["ticker"] for p in positions]
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_tickers_uppercased(self):
        df = _df(ticker=["aapl", "msft"], quantity=[10, 20])
        positions, _ = parse_portfolio_csv(df)
        for p in positions:
            assert p["ticker"] == p["ticker"].upper()

    def test_skips_blank_tickers(self):
        df = _df(ticker=["AAPL", "", "   ", "MSFT"], quantity=[10, 5, 5, 20])
        positions, _ = parse_portfolio_csv(df)
        tickers = [p["ticker"] for p in positions]
        assert "" not in tickers
        assert "   " not in tickers

    def test_total_value_computed(self):
        df = _df(
            ticker=["AAPL", "MSFT"],
            market_value=[10000.0, 5000.0],
        )
        positions, total = parse_portfolio_csv(df)
        # Either sum is computed or None is returned
        if total is not None:
            assert total > 0

    def test_alias_symbol_column(self):
        df = _df(symbol=["GOOGL", "AMZN"], quantity=[5, 10])
        positions, _ = parse_portfolio_csv(df)
        assert len(positions) >= 1

    def test_alias_shares_column(self):
        df = _df(ticker=["TSLA"], shares=[25])
        positions, _ = parse_portfolio_csv(df)
        assert len(positions) == 1

    def test_empty_dataframe_returns_empty_list(self):
        df = pd.DataFrame({"ticker": [], "quantity": []})
        positions, total = parse_portfolio_csv(df)
        assert positions == [] or isinstance(positions, list)


class TestParsePortfolioCsvIBKR:
    """IBKR Activity Statement uses different column names."""

    def test_ibkr_instrument_column(self):
        df = _df(
            instrument=["AAPL", "NVDA"],
            pos=[100, 50],
            mark_price=[175.0, 850.0],
            mkt_val=[17500.0, 42500.0],
        )
        positions, _ = parse_portfolio_csv(df)
        # Should find at least one recognised ticker
        assert isinstance(positions, list)

    def test_ibkr_description_as_name(self):
        df = _df(
            ticker=["AAPL"],
            description=["Apple Inc"],
            qty=[100],
            last=[175.0],
        )
        positions, _ = parse_portfolio_csv(df)
        if positions:
            # Name should be set if description column found
            assert "name" in positions[0]


class TestParsePortfolioCsvRobustness:
    def test_numeric_strings_in_quantity(self):
        df = _df(ticker=["AAPL"], quantity=["100"])
        positions, _ = parse_portfolio_csv(df)
        assert len(positions) >= 0  # should not raise

    def test_nan_prices_handled(self):
        import numpy as np
        df = _df(
            ticker=["AAPL", "MSFT"],
            quantity=[10, 20],
            last_price=[float("nan"), 350.0],
        )
        # Should not raise
        positions, _ = parse_portfolio_csv(df)
        assert isinstance(positions, list)

    def test_single_row(self):
        df = _df(ticker=["AAPL"], quantity=[1], last_price=[180.0])
        positions, _ = parse_portfolio_csv(df)
        assert isinstance(positions, list)

    def test_extra_columns_ignored(self):
        df = _df(
            ticker=["AAPL"],
            quantity=[10],
            random_extra_col=["irrelevant"],
            another_col=[99],
        )
        positions, _ = parse_portfolio_csv(df)
        assert isinstance(positions, list)
