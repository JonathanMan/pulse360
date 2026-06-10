"""
Pie360 — Macro Pulse
=====================
Visual consensus tracker across 9 top macro forecasters.
Signals stored in Supabase; refreshed weekly via Claude Opus web search.

Retired: per-card deep-dives and portfolio review streaming have moved to
the AI chat sidebar — ask there for a deep dive on any forecaster or a
macro-adjusted portfolio review.
"""

from __future__ import annotations

import anthropic
import json
from datetime import date, datetime

import streamlit as st

from components.supabase_client import get_client
from components.pulse360_theme import inject_theme
from assets.logo_helper import header_with_logo

inject_theme()
header_with_logo("Macro Pulse", "Real-time Forecaster Signals & Consensus Tracking")

st.markdown(
    "<style>.main .block-container{max-width:860px;padding-top:1.2rem;}</style>",
    unsafe_allow_html=True,
)

# ── Config ────────────────────────────────────────────────────────────────────
_STALE_DAYS         = 14
_REFRESH_TIMEOUT    = 25
_SIGNALS_TABLE      = "macro_signals"
_SIGNALS_ROW_ID     = 1


def _is_stale(statement_date_str: str) -> bool:
    if not statement_date_str:
        return False
    try:
        dt = datetime.strptime(statement_date_str, "%B %d, %Y").date()
        return (date.today() - dt).days > _STALE_DAYS
    except ValueError:
        return False


# ── Default signals ───────────────────────────────────────────────────────────
DEFAULT_SIGNALS = {
    "last_updated": "May 4, 2026",
    "forecasters": [
        {"name": "Tom Lee",             "specialty": "Equity market & sentiment cycles",   "bias": "Perma-bull",  "signal": "Risk on",  "source_url": "", "statement_date": "May 4, 2026", "summary": "Lee sees strong earnings growth, resilient consumer spending, and improving sentiment as tailwinds for equities. He remains one of Wall Street's most vocal bulls on the S&P 500 reaching new highs."},
        {"name": "Ed Yardeni",          "specialty": "Corporate earnings & productivity",   "bias": "Perma-bull",  "signal": "Risk on",  "source_url": "", "statement_date": "May 4, 2026", "summary": "Yardeni argues that U.S. corporate productivity gains — driven by AI and technology — are underpriced by the market. He sees earnings growth as durable enough to justify current valuations."},
        {"name": "Jeremy Siegel",       "specialty": "Long-run equity returns",             "bias": "Perma-bull",  "signal": "Risk on",  "source_url": "", "statement_date": "May 4, 2026", "summary": "Siegel's long-run thesis holds: equities beat every other asset class over time, and investors who exit miss the recoveries that matter most."},
        {"name": "Campbell Harvey",     "specialty": "Yield curve indicator",               "bias": "Neutral",     "signal": "Risk on",  "source_url": "", "statement_date": "May 4, 2026", "summary": "Harvey's yield curve has re-steepened, which historically marks the window where equities can recover. He notes the recession signal has faded."},
        {"name": "Warren Buffett",      "specialty": "Long-term value & market valuation",  "bias": "Neutral",     "signal": "Caution",  "source_url": "", "statement_date": "May 4, 2026", "summary": "Berkshire's cash pile has hit record highs and Buffett has slowed buybacks — his clearest signal that he finds few things worth buying at current prices."},
        {"name": "Nouriel Roubini",     "specialty": "Systemic crisis detection",           "bias": "Perma-bear",  "signal": "Caution",  "source_url": "", "statement_date": "May 4, 2026", "summary": "Debt levels and stagflation risk are elevated, but not yet a 2008 scenario. Roubini warns the tools to fight the next crisis are already depleted."},
        {"name": "Jeremy Grantham",     "specialty": "Bubble identification",               "bias": "Perma-bear",  "signal": "Risk off", "source_url": "", "statement_date": "May 4, 2026", "summary": "Valuations remain historically extreme. Grantham sees a third bubble in 25 years still deflating — real assets and emerging markets are his relative shelter."},
        {"name": "Michael Burry",       "specialty": "Contrarian deep value",               "bias": "Contrarian",  "signal": "Risk off", "source_url": "", "statement_date": "May 4, 2026", "summary": "Burry has flagged index concentration and passive investment flows as a systemic risk. He's positioned short on broad indices."},
        {"name": "Stanley Druckenmiller","specialty": "Macro timing & liquidity",           "bias": "Flexible",    "signal": "Risk off", "source_url": "", "statement_date": "May 4, 2026", "summary": "Druckenmiller has reduced equity exposure and flagged that the easy money environment is structurally over."},
    ],
}

# ── Style maps ────────────────────────────────────────────────────────────────
SIGNAL_STYLES = {
    "Risk on":  {"bg": "#EAF3DE", "text": "#3B6D11", "bar": "#639922"},
    "Caution":  {"bg": "#FAEEDA", "text": "#854F0B", "bar": "#EF9F27"},
    "Risk off": {"bg": "#FCEBEB", "text": "#A32D2D", "bar": "#E24B4A"},
}
SIGNAL_ORDER = ["Risk on", "Caution", "Risk off"]
BIAS_STYLES = {
    "Perma-bull": {"color": "#2a6ebb", "bg": "#e8f1fb"},
    "Perma-bear": {"color": "#a32d2d", "bg": "#faeaea"},
    "Neutral":    {"color": "#5f5e5a", "bg": "#f0f0ee"},
    "Contrarian": {"color": "#7a4d00", "bg": "#fdf0dc"},
    "Flexible":   {"color": "#3a5f3a", "bg": "#e8f5e8"},
}

MP_CSS = """
<style>
  .mp-consensus-box  { background:#f5f5f3;border:0.5px solid rgba(0,0,0,.1);border-radius:10px;padding:12px 14px;margin-bottom:18px; }
  .mp-bar-track      { border-radius:4px;height:6px;width:100%;margin-bottom:8px;overflow:hidden;display:flex; }
  .mp-bar-legend     { display:flex;gap:14px; }
  .mp-legend-item    { font-size:11px;color:#5f5e5a;display:flex;align-items:center;gap:4px; }
  .mp-legend-dot     { width:8px;height:8px;border-radius:50%;flex-shrink:0;display:inline-block; }
  .mp-consensus-verdict { font-size:13px;font-weight:500;color:#1a1a18;margin:8px 0 0; }
  .mp-group-label    { font-size:11px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;margin:16px 0 8px 2px; }
  .mp-fname          { font-size:15px;font-weight:500;color:#1a1a18;margin:0 0 2px; }
  .mp-fspecialty     { font-size:12px;color:#5f5e5a;margin:0; }
  .mp-signal-badge   { font-size:11px;font-weight:500;padding:3px 10px;border-radius:20px;white-space:nowrap; }
  .mp-bias-tag       { font-size:10px;font-weight:500;padding:2px 7px;border-radius:20px;white-space:nowrap; }
  .mp-fread          { font-size:13px;color:#5f5e5a;line-height:1.55;margin:0;border-left:2px solid rgba(0,0,0,.15);padding-left:10px; }
  .mp-source-meta    { font-size:11px;color:#888780;margin:6px 0 0; }
  .mp-source-link    { color:#2a6ebb!important;text-decoration:none!important; }
  .mp-stale-badge    { color:#854F0B;font-weight:600; }
</style>
"""


# ── Supabase helpers ──────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_signals_from_db() -> dict | None:
    try:
        sb  = get_client()
        row = sb.table(_SIGNALS_TABLE).select("signals_json").eq("id", _SIGNALS_ROW_ID).single().execute()
        if row.data:
            return row.data["signals_json"]
    except Exception:
        pass
    return None


def _save_signals_to_db(signals: dict) -> None:
    try:
        sb = get_client()
        sb.table(_SIGNALS_TABLE).upsert({"id": _SIGNALS_ROW_ID, "signals_json": signals}).execute()
        _load_signals_from_db.clear()
    except Exception as e:
        st.warning(f"Could not save signals to database: {e}")


def get_signals() -> dict:
    if "macro_signals" in st.session_state:
        return st.session_state.macro_signals
    db = _load_signals_from_db()
    if db:
        st.session_state.macro_signals = db
        return db
    return DEFAULT_SIGNALS


def compute_consensus(forecasters: list) -> dict:
    counts = {"Risk on": 0, "Caution": 0, "Risk off": 0}
    for f in forecasters:
        sig = f.get("signal", "Caution")
        if sig in counts:
            counts[sig] += 1
    return counts


# ── Card renderer (no interactive deep-dives) ─────────────────────────────────
def _render_card(f: dict) -> None:
    s  = SIGNAL_STYLES.get(f["signal"], SIGNAL_STYLES["Caution"])
    bs = BIAS_STYLES.get(f.get("bias", ""), {"color": "#888", "bg": "#f0f0f0"})
    bias_html = (
        f'<span class="mp-bias-tag" style="color:{bs["color"]};background:{bs["bg"]};">{f["bias"]}</span>'
        if f.get("bias") else ""
    )
    stmt_date = f.get("statement_date", "")
    stale_html = ' <span class="mp-stale-badge">⚠️ Review needed</span>' if _is_stale(stmt_date) else ""
    source_url = f.get("source_url", "")
    meta = ""
    if stmt_date or source_url:
        parts = []
        if stmt_date:
            parts.append(f"{stmt_date}{stale_html}")
        if source_url:
            parts.append(f'· <a class="mp-source-link" href="{source_url}" target="_blank">Source ↗</a>')
        meta = f'<p class="mp-source-meta">{"  ".join(parts)}</p>'

    st.markdown(f"""
    <div style="background:#fff;border:0.5px solid rgba(0,0,0,.12);border-radius:12px;padding:14px 16px;margin-bottom:10px;">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px;gap:8px;">
        <div>
          <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">
            <p class="mp-fname" style="margin:0;">{f['name']}</p>{bias_html}
          </div>
          <p class="mp-fspecialty">{f['specialty']}</p>
        </div>
        <span class="mp-signal-badge" style="background:{s['bg']};color:{s['text']};">{f['signal']}</span>
      </div>
      <p class="mp-fread">{f['summary']}</p>
      {meta}
    </div>
    """, unsafe_allow_html=True)


# ── Main renderer ─────────────────────────────────────────────────────────────
def render_macro_pulse(signals: dict) -> None:
    forecasters  = signals["forecasters"]
    last_updated = signals.get("last_updated", str(date.today()))
    counts = compute_consensus(forecasters)
    total  = len(forecasters)

    pct_off  = round(counts["Risk off"] / total * 100)
    pct_caut = round(counts["Caution"]  / total * 100)
    pct_on   = 100 - pct_off - pct_caut

    if counts["Risk off"] > counts["Risk on"] and counts["Risk off"] > counts["Caution"]:
        verdict = "Bearish lean — most forecasters signaling caution or risk off"
    elif counts["Risk on"] > counts["Risk off"] and counts["Risk on"] > counts["Caution"]:
        verdict = "Bullish lean — most forecasters constructive on equities"
    else:
        verdict = "Mixed signals — bulls and bears nearly split"

    st.markdown(MP_CSS, unsafe_allow_html=True)
    st.caption(f"Last updated: {last_updated} · Signals refreshed weekly from public statements and investor letters.")

    # Consensus bar
    st.markdown(f"""
    <div class="mp-consensus-box">
      <p style="font-size:12px;color:#5f5e5a;margin:0 0 8px;">Macro consensus across {total} forecasters</p>
      <div class="mp-bar-track">
        <div style="background:#E24B4A;height:6px;width:{pct_off}%;"></div>
        <div style="background:#EF9F27;height:6px;width:{pct_caut}%;"></div>
        <div style="background:#639922;height:6px;width:{pct_on}%;"></div>
      </div>
      <div class="mp-bar-legend">
        <span class="mp-legend-item"><span class="mp-legend-dot" style="background:#E24B4A;"></span>Risk off ({counts['Risk off']})</span>
        <span class="mp-legend-item"><span class="mp-legend-dot" style="background:#EF9F27;"></span>Caution ({counts['Caution']})</span>
        <span class="mp-legend-item"><span class="mp-legend-dot" style="background:#639922;"></span>Risk on ({counts['Risk on']})</span>
      </div>
      <p class="mp-consensus-verdict">{verdict}</p>
    </div>
    """, unsafe_allow_html=True)

    # Forecaster cards grouped by signal
    grouped = {s: [] for s in SIGNAL_ORDER}
    for f in forecasters:
        sig = f.get("signal", "Caution")
        if sig in grouped:
            grouped[sig].append(f)

    for sig in SIGNAL_ORDER:
        group = grouped[sig]
        if not group:
            continue
        lc = SIGNAL_STYLES[sig]["text"]
        st.markdown(f'<p class="mp-group-label" style="color:{lc};">{sig}</p>', unsafe_allow_html=True)
        for f in group:
            _render_card(f)


# ── Claude Opus refresh ───────────────────────────────────────────────────────
REFRESH_PROMPT = """You are refreshing macro forecaster signals for an investment app called Pie360.

Search for the latest public statements from each of these 9 forecasters and assign each a signal.

Forecasters:
1. Tom Lee (Fundstrat) — equity market & sentiment cycles
2. Ed Yardeni (Yardeni Research) — corporate earnings & productivity growth
3. Jeremy Siegel (Wharton) — long-run equity returns
4. Campbell Harvey (Duke) — yield curve indicator
5. Warren Buffett (Berkshire) — long-term value & market valuation
6. Nouriel Roubini (Atlas Capital) — systemic crisis detection
7. Jeremy Grantham (GMO) — bubble identification
8. Michael Burry (Scion) — contrarian deep value
9. Stanley Druckenmiller (Duquesne) — macro timing & liquidity

For each forecaster:
- Find their most recent public statement, interview, or investor letter (past 3 months)
- Assign a signal: "Risk on", "Caution", or "Risk off"
- Write a 2-sentence plain-English summary
- Record the direct URL of the source
- Record the statement date as "Month D, YYYY"

Return ONLY valid JSON:
{
  "last_updated": "Month D, YYYY",
  "forecasters": [
    {
      "name": "Full Name",
      "specialty": "Their specialty",
      "bias": "Perma-bull|Perma-bear|Neutral|Contrarian|Flexible",
      "signal": "Risk on|Caution|Risk off",
      "summary": "Two plain-English sentences.",
      "source_url": "https://...",
      "statement_date": "Month D, YYYY"
    }
  ]
}

Bias values (keep consistent):
Tom Lee, Ed Yardeni, Jeremy Siegel → "Perma-bull"
Nouriel Roubini, Jeremy Grantham → "Perma-bear"
Warren Buffett, Campbell Harvey → "Neutral"
Michael Burry → "Contrarian"
Stanley Druckenmiller → "Flexible"

Order: Risk on first, then Caution, then Risk off.
Do not fabricate — if no recent source found, use last known position and note the date."""


def refresh_signals() -> None:
    try:
        client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
        with st.spinner("Fetching latest signals from public sources…"):
            response = client.messages.create(
                model      = "claude-opus-4-6",
                max_tokens = 4096,
                timeout    = _REFRESH_TIMEOUT,
                tools      = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 18}],
                messages   = [{"role": "user", "content": REFRESH_PROMPT}],
            )
        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        start, end = text.find("{"), text.rfind("}") + 1
        if start != -1 and end > start:
            new_signals = json.loads(text[start:end])
            st.session_state.macro_signals = new_signals
            _save_signals_to_db(new_signals)
            st.success("Signals updated.")
        else:
            st.warning("Could not parse updated signals — showing last known data.")
    except Exception as e:
        st.error(f"Refresh failed: {e}")


# ── Page ──────────────────────────────────────────────────────────────────────
signals = get_signals()
render_macro_pulse(signals)

st.divider()

col1, col2 = st.columns([3, 1])
with col2:
    if st.button("↻ Refresh signals", use_container_width=True):
        refresh_signals()
        st.rerun()
with col1:
    st.info(
        "💬 **Deep dive or portfolio review?** Ask in the AI chat sidebar — "
        "e.g. *\"Deep dive on Druckenmiller's current positioning\"* or "
        "*\"Given this macro consensus, what should I adjust in my portfolio?\"*"
    )
