"""
Pulse360 — Navigation Router
==============================
Entry point for Streamlit Cloud. Defines all pages explicitly via
st.navigation() so page discovery works regardless of repo layout.

Run locally:  streamlit run app.py
Deploy:       push to GitHub → connect to Streamlit Cloud → add secrets
"""

import streamlit as st

st.set_page_config(
    page_title="Pulse360",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

pg = st.navigation(
    {
        "": [
            st.Page("pages/0_Dashboard.py", title="Dashboard", icon="📊", default=True),
        ],
        "Analysis": [
            st.Page("pages/1_Backtest.py",     title="Backtest",      icon="📉"),
            st.Page("pages/2_Phase_Returns.py", title="Phase Returns", icon="📈"),
            st.Page("pages/3_Simulator.py",    title="Simulator",     icon="🎛️"),
            st.Page("pages/4_Portfolio.py",    title="Portfolio",     icon="🗂️"),
        ],
    }
)

pg.run()
