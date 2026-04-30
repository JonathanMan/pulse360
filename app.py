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
            st.Page("pages/0_Dashboard.py",   title="Dashboard",             icon="📊", default=True),
            st.Page("pages/4_Portfolio.py",   title="Investment Analyser",    icon="🗂️"),
            st.Page("pages/5_Briefing.py",    title="AI Research Desk",       icon="🔬"),
            st.Page("pages/7_Stock_Score.py", title="Buffett Score",           icon="🔍"),
            st.Page("pages/8_Screener.py",    title="Stock Screener",          icon="🏆"),
            st.Page("pages/9_Portfolio.py",   title="Portfolio Heatmap",       icon="🌡️"),
            st.Page("pages/6_Buffett.py",     title="Buffett Indicator",      icon="⚖️"),
        ],
        "Analysis": [
            st.Page("pages/2_Phase_Returns.py", title="What to Own & When",   icon="📈"),
            st.Page("pages/3_Simulator.py",     title="Stress Test",          icon="🎛️"),
            st.Page("pages/1_Backtest.py",      title="Model Track Record",   icon="📉"),
        ],
    }
)

with st.sidebar:
    st.markdown("""
<style>
    .nav-guide {
        margin-top: 1.2rem;
        padding-top: 1rem;
        border-top: 1px solid #2a2a4a;
    }
    .nav-guide-item {
        display: flex;
        gap: 8px;
        margin-bottom: 10px;
        align-items: flex-start;
    }
    .nav-guide-icon {
        font-size: 0.75rem;
        margin-top: 1px;
        flex-shrink: 0;
    }
    .nav-guide-text {
        line-height: 1.35;
    }
    .nav-guide-title {
        font-size: 0.82rem;
        font-weight: 600;
        color: #cccccc;
    }
    .nav-guide-desc {
        font-size: 0.78rem;
        color: #aaaaaa;
        border-left: 2px solid #3a3a6a;
        padding-left: 7px;
        margin-top: 3px;
        font-style: italic;
    }
    .nav-guide-section {
        font-size: 0.72rem;
        font-weight: 700;
        color: #666;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin: 12px 0 6px 0;
    }
</style>
<div class="nav-guide">
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">📊 Dashboard</div>
      <div class="nav-guide-desc">Live recession risk, cycle phase & 8-tab macro deep-dive.</div>
    </div>
  </div>
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">🗂️ Investment Analyser</div>
      <div class="nav-guide-desc">Upload your portfolio or a fund brochure for a macro-aware breakdown.</div>
    </div>
  </div>
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">🔬 AI Research Desk</div>
      <div class="nav-guide-desc">On-demand AI research — macro snapshot, M&A, short squeezes, hedges & more.</div>
    </div>
  </div>
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">🔍 Buffett Score</div>
      <div class="nav-guide-desc">Is a stock high quality and fairly priced? Scored using the Buffett/Munger framework.</div>
    </div>
  </div>
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">🏆 Stock Screener</div>
      <div class="nav-guide-desc">Rank ~80 large-caps by Buffett score. Apply a macro overlay to re-rank by cycle.</div>
    </div>
  </div>
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">🌡️ Portfolio Heatmap</div>
      <div class="nav-guide-desc">Paste your tickers — see every holding scored across 5 macro regimes instantly.</div>
    </div>
  </div>
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">⚖️ Buffett Indicator</div>
      <div class="nav-guide-desc">Is the overall stock market cheap or expensive vs the economy?</div>
    </div>
  </div>
  <div class="nav-guide-section">Analysis</div>
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">📈 What to Own & When</div>
      <div class="nav-guide-desc">Stocks, bonds, gold, oil — what has performed best in each cycle phase?</div>
    </div>
  </div>
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">🎛️ Stress Test</div>
      <div class="nav-guide-desc">Dial up a "what if" scenario and see how recession risk would change.</div>
    </div>
  </div>
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">📉 Model Track Record</div>
      <div class="nav-guide-desc">Did this model catch 2001, 2008, and 2020 in time?</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

pg.run()
