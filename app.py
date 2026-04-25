"""
Pulse360 — AI-powered economic cycle dashboard
Personal-use MVP · Streamlit Cloud

Run locally:  streamlit run app.py
Deploy:       push to GitHub → connect to Streamlit Cloud → add secrets
"""

# ── Page config (must be the FIRST Streamlit call) ────────────────────────────
import streamlit as st

st.set_page_config(
    page_title="Pulse360",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports ───────────────────────────────────────────────────────────────────
from datetime import date, datetime
from typing import Optional

import plotly.graph_objects as go

from components.overview_row import render_overview_row
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
)
from models.cycle_classifier import classify_cycle_phase
from models.recession_model import run_recession_model
from data.fred_client import compute_cfnai_signal
from ai.claude_client import (
    format_features_for_prompt,
    get_daily_briefing,
    stream_chat_response,
)
from components.chart_utils import dark_layout, add_nber, chart_meta

# ── Compliance disclaimer ─────────────────────────────────────────────────────
DISCLAIMER = (
    "*Educational macro analysis only — not personalized investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)

# ── Dark-theme CSS ────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .main .block-container { padding-top: 1rem; max-width: 1400px; }
    div[data-testid="metric-container"] {
        background: #1a1a2e; border-radius: 8px;
        padding: 12px 16px; border: 1px solid #333;
    }
    .stTabs [data-baseweb="tab-list"]  { gap: 4px; }
    .stTabs [data-baseweb="tab"]       { background-color: #1a1a2e;
                                         border-radius: 6px 6px 0 0;
                                         padding: 8px 14px; }
    .stTabs [aria-selected="true"]     { background-color: #2a2a4a; }
    .stExpander { border: 1px solid #333 !important; border-radius: 8px !important; }
    section[data-testid="stSidebar"] { width: 360px !important; }
    .stChatMessage { background: #1a1a2e; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────────────────────
col_h, col_r = st.columns([6, 1])
with col_h:
    st.markdown("# 📊 Pulse360")
    st.caption("AI-powered economic cycle dashboard · Personal use")
with col_r:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh", help="Clear cache and reload all data"):
        st.cache_data.clear()
        st.rerun()

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

# ── Persistent overview row ────────────────────────────────────────────────────
render_overview_row(model_output, phase_output, lei_growth)

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
# Shared chart utilities (also used directly in Tab 1 below)
# ══════════════════════════════════════════════════════════════════════════════

def _chart_meta(result: dict, decimals: int = 2) -> None:
    """Local alias — delegates to components.chart_utils.chart_meta."""
    chart_meta(result, decimals)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Macro Overview & Cycle Phase
# ══════════════════════════════════════════════════════════════════════════════

with tabs[0]:
    st.subheader("Macro Overview & Cycle Phase")

    # Time window
    col_tw, _ = st.columns([5, 1])
    with _:
        tw_choice = st.radio("View", ["5Y", "10Y", "20Y"], index=1, horizontal=True,
                             key="tab1_window", label_visibility="collapsed")
    from datetime import timedelta
    today_dt = date.today()
    tw_start = (today_dt - timedelta(days={"5Y": 5*365, "10Y": 10*365, "20Y": 20*365}[tw_choice])).strftime("%Y-%m-%d")

    gdp_lvl  = fetch_series("GDPC1",            start_date=tw_start)
    gdp_gr   = fetch_series("A191RL1Q225SBEA",   start_date=tw_start)
    lei_res  = fetch_series("CFNAI",             start_date=tw_start)

    col1, col2 = st.columns(2)

    # Real GDP level
    with col1:
        st.markdown("##### Real GDP Level")
        if not gdp_lvl["data"].empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=gdp_lvl["data"].index, y=gdp_lvl["data"].values,
                mode="lines", line={"color": "#3498db", "width": 2},
                name="Real GDP",
            ))
            fig = add_nber(fig, start_date=tw_start)
            fig = dark_layout(fig, yaxis_title="Billions (2017 $)")
            st.plotly_chart(fig, use_container_width=True, key="gdp_lvl")
        _chart_meta(gdp_lvl)

    # Real GDP growth
    with col2:
        st.markdown("##### Real GDP Growth (QoQ Ann.)")
        if not gdp_gr["data"].empty:
            colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in gdp_gr["data"].values]
            fig = go.Figure(go.Bar(
                x=gdp_gr["data"].index, y=gdp_gr["data"].values,
                marker_color=colors, name="GDP Growth",
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="#555", line_width=1)
            fig = add_nber(fig, start_date=tw_start)
            fig = dark_layout(fig, yaxis_title="% QoQ Annualised")
            st.plotly_chart(fig, use_container_width=True, key="gdp_gr")
        _chart_meta(gdp_gr)

    # LEI
    st.markdown("##### Chicago Fed National Activity Index (CFNAI)")
    if not lei_res["data"].empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=lei_res["data"].index, y=lei_res["data"].values,
            mode="lines", line={"color": "#9b59b6", "width": 2},
            name="LEI",
        ))
        fig.add_hline(y=lei_res["data"].mean(), line_dash="dot",
                      line_color="#555", line_width=1,
                      annotation_text="Long-run avg", annotation_font_color="#666")
        fig = add_nber(fig, start_date=tw_start)
        fig = dark_layout(fig, yaxis_title="Index Level")
        st.plotly_chart(fig, use_container_width=True, key="tab1_lei")
    _chart_meta(lei_res)

    # Macro Overview Investment Implications
    st.markdown("---")
    with st.expander("💡 Investment Implications", expanded=False):
        from ai.claude_client import get_investment_implications
        macro_readings: dict[str, str] = {}
        if gdp_gr["last_value"] is not None:
            macro_readings["Real GDP Growth (latest quarter)"] = (
                f"{gdp_gr['last_value']:+.1f}% QoQ annualised · as of {gdp_gr['last_date']}"
            )
        if lei_res["last_value"] is not None:
            macro_readings["Conference Board LEI"] = (
                f"{lei_res['last_value']:.2f} · "
                f"6-mo growth: {lei_growth:+.1f}%" if lei_growth is not None
                else f"{lei_res['last_value']:.2f}"
            )
        macro_readings["Recession Probability"] = (
            f"{model_output.probability:.1f}% ({model_output.traffic_light.upper()})"
        )
        macro_readings["Cycle Phase"] = f"{phase_output.phase} ({phase_output.confidence} confidence)"
        if macro_readings:
            with st.spinner("Generating implications…"):
                text = get_investment_implications(
                    tab_key               = "macro",
                    cycle_phase           = phase_output.phase,
                    recession_probability = model_output.probability,
                    traffic_light         = model_output.traffic_light,
                    tab_readings          = macro_readings,
                    phase_notes           = phase_output.notes,
                )
            st.markdown(text)

    st.markdown("---")
    st.caption(DISCLAIMER)


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
    # ── Quick Stats ──────────────────────────────────────────────────────────
    st.markdown("### 📊 Quick Stats")
    tl_colors = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    tl_emoji  = tl_colors.get(model_output.traffic_light, "⚪")
    st.metric(
        label="Recession Probability",
        value=f"{model_output.probability:.1f}%",
        delta=None,
        help="Weighted logit model output",
    )
    st.metric(label="Cycle Phase",    value=phase_output.phase)
    st.metric(label="Confidence",     value=f"{tl_emoji} {phase_output.confidence}")
    if lei_growth is not None:
        st.metric(label="CFNAI (3M avg)", value=f"{lei_growth:+.3f}",
                  help="Chicago Fed National Activity Index. >0 = above trend, <-0.70 = recession signal.")

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
        st.markdown(briefing_text)

    st.markdown("---")

    # ── Chat Sidebar ─────────────────────────────────────────────────────────
    st.markdown("### 💬 Ask Pulse360 AI")
    st.caption("Claude Haiku · Context-aware macro Q&A")

    # Initialise chat history
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []

    # Display history (scrollable within expander to save space)
    if st.session_state["chat_messages"]:
        with st.expander(
            f"Chat history ({len(st.session_state['chat_messages'])} messages)",
            expanded=True,
        ):
            for msg in st.session_state["chat_messages"]:
                role_label = "**You**" if msg["role"] == "user" else "**Pulse360 AI**"
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
