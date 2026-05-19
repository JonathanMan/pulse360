"""
Pie360 — AI Research Desk
=================================
Seven on-demand AI research sections, each running a structured prompt
through Claude Sonnet. Fill in the parameters for each section and click
Run — results stream in live and persist in session state until cleared.

Sections:
  1. Macro Snapshot
  2. Short Squeeze Screener
  3. M&A Watchlist
  4. Sentiment vs Fundamentals
  5. Hedge Fund Tracker
  6. Portfolio Hedge Builder
  7. Weekly Market Report
"""

from __future__ import annotations

import streamlit as st

from ai.claude_client import stream_briefing_section
from components.pulse360_theme import inject_theme

from assets.logo_helper import header_with_logo
header_with_logo("Daily Briefing", "AI-Generated Macro Summary & Investment Recommendations")


inject_theme()

st.markdown("""
<style>
    .main .block-container { padding-top: 1rem; max-width: 1200px; }

    /* ── Result box wrapper (light theme) ── */
    .result-box {
        background: #ffffff;
        border: 1px solid #ececec;
        border-left: 3px solid #0a0a0a;
        border-radius: 8px;
        padding: 18px 20px;
        margin-top: 10px;
        line-height: 1.7;
        color: #0a0a0a;
    }
    .result-box p, .result-box li, .result-box td, .result-box th,
    .result-box span { color: #0a0a0a !important; }
    .result-box h1, .result-box h2, .result-box h3,
    .result-box h4 { color: #0a0a0a !important; font-weight: 600; }

    /* ── Tables inside result boxes (light theme) ── */
    .result-box table {
        width: 100%;
        border-collapse: collapse;
        margin: 8px 0;
    }
    .result-box th {
        background: #f4f4f4 !important;
        color: #0a0a0a !important;
        padding: 8px 12px;
        border: 1px solid #ececec;
        font-size: 13px;
        font-weight: 600;
    }
    .result-box td {
        padding: 7px 12px;
        border: 1px solid #ececec;
        font-size: 13px;
        vertical-align: top;
        color: #0a0a0a !important;
    }
    .result-box tr:nth-child(even) td {
        background: #f9fafb !important;
    }

    /* ── Signal legend chips ── */
    .sig-legend {
        display: inline-flex;
        gap: 14px;
        font-size: 12px;
        color: #6a6a6a;
        margin-bottom: 6px;
    }
    .sig-green  { color: #28a745; font-weight: 600; }
    .sig-orange { color: #c98800; font-weight: 600; }
    .sig-red    { color: #d92626; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 🔬 AI Research Desk")
st.caption(
    "Seven AI-powered research sections — fill in your parameters and click **Run** to stream live analysis from Claude Sonnet. "
    "Results persist in your session until you clear them or restart the app."
)
st.markdown(
    '<div class="sig-legend">'
    '<span class="sig-green">🟢 Positive / Low risk</span>'
    '<span class="sig-orange">🟡 Neutral / Moderate risk</span>'
    '<span class="sig-red">🔴 Negative / High risk</span>'
    "</div>",
    unsafe_allow_html=True,
)
st.caption(
    "*Educational research only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions.*"
)
st.markdown("---")

# ── Session state init ────────────────────────────────────────────────────────
for key in [
    "brief_macro", "brief_squeeze", "brief_ma",
    "brief_sentiment", "brief_hf", "brief_hedge", "brief_weekly",
]:
    if key not in st.session_state:
        st.session_state[key] = ""

# ── Helper: render a streamed section ─────────────────────────────────────────
def _run_section(prompt: str, state_key: str, placeholder) -> None:
    """Stream Claude response into placeholder and persist to session state."""
    st.session_state[state_key] = ""
    full_text = ""
    for chunk in stream_briefing_section(prompt):
        full_text += chunk
        # Render markdown directly so 🟢🟡🔴 and formatting display correctly while streaming
        placeholder.markdown(full_text + " ▌")
    st.session_state[state_key] = full_text
    placeholder.markdown(full_text)

def _result_area(state_key: str) -> None:
    """Render persisted result as styled markdown inside a card container."""
    text = st.session_state.get(state_key, "")
    if not text:
        return
    # Convert markdown → HTML so we can wrap it in a styled div cleanly.
    # Falls back to raw text if the markdown library is not installed.
    try:
        import markdown as _md

        html_body = _md.markdown(
            text,
            extensions=["tables", "fenced_code", "nl2br"],
        )
    except ImportError:
        # Graceful fallback: render as plain markdown outside the styled box
        st.markdown(text)
        return
    st.markdown(
        f'<div class="result-box">{html_body}</div>',
        unsafe_allow_html=True,
    )

# ══════════════════════════════════════════════════════════════════════════════
# 1 · MACRO SNAPSHOT
# ══════════════════════════════════════════════════════════════════════════════

_MACRO_MARKETS = [
    "United States", "Eurozone", "United Kingdom", "Japan", "China",
    "Australia", "Canada", "India", "Brazil", "South Korea",
    "Germany", "France", "Italy", "Spain", "Switzerland",
    "Hong Kong", "Singapore", "South Africa", "Mexico", "Saudi Arabia",
    "Emerging Markets (broad)", "Frontier Markets (broad)",
]

with st.container():
    st.markdown("### 1 · Macro Snapshot")
    st.caption("Search the web and summarise today's macro backdrop across selected markets, identify historically outperforming sectors, and list 3 historical parallels.")

    col1, col2 = st.columns([4, 1])
    with col1:
        macro_markets = st.multiselect(
            "Markets",
            options=_MACRO_MARKETS,
            default=["United States"],
            key="macro_markets",
            placeholder="Select one or more markets…",
        )
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        run_macro = st.button("▶ Run", key="btn_macro", use_container_width=True)

    if run_macro and macro_markets:
        markets_str = ", ".join(macro_markets)
        multi = len(macro_markets) > 1
        prompt = (
            f"Search the web and summarize today's macro backdrop for the following "
            f"{'markets' if multi else 'market'}: {markets_str}.\n\n"
            f"For {'each market' if multi else 'this market'} cover: "
            f"inflation, interest rates, GDP trajectory, and employment.\n"
            + (
                f"After the per-market breakdown, include a **Cross-Market Comparison** section "
                f"highlighting key divergences and convergences between the markets.\n"
                if multi else ""
            )
            + f"Based on the combined setup, identify which sectors and asset classes have "
            f"historically outperformed in similar macro conditions. "
            f"Include 3 historical parallels, the typical outperformance window, and 3 sources.\n\n"
            f"Structure your response with these headers:\n"
            + (
                f"**{'Market-by-Market Backdrop' if multi else 'Current Macro Backdrop'}** "
                f"— {'one sub-section per market with ' if multi else ''}"
                f"key data points for each of the 4 indicators\n"
            )
            + (
                f"**Cross-Market Comparison** — key divergences and what they signal\n"
                if multi else ""
            )
            + f"**Historically Outperforming Sectors & Asset Classes** — table or list with typical outperformance window\n"
            f"**3 Historical Parallels** — date range, macro conditions, what outperformed\n"
            f"**Sources** — 3 linked or named sources"
        )
        placeholder = st.empty()
        with st.spinner(f"Researching macro backdrop for {markets_str}…"):
            _run_section(prompt, "brief_macro", placeholder)
    elif run_macro and not macro_markets:
        st.warning("Please select at least one market.")
    else:
        _result_area("brief_macro")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# 2 · SHORT SQUEEZE SCREENER
# ══════════════════════════════════════════════════════════════════════════════
with st.container():
    st.markdown("### 2 · Short Squeeze Screener")
    st.caption("Find 5 stocks with elevated short interest, high borrow rate, and an upcoming catalyst — using Finviz, Shortquote, and financial news.")

    col1, col2, col3 = st.columns(3)
    with col1:
        sq_sector = st.text_input(
            "Sector / Market Cap Range",
            value="Technology, $1B–$20B",
            key="sq_sector",
            placeholder="e.g. Energy, $500M–$5B",
        )
    with col2:
        sq_short_pct = st.text_input(
            "Min Short Interest",
            value="15%",
            key="sq_short_pct",
            placeholder="e.g. 15%",
        )
    with col3:
        sq_timeframe = st.text_input(
            "Catalyst Timeframe",
            value="30 days",
            key="sq_timeframe",
            placeholder="e.g. 30 days, 2 weeks",
        )

    run_squeeze = st.button("▶ Run", key="btn_squeeze", use_container_width=True)

    if run_squeeze:
        prompt = (
            f"Using web data (Finviz, Shortquote, news), find 5 stocks in {sq_sector} "
            f"with short interest above {sq_short_pct}, elevated borrow rate, and a catalyst within {sq_timeframe}. "
            f"For each ticker include: % short float, days to cover, catalyst, entry strategy, failure risk, and sources.\n\n"
            f"Structure your response as a table or clearly separated entries, one per stock, with all 6 fields for each."
        )
        placeholder = st.empty()
        with st.spinner("Screening for short squeeze candidates…"):
            _run_section(prompt, "brief_squeeze", placeholder)
    else:
        _result_area("brief_squeeze")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# 3 · M&A WATCHLIST
# ══════════════════════════════════════════════════════════════════════════════
with st.container():
    st.markdown("### 3 · M&A Watchlist")
    st.caption("Identify 5 companies with credible takeover rumours or high acquisition likelihood, with acquirer, premium, and regulatory risk.")

    col1, col2 = st.columns(2)
    with col1:
        ma_sector = st.text_input(
            "Sector / Region",
            value="US Technology",
            key="ma_sector",
            placeholder="e.g. European Financials, US Healthcare",
        )
    with col2:
        ma_mktcap = st.text_input(
            "Market Cap Range",
            value="$500M–$10B",
            key="ma_mktcap",
            placeholder="e.g. $1B–$20B",
        )

    run_ma = st.button("▶ Run", key="btn_ma", use_container_width=True)

    if run_ma:
        prompt = (
            f"Search recent financial news in {ma_sector}. "
            f"Identify 5 companies with credible takeover rumors or high acquisition likelihood. "
            f"Market cap range: {ma_mktcap}. "
            f"For each include: ticker, most likely acquirer, sector takeover premium, regulatory risk level, and 2 sources.\n\n"
            f"Structure as 5 clearly separated entries with all 5 fields. "
            f"Be specific about why each company is a credible target (strategic rationale, recent news, financial profile)."
        )
        placeholder = st.empty()
        with st.spinner("Building M&A watchlist…"):
            _run_section(prompt, "brief_ma", placeholder)
    else:
        _result_area("brief_ma")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# 4 · SENTIMENT VS FUNDAMENTALS
# ══════════════════════════════════════════════════════════════════════════════
with st.container():
    st.markdown("### 4 · Sentiment vs Fundamentals")
    st.caption("Find stocks where bearish market sentiment contradicts strong fundamentals — potential mean-reversion opportunities.")

    col1, col2 = st.columns(2)
    with col1:
        sent_sector = st.text_input(
            "Sector / Industry",
            value="US Industrials",
            key="sent_sector",
            placeholder="e.g. Consumer Staples, European Banks",
        )
    with col2:
        sent_mktcap = st.text_input(
            "Market Cap Range",
            value="$2B–$50B",
            key="sent_mktcap",
            placeholder="e.g. $500M–$20B",
        )

    run_sentiment = st.button("▶ Run", key="btn_sentiment", use_container_width=True)

    if run_sentiment:
        prompt = (
            f"Find stocks in {sent_sector} where market sentiment is bearish but fundamentals are strong. "
            f"Market cap: {sent_mktcap}. Return 6 ideas including: ticker, reason for negative sentiment, "
            f"why the fundamentals contradict it, technical entry level, and sources.\n\n"
            f"Structure as 6 clearly separated entries with all 5 fields. "
            f"For 'reason for negative sentiment' cite specific recent events or metrics. "
            f"For 'why fundamentals contradict' cite balance sheet, earnings, or cash flow data. "
            f"For 'technical entry level' give a specific price or technical level with brief rationale."
        )
        placeholder = st.empty()
        with st.spinner("Scanning for sentiment/fundamentals divergence…"):
            _run_section(prompt, "brief_sentiment", placeholder)
    else:
        _result_area("brief_sentiment")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# 5 · HEDGE FUND TRACKER
# ══════════════════════════════════════════════════════════════════════════════
with st.container():
    st.markdown("### 5 · Hedge Fund Tracker")
    st.caption("Track 13F filings — what the top hedge funds are accumulating and exiting this quarter vs last.")

    col1, col2 = st.columns(2)
    with col1:
        hf_number = st.text_input(
            "Number of Funds",
            value="20",
            key="hf_number",
            placeholder="e.g. 10, 20, 50",
        )
    with col2:
        hf_theme = st.text_input(
            "Sector / Theme Focus (optional)",
            value="",
            key="hf_theme",
            placeholder="e.g. AI/Tech, Energy, EM — leave blank for all",
        )

    run_hf = st.button("▶ Run", key="btn_hf", use_container_width=True)

    if run_hf:
        theme_clause = (
            f" Focus on {hf_theme}." if hf_theme.strip() else " Cover all sectors."
        )
        prompt = (
            f"Using recent 13F data (WhaleWisdom, Dataroma), tell me which sectors and stocks "
            f"the top {hf_number} hedge funds are accumulating this quarter vs last quarter.{theme_clause} "
            f"Present new entries, full exits, and increased positions with fund names and sources.\n\n"
            f"Structure your response with these sections:\n"
            f"**Top Accumulations** — stocks with the most new/increased positions, which funds, qty change\n"
            f"**Full Exits** — stocks most funds fully exited this quarter vs last, which funds\n"
            f"**Sector Rotation** — net sector tilts (which sectors gaining/losing hedge fund allocation)\n"
            f"**Notable Individual Moves** — 3–5 high-conviction single-fund moves worth watching\n"
            f"**Sources** — WhaleWisdom, Dataroma, and any other 13F data sources used"
        )
        placeholder = st.empty()
        with st.spinner("Pulling 13F positioning data…"):
            _run_section(prompt, "brief_hf", placeholder)
    else:
        _result_area("brief_hf")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# 6 · PORTFOLIO HEDGE BUILDER
# ══════════════════════════════════════════════════════════════════════════════
with st.container():
    st.markdown("### 6 · Portfolio Hedge Builder")
    st.caption("Design an efficient hedge using options and inverse ETFs given your portfolio exposure, size, and risk tolerance.")

    col1, col2, col3 = st.columns(3)
    with col1:
        hedge_exposure = st.text_input(
            "Portfolio Exposure",
            value="US equities (S&P 500 heavy)",
            key="hedge_exposure",
            placeholder="e.g. US Tech, EM equities, Long duration bonds",
        )
    with col2:
        hedge_size = st.text_input(
            "Portfolio Size ($)",
            value="$500,000",
            key="hedge_size",
            placeholder="e.g. $250,000, $1M",
        )
    with col3:
        hedge_risk = st.selectbox(
            "Risk Tolerance",
            ["Moderate", "Conservative", "Aggressive"],
            key="hedge_risk",
        )

    run_hedge = st.button("▶ Run", key="btn_hedge", use_container_width=True)

    if run_hedge:
        prompt = (
            f"My portfolio is exposed to {hedge_exposure}. "
            f"Current portfolio size: {hedge_size}. "
            f"Risk tolerance: {hedge_risk}. "
            f"Using current options data and inverse ETFs, design an efficient hedge: "
            f"instrument, hedge size (% of portfolio), annualized cost, activation scenario, and sources.\n\n"
            f"Structure your response with these sections:\n"
            f"**Recommended Hedge Strategy** — primary instrument(s), rationale for this exposure\n"
            f"**Implementation** — specific tickers/contracts, hedge size as % of portfolio, entry guidance\n"
            f"**Cost Analysis** — annualised cost of carry, breakeven scenario, drag in bull case\n"
            f"**Activation Scenario** — specific conditions that would trigger the hedge paying off (e.g. SPX -15%, VIX >30)\n"
            f"**Alternatives Considered** — 2 other hedge instruments with pros/cons vs recommended\n"
            f"**Sources** — options chain data, ETF providers, or market data sources referenced"
        )
        placeholder = st.empty()
        with st.spinner("Designing hedge strategy…"):
            _run_section(prompt, "brief_hedge", placeholder)
    else:
        _result_area("brief_hedge")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# 7 · WEEKLY MARKET REPORT
# ══════════════════════════════════════════════════════════════════════════════
with st.container():
    st.markdown("### 7 · Weekly Market Report")
    st.caption("One-page Monday briefing: top 3 macro events, earnings estimates, capital flows, one long and one short with every source linked.")

    col1, col2, col3 = st.columns(3)
    with col1:
        weekly_scope = st.text_input(
            "Scope",
            value="US",
            key="weekly_scope",
            placeholder="e.g. US, Global, Emerging Markets",
        )
    with col2:
        weekly_tickers = st.text_input(
            "Earnings Watch (tickers)",
            value="",
            key="weekly_tickers",
            placeholder="e.g. AAPL, MSFT, AMZN — leave blank for top S&P500",
        )
    with col3:
        weekly_risk = st.selectbox(
            "Risk Level",
            ["Moderate", "Conservative", "Aggressive"],
            key="weekly_risk",
        )

    run_weekly = st.button("▶ Run", key="btn_weekly", use_container_width=True)

    if run_weekly:
        tickers_clause = (
            weekly_tickers.strip() if weekly_tickers.strip()
            else "the top S&P 500 earnings reporters this week"
        )
        prompt = (
            f"Scan the web and deliver a one-page weekly market briefing covering: "
            f"the top 3 macro events for {weekly_scope}, "
            f"earnings estimates for {tickers_clause}, "
            f"sectors with strongest capital flows, "
            f"one high-conviction long and one short with {weekly_risk} risk level, "
            f"and the top risk to watch this week. Every source linked.\n\n"
            f"Structure your response with EXACTLY these sections:\n"
            f"**Top 3 Macro Events This Week** — event, date, expected impact, market reaction to watch\n"
            f"**Earnings Estimates** — ticker, consensus EPS estimate, revenue estimate, key question for the print\n"
            f"**Strongest Capital Flows by Sector** — top 2–3 sectors with net inflows, data source\n"
            f"**High-Conviction Long** — ticker, thesis (3 sentences), entry level, stop loss, target, timeframe\n"
            f"**High-Conviction Short** — ticker, thesis (3 sentences), entry level, stop loss, target, timeframe\n"
            f"**Top Risk to Watch** — specific event/threshold that could disrupt the above calls\n"
            f"**All Sources** — every data source and article linked or named"
        )
        placeholder = st.empty()
        with st.spinner("Building weekly market report…"):
            _run_section(prompt, "brief_weekly", placeholder)
    else:
        _result_area("brief_weekly")

st.markdown("---")

# ── Footer controls ───────────────────────────────────────────────────────────
col_cl, col_sp = st.columns([2, 5])
with col_cl:
    if st.button("🗑️ Clear all results", use_container_width=True):
        for key in [
            "brief_macro", "brief_squeeze", "brief_ma",
            "brief_sentiment", "brief_hf", "brief_hedge", "brief_weekly",
        ]:
            st.session_state[key] = ""
        st.rerun()
with col_sp:
    st.caption(
        "Each section runs independently — click **▶ Run** on any section to refresh it. "
        "Results persist in your session until you clear them or restart the app."
    )
