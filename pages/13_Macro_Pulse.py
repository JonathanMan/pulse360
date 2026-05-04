import streamlit as st
import anthropic
import json
from datetime import date

from components.auth import require_auth
require_auth()

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
            "signal": "Risk on",
            "summary": (
                "Harvey's yield curve has re-steepened, which historically marks the window where equities "
                "can recover. He notes the recession signal has faded, though the all-clear isn't unconditional."
            ),
        },
        {
            "name": "Warren Buffett",
            "specialty": "Long-term value & market valuation",
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
            "signal": "Caution",
            "summary": (
                "Debt levels and stagflation risk are elevated, but not yet a 2008 scenario. Roubini warns "
                "the tools to fight the next crisis are already depleted."
            ),
        },
        {
            "name": "Jeremy Grantham",
            "specialty": "Bubble identification",
            "signal": "Risk off",
            "summary": (
                "Valuations remain historically extreme. Grantham sees a third bubble in 25 years still "
                "deflating — real assets and emerging markets are his relative shelter."
            ),
        },
        {
            "name": "Michael Burry",
            "specialty": "Contrarian deep value",
            "signal": "Risk off",
            "summary": (
                "Burry has flagged index concentration and passive investment flows as a systemic risk. "
                "He's positioned short on broad indices and long on specific undervalued names."
            ),
        },
        {
            "name": "Stanley Druckenmiller",
            "specialty": "Macro timing & liquidity",
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


def get_signals():
    if "macro_signals" not in st.session_state:
        st.session_state.macro_signals = DEFAULT_SIGNALS
    return st.session_state.macro_signals


def compute_consensus(forecasters):
    counts = {"Risk on": 0, "Caution": 0, "Risk off": 0}
    for f in forecasters:
        signal = f.get("signal", "Caution")
        if signal in counts:
            counts[signal] += 1
    return counts


def build_card_html(f):
    s = SIGNAL_STYLES.get(f["signal"], SIGNAL_STYLES["Caution"])
    return f"""
    <div class="fcard">
      <div class="fcard-top">
        <div>
          <p class="fname">{f['name']}</p>
          <p class="fspecialty">{f['specialty']}</p>
        </div>
        <span class="signal-badge" style="background:{s['bg']};color:{s['text']};">{f['signal']}</span>
      </div>
      <p class="fread">{f['summary']}</p>
    </div>
    """


def build_full_html(signals):
    forecasters = signals["forecasters"]
    last_updated = signals.get("last_updated", str(date.today()))
    counts = compute_consensus(forecasters)
    total = len(forecasters)

    # Consensus bar widths
    pct_off   = round(counts["Risk off"] / total * 100)
    pct_caut  = round(counts["Caution"]  / total * 100)
    pct_on    = 100 - pct_off - pct_caut

    # Consensus verdict
    if counts["Risk off"] > counts["Risk on"] and counts["Risk off"] > counts["Caution"]:
        verdict = "Bearish lean — most forecasters signaling caution or risk off"
    elif counts["Risk on"] > counts["Risk off"] and counts["Risk on"] > counts["Caution"]:
        verdict = "Bullish lean — most forecasters constructive on equities"
    else:
        verdict = "Mixed signals — bulls and bears nearly split"

    # Build grouped cards
    grouped = {s: [] for s in SIGNAL_ORDER}
    for f in forecasters:
        sig = f.get("signal", "Caution")
        if sig in grouped:
            grouped[sig].append(f)

    cards_html = ""
    for sig in SIGNAL_ORDER:
        group = grouped[sig]
        if not group:
            continue
        lc = SIGNAL_STYLES[sig]["label_color"]
        cards_html += f'<p class="group-label" style="color:{lc};">{GROUP_LABELS[sig]}</p>'
        for f in group:
            cards_html += build_card_html(f)

    return f"""
    <style>
      .mp-wrap {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
      .section-label {{ font-size: 11px; font-weight: 500; letter-spacing: 0.08em;
        text-transform: uppercase; color: #888780; margin: 0 0 6px; }}
      .section-title {{ font-size: 20px; font-weight: 500; color: #1a1a18; margin: 0 0 4px; }}
      .section-sub {{ font-size: 13px; color: #5f5e5a; line-height: 1.5; margin: 0 0 14px; }}
      .update-row {{ display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 14px; }}
      .update-time {{ font-size: 12px; color: #888780; }}
      .auto-badge {{ display: inline-flex; align-items: center; gap: 5px; font-size: 11px;
        color: #3B6D11; background: #EAF3DE; border-radius: 20px; padding: 3px 8px;
        margin-bottom: 14px; }}
      .auto-dot {{ width: 6px; height: 6px; border-radius: 50%; background: #639922; }}
      .consensus-box {{ background: #f5f5f3; border: 0.5px solid rgba(0,0,0,0.1);
        border-radius: 10px; padding: 12px 14px; margin-bottom: 18px; }}
      .consensus-label {{ font-size: 12px; color: #5f5e5a; margin: 0 0 8px; }}
      .bar-track {{ border-radius: 4px; height: 6px; width: 100%; margin-bottom: 8px;
        overflow: hidden; display: flex; }}
      .bar-legend {{ display: flex; gap: 14px; }}
      .legend-item {{ font-size: 11px; color: #5f5e5a; display: flex;
        align-items: center; gap: 4px; }}
      .legend-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
      .consensus-verdict {{ font-size: 13px; font-weight: 500; color: #1a1a18; margin: 8px 0 0; }}
      .group-label {{ font-size: 11px; font-weight: 500; letter-spacing: 0.06em;
        text-transform: uppercase; margin: 18px 0 10px 2px; }}
      .fcard {{ background: #ffffff; border: 0.5px solid rgba(0,0,0,0.12);
        border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; }}
      .fcard-top {{ display: flex; align-items: flex-start; justify-content: space-between;
        margin-bottom: 10px; gap: 8px; }}
      .fname {{ font-size: 15px; font-weight: 500; color: #1a1a18; margin: 0 0 2px; }}
      .fspecialty {{ font-size: 12px; color: #5f5e5a; margin: 0; }}
      .signal-badge {{ font-size: 11px; font-weight: 500; padding: 3px 10px;
        border-radius: 20px; white-space: nowrap; flex-shrink: 0; margin-top: 2px; }}
      .fread {{ font-size: 13px; color: #5f5e5a; line-height: 1.55; margin: 0;
        border-left: 2px solid rgba(0,0,0,0.15); padding-left: 10px; }}
    </style>

    <div class="mp-wrap">
      <p class="section-label">Macro pulse</p>
      <p class="section-title">What the top forecasters see</p>
      <p class="section-sub">Signals refreshed weekly from public statements, interviews, and investor letters.</p>
      <span class="auto-badge"><span class="auto-dot"></span>Auto-refreshes every Monday at 8am</span>
      <div class="update-row">
        <span class="update-time">Last updated: {last_updated}</span>
      </div>
      <div class="consensus-box">
        <p class="consensus-label">Macro consensus across {total} forecasters</p>
        <div class="bar-track">
          <div style="background:#E24B4A;height:6px;width:{pct_off}%;"></div>
          <div style="background:#EF9F27;height:6px;width:{pct_caut}%;"></div>
          <div style="background:#639922;height:6px;width:{pct_on}%;"></div>
        </div>
        <div class="bar-legend">
          <span class="legend-item">
            <span class="legend-dot" style="background:#E24B4A;"></span>Risk off ({counts['Risk off']})
          </span>
          <span class="legend-item">
            <span class="legend-dot" style="background:#EF9F27;"></span>Caution ({counts['Caution']})
          </span>
          <span class="legend-item">
            <span class="legend-dot" style="background:#639922;"></span>Risk on ({counts['Risk on']})
          </span>
        </div>
        <p class="consensus-verdict">{verdict}</p>
      </div>
      {cards_html}
    </div>
    """


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
      "signal": "Risk on|Caution|Risk off",
      "summary": "Two plain-English sentences about their current view."
    }
  ]
}

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
            st.success("Signals updated successfully.")
        else:
            st.warning("Could not parse updated signals. Showing last known data.")
    except Exception as e:
        st.error(f"Refresh failed: {e}")


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

signals = get_signals()

# Display HTML section
st.components.v1.html(build_full_html(signals), height=1800, scrolling=False)

st.divider()

col1, col2 = st.columns([2, 1])
with col2:
    if st.button("↻ Refresh signals", use_container_width=True):
        refresh_signals()
        st.rerun()

with col1:
    if st.button("Run full macro-adjusted portfolio review ↗", use_container_width=True, type="primary"):
        counts = compute_consensus(signals["forecasters"])
        prompt = (
            f"The macro forecasters are currently split: "
            f"{counts['Risk on']} risk on, {counts['Caution']} caution, {counts['Risk off']} risk off. "
            f"Run a full Pulse360 macro-adjusted review of my portfolio and give me the top 3 "
            f"changes I should consider given this outlook."
        )
        st.chat_message("assistant").write(
            f"Running a full macro-adjusted portfolio review based on the current forecaster signals "
            f"({counts['Risk on']} risk on / {counts['Caution']} caution / {counts['Risk off']} risk off)..."
        )
