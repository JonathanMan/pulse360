"""
Pie360 — Macro Playbook
========================
One-screen AI-powered investment decision support.

Reads the current cycle phase + live macro signals → generates a bespoke
own/reduce/watch playbook via Claude Sonnet. Results are cached per
phase/confidence/profile combo (1 hr) so repeat visits are instant.
"""

from __future__ import annotations

import json
import re
import time

import anthropic
import streamlit as st

from components.cycle_engine import detect_cycle_phase, CycleResult
from components.observability import init_page, log, track, capture_exception
from components.user_profile import get_profile_key
from assets.logo_helper import header_with_logo

init_page("Macro Playbook")

# ── Rules-based fallback playbooks (used when AI unavailable) ─────────────────
_DEFAULTS: dict[str, dict] = {
    "Early / Recovery": {
        "own":    ["Small-cap equities", "Cyclical sectors (Industrials, Materials)",
                   "High-yield credit", "Emerging market equities", "Commodities"],
        "reduce": ["Long-duration Treasuries", "Defensive sectors (Utilities, Staples)", "Cash"],
        "watch":  ["ISM Manufacturing PMI", "Initial jobless claims", "Credit spreads"],
    },
    "Mid / Expansion": {
        "own":    ["Broad equities (S&P 500)", "Technology", "Financials",
                   "Investment-grade credit", "Real estate (REITs)"],
        "reduce": ["Gold", "Long-duration Treasuries", "Defensive cash positions"],
        "watch":  ["Yield curve slope", "CPI trend", "Fed funds rate path"],
    },
    "Late / Peak": {
        "own":    ["Defensive sectors (Healthcare, Staples, Utilities)",
                   "Short-duration bonds", "Gold", "Energy"],
        "reduce": ["Growth / tech equities", "High-yield credit",
                   "Emerging markets", "Small caps"],
        "watch":  ["Yield curve inversion depth", "Unemployment trend",
                   "Credit spreads widening"],
    },
    "Contraction": {
        "own":    ["Long-duration Treasuries", "Gold", "Cash & T-bills",
                   "Defensive equities"],
        "reduce": ["Broad equities", "High-yield credit", "Cyclicals", "Commodities"],
        "watch":  ["Fed policy pivots", "Claims data for trough signal",
                   "LEI turning points"],
    },
}

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.pb-banner {
    display:flex; align-items:center; gap:20px;
    padding:20px 24px; border-radius:0; margin-bottom:24px;
    border:1.5px solid;
}
.pb-icon  { font-size:2.8rem; }
.pb-label { font-size:0.62rem; font-weight:700; letter-spacing:.12em;
            text-transform:uppercase; margin-bottom:3px;
            font-family:'Geist Mono',monospace; }
.pb-name  { font-size:1.6rem; font-weight:800; letter-spacing:-0.02em; margin-bottom:2px; }
.pb-meta  { font-size:0.78rem; color:#6a6a6a;
            font-family:'Geist Mono',monospace; }

.pb-col-hdr {
    font-size:0.65rem; font-weight:700; letter-spacing:.1em;
    text-transform:uppercase; margin-bottom:10px;
    padding-bottom:6px; border-bottom:1.5px solid currentColor;
    font-family:'Geist Mono',monospace;
}
/* Terminal Light v2: light tinted backgrounds, dark signal text */
.pb-item  { padding:8px 12px; border-radius:0; margin-bottom:6px;
            font-size:0.85rem; font-weight:500;
            display:flex; align-items:center; gap:8px; }
.pb-own   { background:#edfbf4; color:#00a35a; border:1px solid #c0ecd9; }
.pb-cut   { background:#fff2f2; color:#d92626; border:1px solid #f5c2c2; }
.pb-watch { background:#eff6ff; color:#1f6feb; border:1px solid #bfdbfe; }

.pb-insight {
    background:#ffffff; border:1px solid #ececec;
    border-radius:0; padding:18px 22px; margin-top:20px;
    font-size:0.88rem; line-height:1.65; color:#0a0a0a;
}
.pb-insight-lbl {
    font-size:0.6rem; font-weight:700; letter-spacing:.12em;
    text-transform:uppercase; color:#7c4dff; margin-bottom:8px;
    font-family:'Geist Mono',monospace;
}
.pb-risk {
    background:#fffbeb; border:1px solid #fde68a;
    border-radius:0; padding:10px 14px; margin-top:12px;
    font-size:0.82rem; color:#c98800;
}
.pb-learner-tip {
    background:#f4f4f4; border:1px solid #ececec;
    border-radius:0; padding:10px 14px; margin-bottom:14px;
    font-size:0.8rem; color:#6a6a6a; line-height:1.5;
}
</style>
""", unsafe_allow_html=True)


# ── AI generation ─────────────────────────────────────────────────────────────
def _build_prompt(result: CycleResult, profile_key: str) -> str:
    """Build the Claude prompt from live cycle data and user profile."""
    style = {
        "Curious Learner":  "Plain English, no jargon. Explain each item in simple terms.",
        "Active Investor":  "Direct and actionable. Standard investment terminology. Specific asset classes and ETF categories.",
        "Pro Analyst":      "Precise. Include specific instruments, factor exposures, and duration considerations. Professional language.",
    }.get(profile_key, "Clear and actionable.")

    signals_lines = "\n".join(
        f"  • {r.name}: {r.formatted} ({r.trend}) → signals {r.implied_phase or 'unclear'}"
        for r in result.signals.values()
    ) if result.signals else "  (indicator data unavailable)"

    return f"""You are a senior macro investment strategist. Generate a concise investment playbook based on current economic conditions.

CURRENT MACRO CONDITIONS:
- Cycle phase: {result.phase}
- Confidence: {result.confidence}% ({result.confidence_label})
- Data as of: {result.as_of.strftime('%B %d, %Y') if result.as_of else 'recent'}

INDICATOR READINGS:
{signals_lines}

USER PROFILE: {profile_key}
STYLE: {style}

Return ONLY valid JSON — no markdown, no explanation:
{{
  "own":     ["item 1", "item 2", "item 3", "item 4", "item 5"],
  "reduce":  ["item 1", "item 2", "item 3", "item 4"],
  "watch":   ["item 1", "item 2", "item 3"],
  "insight": "2-3 sentences: what the data means and what the investor should be thinking right now.",
  "risk":    "1 sentence: the single biggest risk to this playbook being wrong."
}}

Rules:
- own: 4-6 specific assets/sectors/instruments to overweight
- reduce: 3-5 to underweight or avoid
- watch: 3 leading indicators that could change the thesis
- insight: investor-grade synthesis, not generic advice
- risk: the bear case or key tail risk
- All items must reflect the {result.phase} phase specifically"""


def generate_playbook(result: CycleResult, profile_key: str, force: bool = False) -> dict | None:
    """
    Generate (or retrieve cached) investment playbook via Claude Sonnet.
    Cached in session_state keyed on phase + confidence bucket + profile.
    Returns None if Anthropic API key is missing or call fails.
    """
    cache_key = f"_pb_{result.phase}_{result.confidence // 10}_{profile_key}"

    if not force and cache_key in st.session_state:
        return st.session_state[cache_key]

    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=700,
            messages=[{"role": "user", "content": _build_prompt(result, profile_key)}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if model wrapped the JSON
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        json_str = fence_match.group(1).strip() if fence_match else raw
        # Fallback: find first {...} block
        if not json_str.startswith("{"):
            brace_match = re.search(r"\{[\s\S]*\}", json_str)
            json_str = brace_match.group(0) if brace_match else json_str
        playbook = json.loads(json_str)
        st.session_state[cache_key]        = playbook
        st.session_state[f"{cache_key}_ts"] = time.time()
        log.info("playbook_generated", "AI playbook generated", phase=result.phase, profile=profile_key)
        track("playbook_generated", {"phase": result.phase, "profile": profile_key})
        return playbook

    except Exception as exc:
        capture_exception(exc, context={"phase": result.phase, "profile": profile_key})
        st.session_state["_pb_last_error"] = str(exc)
        return None


# ── Profile metadata ──────────────────────────────────────────────────────────
_PROFILE_META: dict[str, dict] = {
    "Curious Learner": {
        "tip": (
            "💡 <strong>What is this page?</strong> Based on where we are in the economic cycle, "
            "this playbook suggests which types of investments to favour, hold less of, or keep "
            "an eye on. It's a starting point for thinking — not personalised financial advice."
        ),
        "own_hdr":   ("📈 Consider Owning",   "#00a35a"),
        "cut_hdr":   ("📉 Consider Reducing", "#d92626"),
        "watch_hdr": ("👁 Worth Watching",    "#1f6feb"),
        "insight_lbl": "💬 What This Means",
        "signals_open": False,
    },
    "Active Investor": {
        "tip": None,
        "own_hdr":   ("📈 Overweight",   "#00a35a"),
        "cut_hdr":   ("📉 Underweight",  "#d92626"),
        "watch_hdr": ("👁 Watch Closely","#1f6feb"),
        "insight_lbl": "🤖 AI Synthesis",
        "signals_open": False,
    },
    "Pro Analyst": {
        "tip": None,
        "own_hdr":   ("📈 Long / Overweight",          "#00a35a"),
        "cut_hdr":   ("📉 Short / Underweight",         "#d92626"),
        "watch_hdr": ("👁 Key Indicators to Monitor",  "#1f6feb"),
        "insight_lbl": "🤖 AI Synthesis — Regime Analysis",
        "signals_open": True,   # expand indicator table by default for analysts
    },
}
_DEFAULT_PROFILE_META = _PROFILE_META["Active Investor"]


def _profile_meta(profile_key: str) -> dict:
    return _PROFILE_META.get(profile_key, _DEFAULT_PROFILE_META)


# ── Render helpers ────────────────────────────────────────────────────────────
def _render_banner(result: CycleResult) -> None:
    color = result.color
    filled = result.confidence // 10
    bar = "█" * filled + "░" * (10 - filled)
    date_str = result.as_of.strftime("%b %d, %Y") if result.as_of else "N/A"
    quality_note = ""
    if result.data_quality == "partial":
        quality_note = " · ⚠️ partial FRED data"
    elif result.data_quality == "unavailable":
        quality_note = " · ❌ no FRED data"

    st.markdown(f"""
<div class="pb-banner" style="background:{color}10;border-color:{color}50;">
  <div class="pb-icon">{result.icon}</div>
  <div style="flex:1;">
    <div class="pb-label" style="color:{color};">Current Cycle Phase</div>
    <div class="pb-name"  style="color:{color};">{result.phase}</div>
    <div class="pb-meta">{bar} {result.confidence}% confidence &nbsp;·&nbsp; as of {date_str}{quality_note}</div>
  </div>
</div>
""", unsafe_allow_html=True)


def _render_columns(playbook: dict, phase: str, profile_key: str = "Active Investor") -> None:
    defaults = _DEFAULTS.get(phase, {})
    own    = playbook.get("own",    defaults.get("own",    []))
    reduce = playbook.get("reduce", defaults.get("reduce", []))
    watch  = playbook.get("watch",  defaults.get("watch",  []))

    meta = _profile_meta(profile_key)

    # Curious Learner: brief glossary tip before the columns
    if meta["tip"]:
        st.markdown(f'<div class="pb-learner-tip">{meta["tip"]}</div>', unsafe_allow_html=True)

    own_label,   own_color   = meta["own_hdr"]
    cut_label,   cut_color   = meta["cut_hdr"]
    watch_label, watch_color = meta["watch_hdr"]

    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown(
            f'<div class="pb-col-hdr" style="color:{own_color};">{own_label}</div>',
            unsafe_allow_html=True,
        )
        for item in own:
            st.markdown(f'<div class="pb-item pb-own">✓ {item}</div>', unsafe_allow_html=True)

    with c2:
        st.markdown(
            f'<div class="pb-col-hdr" style="color:{cut_color};">{cut_label}</div>',
            unsafe_allow_html=True,
        )
        for item in reduce:
            st.markdown(f'<div class="pb-item pb-cut">↓ {item}</div>', unsafe_allow_html=True)

    with c3:
        st.markdown(
            f'<div class="pb-col-hdr" style="color:{watch_color};">{watch_label}</div>',
            unsafe_allow_html=True,
        )
        for item in watch:
            st.markdown(f'<div class="pb-item pb-watch">◉ {item}</div>', unsafe_allow_html=True)


def _render_insight(playbook: dict, ts: float | None, profile_key: str = "Active Investor") -> None:
    insight = playbook.get("insight", "")
    risk    = playbook.get("risk", "")
    lbl     = _profile_meta(profile_key)["insight_lbl"]

    age = ""
    if ts:
        mins = int((time.time() - ts) / 60)
        age  = f" · Generated {mins}m ago" if mins > 0 else " · Just generated"

    risk_html = f'<div class="pb-risk">⚠️ Key risk: {risk}</div>' if risk else ""

    st.markdown(f"""
<div class="pb-insight">
  <div class="pb-insight-lbl">{lbl}{age}</div>
  {insight}
  {risk_html}
</div>
""", unsafe_allow_html=True)


# ── Page ──────────────────────────────────────────────────────────────────────
header_with_logo("Macro Playbook", "AI-Powered Investment Decision Support")

# Load cycle data
fred_key = st.secrets.get("FRED_API_KEY", "") or ""
with st.spinner("Loading macro signals…"):
    try:
        cycle_result = detect_cycle_phase(fred_key)
    except Exception as _exc:
        capture_exception(_exc)
        st.error("Could not load cycle data. Check FRED_API_KEY in Streamlit secrets.")
        st.stop()

# Phase banner
_render_banner(cycle_result)

# Get or generate playbook
profile_key = get_profile_key()
_ck  = f"_pb_{cycle_result.phase}_{cycle_result.confidence // 10}_{profile_key}"
_ck_ts = f"{_ck}_ts"

playbook = st.session_state.get(_ck)
if playbook is None:
    with st.spinner("Generating investment playbook…"):
        playbook = generate_playbook(cycle_result, profile_key)

# Render playbook
if playbook:
    _render_columns(playbook, cycle_result.phase, profile_key)
    _render_insight(playbook, st.session_state.get(_ck_ts), profile_key)
else:
    last_err = st.session_state.get("_pb_last_error", "")
    if last_err:
        st.caption(f"⚠️ AI generation failed: {last_err}. Showing rules-based defaults.")
    else:
        st.caption("⚠️ AI generation unavailable (check ANTHROPIC_API_KEY). Showing rules-based defaults.")
    defaults = _DEFAULTS.get(cycle_result.phase, {})
    _render_columns(defaults, cycle_result.phase, profile_key)
    lbl = _profile_meta(profile_key)["insight_lbl"]
    st.markdown(
        f'<div class="pb-insight"><div class="pb-insight-lbl">{lbl}</div>{cycle_result.summary}</div>',
        unsafe_allow_html=True,
    )

# Controls
st.markdown("---")
rc, sc = st.columns([1, 5])
with rc:
    if st.button("🔄 Regenerate", width="stretch",
                 help="Discard cache and generate a fresh playbook"):
        st.session_state.pop(_ck, None)
        st.session_state.pop(_ck_ts, None)
        st.rerun()
with sc:
    st.caption("Playbook auto-refreshes when cycle phase changes. FRED data cached 1 hr.")

# Indicator signals — simple table, avoids calling cycle_result.render() which
# has nested-expander and HTML issues in Streamlit 1.50.
# Pro Analyst: expanded by default so signals are immediately visible.
_signals_open = _profile_meta(profile_key)["signals_open"]
with st.expander("📡 Indicator signals driving this playbook", expanded=_signals_open):
    if cycle_result.signals:
        import pandas as _pd
        from components.cycle_engine import _PHASE_COLORS as _PC
        rows = []
        for r in cycle_result.signals.values():
            implied = r.implied_phase or "—"
            rows.append({
                "Indicator": r.name,
                "Value":     r.formatted,
                "Trend":     r.trend,
                "Signals":   implied,
                "Note":      r.note,
            })
        df = _pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.caption("No indicator data available.")
    st.caption(f"Model confidence: {cycle_result.confidence}% ({cycle_result.confidence_label}) · {cycle_result.summary}")
