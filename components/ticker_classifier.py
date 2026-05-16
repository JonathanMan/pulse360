"""
components/ticker_classifier.py
================================
Maps tickers to sector + asset class for the Pie360 rebalancing engine.

Three-tier lookup:
1. TICKER_LOOKUP  — hardcoded table for ETFs and common instruments
2. Sector passthrough — scored stocks already carry a Sector field from the
   Buffett scorer; this module maps that sector string → asset class
3. Claude fallback — for genuinely unknown tickers, calls the Anthropic API
   once and caches the result for the session

Public API
----------
    from components.ticker_classifier import classify_all

    classifications = classify_all(scored, failed)
    # → {"AAPL": {"sector": "Technology", "asset_class": "Equity", "source": "scorer"},
    #    "TLT":  {"sector": "Long-Term Bonds", "asset_class": "Bond", "source": "lookup"},
    #    ...}

Asset classes
-------------
    Equity | Bond | Commodity | Cash | Real Estate | Crypto
"""

from __future__ import annotations

import json
import os

import streamlit as st

# ── Asset class colour palette (used by the UI) ───────────────────────────────
ASSET_CLASS_COLORS: dict[str, str] = {
    "Equity":      "#2563eb",   # blue
    "Bond":        "#059669",   # green
    "Commodity":   "#d97706",   # amber
    "Cash":        "#6b7280",   # grey
    "Real Estate": "#7c3aed",   # purple
    "Crypto":      "#db2777",   # pink
}

# ── Hardcoded lookup: ETFs and well-known non-equity instruments ──────────────
# Individual stocks are NOT listed here — the Buffett scorer provides their
# sector, which is more accurate than any static table.
TICKER_LOOKUP: dict[str, dict[str, str]] = {
    # ── Broad equity ETFs ────────────────────────────────────────────────────
    "SPY":   {"sector": "Broad Equity",       "asset_class": "Equity"},
    "VOO":   {"sector": "Broad Equity",       "asset_class": "Equity"},
    "VTI":   {"sector": "Broad Equity",       "asset_class": "Equity"},
    "IVV":   {"sector": "Broad Equity",       "asset_class": "Equity"},
    "DIA":   {"sector": "Broad Equity",       "asset_class": "Equity"},
    "QQQ":   {"sector": "Technology",         "asset_class": "Equity"},
    "QQQM":  {"sector": "Technology",         "asset_class": "Equity"},
    "IWM":   {"sector": "Small Cap Equity",   "asset_class": "Equity"},
    "VB":    {"sector": "Small Cap Equity",   "asset_class": "Equity"},
    "MDY":   {"sector": "Mid Cap Equity",     "asset_class": "Equity"},

    # ── International equity ─────────────────────────────────────────────────
    "VEA":   {"sector": "International Developed", "asset_class": "Equity"},
    "EFA":   {"sector": "International Developed", "asset_class": "Equity"},
    "VWO":   {"sector": "Emerging Markets",        "asset_class": "Equity"},
    "EEM":   {"sector": "Emerging Markets",        "asset_class": "Equity"},
    "CQQQ":  {"sector": "China Technology",        "asset_class": "Equity"},
    "FXI":   {"sector": "China Equity",            "asset_class": "Equity"},
    "EWJ":   {"sector": "Japan Equity",            "asset_class": "Equity"},

    # ── Sector ETFs ───────────────────────────────────────────────────────────
    "XLK":   {"sector": "Technology",              "asset_class": "Equity"},
    "XLF":   {"sector": "Financials",              "asset_class": "Equity"},
    "XLV":   {"sector": "Healthcare",              "asset_class": "Equity"},
    "XLE":   {"sector": "Energy",                  "asset_class": "Equity"},
    "XLI":   {"sector": "Industrials",             "asset_class": "Equity"},
    "XLP":   {"sector": "Consumer Staples",        "asset_class": "Equity"},
    "XLY":   {"sector": "Consumer Discretionary",  "asset_class": "Equity"},
    "XLU":   {"sector": "Utilities",               "asset_class": "Equity"},
    "XLB":   {"sector": "Materials",               "asset_class": "Equity"},
    "XLRE":  {"sector": "Real Estate",             "asset_class": "Real Estate"},
    "XLC":   {"sector": "Communication Services",  "asset_class": "Equity"},
    "ARKK":  {"sector": "Disruptive Innovation",   "asset_class": "Equity"},
    "ARKW":  {"sector": "Next Generation Internet","asset_class": "Equity"},
    "ARKG":  {"sector": "Genomics",                "asset_class": "Equity"},

    # ── Bond ETFs ─────────────────────────────────────────────────────────────
    "TLT":   {"sector": "Long-Term Bonds",         "asset_class": "Bond"},
    "TLH":   {"sector": "Long-Term Bonds",         "asset_class": "Bond"},
    "EDV":   {"sector": "Long-Term Bonds",         "asset_class": "Bond"},
    "IEF":   {"sector": "Intermediate Bonds",      "asset_class": "Bond"},
    "IEI":   {"sector": "Intermediate Bonds",      "asset_class": "Bond"},
    "SHY":   {"sector": "Short-Term Bonds",        "asset_class": "Bond"},
    "HYG":   {"sector": "High Yield Bonds",        "asset_class": "Bond"},
    "JNK":   {"sector": "High Yield Bonds",        "asset_class": "Bond"},
    "LQD":   {"sector": "Investment Grade Bonds",  "asset_class": "Bond"},
    "AGG":   {"sector": "Aggregate Bonds",         "asset_class": "Bond"},
    "BND":   {"sector": "Aggregate Bonds",         "asset_class": "Bond"},
    "TIPS":  {"sector": "Inflation-Protected Bonds","asset_class": "Bond"},
    "TIP":   {"sector": "Inflation-Protected Bonds","asset_class": "Bond"},
    "EMB":   {"sector": "Emerging Market Bonds",   "asset_class": "Bond"},

    # ── Cash equivalents ──────────────────────────────────────────────────────
    "BIL":   {"sector": "Cash",                    "asset_class": "Cash"},
    "SHV":   {"sector": "Cash",                    "asset_class": "Cash"},
    "SGOV":  {"sector": "Cash",                    "asset_class": "Cash"},
    "VMFXX": {"sector": "Cash",                    "asset_class": "Cash"},

    # ── Commodities ───────────────────────────────────────────────────────────
    "GLD":   {"sector": "Gold",                    "asset_class": "Commodity"},
    "IAU":   {"sector": "Gold",                    "asset_class": "Commodity"},
    "SLV":   {"sector": "Silver",                  "asset_class": "Commodity"},
    "GDX":   {"sector": "Gold Miners",             "asset_class": "Commodity"},
    "USO":   {"sector": "Oil",                     "asset_class": "Commodity"},
    "UCO":   {"sector": "Oil",                     "asset_class": "Commodity"},
    "DBA":   {"sector": "Agriculture",             "asset_class": "Commodity"},
    "DBC":   {"sector": "Broad Commodities",       "asset_class": "Commodity"},
    "PDBC":  {"sector": "Broad Commodities",       "asset_class": "Commodity"},

    # ── Real estate ───────────────────────────────────────────────────────────
    "VNQ":   {"sector": "Real Estate",             "asset_class": "Real Estate"},
    "IYR":   {"sector": "Real Estate",             "asset_class": "Real Estate"},

    # ── Crypto ────────────────────────────────────────────────────────────────
    "BTC-USD": {"sector": "Crypto",               "asset_class": "Crypto"},
    "ETH-USD": {"sector": "Crypto",               "asset_class": "Crypto"},
    "IBIT":    {"sector": "Bitcoin ETF",           "asset_class": "Crypto"},
    "FBTC":    {"sector": "Bitcoin ETF",           "asset_class": "Crypto"},
    "GBTC":    {"sector": "Bitcoin Trust",         "asset_class": "Crypto"},
}

# ── Sector string → asset class (for stocks scored by the Buffett engine) ─────
# These sector strings match what score_ticker_cached returns in s["Sector"].
SECTOR_TO_ASSET_CLASS: dict[str, str] = {
    "Technology":              "Equity",
    "Healthcare":              "Equity",
    "Financials":              "Equity",
    "Financial Services":      "Equity",
    "Consumer Discretionary":  "Equity",
    "Consumer Cyclical":       "Equity",
    "Consumer Staples":        "Equity",
    "Consumer Defensive":      "Equity",
    "Energy":                  "Equity",
    "Utilities":               "Equity",
    "Materials":               "Equity",
    "Basic Materials":         "Equity",
    "Industrials":             "Equity",
    "Real Estate":             "Real Estate",
    "Communication Services":  "Equity",
    "Communication":           "Equity",
    "Unknown":                 "Equity",   # default for unrecognised scored stocks
    "—":                       "Equity",
}


# ── Claude fallback ───────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _classify_via_claude(ticker: str, company: str) -> dict[str, str]:
    """
    Ask Claude to classify a ticker it doesn't recognise.
    Cached for 1 hour — never called for tickers in TICKER_LOOKUP or with
    a known sector from the Buffett scorer.

    Returns {"sector": str, "asset_class": str, "source": "claude"}
    Falls back gracefully if the API is unavailable.
    """
    try:
        import anthropic
        api_key = (
            st.secrets.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY", "")
        )
        if not api_key:
            raise ValueError("No Anthropic API key")

        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            f'Classify the financial instrument with ticker "{ticker}" '
            f'(company/name: "{company or ticker}") into:\n'
            '1. sector — a short descriptive sector name (e.g. "Technology", '
            '"Healthcare", "Long-Term Bonds", "Gold", "Cash", "Crypto")\n'
            '2. asset_class — exactly one of: Equity | Bond | Commodity | Cash | '
            'Real Estate | Crypto\n\n'
            'Respond ONLY with a JSON object, no explanation:\n'
            '{"sector": "...", "asset_class": "..."}'
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip any markdown fences Claude might add
        raw = raw.strip("` \n").lstrip("json").strip()
        parsed = json.loads(raw)
        sector      = str(parsed.get("sector", "Unknown")).strip()
        asset_class = str(parsed.get("asset_class", "Equity")).strip()
        # Validate asset_class is one of the allowed values
        valid_classes = {"Equity", "Bond", "Commodity", "Cash", "Real Estate", "Crypto"}
        if asset_class not in valid_classes:
            asset_class = "Equity"
        return {"sector": sector, "asset_class": asset_class, "source": "claude"}
    except Exception:
        return {"sector": "Unknown", "asset_class": "Equity", "source": "fallback"}


# ── Public API ────────────────────────────────────────────────────────────────

def classify_ticker(
    ticker: str,
    sector_from_scorer: str | None = None,
    company: str = "",
) -> dict[str, str]:
    """
    Classify a single ticker.

    Args:
        ticker:             Uppercase ticker string.
        sector_from_scorer: Sector string already provided by the Buffett
                            scorer (s["Sector"]). If given and recognised,
                            the hardcoded lookup and Claude are skipped.
        company:            Company name — used as context for the Claude
                            fallback only.

    Returns:
        {"sector": str, "asset_class": str, "source": "scorer"|"lookup"|"claude"|"fallback"}
    """
    ticker = ticker.upper().strip()

    # 1. Hardcoded lookup (ETFs and known instruments)
    if ticker in TICKER_LOOKUP:
        result = TICKER_LOOKUP[ticker].copy()
        result["source"] = "lookup"
        return result

    # 2. Sector passthrough from Buffett scorer
    if sector_from_scorer and sector_from_scorer not in ("—", "", None):
        asset_class = SECTOR_TO_ASSET_CLASS.get(sector_from_scorer, "Equity")
        return {
            "sector":      sector_from_scorer,
            "asset_class": asset_class,
            "source":      "scorer",
        }

    # 3. Claude fallback for unknown tickers
    return _classify_via_claude(ticker, company)


def classify_all(
    scored: list[dict],
    failed: list[str],
) -> dict[str, dict[str, str]]:
    """
    Classify every ticker in the watchlist.

    Args:
        scored: list of scored stock dicts (each has "Ticker", "Sector", "Company")
        failed: list of ticker strings that couldn't be Buffett-scored (ETFs, etc.)

    Returns:
        dict mapping uppercase ticker → {"sector", "asset_class", "source"}
    """
    result: dict[str, dict[str, str]] = {}

    for s in scored:
        ticker = str(s.get("Ticker", "")).upper()
        if not ticker:
            continue
        result[ticker] = classify_ticker(
            ticker,
            sector_from_scorer=s.get("Sector"),
            company=s.get("Company", ""),
        )

    for ticker in failed:
        ticker = ticker.upper().strip()
        if not ticker or ticker in result:
            continue
        result[ticker] = classify_ticker(ticker, company="")

    return result
