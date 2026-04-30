"""
Pulse360 — Claude API Client
==============================
Handles all Anthropic API calls for the AI layer:
  • get_daily_briefing()          → cached 6h, returns markdown string
  • get_investment_implications() → cached 2h per tab, returns prose string
  • stream_chat_response()        → streaming generator for the chat sidebar
  • stream_briefing_section()     → streaming generator for AI Research Desk sections
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from typing import Generator, Optional

import streamlit as st
import anthropic

from ai.prompts import (
    BRIEFING_SYSTEM,
    DISCLAIMER,
    IMPLICATIONS_SYSTEM,
    build_briefing_prompt,
    build_chat_system_prompt,
    build_implications_prompt,
)

logger = logging.getLogger(__name__)

SONNET  = "claude-sonnet-4-5"
HAIKU   = "claude-haiku-4-5-20251001"


@st.cache_resource(show_spinner=False)
def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])


# ─────────────────────────────────────────────────────────────────────────────
# Daily briefing  (cached 6 hours — one API call per 6h window)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=21600, show_spinner=False)   # 6 hours
def get_daily_briefing(
    date_str: str,
    cycle_phase: str,
    phase_confidence: str,
    recession_probability: float,
    traffic_light: str,
    feature_contributions: list[dict],
    lei_growth: Optional[float],
    unrate: Optional[float],
    nber_active: bool,
    recent_crossings: Optional[list[str]] = None,
    recent_releases: Optional[list[str]] = None,
) -> str:
    """
    Generate the daily macro briefing via Claude Sonnet.
    Cached for 6 hours — will not re-call the API within that window.

    Returns:
        Markdown string (the briefing + disclaimer), or an error message.
    """
    user_prompt = build_briefing_prompt(
        date_str              = date_str,
        cycle_phase           = cycle_phase,
        phase_confidence      = phase_confidence,
        recession_probability = recession_probability,
        traffic_light         = traffic_light,
        feature_contributions = feature_contributions,
        lei_growth            = lei_growth,
        unrate                = unrate,
        nber_active           = nber_active,
        recent_crossings      = recent_crossings,
        recent_releases       = recent_releases,
    )

    try:
        client   = _get_client()
        response = client.messages.create(
            model      = SONNET,
            max_tokens = 1024,
            system     = BRIEFING_SYSTEM,
            messages   = [{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text.strip()
        return text + DISCLAIMER

    except Exception as exc:
        logger.error("get_daily_briefing failed: %s", exc)
        return f"⚠️ Briefing unavailable: {exc}\n\n{DISCLAIMER}"


# ─────────────────────────────────────────────────────────────────────────────
# Investment Implications  (cached 2 hours per tab)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=7200, show_spinner=False)   # 2 hours
def get_investment_implications(
    tab_key: str,
    cycle_phase: str,
    recession_probability: float,
    traffic_light: str,
    tab_readings: dict[str, str],
    phase_notes: Optional[str] = None,
) -> str:
    """
    Generate the Investment Implications callout for a specific tab.
    Cached for 2 hours — readings won't change faster than that.

    Args:
        tab_key:     One of: macro, growth, labor, inflation, monetary,
                     markets, housing, global
        tab_readings: Dict of {indicator_label: formatted_value_string}
                     e.g. {"ISM Manufacturing PMI (NAPM)": "48.2 — contraction"}

    Returns:
        Prose string (3–4 sentences + disclaimer), or an error message.
    """
    user_prompt = build_implications_prompt(
        tab_key               = tab_key,
        cycle_phase           = cycle_phase,
        recession_probability = recession_probability,
        traffic_light         = traffic_light,
        tab_readings          = tab_readings,
        phase_notes           = phase_notes,
    )

    try:
        client   = _get_client()
        response = client.messages.create(
            model      = HAIKU,
            max_tokens = 300,
            system     = IMPLICATIONS_SYSTEM,
            messages   = [{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text.strip()
        return text + DISCLAIMER

    except Exception as exc:
        logger.error("get_investment_implications(%s) failed: %s", tab_key, exc)
        return f"⚠️ Implications unavailable: {exc}\n\n{DISCLAIMER}"


# ─────────────────────────────────────────────────────────────────────────────
# Chat sidebar  (streaming, no cache — always live)
# ─────────────────────────────────────────────────────────────────────────────

def stream_scenario_analysis(
    scenario_inputs: list[dict],
    probability: float,
    traffic_light: str,
    cycle_phase: str,
) -> Generator[str, None, None]:
    """
    Stream a professional macro interpretation of a hypothetical scenario.

    Args:
        scenario_inputs: list of dicts with keys:
            name, weight, formatted_value, stress, contribution, description
        probability:   model output 0–100
        traffic_light: "green" | "yellow" | "red"
        cycle_phase:   e.g. "Mid Expansion"

    Yields:
        Text chunks as they stream from Claude Haiku.
    """
    lines = "\n".join([
        f"  • {inp['name']} ({inp['weight']*100:.0f}% weight): "
        f"{inp['formatted_value']} — stress {inp['stress']:.2f} — {inp['description']}"
        for inp in scenario_inputs
    ])

    user_prompt = (
        f"Scenario inputs:\n{lines}\n\n"
        f"Model output:\n"
        f"  • Recession probability: {probability:.1f}%\n"
        f"  • Traffic light: {traffic_light.upper()}\n"
        f"  • Cycle phase: {cycle_phase}\n\n"
        "Provide a 3–4 sentence professional macro interpretation. Cover: "
        "(1) which inputs are driving the signal most, "
        "(2) what this combination suggests about the economic outlook, "
        "(3) key risks and what to watch for next. "
        "Plain prose, no bullet points, probabilistic not certain."
    )

    system_prompt = (
        "You are the Pulse360 macro analysis engine. You interpret economic indicator "
        "scenarios for professional investors and macro analysts. Write in plain English — "
        "analyst tone, action-oriented, probabilistic not certain. 3–4 sentences max. "
        "No bullet points. Never give specific buy/sell advice. "
        "Always end with a one-sentence reminder that this is educational analysis, "
        "not investment advice."
    )

    try:
        client = _get_client()
        with client.messages.stream(
            model      = HAIKU,
            max_tokens = 350,
            system     = system_prompt,
            messages   = [{"role": "user", "content": user_prompt}],
        ) as stream:
            for chunk in stream.text_stream:
                yield chunk
    except Exception as exc:
        logger.error("stream_scenario_analysis failed: %s", exc)
        yield f"\n\n⚠️ Analysis unavailable: {exc}"


def stream_chat_response(
    messages: list[dict],               # [{role: user|assistant, content: str}, ...]
    cycle_phase: str,
    recession_probability: float,
    traffic_light: str,
    feature_summary: list[dict],
    active_tab: str,
    lei_growth: Optional[float],
) -> Generator[str, None, None]:
    """
    Stream a chat response from Claude Haiku.

    Args:
        messages:     Conversation history (last 5 turns max, enforced by caller)
        ...rest:      Current dashboard state, injected into system prompt

    Yields:
        Text chunks as they stream from the API.
    """
    system_prompt = build_chat_system_prompt(
        cycle_phase           = cycle_phase,
        recession_probability = recession_probability,
        traffic_light         = traffic_light,
        feature_summary       = feature_summary,
        active_tab            = active_tab,
        lei_growth            = lei_growth,
    )

    try:
        client = _get_client()
        with client.messages.stream(
            model      = HAIKU,
            max_tokens = 512,
            system     = system_prompt,
            messages   = messages[-10:],   # cap at 10 turns to control context cost
        ) as stream:
            for text_chunk in stream.text_stream:
                yield text_chunk

    except Exception as exc:
        logger.error("stream_chat_response failed: %s", exc)
        yield f"\n\n⚠️ Chat unavailable: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# Helper: format feature contributions for prompt injection
# ─────────────────────────────────────────────────────────────────────────────

def format_features_for_prompt(features: list) -> list[dict]:
    """
    Convert FeatureContribution dataclass instances to plain dicts
    for JSON-serialisable prompt injection (required for @st.cache_data).
    """
    return [
        {
            "name":              f.name,
            "series_id":         f.series_id,
            "weight":            f.weight,
            "current_value":     f.current_value,
            "stress_score":      f.stress_score,
            "contribution":      f.contribution,
            "signal_description": f.signal_description,
        }
        for f in features
    ]


# ─────────────────────────────────────────────────────────────────────────────
# AI Research Desk — generic streaming section runner
# ─────────────────────────────────────────────────────────────────────────────

_BRIEFING_SYSTEM = """You are the Pulse360 AI Research Desk engine.
You produce high-signal, structured financial research for a sophisticated personal investor.

RULES:
1. Be specific and data-grounded. Reference real tickers, real values, real sources where possible.
2. Be probabilistic — "historically leads to" not "will cause".
3. Structure your response clearly with the sections and format requested in the prompt.
4. Always cite sources inline (e.g. [Finviz], [WhaleWisdom], [FRED], [Reuters]) when referencing data.
5. Never give personalised investment advice. Frame everything as research and historical context.
6. Be concise but complete — cover every output field the prompt requests.
7. End every response with:
   *Educational research only — not personalised investment advice. Consult a licensed advisor.*

SIGNAL COLOUR CODING — apply consistently to every key reading, ticker, metric, or finding:
- Prefix with 🟢 when the reading is positive, bullish, or low-risk
  (e.g. strong earnings, low short interest risk, solid balance sheet, accommodative conditions)
- Prefix with 🟡 when the reading is neutral, mixed, or moderate risk
  (e.g. uncertain outlook, elevated but not extreme, conflicting signals)
- Prefix with 🔴 when the reading is negative, bearish, or high-risk
  (e.g. deteriorating fundamentals, high regulatory risk, dangerous valuation, danger zone)

Apply the signal prefix to bullet points, table rows, and inline metric values wherever a clear
positive/neutral/negative judgement can be made. Not every word needs a prefix — use them on
the key finding per line."""


# ─────────────────────────────────────────────────────────────────────────────
# Buffett Indicator analysis  (streaming, user-triggered)
# ─────────────────────────────────────────────────────────────────────────────

_BUFFETT_SYSTEM = """You are the Pulse360 macro valuation analyst.
You answer the question: "What does the Warren Buffett Indicator say today for the current market conditions?"

Write for a sophisticated personal investor. Rules:
1. Lead with the current ratio and its valuation zone — no preamble.
2. Explain what the ratio means in plain English and historical context.
3. Describe what Buffett himself has said about similar levels (cite actual quotes if known).
4. Explain what this implies for portfolio positioning — asset allocation, sector preference, cash levels.
5. Address how the current reading interacts with the economic cycle phase and recession probability provided.
6. Be specific and data-driven. Reference historical episodes (e.g. dot-com peak ~190%, 2009 trough ~60%).
7. Use 🟢 / 🟡 / 🔴 signal prefixes on key findings.
8. 400–500 words. Structured prose, not bullet points.
9. End with: *Educational analysis only — not personalised investment advice.*"""


def get_buffett_analysis(
    current_ratio: float,
    historical_avg: float,
    historical_percentile: float,
    zone_label: str,
    cycle_phase: str,
    recession_probability: float,
    traffic_light: str,
    premium_to_avg: float,
) -> Generator[str, None, None]:
    """
    Stream a full Buffett Indicator analysis answering:
    "What does the Warren Buffett Indicator say today for the current market conditions?"

    Yields:
        Text chunks from Claude Sonnet.
    """
    user_prompt = (
        f"Warren Buffett Indicator reading today:\n"
        f"  • Current ratio: {current_ratio:.1f}% of GDP\n"
        f"  • Valuation zone: {zone_label}\n"
        f"  • Historical average: {historical_avg:.1f}%\n"
        f"  • Premium / discount to average: {premium_to_avg:+.1f}pp\n"
        f"  • Historical percentile: {historical_percentile:.0f}th (higher = more expensive than usual)\n\n"
        f"Current macro context:\n"
        f"  • Cycle phase: {cycle_phase}\n"
        f"  • Recession probability: {recession_probability:.1f}% ({traffic_light.upper()})\n\n"
        "Answer the question: What does the Warren Buffett Indicator say today about "
        "current market conditions and what should an investor do about it?"
    )

    try:
        client = _get_client()
        with client.messages.stream(
            model      = SONNET,
            max_tokens = 700,
            system     = _BUFFETT_SYSTEM,
            messages   = [{"role": "user", "content": user_prompt}],
        ) as stream:
            for chunk in stream.text_stream:
                yield chunk
    except Exception as exc:
        logger.error("get_buffett_analysis failed: %s", exc)
        yield f"\n\n⚠️ Analysis unavailable: {exc}"


def extract_tickers_from_screenshot(
    image_bytes: bytes,
    media_type: str,
) -> list[str]:
    """
    Use Claude Haiku vision to extract stock ticker symbols from a broker
    portfolio screenshot.

    Args:
        image_bytes: Raw bytes of the uploaded image.
        media_type:  MIME type string, e.g. "image/png", "image/jpeg".

    Returns:
        Deduplicated list of uppercase ticker strings (e.g. ["AAPL", "MSFT"]).
        Returns [] if nothing is found or on API error.
    """
    import base64

    # Normalise media type — file_uploader sometimes returns "image/jpg"
    _mt_map = {"image/jpg": "image/jpeg"}
    media_type = _mt_map.get(media_type, media_type)

    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    extraction_prompt = (
        "Look at this brokerage or portfolio screenshot and extract every "
        "stock / ETF ticker symbol that is visible.\n\n"
        "Rules:\n"
        "- Return ONLY the ticker symbols, one per line, no explanations.\n"
        "- Use standard US exchange format (e.g. AAPL, BRK-B, SPY).\n"
        "- If a company name appears without a ticker, infer it if obvious "
        "(e.g. 'Apple Inc' -> AAPL, 'Microsoft' -> MSFT).\n"
        "- Skip cash, money-market, and sweep funds (e.g. SPAXX, FDRXX, VMFXX).\n"
        "- Skip duplicate entries.\n"
        "- If you cannot find any stock tickers, respond with exactly: "
        "NO_TICKERS_FOUND\n\n"
        "Return ONLY the tickers, one per line, nothing else."
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model      = HAIKU,
            max_tokens = 400,
            messages   = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type":       "base64",
                                "media_type": media_type,
                                "data":       b64,
                            },
                        },
                        {"type": "text", "text": extraction_prompt},
                    ],
                }
            ],
        )
        raw = response.content[0].text.strip()
        if "NO_TICKERS_FOUND" in raw.upper():
            return []
        tickers = [
            t.strip().upper()
            for t in raw.replace(",", "\n").splitlines()
            if t.strip() and 1 <= len(t.strip()) <= 7
        ]
        return list(dict.fromkeys(tickers))  # preserve order, deduplicate
    except Exception as exc:
        logger.error("extract_tickers_from_screenshot failed: %s", exc)
        return []


def stream_briefing_section(
    prompt: str,
    max_tokens: int = 1200,
) -> Generator[str, None, None]:
    """
    Stream a response for one AI Research Desk section.

    Args:
        prompt:     The fully-rendered prompt for this section (placeholders already substituted).
        max_tokens: Token budget for the response (default 1200).

    Yields:
        Text chunks as they stream from Claude Sonnet.
    """
    try:
        client = _get_client()
        with client.messages.stream(
            model      = SONNET,
            max_tokens = max_tokens,
            system     = _BRIEFING_SYSTEM,
            messages   = [{"role": "user", "content": prompt}],
        ) as stream:
            for chunk in stream.text_stream:
                yield chunk
    except Exception as exc:
        logger.error("stream_briefing_section failed: %s", exc)
        yield f"\n\n⚠️ Research unavailable: {exc}"
