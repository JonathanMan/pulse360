"""
Pulse360 — Portfolio Analyser AI Module
=========================================
Handles all Claude API calls for the Portfolio Analyser tab.

Two entry points:
  • stream_portfolio_from_screenshot()  → accepts image bytes, uses Claude vision
    to extract positions and generate a macro-aware analysis in one pass.
  • stream_portfolio_from_positions()   → accepts a structured list of positions
    (parsed from CSV or manual entry) and generates the same analysis.

Both functions are streaming generators that yield text chunks for use with
Streamlit's st.write_stream() or manual placeholder.markdown() pattern.

Tone rules (from briefing.md §7):
  • Plain English, not jargon. Written for a smart amateur, not a quant.
  • Probabilistic, not certain.
  • Action-oriented — every flag pairs with a "why it matters" line.
  • Never personalised investment advice. Always end with the disclaimer.
"""

from __future__ import annotations

import base64
import logging
from typing import Generator

import streamlit as st
import anthropic

from ai.prompts import DISCLAIMER

logger = logging.getLogger(__name__)

SONNET = "claude-sonnet-4-5"

# ── Sector mapping for common tickers ────────────────────────────────────────
# Used when analysing CSV/structured data (screenshot path uses Claude vision)

TICKER_SECTORS: dict[str, str] = {
    # Mega-cap tech
    "AAPL":  "Technology",
    "MSFT":  "Technology",
    "GOOGL": "Technology",
    "GOOG":  "Technology",
    "META":  "Technology",
    "AMZN":  "Consumer Discretionary / Cloud",
    "NVDA":  "Semiconductors",
    "TSM":   "Semiconductors",
    "AVGO":  "Semiconductors",
    "CRDO":  "Semiconductors",
    # EV / Auto
    "TSLA":  "EV / Auto Tech",
    "RIVN":  "EV / Auto Tech",
    # Financials
    "JPM":   "Financials",
    "BAC":   "Financials",
    "GS":    "Financials",
    "MS":    "Financials",
    # Healthcare
    "JNJ":   "Healthcare",
    "UNH":   "Healthcare",
    "LLY":   "Healthcare",
    "PFE":   "Healthcare",
    # Energy
    "XOM":   "Energy",
    "CVX":   "Energy",
    # ETFs — broad
    "SPY":   "ETF — S&P 500",
    "QQQ":   "ETF — Nasdaq-100",
    "IWM":   "ETF — Russell 2000",
    "VTI":   "ETF — Total Market",
    "VOO":   "ETF — S&P 500",
    # ETFs — sector
    "SMH":   "ETF — Semiconductors",
    "XLK":   "ETF — Technology",
    "XLF":   "ETF — Financials",
    "XLE":   "ETF — Energy",
    "XLV":   "ETF — Healthcare",
    "XLI":   "ETF — Industrials",
    "XLU":   "ETF — Utilities",
    "XLRE":  "ETF — Real Estate",
    # International / EM
    "CQQQ":  "ETF — China Tech",
    "EEM":   "ETF — Emerging Markets",
    "EFA":   "ETF — Developed ex-US",
    # Fixed income
    "TLT":   "ETF — Long-duration Treasuries",
    "AGG":   "ETF — Investment Grade Bonds",
    "HYG":   "ETF — High-yield Bonds",
    # Commodities / alternatives
    "GLD":   "ETF — Gold",
    "SLV":   "ETF — Silver",
    "USO":   "ETF — Oil",
}


# ─────────────────────────────────────────────────────────────────────────────
# System prompt (shared by both entry points)
# ─────────────────────────────────────────────────────────────────────────────

_PORTFOLIO_SYSTEM = """You are the Pulse360 Portfolio Analyser — an AI layer embedded in an economic cycle \
dashboard that helps a personal investor understand how their holdings align with the current macro environment.

YOUR JOB:
Write a plain-English portfolio analysis that is genuinely useful to a smart amateur investor. \
You are NOT a financial advisor. You are a macro-aware analyst flagging cycle-relevant risks and context.

TONE RULES — follow all of them:
1. Plain English. No jargon unless you define it inline. Write for a smart person, not a quant.
2. Probabilistic. Say "historically underperforms" not "will crash". Name uncertainty.
3. Action-oriented. Every flag must answer "so what?" in one sentence.
4. Short and scannable. Use markdown headers and bullet points throughout.
5. Never give personalised buy/sell advice. Frame everything in general historical/cycle terms.
6. Never fabricate data. Only reference numbers explicitly provided.
7. Never strip or skip the disclaimer — it is appended automatically.

OUTPUT STRUCTURE — use EXACTLY these sections in this order:

## Portfolio snapshot
One-paragraph summary: total value (if known), number of positions, overall character \
(e.g. "growth-heavy tech portfolio", "well-diversified across sectors").

## Macro context
2–3 sentences connecting the current cycle phase and recession probability to what it \
historically means for this type of portfolio. Be specific about the phase.

## Risk flags
3–5 bullet points. Each flag: bold title, one sentence explaining the risk, one sentence \
on why it matters *right now* given the cycle. Ordered most-to-least important.

## Position notes
One bullet per holding. Format: **TICKER** — sector/type — plain English description of \
what the company does — one sentence on its macro sensitivity given the current cycle phase. \
Keep each bullet to 2 sentences max.

## What to watch
2–3 specific macro events or thresholds (from the dashboard data provided) that would most \
affect this portfolio. Name the indicator, the threshold, and what it would mean.

Word budget: aim for ~600 words. The disclaimer is appended automatically — do not include it."""


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build the macro context block injected into every prompt
# ─────────────────────────────────────────────────────────────────────────────

def _macro_context_block(
    cycle_phase: str,
    recession_probability: float,
    traffic_light: str,
    feature_summary: list[dict],
) -> str:
    tl_label = {
        "green":  "LOW (<25%)",
        "yellow": "ELEVATED (25–50%)",
        "red":    "HIGH (≥50%)",
    }.get(traffic_light, traffic_light.upper())

    top_drivers = sorted(feature_summary, key=lambda f: f.get("contribution", 0), reverse=True)[:3]
    drivers_text = "\n".join(
        f"  • {f['name']}: {f.get('signal_description', '')} "
        f"(contrib: {f.get('contribution', 0):.1f}pp)"
        for f in top_drivers
    )

    return f"""
CURRENT PULSE360 DASHBOARD STATE:
  Cycle Phase:           {cycle_phase}
  Recession Probability: {recession_probability:.1f}%  →  {tl_label}

Top model drivers:
{drivers_text}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Entry point 1: Screenshot → Claude vision
# ─────────────────────────────────────────────────────────────────────────────

def stream_portfolio_from_screenshot(
    image_bytes: bytes,
    image_media_type: str,          # e.g. "image/png", "image/jpeg"
    cycle_phase: str,
    recession_probability: float,
    traffic_light: str,
    feature_summary: list[dict],
) -> Generator[str, None, None]:
    """
    Accept a broker portfolio screenshot, extract positions via Claude vision,
    and stream a macro-aware analysis.

    Args:
        image_bytes:       Raw image bytes from st.file_uploader
        image_media_type:  MIME type string, e.g. "image/png"
        cycle_phase:       e.g. "Late Expansion"
        recession_probability: 0–100 float
        traffic_light:     "green" | "yellow" | "red"
        feature_summary:   Top features from recession model (list of dicts)

    Yields:
        Text chunks from Claude Sonnet.
    """
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    macro_block = _macro_context_block(
        cycle_phase, recession_probability, traffic_light, feature_summary
    )

    user_content = [
        {
            "type": "image",
            "source": {
                "type":       "base64",
                "media_type": image_media_type,
                "data":       image_b64,
            },
        },
        {
            "type": "text",
            "text": (
                f"This is a screenshot of a brokerage portfolio positions page.\n\n"
                f"{macro_block}\n\n"
                "Please read all visible positions from the screenshot — including ticker, "
                "company name, quantity, average cost, current price, and unrealised P&L % "
                "where visible — and produce the full portfolio analysis as instructed. "
                "If any column is partially cut off or unclear, note it briefly but still "
                "proceed with what is visible. Do not ask for clarification — make reasonable "
                "inferences and flag any uncertainty inline."
            ),
        },
    ]

    try:
        client = st.session_state.get("_anthropic_client") or _get_client()
        with client.messages.stream(
            model      = SONNET,
            max_tokens = 2048,
            system     = _PORTFOLIO_SYSTEM,
            messages   = [{"role": "user", "content": user_content}],
        ) as stream:
            for chunk in stream.text_stream:
                yield chunk
        yield DISCLAIMER

    except Exception as exc:
        logger.error("stream_portfolio_from_screenshot failed: %s", exc)
        yield f"\n\n⚠️ Analysis unavailable: {exc}{DISCLAIMER}"


# ─────────────────────────────────────────────────────────────────────────────
# Entry point 2: Structured positions list → Claude text
# ─────────────────────────────────────────────────────────────────────────────

def stream_portfolio_from_positions(
    positions: list[dict],          # each: {ticker, name, quantity, avg_price, last_price, pnl_pct}
    total_value: float | None,
    cycle_phase: str,
    recession_probability: float,
    traffic_light: str,
    feature_summary: list[dict],
) -> Generator[str, None, None]:
    """
    Accept a structured list of positions (parsed from CSV or manual entry)
    and stream a macro-aware portfolio analysis.

    Args:
        positions:   List of position dicts. Required key: ticker.
                     Optional: name, quantity, avg_price, last_price, pnl_pct, market_value
        total_value: Total portfolio market value (float) or None
        ...rest:     Current dashboard state

    Yields:
        Text chunks from Claude Sonnet.
    """
    macro_block = _macro_context_block(
        cycle_phase, recession_probability, traffic_light, feature_summary
    )

    # Build positions table
    pos_lines = []
    for p in positions:
        ticker = p.get("ticker", "?")
        sector = TICKER_SECTORS.get(ticker.upper(), "Unknown sector")
        name   = p.get("name", "")
        qty    = p.get("quantity", "")
        avg    = p.get("avg_price", "")
        last   = p.get("last_price", "")
        pnl    = p.get("pnl_pct", "")
        mval   = p.get("market_value", "")

        parts = [f"**{ticker}**"]
        if name:
            parts.append(f"({name})")
        parts.append(f"| Sector: {sector}")
        if qty:
            parts.append(f"| Qty: {qty}")
        if avg:
            parts.append(f"| Avg cost: ${avg}")
        if last:
            parts.append(f"| Last: ${last}")
        if pnl:
            parts.append(f"| Unrealised P&L: {pnl}%")
        if mval:
            parts.append(f"| Market value: ${mval}")
        pos_lines.append("  " + " ".join(str(x) for x in parts))

    positions_text = "\n".join(pos_lines)
    total_text = f"${total_value:,.2f}" if total_value else "Not provided"

    user_prompt = (
        f"{macro_block}\n\n"
        f"PORTFOLIO POSITIONS (total value: {total_text}):\n"
        f"{positions_text}\n\n"
        "Produce the full portfolio analysis as instructed."
    )

    try:
        client = _get_client()
        with client.messages.stream(
            model      = SONNET,
            max_tokens = 2048,
            system     = _PORTFOLIO_SYSTEM,
            messages   = [{"role": "user", "content": user_prompt}],
        ) as stream:
            for chunk in stream.text_stream:
                yield chunk
        yield DISCLAIMER

    except Exception as exc:
        logger.error("stream_portfolio_from_positions failed: %s", exc)
        yield f"\n\n⚠️ Analysis unavailable: {exc}{DISCLAIMER}"


# ─────────────────────────────────────────────────────────────────────────────
# CSV parser — handles IBKR and generic broker formats
# ─────────────────────────────────────────────────────────────────────────────

def parse_portfolio_csv(df) -> tuple[list[dict], float | None]:
    """
    Parse a pandas DataFrame (from st.file_uploader CSV) into a list of
    position dicts and an optional total market value.

    Supports:
      • IBKR Activity Statement export
      • Generic broker CSV with flexible column name matching

    Returns:
        (positions, total_value)
        positions: list of dicts with keys: ticker, name, quantity,
                   avg_price, last_price, pnl_pct, market_value
        total_value: float or None
    """
    import pandas as pd

    # Normalise column names: lowercase, strip whitespace
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    # Column name aliases (IBKR uses different names depending on export type)
    _alias = {
        "ticker":       ["ticker", "symbol", "instrument", "security", "stock"],
        "name":         ["name", "description", "company", "security_name", "financial_instrument"],
        "quantity":     ["quantity", "qty", "position", "shares", "units", "pos"],
        "avg_price":    ["avg_price", "average_cost", "avg_cost", "cost_basis",
                         "average_price", "avg._price", "cost"],
        "last_price":   ["last_price", "last", "price", "market_price", "current_price",
                         "mark_price", "close"],
        "pnl_pct":      ["pnl_pct", "unrealized_p&l_%", "unrealizedpnl%", "unrlzd_p&l_%",
                         "unrealized_pnl_pct", "gain/loss_%", "return_%", "unrlzd_p.l._%",
                         "unrlzd_p&l_percent", "% gain/loss", "pct_gain_loss"],
        "market_value": ["market_value", "mkt_val", "value", "current_value",
                         "market_val", "total_value"],
    }

    def _find_col(key: str) -> str | None:
        for alias in _alias[key]:
            if alias in df.columns:
                return alias
        return None

    col_ticker = _find_col("ticker")
    col_name   = _find_col("name")
    col_qty    = _find_col("quantity")
    col_avg    = _find_col("avg_price")
    col_last   = _find_col("last_price")
    col_pnl    = _find_col("pnl_pct")
    col_mval   = _find_col("market_value")

    if not col_ticker:
        # Try to use first column as ticker
        col_ticker = df.columns[0]

    positions = []
    total_value = None

    for _, row in df.iterrows():
        ticker = str(row.get(col_ticker, "")).strip().upper()

        # Skip header rows, subtotals, and empty rows that sneak in from IBKR exports
        if not ticker or ticker in {"", "TICKER", "SYMBOL", "FINANCIAL INSTRUMENTS", "TOTAL"}:
            continue
        if ticker.startswith("---") or ticker.startswith("Total"):
            # Try to capture total value from subtotal row
            if col_mval and not pd.isna(row.get(col_mval)):
                try:
                    total_value = float(str(row[col_mval]).replace(",", "").replace("$", ""))
                except (ValueError, TypeError):
                    pass
            continue

        def _safe_float(col):
            if col is None:
                return None
            val = row.get(col)
            if val is None or (hasattr(val, "__class__") and val.__class__.__name__ == "float" and str(val) == "nan"):
                return None
            try:
                return round(float(str(val).replace(",", "").replace("$", "").replace("%", "").strip()), 4)
            except (ValueError, TypeError):
                return None

        positions.append({
            "ticker":       ticker,
            "name":         str(row[col_name]).strip() if col_name and not str(row.get(col_name, "")).strip() == "nan" else "",
            "quantity":     _safe_float(col_qty),
            "avg_price":    _safe_float(col_avg),
            "last_price":   _safe_float(col_last),
            "pnl_pct":      _safe_float(col_pnl),
            "market_value": _safe_float(col_mval),
        })

    # Compute total from individual market values if not captured above
    if total_value is None:
        vals = [p["market_value"] for p in positions if p["market_value"] is not None]
        if vals:
            total_value = round(sum(vals), 2)

    return positions, total_value


# ─────────────────────────────────────────────────────────────────────────────
# Internal: shared Anthropic client (mirrors claude_client.py pattern)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
