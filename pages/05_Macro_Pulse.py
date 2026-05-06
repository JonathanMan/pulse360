import streamlit as st
import anthropic
import json
from datetime import date
from components.supabase_client import get_client

# Constrain to a readable width (app.py uses layout="wide")
st.markdown(
    "<style>.main .block-container{max-width:860px;padding-top:1.2rem;}</style>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Default signal data — overwritten on refresh
# ---------------------------------------------------------------------------

DEFAULT_SIGNALS = {
    "last_updated": "May 4, 2026",
    "forecasters": [
        {
            "name": "Tom Lee",
            "specialty": "Equity market & sentiment cycles",
            "bias": "Perma-bull",
            "signal": "Risk on",
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
            "summary": (
                "Druckenmiller is watching Fed policy and liquidity cycles closely. He's reduced equity "
                "exposure and flagged that the easy money environment is structurally over."
            ),
        },
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIGNAL_STYLES = {
    "Risk on":  {"bg": "#EAF3DE", "text": "#3B6D11", "bar": "#639922",  "label_color": "#3B6D11"},
    "Caution":  {"bg": "#FAEEDA", "text": "#854F0B", "bar": "#EF9F27",  "label_color": "#854F0B"},
    "Risk off": {"bg": "#FCEBEB", "text": "#A32D2D", "bar": "#E24B4A",  "label_color": "#A32D2D"},
}

SIGNAL_ORDER = ["Risk on", "Caution", "Risk off"]
GROUP_LABELS = {"Risk on": "Risk on", "Caution": "Caution", "Risk off": "Risk off"}


_SIGNALS_TABLE = "macro_signals"
_SIGNALS_ROW_ID = 1


@st.cache_data(ttl=300)  # refresh from DB at most every 5 minutes
def _load_signals_from_db() -> dict | None:
    """Fetch latest signals from Supabase. Returns None if unavailable."""
    try:
        sb = get_client()
        row = (
            sb.table(_SIGNALS_TABLE)
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


def _save_signals_to_db(signals: dict) -> None:
    """Upsert signals to Supabase and bust the cache so next load is fresh."""
    try:
        sb = get_client()
        sb.table(_SIGNALS_TABLE).upsert({
            "id": _SIGNALS_ROW_ID,
            "signals_json": signals,
        }).execute()
        _load_signals_from_db.clear()
    except Exception as e:
        st.warning(f"Could not save signals to database: {e}")


def get_signals() -> dict:
    """Return signals: session_state → Supabase DB → DEFAULT_SIGNALS fallback."""
    if "macro_signals" in st.session_state:
        return st.session_state.macro_signals
    db_signals = _load_signals_from_db()
    if db_signals:
        st.session_state.macro_signals = db_signals
        return db_signals
    return DEFAULT_SIGNALS


def compute_consensus(forecasters):
    counts = {"Risk on": 0, "Caution": 0, "Risk off": 0}
    for f in forecasters:
        signal = f.get("signal", "Caution")
        if signal in counts:
            counts[signal] += 1
    return counts


BIAS_STYLES = {
    "Perma-bull":  {"color": "#2a6ebb", "bg": "#e8f1fb"},
    "Perma-bear":  {"color": "#a32d2d", "bg": "#faeaea"},
    "Neutral":     {"color": "#5f5e5a", "bg": "#f0f0ee"},
    "Contrarian":  {"color": "#7a4d00", "bg": "#fdf0dc"},
    "Flexible":    {"color": "#3a5f3a", "bg": "#e8f5e8"},
}


def build_card_html(f):
    s = SIGNAL_STYLES.get(f["signal"], SIGNAL_STYLES["Caution"])
    bias = f.get("bias", "")
    bs = BIAS_STYLES.get(bias, {"color": "#888", "bg": "#f0f0f0"})
    bias_html = (
        f'<span class="bias-tag" style="color:{bs["color"]};background:{bs["bg"]};">'
        f'{bias}</span>'
    ) if bias else ""
    return f"""
    <div class="fcard">
      <div class="fcard-top">
        <div>
          <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">
            <p class="fname" style="margin:0;">{f['name']}</p>
            {bias_html}
          </div>
          <p class="fspecialty">{f['specialty']}</p>
        </div>
        <span class="signal-badge" style="background:{s['bg']};color:{s['text']};">{f['signal']}</span>
      </div>
      <p class="fread">{f['summary']}</p>
    </div>
    """


MP_CSS = """
<style>
  .mp-section-label { font-size: 11px; font-weight: 500; letter-spacing: 0.08em;
    text-transform: uppercase; color: #888780; margin: 0 0 6px; }
  .mp-section-title { font-size: 20px; font-weight: 500; color: #1a1a18; margin: 0 0 4px; }
  .mp-section-sub { font-size: 13px; color: #5f5e5a; line-height: 1.5; margin: 0 0 10px; }
  .mp-auto-badge { display: inline-flex; align-items: center; gap: 5px; font-size: 11px;
    color: #3B6D11; background: #EAF3DE; border-radius: 20px; padding: 3px 8px;
    margin-bottom: 10px; }
  .mp-auto-dot { width: 6px; height: 6px; border-radius: 50%; background: #639922;
    display: inline-block; }
  .mp-update-time { font-size: 12px; color: #888780; margin-bottom: 14px; }
  .mp-consensus-box { background: #f5f5f3; border: 0.5px solid rgba(0,0,0,0.1);
    border-radius: 10px; padding: 12px 14px; margin-bottom: 18px; }
  .mp-consensus-label { font-size: 12px; color: #5f5e5a; margin: 0 0 8px; }
  .mp-bar-track { border-radius: 4px; height: 6px; width: 100%; margin-bottom: 8px;
    overflow: hidden; display: flex; }
  .mp-bar-legend { display: flex; gap: 14px; }
  .mp-legend-item { font-size: 11px; color: #5f5e5a; display: flex;
    align-items: center; gap: 4px; }
  .mp-legend-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
    display: inline-block; }
  .mp-consensus-verdict { font-size: 13px; font-weight: 500; color: #1a1a18; margin: 8px 0 0; }
  .mp-group-label { font-size: 11px; font-weight: 500; letter-spacing: 0.06em;
    text-transform: uppercase; margin: 16px 0 8px 2px; }
  .mp-fcard { background: #ffffff; border: 0.5px solid rgba(0,0,0,0.12);
    border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; }
  .mp-fcard-top { display: flex; align-items: flex-start; justify-content: space-between;
    margin-bottom: 10px; gap: 8px; }
  .mp-fname { font-size: 15px; font-weight: 500; color: #1a1a18; margin: 0 0 2px; }
  .mp-fspecialty { font-size: 12px; color: #5f5e5a; margin: 0; }
  .mp-signal-badge { font-size: 11px; font-weight: 500; padding: 3px 10px;
    border-radius: 20px; white-space: nowrap; flex-shrink: 0; margin-top: 2px; }
  .mp-fread { font-size: 13px; color: #5f5e5a; line-height: 1.55; margin: 0;
    border-left: 2px solid rgba(0,0,0,0.15); padding-left: 10px; }
  .mp-bias-tag { font-size: 10px; font-weight: 500; padding: 2px 7px;
    border-radius: 20px; white-space: nowrap; letter-spacing: 0.02em; }
</style>
"""


def build_card_html_native(f):
    """Card HTML for native st.markdown rendering (prefixed classes, no iframe)."""
    s = SIGNAL_STYLES.get(f["signal"], SIGNAL_STYLES["Caution"])
    bias = f.get("bias", "")
    bs = BIAS_STYLES.get(bias, {"color": "#888", "bg": "#f0f0f0"})
    bias_html = (
        f'<span class="mp-bias-tag" style="color:{bs["color"]};background:{bs["bg"]};">'
        f'{bias}</span>'
    ) if bias else ""
    return f"""
    <div class="mp-fcard">
      <div class="mp-fcard-top">
        <div>
          <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">
            <p class="mp-fname" style="margin:0;">{f['name']}</p>
            {bias_html}
          </div>
          <p class="mp-fspecialty">{f['specialty']}</p>
        </div>
        <span class="mp-signal-badge" style="background:{s['bg']};color:{s['text']};">{f['signal']}</span>
      </div>
      <p class="mp-fread">{f['summary']}</p>
    </div>
    """


def _run_deep_dive(f):
    """Synchronous deep-dive call — returns full text. Short enough that streaming isn't needed."""
    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    first_name = f["name"].split()[0]
    prompt = f"""You are a macro research analyst at Pulse360 giving a concise deep dive on one forecaster.

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
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _render_forecaster_card(f):
    """Render a single forecaster card with an interactive deep-dive CTA."""
    card_key = f["name"].replace(" ", "_").lower()
    dd_key = f"deep_dive_{card_key}"

    s = SIGNAL_STYLES.get(f["signal"], SIGNAL_STYLES["Caution"])
    bias = f.get("bias", "")
    bs = BIAS_STYLES.get(bias, {"color": "#888", "bg": "#f0f0f0"})
    bias_html = (
        f'<span class="mp-bias-tag" style="color:{bs["color"]};background:{bs["bg"]};">'
        f'{bias}</span>'
    ) if bias else ""

    with st.container(border=True):
        # Header: name + bias on left, signal badge on right
        col_info, col_badge = st.columns([5, 1])
        with col_info:
            st.markdown(f"""
              <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-bottom:2px;">
                <p class="mp-fname" style="margin:0;">{f['name']}</p>{bias_html}
              </div>
              <p class="mp-fspecialty">{f['specialty']}</p>
            """, unsafe_allow_html=True)
        with col_badge:
            st.markdown(
                f'<div style="text-align:right;margin-top:4px;">'
                f'<span class="mp-signal-badge" style="background:{s["bg"]};color:{s["text"]};">'
                f'{f["signal"]}</span></div>',
                unsafe_allow_html=True,
            )

        # Summary
        st.markdown(
            f'<p class="mp-fread">{f["summary"]}</p>',
            unsafe_allow_html=True,
        )

        # State: None → show button | "run" → fetch | string → show result
        dd_state = st.session_state.get(dd_key)

        if dd_state == "run":
            # Fetch and cache
            st.divider()
            with st.spinner(f"Analysing {f['name'].split()[0]}..."):
                result = _run_deep_dive(f)
            st.session_state[dd_key] = result
            st.rerun()

        elif dd_state:
            # Show cached result
            st.divider()
            st.markdown(dd_state)
            if st.button("✕ Close", key=f"close_{card_key}"):
                del st.session_state[dd_key]
                st.rerun()

        else:
            # Show CTA button
            if st.button(
                f"Deep dive: {f['name'].split()[0]} ↗",
                key=f"btn_{card_key}",
            ):
                st.session_state[dd_key] = "run"
                st.rerun()


def render_macro_pulse(signals):
    """Render the full Macro Pulse section using native st.markdown — no iframe."""
    forecasters = signals["forecasters"]
    last_updated = signals.get("last_updated", str(date.today()))
    counts = compute_consensus(forecasters)
    total = len(forecasters)

    pct_off  = round(counts["Risk off"] / total * 100)
    pct_caut = round(counts["Caution"]  / total * 100)
    pct_on   = 100 - pct_off - pct_caut

    if counts["Risk off"] > counts["Risk on"] and counts["Risk off"] > counts["Caution"]:
        verdict = "Bearish lean — most forecasters signaling caution or risk off"
    elif counts["Risk on"] > counts["Risk off"] and counts["Risk on"] > counts["Caution"]:
        verdict = "Bullish lean — most forecasters constructive on equities"
    else:
        verdict = "Mixed signals — bulls and bears nearly split"

    # Inject CSS once
    st.markdown(MP_CSS, unsafe_allow_html=True)

    # Header
    st.markdown(f"""
      <p class="mp-section-label">Macro pulse</p>
      <p class="mp-section-title">What the top forecasters see</p>
      <p class="mp-section-sub">Signals refreshed weekly from public statements, interviews, and investor letters.</p>
      <span class="mp-auto-badge"><span class="mp-auto-dot"></span>Auto-refreshes every Monday at 8am</span>
      <p class="mp-update-time">Last updated: {last_updated}</p>
    """, unsafe_allow_html=True)

    # Consensus box
    st.markdown(f"""
      <div class="mp-consensus-box">
        <p class="mp-consensus-label">Macro consensus across {total} forecasters</p>
        <div class="mp-bar-track">
          <div style="background:#E24B4A;height:6px;width:{pct_off}%;"></div>
          <div style="background:#EF9F27;height:6px;width:{pct_caut}%;"></div>
          <div style="background:#639922;height:6px;width:{pct_on}%;"></div>
        </div>
        <div class="mp-bar-legend">
          <span class="mp-legend-item">
            <span class="mp-legend-dot" style="background:#E24B4A;"></span>Risk off ({counts['Risk off']})
          </span>
          <span class="mp-legend-item">
            <span class="mp-legend-dot" style="background:#EF9F27;"></span>Caution ({counts['Caution']})
          </span>
          <span class="mp-legend-item">
            <span class="mp-legend-dot" style="background:#639922;"></span>Risk on ({counts['Risk on']})
          </span>
        </div>
        <p class="mp-consensus-verdict">{verdict}</p>
      </div>
    """, unsafe_allow_html=True)

    # Grouped forecaster cards
    grouped = {s: [] for s in SIGNAL_ORDER}
    for f in forecasters:
        sig = f.get("signal", "Caution")
        if sig in grouped:
            grouped[sig].append(f)

    for sig in SIGNAL_ORDER:
        group = grouped[sig]
        if not group:
            continue
        lc = SIGNAL_STYLES[sig]["label_color"]
        st.markdown(
            f'<p class="mp-group-label" style="color:{lc};">{GROUP_LABELS[sig]}</p>',
            unsafe_allow_html=True,
        )
        for f in group:
            _render_forecaster_card(f)


# ---------------------------------------------------------------------------
# Refresh via Anthropic API (web search)
# ---------------------------------------------------------------------------

REFRESH_PROMPT = """You are refreshing macro forecaster signals for an investment app called Pulse360.

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

Return ONLY valid JSON in this exact format:
{
  "last_updated": "Month D, YYYY",
  "forecasters": [
    {
      "name": "Full Name",
      "specialty": "Their specialty",
      "bias": "Perma-bull|Perma-bear|Neutral|Contrarian|Flexible",
      "signal": "Risk on|Caution|Risk off",
      "summary": "Two plain-English sentences about their current view."
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


def refresh_signals():
    try:
        client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
        with st.spinner("Fetching latest signals from public sources..."):
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4096,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 18}],
                messages=[{"role": "user", "content": REFRESH_PROMPT}],
            )
        # Extract text content from response
        text_content = ""
        for block in response.content:
            if hasattr(block, "text"):
                text_content += block.text

        # Parse JSON from response
        start = text_content.find("{")
        end = text_content.rfind("}") + 1
        if start != -1 and end > start:
            new_signals = json.loads(text_content[start:end])
            st.session_state.macro_signals = new_signals
            _save_signals_to_db(new_signals)  # persist across sessions
            st.success("Signals updated successfully.")
        else:
            st.warning("Could not parse updated signals. Showing last known data.")
    except Exception as e:
        st.error(f"Refresh failed: {e}")


# ---------------------------------------------------------------------------
# Portfolio review helpers
# ---------------------------------------------------------------------------

def _build_review_prompt(signals):
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


def _stream_review(prompt):
    """Generator that yields text chunks from Claude for st.write_stream."""
    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        yield from stream.text_stream


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

if "portfolio_review" not in st.session_state:
    st.session_state.portfolio_review = None

signals = get_signals()

render_macro_pulse(signals)

st.divider()

col1, col2 = st.columns([2, 1])
with col2:
    if st.button("↻ Refresh signals", use_container_width=True):
        refresh_signals()
        st.session_state.portfolio_review = None  # clear stale review on signal refresh
        st.rerun()

with col1:
    run_review = st.button(
        "Run full macro-adjusted portfolio review ↗",
        use_container_width=True,
        type="primary",
    )

if run_review:
    prompt = _build_review_prompt(signals)
    st.markdown("---")
    st.markdown("#### Macro-Adjusted Portfolio Review")
    try:
        result = st.write_stream(_stream_review(prompt))
        st.session_state.portfolio_review = result
    except Exception as e:
        st.error(f"Review failed: {e}")
elif st.session_state.portfolio_review:
    st.markdown("---")
    st.markdown("#### Macro-Adjusted Portfolio Review")
    st.markdown(st.session_state.portfolio_review)
