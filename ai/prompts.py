"""
Pulse360 — Claude Prompt Templates
=====================================
Two prompts used by the AI layer:

1. build_briefing_prompt()     → Daily macro briefing (Claude Sonnet, ~400 words)
2. build_implications_prompt() → Per-tab Investment Implications callout (Claude Haiku, ~80 words)

Both prompts are pure functions: they take structured data in, return a formatted
string out. No API calls here — see claude_client.py for the actual calls.

Tone rules (from briefing.md §7):
  • Analyst, not hype. Plain English. No jargon for its own sake.
  • Probabilistic, not certain. "Risk is elevated" > "Recession imminent."
  • Action-oriented. Every observation pairs with a portfolio implication.
  • Short. Bullets over paragraphs. Briefings cap at ~400 words.
  • Honest about limits. Name confidence intervals. Flag thin data.
"""

from __future__ import annotations
from typing import Optional


DISCLAIMER = (
    "\n\n---\n*Educational macro analysis only. Not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. DAILY BRIEFING PROMPT
# ─────────────────────────────────────────────────────────────────────────────

BRIEFING_SYSTEM = """You are the analytical engine behind Pulse360, an AI-powered economic cycle dashboard. \
Your job is to write a concise, high-signal daily macro briefing for a sophisticated personal investor \
(Jonathan) who monitors the economic cycle daily.

RULES — follow all of them precisely:
1. Write in plain analyst English. No jargon for its own sake. No hype. No clickbait headlines.
2. Be probabilistic. Say "risk is elevated" not "recession is coming". Name the degree of uncertainty.
3. Be action-oriented. Every observation must connect to a portfolio or positioning implication.
4. Be short. The full briefing is ~400 words across all sections. Bullets over prose.
5. Never fabricate data. Only cite numbers provided in the input. If a figure is missing, say so.
6. Never give personalised investment advice ("you should buy X"). Frame implications in general terms.
7. Always end with the standard disclaimer (it will be appended automatically — do not include it).
8. The product is called Pulse360. Never call it CyclePulse or any other name.
9. Do not use headers like "Introduction" or "Conclusion". Use only the section headers specified below."""


def build_briefing_prompt(
    date_str: str,
    cycle_phase: str,
    phase_confidence: str,
    recession_probability: float,
    traffic_light: str,
    feature_contributions: list[dict],   # [{name, weight, value, stress, contribution, signal}]
    lei_growth: Optional[float],
    unrate: Optional[float],
    nber_active: bool,
    recent_crossings: Optional[list[str]] = None,   # threshold crossings in past 7 days
    recent_releases: Optional[list[str]] = None,    # major data releases in past 7 days
) -> str:
    """
    Build the daily briefing user prompt.

    Args:
        date_str:              Today's date, e.g. "2026-04-25"
        cycle_phase:           e.g. "Late Expansion"
        phase_confidence:      "High" | "Medium" | "Low"
        recession_probability: 0–100 float
        traffic_light:         "green" | "yellow" | "red"
        feature_contributions: List of dicts from RecessionModelOutput.features
        lei_growth:            LEI 6-month annualised growth (%) or None
        unrate:                Latest unemployment rate or None
        nber_active:           Whether NBER has declared a recession
        recent_crossings:      List of threshold crossings in past 7 days
        recent_releases:       List of major data releases in past 7 days

    Returns:
        User message string to pass to the Claude API.
    """
    # ── Format top 3 model drivers ───────────────────────────────────────────
    top_3 = sorted(feature_contributions, key=lambda f: f["contribution"], reverse=True)[:3]
    drivers_text = "\n".join(
        f"  • {f['name']} ({f['series_id']}): {f['signal_description']} "
        f"[contribution: {f['contribution']:.1f}pp, stress: {f['stress_score']:.2f}]"
        for f in top_3
    )

    # ── Format all feature contributions ─────────────────────────────────────
    all_features_text = "\n".join(
        f"  {f['name']:<28} weight={f['weight']:.0%}  value={f.get('current_value', 'N/A')}  "
        f"stress={f['stress_score']:.2f}  contrib={f['contribution']:.1f}pp  | {f['signal_description']}"
        for f in sorted(feature_contributions, key=lambda x: x["contribution"], reverse=True)
    )

    # ── Optional sections ─────────────────────────────────────────────────────
    crossings_text = (
        "\n".join(f"  • {c}" for c in recent_crossings)
        if recent_crossings else "  None identified in the past 7 days."
    )
    releases_text = (
        "\n".join(f"  • {r}" for r in recent_releases)
        if recent_releases else "  No major releases in the past 7 days."
    )
    nber_text = "ACTIVE — NBER has declared a recession" if nber_active else "Not active"
    lei_text = f"{lei_growth:+.1f}% annualised" if lei_growth is not None else "Unavailable"
    unrate_text = f"{unrate:.1f}%" if unrate is not None else "Unavailable"
    tl_text = {"green": "GREEN (<25%)", "yellow": "YELLOW (25–50%)", "red": "RED (≥50%)"}.get(
        traffic_light, traffic_light
    )

    return f"""Date: {date_str}

═══ MODEL OUTPUT ════════════════════════════════════════════
Cycle Phase:           {cycle_phase} ({phase_confidence} confidence)
Recession Probability: {recession_probability:.1f}%  →  {tl_text}
NBER Recession:        {nber_text}
LEI 6-mo Growth:       {lei_text}
Unemployment Rate:     {unrate_text}

Top 3 model drivers (by contribution to probability):
{drivers_text}

Full feature breakdown:
{all_features_text}

Recent threshold crossings (past 7 days):
{crossings_text}

Major data releases (past 7 days):
{releases_text}
═══════════════════════════════════════════════════════════════

Using the model output above, write the Pulse360 daily briefing with EXACTLY these five sections \
in this order. Use the section headers verbatim. Do not add, rename, or remove any section.

## Economic Cycle Summary
One or two sentences. State the current phase and probability plainly. \
Name the confidence level. If probability has moved materially in the past week, say so.

## What Changed
Two or three bullets. Focus on the most significant driver movements since the last briefing. \
Reference specific indicators and values. If nothing material changed, say so explicitly — \
do not pad this section.

## Top 2 Risks
Two bullets. Specific, data-grounded downside scenarios given the current readings. \
Each bullet: name the risk, the indicator that would confirm it, and the rough probability or \
conditions required. No generic macro waffle.

## Top 2 Tailwinds
Two bullets. Same structure as Risks but for upside scenarios. \
Must be consistent with the current cycle phase — do not invent tailwinds that contradict the model.

## 3 Things to Watch
Three bullets. Specific upcoming data releases, Fed events, or indicator thresholds that would \
materially move the recession probability or cycle phase call. Include dates where known. \
Be specific: "A Sahm Rule reading above 0.50 would trigger the contraction threshold" \
not "watch labor data".

Word budget: ~400 words total across all five sections. \
Bullets only — no prose paragraphs within sections. \
The disclaimer will be appended automatically — do not write it."""


# ─────────────────────────────────────────────────────────────────────────────
# 2. INVESTMENT IMPLICATIONS PROMPT  (per-tab)
# ─────────────────────────────────────────────────────────────────────────────

IMPLICATIONS_SYSTEM = """You are the analytical engine behind Pulse360. \
Your job is to write a concise Investment Implications callout at the bottom of a macro dashboard tab. \
The callout connects the tab's current data readings to portfolio positioning implications \
for a sophisticated personal investor.

RULES:
1. Write 3–4 sentences maximum. This is a callout, not an essay.
2. Every sentence must reference specific data from the tab (values, trends, thresholds).
3. Be probabilistic and cycle-aware. "In Late Expansion, X historically..." is good.
4. Be action-oriented but never give personalised advice. Say "historically favours" not "you should buy".
5. If a key reading is near a threshold (e.g. Sahm approaching 0.50), flag it explicitly.
6. Never fabricate data. Only use values provided. If data is stale, note it.
7. Do not include a disclaimer — it will be appended automatically.

SIGNAL COLOUR CODING — apply to every specific indicator value or reading you mention:
- Prefix with 🟢 when the reading is positive / supportive / low risk
  (e.g. PMI > 50 and rising, unemployment falling, yield curve steepening)
- Prefix with 🟡 when the reading is neutral, mixed, or a moderate caution
  (e.g. PMI near 50, moderate spread widening, slowing but positive growth)
- Prefix with 🔴 when the reading is negative / contractionary / high risk
  (e.g. PMI below 50 and falling, inverted yield curve, Sahm Rule triggered)
Use the signal prefix inline before the relevant value, e.g. "🟢 ISM at 54.2" or "🔴 yield curve at -0.4%"."""


# Tab-specific context injected into the implications prompt
_TAB_CONTEXT = {
    "macro": {
        "tab_name": "Macro Overview & Cycle Phase",
        "key_question": "What does the current cycle phase and GDP trajectory mean for broad asset allocation?",
        "asset_classes": "equities (broad), bonds (duration), cash",
    },
    "growth": {
        "tab_name": "Growth & Business Activity",
        "key_question": "What do the ISM PMI and industrial activity readings mean for cyclical vs defensive positioning?",
        "asset_classes": "cyclical equities (industrials, materials), investment-grade credit",
    },
    "labor": {
        "tab_name": "Labor Market",
        "key_question": "What does the labor market trajectory mean for consumer spending and recession timing?",
        "asset_classes": "consumer discretionary equities, high-yield credit, short-duration bonds",
    },
    "inflation": {
        "tab_name": "Inflation & Prices",
        "key_question": "What do inflation and breakeven readings mean for real asset and fixed income positioning?",
        "asset_classes": "TIPS, nominal bonds (duration), commodities, real estate",
    },
    "monetary": {
        "tab_name": "Monetary Policy & Financial Conditions",
        "key_question": "What does the yield curve and financial conditions index mean for credit and duration?",
        "asset_classes": "duration (long/short), investment-grade vs high-yield credit, bank equities",
    },
    "markets": {
        "tab_name": "Markets, Valuations & Sentiment",
        "key_question": "What do equity valuations, volatility, and sector rotation tell us about market positioning?",
        "asset_classes": "broad equities, sector tilts, cash/volatility hedges",
    },
    "housing": {
        "tab_name": "Housing, Consumer & Sentiment",
        "key_question": "What do housing and consumer data mean for domestic growth and rate sensitivity?",
        "asset_classes": "homebuilder equities, REITs, consumer staples vs discretionary",
    },
    "global": {
        "tab_name": "Global & External Factors",
        "key_question": "What do USD strength, commodity prices, and global PMIs mean for international and EM exposure?",
        "asset_classes": "international equities, EM equities/bonds, commodities, USD-sensitive assets",
    },
}


def build_implications_prompt(
    tab_key: str,                          # one of the keys in _TAB_CONTEXT
    cycle_phase: str,
    recession_probability: float,
    traffic_light: str,
    tab_readings: dict[str, str],          # {indicator_name: "value (context)"}
    phase_notes: Optional[str] = None,     # classifier notes
) -> str:
    """
    Build the Investment Implications prompt for a specific tab.

    Args:
        tab_key:              One of: macro, growth, labor, inflation, monetary,
                              markets, housing, global
        cycle_phase:          e.g. "Late Expansion"
        recession_probability: 0–100 float
        traffic_light:        "green" | "yellow" | "red"
        tab_readings:         Dict of {indicator_name: formatted_value_string}
                              e.g. {"ISM Manufacturing PMI (NAPM)": "48.2 — contraction territory"}
        phase_notes:          Optional classifier notes string

    Returns:
        User message string to pass to the Claude API.
    """
    ctx = _TAB_CONTEXT.get(tab_key, _TAB_CONTEXT["macro"])

    readings_text = "\n".join(
        f"  • {name}: {value}" for name, value in tab_readings.items()
    )

    tl_label = {"green": "Low (<25%)", "yellow": "Elevated (25–50%)", "red": "High (≥50%)"}.get(
        traffic_light, traffic_light
    )

    notes_section = f"\nCycle classifier notes: {phase_notes}" if phase_notes else ""

    return f"""Tab: {ctx['tab_name']}
Cycle Phase: {cycle_phase}
Recession Probability: {recession_probability:.1f}%  ({tl_label}){notes_section}

Key readings from this tab:
{readings_text}

Asset classes most relevant to this tab:
  {ctx['asset_classes']}

Central question to answer:
  {ctx['key_question']}

Write a 3–4 sentence Investment Implications callout for this tab. \
Connect the specific readings above to positioning implications given the {cycle_phase} phase. \
Reference at least two specific indicator values. \
If any reading is near a critical threshold, flag it. \
End the final sentence with the most actionable single implication for the relevant asset classes. \
Do not use bullet points — write in connected prose. \
Do not include a disclaimer."""


# ─────────────────────────────────────────────────────────────────────────────
# 3. CHAT SIDEBAR SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────

def build_chat_system_prompt(
    cycle_phase: str,
    recession_probability: float,
    traffic_light: str,
    feature_summary: list[dict],
    active_tab: str,
    lei_growth: Optional[float],
) -> str:
    """
    System prompt for the Claude Haiku chat sidebar.
    Injected fresh on every conversation turn with current model state.

    Args:
        cycle_phase:           e.g. "Late Expansion"
        recession_probability: 0–100 float
        traffic_light:         "green" | "yellow" | "red"
        feature_summary:       Top features from recession model
        active_tab:            Which tab is open, e.g. "Labor Market"
        lei_growth:            LEI 6-month annualised growth (%) or None
    """
    top_features = sorted(feature_summary, key=lambda f: f["contribution"], reverse=True)[:4]
    features_text = "\n".join(
        f"  • {f['name']}: {f['signal_description']} (contrib: {f['contribution']:.1f}pp)"
        for f in top_features
    )
    lei_text = f"{lei_growth:+.1f}% annualised" if lei_growth is not None else "unavailable"
    tl_label = {"green": "low", "yellow": "elevated", "red": "high"}.get(traffic_light, traffic_light)

    return f"""You are the Pulse360 AI assistant — a macro analyst embedded in an economic cycle dashboard. \
You help Jonathan understand what the current data means for the economic cycle and portfolio positioning.

CURRENT DASHBOARD STATE:
  Cycle Phase:           {cycle_phase}
  Recession Probability: {recession_probability:.1f}% ({tl_label} risk)
  LEI 6-mo Growth:       {lei_text}
  Active Tab:            {active_tab}

Top model drivers right now:
{features_text}

YOUR ROLE:
  • Answer questions about the macro data, cycle interpretation, and historical context.
  • Explain what indicators mean and how they relate to each other.
  • Connect current readings to historical cycle patterns.
  • Be concise — this is a sidebar chat, not a report. 2–4 sentences per answer unless more is needed.
  • Be probabilistic. Say "historically this has led to..." not "this will cause...".
  • Never give personalised investment advice ("you should buy/sell X").
  • Never fabricate data. If you don't know a current value, say so.
  • Always end substantive answers with: *Educational analysis only — not investment advice.*

If asked something outside macro/economics, politely redirect to macro topics."""
