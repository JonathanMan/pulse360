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

# ── Global styles ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main p, .main li, .main span, .main strong, .main b,
    .main [data-testid="stMarkdownContainer"] p,
    .main [data-testid="stMarkdownContainer"] li,
    .main [data-testid="stMarkdownContainer"] strong,
    .main [data-testid="stMarkdownContainer"] b { color: #ffffff !important; }

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

    .main [data-testid="stCaptionContainer"],
    .main small { color: #aaaaaa !important; }

    div[data-testid="metric-container"] label { color: #cccccc !important; }
    div[data-testid="metric-container"] [data-testid="stMetricValue"] { color: #ffffff !important; }

    .main [data-testid="stMarkdownContainer"] td,
    .main [data-testid="stMarkdownContainer"] th { color: #ffffff !important; }

    .main label { color: #cccccc !important; }
    .main [data-testid="stExpander"] summary { color: #ffffff !important; }
    .stTabs [data-baseweb="tab"] { color: #cccccc !important; }
    .stTabs [aria-selected="true"] { color: #ffffff !important; }

    /* ── Onboarding card styles ── */
    .profile-card {
        border: 1px solid #2a2a4a;
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 8px;
        background: #0e0e1a;
        cursor: pointer;
        transition: border-color 0.2s;
    }
    .profile-card.selected {
        border-color: #6c63ff;
        background: #13132a;
    }
    .profile-card-title {
        font-size: 1rem;
        font-weight: 700;
        color: #ffffff;
        margin-bottom: 4px;
    }
    .profile-card-desc {
        font-size: 0.82rem;
        color: #aaaaaa;
        line-height: 1.4;
    }
    .profile-badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


# ── Onboarding ─────────────────────────────────────────────────────────────────
def _render_onboarding() -> None:
    """
    Full-page onboarding shown on first visit.
    Sets st.session_state['pulse360_profile'] and reruns when complete.
    Calls st.stop() to block normal page rendering until done.
    """
    from components.user_profile import PROFILES

    st.markdown("""
<div style="text-align:center; padding: 2rem 0 1rem 0;">
  <div style="font-size:2.8rem; margin-bottom:0.3rem;">📊</div>
  <h1 style="font-size:2.2rem; font-weight:800; color:#ffffff; margin:0;">
    Welcome to Pulse360
  </h1>
  <p style="color:#aaaaaa; font-size:1rem; margin-top:0.5rem;">
    AI-Powered Economic Cycle Dashboard &nbsp;·&nbsp; Real-time Business Cycle Monitoring
  </p>
</div>
""", unsafe_allow_html=True)

    st.markdown("---")

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            "#### How would you describe yourself as an investor?",
            help="This sets your starting view. You can change it any time from the sidebar.",
        )
        st.caption("Pulse360 adapts to your level — beginner-friendly or full analyst mode.")

        chosen = st.radio(
            "Profile",
            options=list(PROFILES.keys()),
            format_func=lambda k: f"{PROFILES[k]['icon']}  {PROFILES[k]['label']}",
            label_visibility="collapsed",
            key="onboarding_choice",
        )

        # Preview card for the chosen profile
        p = PROFILES[chosen]
        st.markdown(f"""
<div style="
  border:1px solid #2a2a4a;
  border-radius:10px;
  padding:16px 18px;
  margin: 12px 0 20px 0;
  background:#0e0e1a;
">
  <div style="font-size:0.85rem; color:#888; margin-bottom:8px; text-transform:uppercase;
              letter-spacing:.05em; font-weight:600;">What you'll see</div>
  {''.join(f'<div style="color:#cccccc; font-size:0.85rem; margin-bottom:4px;">✓ {f}</div>'
           for f in p['features'])}
  {'<div style="margin-top:10px; font-size:0.8rem; color:#555;">Hidden for now (unlock by switching profile): '
   + ', '.join(p['hidden']) + '</div>' if p['hidden'] else ''}
</div>
""", unsafe_allow_html=True)

        if st.button("Get Started", type="primary", use_container_width=True):
            st.session_state["pulse360_profile"] = chosen
            # Clear any stale session data from a previous profile
            for key in ["portfolio_scored", "heatmap_prefill", "heatmap_extract_msg"]:
                st.session_state.pop(key, None)
            st.rerun()

    st.stop()


# ── Run onboarding if no profile set ──────────────────────────────────────────
if "pulse360_profile" not in st.session_state:
    _render_onboarding()

# ── Build dynamic navigation ───────────────────────────────────────────────────
from components.user_profile import get_nav_pages, get_profile, PROFILES  # noqa: E402

nav_sections = get_nav_pages()
pg = st.navigation(nav_sections)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    profile = get_profile()
    profile_key = st.session_state.get("pulse360_profile", "Beginner")

    # Profile badge + switcher
    st.markdown(f"""
<style>
  .pb-wrap {{
    margin-bottom: 0.8rem;
    padding: 10px 12px;
    border-radius: 8px;
    background: #0e0e1a;
    border: 1px solid #2a2a4a;
  }}
  .pb-label {{
    font-size: 0.68rem;
    color: #666;
    text-transform: uppercase;
    letter-spacing: .05em;
    margin-bottom: 4px;
  }}
  .pb-name {{
    font-size: 0.88rem;
    font-weight: 700;
    color: {profile["colour"]};
  }}
  .pb-desc {{
    font-size: 0.75rem;
    color: #888;
    margin-top: 3px;
    line-height: 1.3;
  }}
</style>
<div class="pb-wrap">
  <div class="pb-label">Your profile</div>
  <div class="pb-name">{profile["icon"]}  {profile["label"]}</div>
  <div class="pb-desc">{profile["description"]}</div>
</div>
""", unsafe_allow_html=True)

    # Profile switcher (compact selectbox)
    new_profile = st.selectbox(
        "Switch profile",
        options=list(PROFILES.keys()),
        format_func=lambda k: f"{PROFILES[k]['icon']} {PROFILES[k]['label']}",
        index=list(PROFILES.keys()).index(profile_key),
        label_visibility="collapsed",
        key="sidebar_profile_switch",
    )
    if new_profile != profile_key:
        st.session_state["pulse360_profile"] = new_profile
        for key in ["portfolio_scored", "heatmap_prefill", "heatmap_extract_msg"]:
            st.session_state.pop(key, None)
        st.rerun()

    # Nav guide (only show entries relevant to current profile)
    level = profile["level"]

    guide_items = [
        ("📊", "Dashboard",          "Live recession risk, cycle phase & macro deep-dive.", 0),
        ("🗂️", "Investment Analyser", "Upload your portfolio or a fund brochure for a macro-aware breakdown.", 0),
        ("🔬", "AI Research Desk",    "On-demand AI research — macro snapshot, M&A, short squeezes & more.", 0),
        ("🔍", "Buffett Score",       "Is a stock high quality and fairly priced? Buffett/Munger framework.", 0),
        ("🏆", "Stock Screener",      "Rank ~80 large-caps by Buffett score. Apply a macro cycle overlay.", 1),
        ("📋", "Portfolio Heatmap",   "Paste your tickers — stress-test across 5 macro regimes instantly.", 1),
        ("⚖️", "Buffett Indicator",   "Is the overall stock market cheap or expensive vs the economy?", 0),
    ]
    analysis_items = [
        ("📈", "What to Own & When",  "Stocks, bonds, gold, oil — what performs best in each cycle phase?", 0),
        ("🎛️", "Stress Test",         "Dial up a 'what if' scenario and see how recession risk changes.", 1),
        ("📉", "Model Track Record",  "Did this model catch 2001, 2008, and 2020 in time?", 2),
    ]

    items_html = ""
    for icon, title, desc, min_level in guide_items:
        if level >= min_level:
            items_html += f"""
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">{icon} {title}</div>
      <div class="nav-guide-desc">{desc}</div>
    </div>
  </div>"""

    items_html += '<div class="nav-guide-section">Analysis</div>'
    for icon, title, desc, min_level in analysis_items:
        if level >= min_level:
            items_html += f"""
  <div class="nav-guide-item">
    <div class="nav-guide-text">
      <div class="nav-guide-title">{icon} {title}</div>
      <div class="nav-guide-desc">{desc}</div>
    </div>
  </div>"""

    # Locked items hint
    locked = (
        [t for _, t, _, ml in guide_items if ml > level]
        + [t for _, t, _, ml in analysis_items if ml > level]
    )
    locked_html = ""
    if locked:
        locked_html = f"""
<div style="margin-top:14px; padding:8px 10px; border-radius:6px;
            background:#0e0e1a; border:1px dashed #2a2a4a;">
  <div style="font-size:0.7rem; color:#555; margin-bottom:4px;">
    Unlock more by switching profile:
  </div>
  <div style="font-size:0.72rem; color:#444;">
    {'  ·  '.join(locked)}
  </div>
</div>"""

    st.markdown(f"""
<style>
  .nav-guide {{ margin-top:1rem; padding-top:0.8rem; border-top:1px solid #2a2a4a; }}
  .nav-guide-item {{ display:flex; gap:8px; margin-bottom:10px; align-items:flex-start; }}
  .nav-guide-text {{ line-height:1.35; }}
  .nav-guide-title {{ font-size:0.82rem; font-weight:600; color:#cccccc; }}
  .nav-guide-desc {{
    font-size:0.78rem; color:#aaaaaa;
    border-left:2px solid #3a3a6a;
    padding-left:7px; margin-top:3px; font-style:italic;
  }}
  .nav-guide-section {{
    font-size:0.72rem; font-weight:700; color:#666;
    text-transform:uppercase; letter-spacing:.05em; margin:12px 0 6px 0;
  }}
  .settings-link {{
    display:block;
    margin-top:18px;
    padding:8px 12px;
    border-radius:7px;
    background:#0e0e1a;
    border:1px solid #2a2a4a;
    font-size:0.8rem;
    color:#888;
    text-decoration:none;
    transition:border-color .2s, color .2s;
  }}
  .settings-link:hover {{ border-color:#6c63ff; color:#cccccc; }}
</style>
<div class="nav-guide">
{items_html}
</div>
{locked_html}
""", unsafe_allow_html=True)

    # Settings shortcut at the very bottom of the sidebar
    st.markdown("---")
    st.page_link("pages/10_Settings.py", label="⚙️  Settings & profile", use_container_width=True)

pg.run()
