"""
Pulse360 — Claude API Client
==============================
Handles all Anthropic API calls for the AI layer:
  • get_daily_briefing()          → cached 6h, returns markdown string
  • get_investment_implications() → cached 2h per tab, returns prose string
  • stream_chat_response()        → streaming generator for the chat sidebar
  • stream_briefing_section()     → streaming generator for At a Glance sections
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
# At a Glance Briefing — generic streaming section runner
# ─────────────────────────────────────────────────────────────────────────────

_BRIEFING_SYSTEM = """You are the Pulse360 At a Glance research engine.
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


def stream_briefing_section(
    prompt: str,
    max_tokens: int = 1200,
) -> Generator[str, None, None]:
    """
    Stream a response for one At a Glance briefing section.

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
