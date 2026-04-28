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

# ── Global styles — injected once, applied to every page ─────────────────────
# Scoped to .main so the sidebar nav retains its original Streamlit styling.
st.markdown("""
<style>
    /* ── Body text → white ── */
    .main p, .main li, .main span, .main strong, .main b,
    .main [data-testid="stMarkdownContainer"] p,
    .main [data-testid="stMarkdownContainer"] li,
    .main [data-testid="stMarkdownContainer"] strong,
    .main [data-testid="stMarkdownContainer"] b { color: #ffffff !important; }

    /* ── Headings → white (markdown + native st.header/subheader/title) ── */
    .main h1, .main h2, .main h3,
    .main h4, .main h5, .main h6,
    .main [data-testid="stMarkdownContainer"] h1,
    .main [data-testid="stMarkdownContainer"] h2,
    .main [data-testid="stMarkdownContainer"] h3,
    .main [data-testid="stMarkdownContainer"] h4,
    .main [data-testid="stMarkdownContainer"] h5,
    .main [data-testid="stMarkdownContainer"] h6,
    .main [data-testid="stHeadingWithActionElements"] h1,
    .main [data-testid="stHeadingWithActionElements"] h2,
    .main [data-testid="stHeadingWithActionElements"] h3,
    .main [data-testid="stHeadingWithActionElements"] h4,
    .main [data-testid="stHeadingWithActionElements"],
    [data-testid="stHeadingWithActionElements"] span { color: #ffffff !important; }

    /* ── Captions / helper text ── */
    .main [data-testid="stCaptionContainer"],
    .main small { color: #aaaaaa !important; }

    /* ── Metric labels & values ── */
    div[data-testid="metric-container"] label { color: #cccccc !important; }
    div[data-testid="metric-container"] [data-testid="stMetricValue"] { color: #ffffff !important; }

    /* ── Table cells ── */
    .main [data-testid="stMarkdownContainer"] td,
    .main [data-testid="stMarkdownContainer"] th { color: #ffffff !important; }

    /* ── Input / selectbox labels ── */
    .main label { color: #cccccc !important; }

    /* ── Expander headers ── */
    .main [data-testid="stExpander"] summary { color: #ffffff !important; }

    /* ── Tab labels ── */
    .stTabs [data-baseweb="tab"] { color: #cccccc !important; }
    .stTabs [aria-selected="true"] { color: #ffffff !important; }
</style>
""", unsafe_allow_html=True)

pg = st.navigation(
    {
        "": [
            st.Page("pages/0_Dashboard.py", title="Dashboard",   icon="📊", default=True),
            st.Page("pages/5_Briefing.py",  title="At a Glance", icon="📋"),
        ],
        "Analysis": [
            st.Page("pages/1_Backtest.py",      title="Backtest",      icon="📉"),
            st.Page("pages/2_Phase_Returns.py", title="Phase Returns", icon="📈"),
            st.Page("pages/3_Simulator.py",     title="Simulator",     icon="🎛️"),
            st.Page("pages/4_Portfolio.py",     title="Portfolio",     icon="🗂️"),
        ],
    }
)

pg.run()
