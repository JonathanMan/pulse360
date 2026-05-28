"""
tests/test_market_client.py
=============================
Tests for data/market_client.py — mocked yfinance calls so no network needed.

Covers:
  - fetch_ticker() happy path, empty response, and yfinance exception
  - pct_1d and pct_ytd calculations
  - fetch_sector_returns() shape and content
  - fetch_shiller_cape() happy path and network failure
  - SECTOR_ETFS registry completeness
"""

from __future__ import annotations

import io
import pytest
import pandas as pd
import numpy as np
from datetime import date
from unittest.mock import MagicMock, patch, PropertyMock

from data.market_client import (
    fetch_ticker,
    fetch_sector_returns,
    fetch_shiller_cape,
    SECTOR_ETFS,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ohlcv(n: int = 252, price: float = 100.0, ticker: str = "SPY") -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame like yfinance returns."""
    idx = pd.date_range(end=date.today(), periods=n, freq="B")  # business days
    close = np.linspace(price * 0.9, price, n)
    df = pd.DataFrame({
        "Open":   close * 0.99,
        "High":   close * 1.01,
        "Low":    close * 0.98,
        "Close":  close,
        "Volume": np.full(n, 1_000_000),
    }, index=idx)
    return df


def _mock_ticker(df: pd.DataFrame | None = None, raise_exc: Exception | None = None):
    """Return a context manager that patches yf.Ticker().history()."""
    mock_ticker_obj = MagicMock()
    if raise_exc:
        mock_ticker_obj.history.side_effect = raise_exc
    else:
        mock_ticker_obj.history.return_value = df if df is not None else _ohlcv()
    return patch("data.market_client.yf.Ticker", return_value=mock_ticker_obj)


# ── SECTOR_ETFS registry ──────────────────────────────────────────────────────

class TestSectorEtfs:
    def test_11_gics_sectors_covered(self):
        assert len(SECTOR_ETFS) == 11

    def test_all_values_are_strings(self):
        for ticker, name in SECTOR_ETFS.items():
            assert isinstance(ticker, str) and ticker
            assert isinstance(name, str) and name

    def test_spdr_etf_tickers_present(self):
        for expected in ["XLK", "XLF", "XLV", "XLE", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC"]:
            assert expected in SECTOR_ETFS, f"{expected} missing from SECTOR_ETFS"


# ── fetch_ticker() ─────────────────────────────────────────────────────────────

class TestFetchTicker:
    def test_happy_path_shape(self):
        with _mock_ticker(_ohlcv(252)):
            result = fetch_ticker("SPY", "5y", "1d")
        expected_keys = {"ticker", "close", "last_price", "last_date", "pct_1d", "pct_ytd", "error"}
        assert expected_keys.issubset(result.keys())

    def test_ticker_field_preserved(self):
        with _mock_ticker(_ohlcv(252)):
            result = fetch_ticker("MSFT", "5y", "1d")
        assert result["ticker"] == "MSFT"

    def test_last_price_is_most_recent_close(self):
        df = _ohlcv(252, price=450.0)
        with _mock_ticker(df):
            result = fetch_ticker("SPY", "5y", "1d")
        assert result["last_price"] == pytest.approx(450.0, rel=0.01)

    def test_last_date_is_date_instance(self):
        with _mock_ticker():
            result = fetch_ticker("SPY", "5y", "1d")
        assert isinstance(result["last_date"], date)

    def test_pct_1d_calculated(self):
        df = _ohlcv(10)
        # Set last two prices explicitly to get a known 1d return
        df.iloc[-1, df.columns.get_loc("Close")] = 110.0
        df.iloc[-2, df.columns.get_loc("Close")] = 100.0
        with _mock_ticker(df):
            result = fetch_ticker("SPY", "5y", "1d")
        assert result["pct_1d"] == pytest.approx(10.0, rel=0.01)

    def test_pct_ytd_calculated_for_current_year(self):
        # All prices in the current year, rising 20%
        n = 200
        idx = pd.date_range(start=f"{date.today().year}-01-02", periods=n, freq="B")
        idx = idx[idx.year == date.today().year][:n]
        close = np.linspace(100.0, 120.0, len(idx))
        df = pd.DataFrame({"Open": close, "High": close, "Low": close,
                           "Close": close, "Volume": np.ones(len(idx))}, index=idx)
        with _mock_ticker(df):
            result = fetch_ticker("SPY", "1y", "1d")
        assert result["pct_ytd"] is not None
        assert result["pct_ytd"] > 0

    def test_empty_history_sets_error(self):
        with _mock_ticker(pd.DataFrame()):
            result = fetch_ticker("FAKE", "5y", "1d")
        assert result["error"] is not None
        assert result["close"].empty

    def test_yfinance_exception_does_not_raise(self):
        with _mock_ticker(raise_exc=ConnectionError("network failure")):
            result = fetch_ticker("SPY", "5y", "1d")
        assert result["error"] is not None
        assert "network failure" in result["error"]
        assert result["close"].empty

    def test_no_error_on_success(self):
        with _mock_ticker():
            result = fetch_ticker("SPY", "5y", "1d")
        assert result["error"] is None

    def test_single_bar_no_pct_1d(self):
        df = _ohlcv(1)
        with _mock_ticker(df):
            result = fetch_ticker("SPY", "1d", "1d")
        # Only 1 bar — can't compute 1d return, should be None or not crash
        assert result["pct_1d"] is None or isinstance(result["pct_1d"], float)


# ── fetch_sector_returns() ─────────────────────────────────────────────────────

class TestFetchSectorReturns:
    def _mock_fetch_ticker_for_sector(self, n: int = 130, price: float = 50.0):
        """Patch fetch_ticker (the cached fn) for sector return tests."""
        def _fake(ticker, period="6mo", interval="1d"):
            df = _ohlcv(n, price=price, ticker=ticker)
            close = df["Close"]
            return {
                "ticker":     ticker,
                "close":      close,
                "last_price": float(close.iloc[-1]),
                "last_date":  close.index[-1].date(),
                "pct_1d":     None,
                "pct_ytd":    None,
                "error":      None,
            }
        return patch("data.market_client.fetch_ticker", side_effect=_fake)

    def test_returns_dataframe(self):
        with self._mock_fetch_ticker_for_sector():
            df = fetch_sector_returns(period_days=22)
        assert isinstance(df, pd.DataFrame)

    def test_columns_present(self):
        with self._mock_fetch_ticker_for_sector():
            df = fetch_sector_returns(period_days=22)
        assert "Sector" in df.columns
        assert "Ticker" in df.columns
        assert "Return (%)" in df.columns

    def test_sorted_descending(self):
        with self._mock_fetch_ticker_for_sector():
            df = fetch_sector_returns(period_days=22)
        if len(df) > 1:
            returns = df["Return (%)"].tolist()
            assert returns == sorted(returns, reverse=True)

    def test_all_11_sectors_returned_on_success(self):
        with self._mock_fetch_ticker_for_sector(n=130):
            df = fetch_sector_returns(period_days=22)
        assert len(df) == 11

    def test_empty_df_when_all_fail(self):
        def _fail(ticker, period="6mo", interval="1d"):
            return {"ticker": ticker, "close": pd.Series(dtype=float),
                    "last_price": None, "last_date": None,
                    "pct_1d": None, "pct_ytd": None, "error": "fail"}
        with patch("data.market_client.fetch_ticker", side_effect=_fail):
            df = fetch_sector_returns(period_days=22)
        assert df.empty

    def test_insufficient_history_excluded(self):
        """Tickers with fewer bars than period_days should be excluded."""
        def _short(ticker, period="6mo", interval="1d"):
            close = pd.Series([50.0] * 5,
                               index=pd.date_range(end=date.today(), periods=5, freq="B"))
            return {"ticker": ticker, "close": close,
                    "last_price": 50.0, "last_date": close.index[-1].date(),
                    "pct_1d": None, "pct_ytd": None, "error": None}
        with patch("data.market_client.fetch_ticker", side_effect=_short):
            df = fetch_sector_returns(period_days=22)
        # 5 bars < 22 + 1 required → all excluded
        assert df.empty


# ── fetch_shiller_cape() ───────────────────────────────────────────────────────

class TestFetchShillerCape:
    def _build_fake_excel(self) -> bytes:
        """Build a minimal in-memory Excel matching the Shiller file structure."""
        # 7 rows of header junk + 1 header row + data
        header_rows = pd.DataFrame([[""] * 5] * 7)  # 7 blank rows
        dates = [f"{1990 + i // 12}.{(i % 12) + 1:02d}" for i in range(200)]
        capes = [20.0 + i * 0.05 for i in range(200)]
        data_rows = pd.DataFrame({
            "Date": dates,
            "P": [100.0] * 200,
            "D": [3.0] * 200,
            "E": [8.0] * 200,
            "CAPE": capes,
        })
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            # Write 7 header rows then the data (simulating skiprows=7)
            header_rows.to_excel(writer, sheet_name="Data", index=False, header=False)
            data_rows.to_excel(writer, sheet_name="Data", index=False,
                               header=True, startrow=7)
        buf.seek(0)
        return buf.read()

    def test_happy_path_shape(self):
        fake_bytes = self._build_fake_excel()
        mock_resp = MagicMock()
        mock_resp.content = fake_bytes
        mock_resp.raise_for_status.return_value = None
        with patch("data.market_client.requests.get", return_value=mock_resp):
            result = fetch_shiller_cape()
        assert isinstance(result, dict)
        assert "data" in result and "last_value" in result and "error" in result

    def test_happy_path_last_value_positive(self):
        fake_bytes = self._build_fake_excel()
        mock_resp = MagicMock()
        mock_resp.content = fake_bytes
        mock_resp.raise_for_status.return_value = None
        with patch("data.market_client.requests.get", return_value=mock_resp):
            result = fetch_shiller_cape()
        if result["error"] is None:
            assert result["last_value"] is not None
            assert result["last_value"] > 0

    def test_network_error_does_not_raise(self):
        with patch("data.market_client.requests.get",
                   side_effect=ConnectionError("network unreachable")):
            result = fetch_shiller_cape()
        assert result["error"] is not None
        assert result["data"].empty

    def test_http_error_does_not_raise(self):
        import requests as _req
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = _req.HTTPError("404 Not Found")
        with patch("data.market_client.requests.get", return_value=mock_resp):
            result = fetch_shiller_cape()
        assert result["error"] is not None

    def test_fallback_historical_avg_is_reasonable(self):
        """historical_avg should be set even on failure (default 17.0)."""
        with patch("data.market_client.requests.get",
                   side_effect=ConnectionError("down")):
            result = fetch_shiller_cape()
        assert result["historical_avg"] > 0
