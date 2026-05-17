"""
components/prompts.py
======================
All Claude API prompt logic for Pie360.

Centralising prompts makes them easy to version, test, and reuse across
pages without importing Streamlit page files.

Public API
----------
    from components.prompts import (
        REFRESH_PROMPT,
        build_review_prompt,
        run_deep_dive,
        stream_review,
        refresh_signals,
    )
"""

from __future__ import annotations

import json
import os

import anthropic
import streamlit as st
from components.observability import log, capture_exception

from components.forecasters import compute_consensus, save_signals

# ── Config ────────────────────────────────────────────────────────────────────
REFRESH_TIMEOUT_SECS = 25   # max seconds for the web-search refresh call
STALE_DAYS           = 14   # re-exported for convenience


# ── Signal refresh prompt ─────────────────────────────────────────────────────

REFRESH_PROMPT = """\
You are refreshing macro forecaster signals for an investment app called Pie360.

Search for the latest public statements from each of these 9 forecasters and assign each a signal.

Forecasters:
1. Tom Lee (Fundstrat) — equity market & sentiment cycles
2. Ed Yardeni (Yardeni Research) — corporate earnings & productivity growth
3. Jeremy Siegel (Wharton) — long-run equity returns
4. Campbell Harvey (Duke) — yield curve indicator
5. Warren Buffett (Berkshire) — long-term value & market valuation. Also check Berkshire cash levels and buyback pace.
6. Nouriel Roubini (Atlas Capital) — systemic crisis detection
7. Jeremy Grantham (GMO) — bubble identification
8. Michael Burry (Scion) — contrarian deep value
9. Stanley Druckenmiller (Duquesne) — macro timing & liquidity

For each forecaster:
- Search for their most recent public statement, interview, or investor letter (past 3 months if possible)
- Assign a signal: "Risk on", "Caution", or "Risk off"
- Write a 2-sentence plain-English summary (no jargon)
- Record the direct URL of the source you used (article, interview, letter page)
- Record the date of that source statement in "Month D, YYYY" format

Return ONLY valid JSON in this exact format:
{
  "last_updated": "Month D, YYYY",
  "forecasters": [
    {
      "name": "Full Name",
      "specialty": "Their specialty",
      "bias": "Perma-bull|Perma-bear|Neutral|Contrarian|Flexible",
      "signal": "Risk on|Caution|Risk off",
      "summary": "Two plain-English sentences about their current view.",
      "source_url": "https://... (direct URL to the article/interview/letter; empty string if not found)",
      "statement_date": "Month D, YYYY (date of the source statement; empty string if unknown)"
    }
  ]
}

Bias values (keep consistent — these reflect long-run reputation, not current signal):
- Tom Lee, Ed Yardeni, Jeremy Siegel → "Perma-bull"
- Nouriel Roubini, Jeremy Grantham → "Perma-bear"
- Warren Buffett, Campbell Harvey → "Neutral"
- Michael Burry → "Contrarian"
- Stanley Druckenmiller → "Flexible"

Order the forecasters: Risk on first, then Caution, then Risk off.
Do not fabricate views — if no recent source is found, use last known position and note the date in the summary.
Keep the same 9 forecasters and specialties as listed above."""


# ── Deep-dive prompt ──────────────────────────────────────────────────────────

def _build_deep_dive_prompt(f: dict) -> str:
    first_name = f["name"].split()[0]
    return f"""You are a macro research analyst at Pie360 giving a concise deep dive on one forecaster.

Forecaster: {f['name']}
Specialty: {f.get('specialty', '')}
Bias: {f.get('bias', '')}
Current signal: {f['signal']}
Current view: {f['summary']}

Write a tight 3-part brief:

**Core thesis** — What is {first_name}'s current investment framework? What does he/she think is driving markets right now? (2-3 sentences)

**Recent positioning** — What specific moves, bets, or statements reveal conviction? Be concrete — name assets, sectors, or calls where possible. (2-3 sentences)

**Portfolio implication** — One specific, actionable takeaway for a diversified investor given this signal. (1-2 sentences)

Total length: 150-200 words. Write for a sophisticated investor. Be specific, not generic."""


def run_deep_dive(f: dict) -> str:
    """
    Call Claude Sonnet synchronously for a forecaster deep-dive.
    Returns the response text, or an error string on failure.
    """
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
        client  = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": _build_deep_dive_prompt(f)}],
        )
        return response.content[0].text
    except Exception as exc:
        return f"⚠️ Deep-dive unavailable: {exc}"


# ── Portfolio review prompt ───────────────────────────────────────────────────

def build_review_prompt(signals: dict) -> str:
    """Build the portfolio review prompt from current forecaster signals."""
    counts = compute_consensus(signals["forecasters"])
    forecaster_lines = "\n".join([
        f"- {f['name']} ({f.get('specialty', '')}): {f['signal']} — {f['summary']}"
        for f in signals["forecasters"]
    ])
    return f"""You are a senior macro strategist giving a concise portfolio review.

Current macro consensus across {len(signals['forecasters'])} top forecasters:
Risk on: {counts['Risk on']} | Caution: {counts['Caution']} | Risk off: {counts['Risk off']}

Individual signals:
{forecaster_lines}

Provide a crisp, actionable review with three sections:
1. **Cycle read** — 2-3 sentences on what this consensus implies about the current economic cycle phase
2. **Top 3 portfolio adjustments** — specific, actionable allocation moves given this macro backdrop
3. **Key risks to monitor** — 2-3 near-term catalysts that could change the picture

Write for a professional investor. Be specific, not generic."""


def stream_review(prompt: str):
    """
    Generator that yields text chunks from Claude Sonnet for st.write_stream.
    Usage: result = st.write_stream(stream_review(prompt))
    """
    api_key = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    client  = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    ) as s:
        yield from s.text_stream


# ── Signal refresh (Claude Opus + web search) ─────────────────────────────────

def refresh_signals() -> bool:
    """
    Fetch the latest forecaster signals via Claude Opus web search.
    Updates session_state and persists to Supabase.
    Returns True on success, False on failure.
    """
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
        client  = anthropic.Anthropic(api_key=api_key)
        with st.spinner("Fetching latest signals from public sources…"):
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4096,
                timeout=REFRESH_TIMEOUT_SECS,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 18}],
                messages=[{"role": "user", "content": REFRESH_PROMPT}],
            )

        # Extract text from response blocks
        text_content = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )

        # Parse JSON
        start = text_content.find("{")
        end   = text_content.rfind("}") + 1
        if start != -1 and end > start:
            new_signals = json.loads(text_content[start:end])
            st.session_state.macro_signals = new_signals
            save_signals(new_signals)
            st.success("Signals updated successfully.")
            return True
        else:
            st.warning("Could not parse updated signals. Showing last known data.")
            return False
    except Exception as exc:
        capture_exception(exc, context={"component": "prompts", "fn": "refresh_signals"})
        st.error(f"Refresh failed: {exc}")
        return False
