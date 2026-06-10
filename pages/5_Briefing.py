"""
Pie360 — AI Research Desk
==========================
Chat-style research interface backed by Claude Sonnet.
Seven quick-start templates plus an open chat input for custom queries.
"""

from __future__ import annotations

import streamlit as st

from ai.claude_client import stream_briefing_section
from components.pulse360_theme import inject_theme
from assets.logo_helper import header_with_logo

inject_theme()
header_with_logo("AI Research Desk", "Claude-powered macro & equity research • type a question or pick a quick-start")

st.markdown("""
<style>
    .main .block-container { padding-top: 1rem; max-width: 1000px; }
</style>
""", unsafe_allow_html=True)

st.caption(
    "*Educational research only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions.*"
)

# ── Quick-start prompt templates ──────────────────────────────────────────────
_QUICK_STARTS: list[tuple[str, str, str]] = [
    (
        "🌍 Macro Snapshot",
        "Macro Snapshot",
        "Search the web and summarise today's macro backdrop for the United States covering "
        "inflation, interest rates, GDP trajectory, and employment. Identify which sectors and "
        "asset classes have historically outperformed in similar conditions. Include 3 historical "
        "parallels and 3 sources.",
    ),
    (
        "📉 Short Squeeze Screen",
        "Short Squeeze Screener",
        "Using web data (Finviz, Shortquote, news), find 5 US stocks in Technology ($1B–$20B "
        "market cap) with short interest above 15%, elevated borrow rate, and a catalyst within "
        "30 days. For each include: % short float, days to cover, catalyst, entry strategy, "
        "failure risk, and sources.",
    ),
    (
        "🤝 M&A Watchlist",
        "M&A Watchlist",
        "Search recent financial news in US Technology. Identify 5 companies ($500M–$10B market "
        "cap) with credible takeover rumours or high acquisition likelihood. For each include: "
        "ticker, most likely acquirer, sector takeover premium, regulatory risk level, and "
        "2 sources.",
    ),
    (
        "🧭 Sentiment vs Fundamentals",
        "Sentiment vs Fundamentals",
        "Find 6 US Industrials stocks ($2B–$50B market cap) where market sentiment is bearish "
        "but fundamentals are strong. For each include: ticker, reason for negative sentiment, "
        "why the fundamentals contradict it, technical entry level, and sources.",
    ),
    (
        "🦈 Hedge Fund Tracker",
        "Hedge Fund Tracker",
        "Using recent 13F data (WhaleWisdom, Dataroma), tell me which sectors and stocks the "
        "top 20 hedge funds are accumulating this quarter vs last. Cover: top accumulations, "
        "full exits, sector rotation, and 3 notable high-conviction single-fund moves with sources.",
    ),
    (
        "🛡️ Portfolio Hedge Builder",
        "Portfolio Hedge Builder",
        "My portfolio is exposed to US equities (S&P 500 heavy), size $500,000, moderate risk "
        "tolerance. Using current options data and inverse ETFs, design an efficient hedge: "
        "instrument, hedge size, annualised cost, activation scenario, and sources.",
    ),
    (
        "📋 Weekly Market Report",
        "Weekly Market Report",
        "Scan the web and deliver a one-page US weekly market briefing covering: top 3 macro "
        "events, earnings estimates for the top S&P 500 reporters this week, sectors with "
        "strongest capital flows, one high-conviction long and one short (moderate risk), "
        "and the top risk to watch. Every source linked.",
    ),
]

# ── Session state ─────────────────────────────────────────────────────────────
if "research_history" not in st.session_state:
    st.session_state["research_history"] = []  # list of {"role": ..., "content": ...}
if "_pending_research" not in st.session_state:
    st.session_state["_pending_research"] = None

# ── Quick-start buttons ───────────────────────────────────────────────────────
cols = st.columns(4)
for i, (label, title, prompt) in enumerate(_QUICK_STARTS):
    with cols[i % 4]:
        if st.button(label, key=f"qs_{i}", use_container_width=True):
            st.session_state["_pending_research"] = (title, prompt)
            st.rerun()

st.markdown("---")

# ── Chat history ──────────────────────────────────────────────────────────────
for msg in st.session_state["research_history"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Process pending quick-start ───────────────────────────────────────────────
pending = st.session_state.pop("_pending_research", None)
if pending:
    title, prompt = pending
    with st.chat_message("user"):
        st.markdown(f"**{title}** *(quick start)*")
    st.session_state["research_history"].append(
        {"role": "user", "content": f"**{title}** *(quick start)*"}
    )
    with st.chat_message("assistant"):
        response = st.write_stream(stream_briefing_section(prompt, max_tokens=2000))
    st.session_state["research_history"].append(
        {"role": "assistant", "content": response}
    )

# ── Open chat input ───────────────────────────────────────────────────────────
if user_input := st.chat_input("Ask anything — macro, equity, sector, hedging…"):
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state["research_history"].append({"role": "user", "content": user_input})
    with st.chat_message("assistant"):
        response = st.write_stream(stream_briefing_section(user_input, max_tokens=2000))
    st.session_state["research_history"].append(
        {"role": "assistant", "content": response}
    )

# ── Footer ────────────────────────────────────────────────────────────────────
if st.session_state["research_history"]:
    st.markdown("---")
    if st.button("🗑️ Clear conversation", key="clear_research"):
        st.session_state["research_history"] = []
        st.rerun()
