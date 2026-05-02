"""
Pulse360 — Buffett Indicator Page
===================================
Standalone page for the Warren Buffett Indicator.
Loaded by app.py via st.navigation(). set_page_config is
handled once in app.py — do NOT call it here.
"""

import streamlit as st
from datetime import datetime

from components.tabs.tab9_buffett import render_tab9
from data.fred_client import fetch_model_inputs
from models.recession_model import run_recession_model
from models.cycle_classifier import classify_cycle_phase
from data.fred_client import compute_cfnai_signal

# ── Dark-theme CSS (mirrors Dashboard) ───────────────────────────────────────
from components.taplox_theme import inject_theme
inject_theme()

st.markdown("""
<style>
    .main .block-container { padding-top: 1rem; max-width: 1400px; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
col_h, col_r = st.columns([6, 1])
with col_h:
    st.markdown("# ⚖️ Buffett Indicator")
    st.caption("Warren Buffett's preferred measure of overall market valuation · Powered by Pulse360")
with col_r:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh", help="Clear cache and reload all data"):
        st.cache_data.clear()
        st.rerun()

# ── Load model state (needed for AI analysis context) ────────────────────────
with st.spinner("Loading macro context…"):
    model_inputs = fetch_model_inputs()

model_output = run_recession_model(model_inputs)
lei_growth   = compute_cfnai_signal(model_inputs["CFNAI"]["data"])

from data.fred_client import fetch_series
unrate_result = fetch_series("UNRATE", start_date="2010-01-01")
unrate_data   = unrate_result["data"] if not unrate_result["data"].empty else None

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

# ── Render tab content ────────────────────────────────────────────────────────
render_tab9(model_output, phase_output)

# ── Footer ────────────────────────────────────────────────────────────────────
st.caption(f"Refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
