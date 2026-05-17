"""
components/forecasters.py
==========================
Forecaster signal data, persistence, and consensus computation for Pie360.

Responsibilities
----------------
  • DEFAULT_SIGNALS — the canonical static forecaster dataset
  • Signal style constants (colors, badges, ordering)
  • Supabase persistence: load/save signals to macro_signals table
  • get_signals() — session_state → Supabase → DEFAULT_SIGNALS waterfall
  • compute_consensus() — plain count or credibility-weighted count
  • _is_stale() — staleness check for source citation dates

Public API
----------
    from components.forecasters import (
        get_signals, save_signals, compute_consensus,
        DEFAULT_SIGNALS, SIGNAL_STYLES, BIAS_STYLES,
        SIGNAL_ORDER, GROUP_LABELS, FORECASTER_NAMES,
    )
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import streamlit as st

from components.supabase_client import get_client

# ── Staleness config ───────────────────────────────────────────────────────────
STALE_DAYS = 14   # signal older than this triggers "⚠️ Review needed"


def is_stale(statement_date_str: str) -> bool:
    """Return True if statement_date is more than STALE_DAYS days ago."""
    if not statement_date_str:
        return False
    try:
        dt = datetime.strptime(statement_date_str, "%B %d, %Y").date()
        return (date.today() - dt).days > STALE_DAYS
    except ValueError:
        return False


# ── Canonical forecaster list ─────────────────────────────────────────────────
# Bias and specialty are stable long-run attributes; signal and summary are
# refreshed weekly via the Anthropic web-search call.

FORECASTER_NAMES: list[str] = [
    "Tom Lee",
    "Ed Yardeni",
    "Jeremy Siegel",
    "Campbell Harvey",
    "Warren Buffett",
    "Nouriel Roubini",
    "Jeremy Grantham",
    "Michael Burry",
    "Stanley Druckenmiller",
]

DEFAULT_SIGNALS: dict[str, Any] = {
    "last_updated": "May 4, 2026",
    "forecasters": [
        {
            "name": "Tom Lee",
            "specialty": "Equity market & sentiment cycles",
            "bias": "Perma-bull",
            "signal": "Risk on",
            "source_url": "",
            "statement_date": "May 4, 2026",
            "summary": (
                "Lee sees strong earnings growth, resilient consumer spending, and improving sentiment "
                "as tailwinds for equities. He remains one of Wall Street's most vocal bulls on the "
                "S&P 500 reaching new highs."
            ),
        },
        {
            "name": "Ed Yardeni",
            "specialty": "Corporate earnings & productivity growth",
            "bias": "Perma-bull",
            "signal": "Risk on",
            "source_url": "",
            "statement_date": "May 4, 2026",
            "summary": (
                "Yardeni argues that U.S. corporate productivity gains — driven by AI and technology — "
                "are underpriced by the market. He sees earnings growth as durable enough to justify "
                "current valuations."
            ),
        },
        {
            "name": "Jeremy Siegel",
            "specialty": "Long-run equity returns",
            "bias": "Perma-bull",
            "signal": "Risk on",
            "source_url": "",
            "statement_date": "May 4, 2026",
            "summary": (
                "Siegel's long-run thesis holds: equities beat every other asset class over time, and "
                "investors who exit miss the recoveries that matter most. He cautions against letting "
                "short-term fear drive long-term decisions."
            ),
        },
        {
            "name": "Campbell Harvey",
            "specialty": "Yield curve indicator",
            "bias": "Neutral",
            "signal": "Risk on",
            "source_url": "",
            "statement_date": "May 4, 2026",
            "summary": (
                "Harvey's yield curve has re-steepened, which historically marks the window where equities "
                "can recover. He notes the recession signal has faded, though the all-clear isn't unconditional."
            ),
        },
        {
            "name": "Warren Buffett",
            "specialty": "Long-term value & market valuation",
            "bias": "Neutral",
            "signal": "Caution",
            "source_url": "",
            "statement_date": "May 4, 2026",
            "summary": (
                "Berkshire's cash pile has hit record highs and Buffett has slowed buybacks — his clearest "
                "signal that he finds few things worth buying at current prices. His market cap-to-GDP "
                "indicator remains in overvalued territory."
            ),
        },
        {
            "name": "Nouriel Roubini",
            "specialty": "Systemic crisis detection",
            "bias": "Perma-bear",
            "signal": "Caution",
            "source_url": "",
            "statement_date": "May 4, 2026",
            "summary": (
                "Debt levels and stagflation risk are elevated, but not yet a 2008 scenario. Roubini warns "
                "the tools to fight the next crisis are already depleted."
            ),
        },
        {
            "name": "Jeremy Grantham",
            "specialty": "Bubble identification",
            "bias": "Perma-bear",
            "signal": "Risk off",
            "source_url": "",
            "statement_date": "May 4, 2026",
            "summary": (
                "Valuations remain historically extreme. Grantham sees a third bubble in 25 years still "
                "deflating — real assets and emerging markets are his relative shelter."
            ),
        },
        {
            "name": "Michael Burry",
            "specialty": "Contrarian deep value",
            "bias": "Contrarian",
            "signal": "Risk off",
            "source_url": "",
            "statement_date": "May 4, 2026",
            "summary": (
                "Burry has flagged index concentration and passive investment flows as a systemic risk. "
                "He's positioned short on broad indices and long on specific undervalued names."
            ),
        },
        {
            "name": "Stanley Druckenmiller",
            "specialty": "Macro timing & liquidity",
            "bias": "Flexible",
            "signal": "Risk off",
            "source_url": "",
            "statement_date": "May 4, 2026",
            "summary": (
                "Druckenmiller is watching Fed policy and liquidity cycles closely. He's reduced equity "
                "exposure and flagged that the easy money environment is structurally over."
            ),
        },
    ],
}


# ── Display constants ─────────────────────────────────────────────────────────

SIGNAL_STYLES: dict[str, dict[str, str]] = {
    "Risk on":  {"bg": "#EAF3DE", "text": "#3B6D11", "bar": "#639922",  "label_color": "#3B6D11"},
    "Caution":  {"bg": "#FAEEDA", "text": "#854F0B", "bar": "#EF9F27",  "label_color": "#854F0B"},
    "Risk off": {"bg": "#FCEBEB", "text": "#A32D2D", "bar": "#E24B4A",  "label_color": "#A32D2D"},
}

BIAS_STYLES: dict[str, dict[str, str]] = {
    "Perma-bull":  {"color": "#2a6ebb", "bg": "#e8f1fb"},
    "Perma-bear":  {"color": "#a32d2d", "bg": "#faeaea"},
    "Neutral":     {"color": "#5f5e5a", "bg": "#f0f0ee"},
    "Contrarian":  {"color": "#7a4d00", "bg": "#fdf0dc"},
    "Flexible":    {"color": "#3a5f3a", "bg": "#e8f5e8"},
}

SIGNAL_ORDER: list[str]         = ["Risk on", "Caution", "Risk off"]
GROUP_LABELS: dict[str, str]    = {"Risk on": "Risk on", "Caution": "Caution", "Risk off": "Risk off"}


# ── Supabase persistence ───────────────────────────────────────────────────────

_SIGNALS_TABLE  = "macro_signals"
_SIGNALS_ROW_ID = 1


@st.cache_data(ttl=300, show_spinner=False)
def _load_signals_from_db() -> dict | None:
    """Fetch latest signals from Supabase. Returns None if unavailable."""
    try:
        row = (
            get_client()
            .table(_SIGNALS_TABLE)
            .select("signals_json")
            .eq("id", _SIGNALS_ROW_ID)
            .single()
            .execute()
        )
        if row.data:
            return row.data["signals_json"]
    except Exception:
        pass
    return None


def save_signals(signals: dict) -> None:
    """Upsert signals to Supabase and bust the 5-min read cache."""
    try:
        get_client().table(_SIGNALS_TABLE).upsert({
            "id":           _SIGNALS_ROW_ID,
            "signals_json": signals,
        }).execute()
        _load_signals_from_db.clear()
    except Exception as exc:
        st.warning(f"Could not save signals to database: {exc}")


def get_signals() -> dict:
    """
    Return the current forecaster signals.
    Waterfall: session_state → Supabase DB → DEFAULT_SIGNALS.
    """
    if "macro_signals" in st.session_state:
        return st.session_state.macro_signals
    db_signals = _load_signals_from_db()
    if db_signals:
        st.session_state.macro_signals = db_signals
        return db_signals
    return DEFAULT_SIGNALS


# ── Consensus computation ──────────────────────────────────────────────────────

def compute_consensus(
    forecasters: list[dict],
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """
    Compute consensus signal counts (or weighted scores) across forecasters.

    Args:
        forecasters: list of forecaster dicts from signals["forecasters"]
        weights:     {forecaster_name: weight_float} — if None, equal weight (1.0 each)
                     Enables T3-3 per-user credibility weights.

    Returns:
        {"Risk on": float, "Caution": float, "Risk off": float}
        Values are raw counts when weights=None, weighted scores otherwise.
    """
    counts: dict[str, float] = {"Risk on": 0.0, "Caution": 0.0, "Risk off": 0.0}
    for f in forecasters:
        signal = f.get("signal", "Caution")
        if signal in counts:
            w = float(weights.get(f["name"], 1.0)) if weights else 1.0
            counts[signal] += w
    return counts
