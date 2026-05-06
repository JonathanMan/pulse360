"""
Pie360 — Main Dashboard
AI-powered economic cycle dashboard · Personal-use MVP

This file is loaded by app.py via st.navigation(). set_page_config is
handled once in app.py — do NOT call it here.
"""

# ── Imports ───────────────────────────────────────────────────────────────────
import streamlit as st
from datetime import date, datetime
from typing import Optional

import plotly.graph_objects as go

from components.overview_row import render_overview_row
from components.weekly_diff import render_weekly_diff
from components.tabs.tab1_macro     import render_tab1
from components.tabs.tab2_growth    import render_tab2
from components.tabs.tab3_labor     import render_tab3
from components.tabs.tab4_inflation import render_tab4
from components.tabs.tab5_monetary  import render_tab5
from components.tabs.tab6_markets   import render_tab6
from components.tabs.tab7_housing   import render_tab7
from components.tabs.tab8_global    import render_tab8

from data.fred_client import (
    compute_lei_growth,
    fetch_model_inputs,
    fetch_series,
    prefetch_all_series,
)
from models.cycle_classifier import classify_cycle_phase
from models.recession_model import run_recession_model
from data.fred_client import compute_cfnai_signal
from ai.claude_client import (
    format_features_for_prompt,
    get_daily_briefing,
    stream_chat_response,
)
from ai.email_briefing import compose_briefing_html, send_briefing_email
from components.chart_utils import dark_layout, add_nber, chart_meta
from models.backtest import run_historical_backtest
from data.market_client import fetch_shiller_cape, fetch_sector_returns

# ── Compliance disclaimer ─────────────────────────────────────────────────────
DISCLAIMER = (
    "*Educational macro analysis only — not personalized investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pie360 is not a Registered Investment Advisor.*"
)

# ── Page CSS ──────────────────────────────────────────────────────────────────
from components.pulse360_theme import inject_theme

from assets.logo_helper import header_with_logo
inject_theme()
st.markdown("""
<style>
    .main .block-container { padding-top: 1rem; max-width: 1400px; }
    section[data-testid="stSidebar"] { width: 360px !important; }
</style>
""", unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────────────────────
col_h, col_r = st.columns([8, 1])
with col_h:
    header_with_logo("Dashboard", "Pie360 — AI-Powered Economic Cycle Dashboard")
with col_r:
    st.markdown("<br><br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh", help="Clear cache and reload all data"):
        st.cache_data.clear()
        st.rerun()

# ── Cold-start cache warm-up (runs once per server process) ───────────────────
@st.cache_resource(show_spinner=False)
def _warm_caches() -> None:
    """
    Fire all data fetches in parallel at cold start so the first render is fast.
    - FRED series (all tabs, model inputs, yield curve)
    - Shiller CAPE (Yale Excel, ~24h TTL)
    - Sector ETF returns (yfinance, ~1h TTL)
    All are @st.cache_data calls so subsequent reruns hit memory instantly.
    """
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=3) as pool:
        pool.submit(prefetch_all_series)   # populates all FRED @st.cache_data
        pool.submit(fetch_shiller_cape)    # pre-warm Yale CAPE
        pool.submit(fetch_sector_returns)  # pre-warm sector ETF heatmap

_warm_caches()

# ── Load model data ────────────────────────────────────────────────────────────
with st.spinner("Loading economic data…"):
    model_inputs = fetch_model_inputs()

model_output = run_recession_model(model_inputs)
lei_growth   = compute_cfnai_signal(model_inputs["CFNAI"]["data"])

unrate_result = fetch_series("UNRATE", start_date="2010-01-01")
unrate_data   = unrate_result["data"] if not unrate_result["data"].empty else None
unrate_latest = float(unrate_result["last_value"]) if unrate_result["last_value"] else None

nber_result = fetch_series("USREC", start_date="2010-01-01")
nber_active = (
    not nber_result["data"].empty and bool(nber_result["data"].iloc[-1] == 1)
)

phase_output = classify_cycle_phase(
    model_output = model_output,
    lei_growth   = lei_growth,
    unrate_data  = unrate_data,
    nber_active  = nber_active,
)

# ── Month-over-month probability delta ────────────────────────────────────────
def _prev_month_prob() -> Optional[float]:
    """Return last month's recession probability from the cached backtest.

    Cached in session_state so the backtest only runs once per session,
    not on every Streamlit rerun.
    """
    _CACHE_KEY = "_p360_prev_prob_cache"
    if _CACHE_KEY in st.session_state:
        return st.session_state[_CACHE_KEY]
    try:
        bt = run_historical_backtest()
        if bt.empty or len(bt) < 2:
            result = None
        else:
            result = float(bt["probability"].iloc[-2])
    except Exception:
        result = None
    st.session_state[_CACHE_KEY] = result
    return result

_prev_prob = _prev_month_prob()
prob_delta: Optional[float] = (
    round(model_output.probability - _prev_prob, 1)
    if _prev_prob is not None else None
)

# ── Share model state with other pages via session_state ──────────────────────
st.session_state["cycle_phase"]           = phase_output.phase
st.session_state["recession_probability"] = model_output.probability
st.session_state["traffic_light"]         = model_output.traffic_light
st.session_state["feature_summary"]       = format_features_for_prompt(model_output.features)

# Populate live values for the alert engine (keyed by FRED series_id)
st.session_state["pulse360_recession_prob"] = model_output.probability
st.session_state["pulse360_live_values"] = {
    f.series_id: f.current_value
    for f in model_output.features
    if f.current_value is not None
}

# ── Persistent overview row ────────────────────────────────────────────────────
render_overview_row(model_output, phase_output, lei_growth, prob_delta=prob_delta)

# ── Weekly diff panel ─────────────────────────────────────────────────────────
render_weekly_diff(
    model_output     = model_output,
    phase_output     = phase_output,
    prev_month_prob  = _prev_prob,
)

# ── Tabs ───────────────────────────────────────────────────────────────────────
tabs = st.tabs([
    "1 · Macro Overview",
    "2 · Growth",
    "3 · Labor",
    "4 · Inflation",
    "5 · Monetary Policy",
    "6 · Markets",
    "7 · Housing & Consumer",
    "8 · Global",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Macro Overview & Cycle Phase
# ══════════════════════════════════════════════════════════════════════════════

with tabs[0]:
    render_tab1(model_output, phase_output, lei_growth=lei_growth)

# ══════════════════════════════════════════════════════════════════════════════
# TABS 2–8 — Full tab renders
# ══════════════════════════════════════════════════════════════════════════════

with tabs[1]:
    render_tab2(model_output, phase_output)

with tabs[2]:
    render_tab3(model_output, phase_output)

with tabs[3]:
    render_tab4(model_output, phase_output)

with tabs[4]:
    render_tab5(model_output, phase_output)

with tabs[5]:
    render_tab6(model_output, phase_output)

with tabs[6]:
    render_tab7(model_output, phase_output)

with tabs[7]:
    render_tab8(model_output, phase_output)

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — Quick Stats + AI Daily Briefing + Chat
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    # ── Quick Stats (compact card) ───────────────────────────────────────────
    tl_color  = {"green": "#28a745", "yellow": "#c98800", "red": "#d92626"}.get(
        model_output.traffic_light, "#6a6a6a"
    )
    delta_html = ""
    if prob_delta is not None:
        d_color = "#d92626" if prob_delta > 0 else "#00a35a"
        d_arrow = "▲" if prob_delta > 0 else "▼"
        delta_html = (
            f'<span style="font-size:11px;color:{d_color};margin-left:6px;">'
            f'{d_arrow} {prob_delta:+.1f}pp MoM</span>'
        )
    cfnai_html = ""
    if lei_growth is not None:
        c_color = "#28a745" if lei_growth > 0 else "#d92626"
        cfnai_html = (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:4px 0;border-top:1px solid #ececec;">'
            f'<span style="color:#6a6a6a;font-size:12px;">CFNAI 3M avg</span>'
            f'<span style="color:{c_color};font-size:12px;font-weight:600;">'
            f'{lei_growth:+.3f}</span></div>'
        )
    conf_color = {"High": "#28a745", "Medium": "#c98800", "Low": "#d92626"}.get(
        phase_output.confidence, "#6a6a6a"
    )
    st.markdown(
        f"""
        <div style="background:#ffffff;border:1px solid #ececec;border-radius:10px;
                    padding:10px 14px;margin-bottom:8px;">
          <div style="font-size:11px;color:#a0a0a0;margin-bottom:6px;font-weight:600;
                      letter-spacing:.05em;">📊 QUICK STATS</div>
          <div style="display:flex;justify-content:space-between;align-items:baseline;
                      padding:4px 0;border-top:1px solid #ececec;">
            <span style="color:#6a6a6a;font-size:12px;">Recession Prob.</span>
            <span>
              <span style="color:{tl_color};font-size:18px;font-weight:700;">
                {model_output.probability:.1f}%
              </span>{delta_html}
            </span>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;
                      padding:4px 0;border-top:1px solid #ececec;">
            <span style="color:#6a6a6a;font-size:12px;">Cycle Phase</span>
            <span style="color:#0a0a0a;font-size:13px;font-weight:600;">
              {phase_output.emoji} {phase_output.phase}
            </span>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;
                      padding:4px 0;border-top:1px solid #ececec;">
            <span style="color:#6a6a6a;font-size:12px;">Confidence</span>
            <span style="color:{conf_color};font-size:12px;font-weight:600;">
              {phase_output.confidence}
            </span>
          </div>
          {cfnai_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # ── Daily Briefing ───────────────────────────────────────────────────────
    st.markdown("### 🤖 AI Daily Briefing")
    st.caption("Powered by Claude Sonnet · Cached 6 hours")

    if st.button("📋 Generate Briefing", use_container_width=True, key="gen_briefing"):
        st.session_state["show_briefing"] = True

    if st.session_state.get("show_briefing"):
        with st.spinner("Generating daily briefing…"):
            feature_dicts = format_features_for_prompt(model_output.features)
            briefing_text = get_daily_briefing(
                date_str              = date.today().strftime("%Y-%m-%d"),
                cycle_phase           = phase_output.phase,
                phase_confidence      = phase_output.confidence,
                recession_probability = model_output.probability,
                traffic_light         = model_output.traffic_light,
                feature_contributions = feature_dicts,
                lei_growth            = lei_growth,
                unrate                = unrate_latest,
                nber_active           = nber_active,
                recent_crossings      = None,
                recent_releases       = None,
            )
        st.session_state["briefing_text"] = briefing_text
        st.markdown(briefing_text)

    elif "briefing_text" in st.session_state:
        st.markdown(st.session_state["briefing_text"])

    # ── Email briefing button ────────────────────────────────────────────────
    if st.session_state.get("briefing_text"):
        if st.button("📧 Email me this briefing", use_container_width=True, key="email_briefing"):
            html = compose_briefing_html(
                briefing_md           = st.session_state["briefing_text"],
                cycle_phase           = phase_output.phase,
                recession_probability = model_output.probability,
                traffic_light         = model_output.traffic_light,
            )
            ok, msg = send_briefing_email(
                to      = st.secrets.get("BRIEFING_EMAIL", "jonathancyman@gmail.com"),
                subject = (
                    f"Pie360 · {date.today():%d %b %Y} · "
                    f"{phase_output.phase} · {model_output.probability:.0f}% risk"
                ),
                html    = html,
            )
            if ok:
                st.success(msg)
            else:
                st.warning(
                    f"{msg}\n\n"
                    "To activate email delivery, open `ai/email_briefing.py` and "
                    "uncomment one of the transport blocks (Gmail, Resend, or SendGrid)."
                )

    st.markdown("---")

    # ── Chat Sidebar ─────────────────────────────────────────────────────────
    st.markdown("### 💬 Ask Pie360 AI")
    st.caption("Claude Haiku · Context-aware macro Q&A")

    # Initialise chat history
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []

    # Cap history at 20 messages (10 exchanges) to prevent unbounded context
    # growth that slows down each Claude API call.
    _MAX_CHAT_MESSAGES = 20
    if len(st.session_state["chat_messages"]) > _MAX_CHAT_MESSAGES:
        st.session_state["chat_messages"] = (
            st.session_state["chat_messages"][-_MAX_CHAT_MESSAGES:]
        )

    # Display history (scrollable within expander to save space)
    if st.session_state["chat_messages"]:
        with st.expander(
            f"Chat history ({len(st.session_state['chat_messages'])} messages)",
            expanded=True,
        ):
            for msg in st.session_state["chat_messages"]:
                role_label = "**You**" if msg["role"] == "user" else "**Pie360 AI**"
                st.markdown(f"{role_label}: {msg['content']}")
                st.markdown("---")

        if st.button("🗑️ Clear chat", use_container_width=True, key="clear_chat"):
            st.session_state["chat_messages"] = []
            st.rerun()

    # ── Chat input ────────────────────────────────────────────────────────────
    with st.form("chat_form", clear_on_submit=True):
        user_input = st.text_area(
            "Ask a macro question…",
            placeholder="e.g. What does the yield curve inversion mean for equities?",
            height=80,
            key="chat_input_area",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Send ▶", use_container_width=True)

    if submitted and user_input.strip():
        # Append user message
        st.session_state["chat_messages"].append(
            {"role": "user", "content": user_input.strip()}
        )

        # Build feature summary for system prompt
        feature_dicts_chat = format_features_for_prompt(model_output.features)

        # Stream the response
        with st.spinner("Thinking…"):
            response_chunks = list(stream_chat_response(
                messages              = st.session_state["chat_messages"],
                cycle_phase           = phase_output.phase,
                recession_probability = model_output.probability,
                traffic_light         = model_output.traffic_light,
                feature_summary       = feature_dicts_chat,
                active_tab            = "Dashboard",
                lei_growth            = lei_growth,
            ))
        response_text = "".join(response_chunks)

        # Append assistant message
        st.session_state["chat_messages"].append(
            {"role": "assistant", "content": response_text}
        )
        st.rerun()

    st.markdown("---")
    st.caption(f"Refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    st.caption(DISCLAIMER)
