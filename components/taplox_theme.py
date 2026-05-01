"""
components/taplox_theme.py
===========================
Taplox-inspired visual theme for Pulse360.

Injects comprehensive CSS into Streamlit's HTML to give the app the clean,
professional light-mode look of the Taplox Next.js admin template.

Colour palette
--------------
  BLUE        #3b7ddd   primary action / links
  BLUE_LIGHT  #e8f1fb   active nav bg / hover
  PAGE_BG     #f5f7fb   outer page background
  CARD_BG     #ffffff   cards / sidebar
  BORDER      #e9ecef   dividers / card borders
  TEXT_PRI    #293241   primary text
  TEXT_SEC    #6c757d   labels / secondary
  TEXT_MUT    #adb5bd   muted / placeholder

Usage
-----
    from components.taplox_theme import inject_theme, page_header, card_wrap
    inject_theme()   # call once near top of each page
"""

from __future__ import annotations
import streamlit as st

# ── Public colour tokens (import these in pages for custom HTML) ──────────────
BLUE        = "#3b7ddd"
BLUE_LIGHT  = "#e8f1fb"
PAGE_BG     = "#f5f7fb"
CARD_BG     = "#ffffff"
BORDER      = "#e9ecef"
BORDER_DARK = "#dee2e6"
TEXT_PRI    = "#293241"
TEXT_SEC    = "#6c757d"
TEXT_MUT    = "#adb5bd"
SUCCESS     = "#28a745"
DANGER      = "#e74c3c"
WARNING     = "#f39c12"

# ── Master CSS string ─────────────────────────────────────────────────────────
_CSS = f"""
<style>
/* ── Page background ─────────────────────────────────────────────────────── */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMainBlockContainer"],
section.main, .main, .block-container {{
    background-color: {PAGE_BG} !important;
}}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"],
[data-testid="stSidebarContent"],
[data-testid="stSidebarCollapsedControl"] {{
    background-color: {CARD_BG} !important;
    border-right: 1px solid {BORDER} !important;
}}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] li,
[data-testid="stSidebar"] a {{
    color: {TEXT_SEC} !important;
    font-size: 0.875rem !important;
}}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{
    color: {TEXT_PRI} !important;
    font-size: 0.68rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    font-weight: 600 !important;
}}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] b {{
    color: {TEXT_PRI} !important;
    font-weight: 600 !important;
}}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] div {{
    color: {TEXT_SEC} !important;
}}

/* ── Body headings & text ─────────────────────────────────────────────────── */
h1, h2, h3, h4, h5, h6,
[data-testid="stHeadingWithActionElements"] span,
[data-testid="stHeadingWithActionElements"] h1,
[data-testid="stHeadingWithActionElements"] h2,
[data-testid="stHeadingWithActionElements"] h3,
[data-testid="stHeadingWithActionElements"] h4 {{
    color: {TEXT_PRI} !important;
}}
.main p, .main li,
.main [data-testid="stMarkdownContainer"] p,
.main [data-testid="stMarkdownContainer"] li,
.main [data-testid="stMarkdownContainer"] span {{
    color: {TEXT_SEC} !important;
}}
.main [data-testid="stMarkdownContainer"] strong,
.main [data-testid="stMarkdownContainer"] b {{
    color: {TEXT_PRI} !important;
}}
[data-testid="stCaptionContainer"] p,
.main small {{
    color: {TEXT_MUT} !important;
}}

/* ── Metric tiles ─────────────────────────────────────────────────────────── */
[data-testid="metric-container"] {{
    background: {CARD_BG} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 8px !important;
    padding: 1.1rem 1rem !important;
}}
[data-testid="stMetricValue"] {{
    color: {TEXT_PRI} !important;
    font-size: 1.45rem !important;
    font-weight: 600 !important;
}}
[data-testid="stMetricLabel"] label,
[data-testid="stMetricLabel"] p {{
    color: {TEXT_SEC} !important;
    font-size: 0.72rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.04em !important;
    font-weight: 500 !important;
}}
[data-testid="stMetricDelta"] {{
    font-size: 0.78rem !important;
}}

/* ── Primary + secondary buttons ─────────────────────────────────────────── */
.stButton > button[kind="primary"],
.stFormSubmitButton > button {{
    background-color: {BLUE} !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
}}
.stButton > button:not([kind="primary"]) {{
    background-color: {CARD_BG} !important;
    color: {TEXT_PRI} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 6px !important;
}}
.stButton > button:hover {{
    border-color: {BLUE} !important;
    color: {BLUE} !important;
}}
[data-testid="stDownloadButton"] > button {{
    background-color: {CARD_BG} !important;
    color: {TEXT_PRI} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 6px !important;
}}

/* ── Form inputs ─────────────────────────────────────────────────────────── */
.stTextInput > div > div > input,
.stTextArea textarea,
[data-baseweb="select"] > div,
[data-baseweb="input"] > div {{
    background-color: {CARD_BG} !important;
    color: {TEXT_PRI} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 6px !important;
}}
.stTextInput label, .stSelectbox label,
.stMultiSelect label, .stTextArea label,
.stSlider label, .stCheckbox label,
.stRadio label, .stNumberInput label {{
    color: {TEXT_SEC} !important;
    font-size: 0.875rem !important;
}}

/* ── Tabs ────────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    background-color: transparent !important;
    border-bottom: 1px solid {BORDER} !important;
    gap: 0 !important;
}}
.stTabs [data-baseweb="tab"] {{
    background-color: transparent !important;
    color: {TEXT_SEC} !important;
    border-bottom: 2px solid transparent !important;
    padding: 8px 18px !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
}}
.stTabs [aria-selected="true"] {{
    color: {BLUE} !important;
    border-bottom-color: {BLUE} !important;
}}

/* ── Expanders ───────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {{
    background-color: {CARD_BG} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 8px !important;
    margin-bottom: 8px !important;
}}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p {{
    color: {TEXT_PRI} !important;
    font-weight: 500 !important;
}}

/* ── Alerts ──────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {{
    border-radius: 8px !important;
}}

/* ── DataFrames ──────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"],
[data-testid="stDataFrame"] table {{
    background-color: {CARD_BG} !important;
}}
[data-testid="stDataFrame"] th {{
    background-color: {PAGE_BG} !important;
    color: {TEXT_SEC} !important;
}}

/* ── Sidebar toggle button ───────────────────────────────────────────────── */
[data-testid="stSidebarCollapseButton"] svg {{
    color: {TEXT_SEC} !important;
}}

/* ── Horizontal dividers ─────────────────────────────────────────────────── */
hr {{
    border-color: {BORDER} !important;
}}

/* ── Scrollbar ───────────────────────────────────────────────────────────── */
::-webkit-scrollbar {{ width: 5px; height: 5px; }}
::-webkit-scrollbar-track {{ background: {PAGE_BG}; }}
::-webkit-scrollbar-thumb {{ background: #ced4da; border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: #adb5bd; }}
</style>
"""


def inject_theme() -> None:
    """Inject Taplox light-mode CSS into the current Streamlit page.

    Call this once near the top of each page, before any st.markdown output.
    """
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    """Render a Taplox-style page header with optional subtitle."""
    sub = (
        f'<p style="color:{TEXT_SEC};font-size:0.875rem;margin:4px 0 0;">{subtitle}</p>'
        if subtitle else ""
    )
    st.markdown(
        f'<div style="margin-bottom:1.5rem;padding-bottom:1rem;'
        f'border-bottom:1px solid {BORDER};">'
        f'<h1 style="color:{TEXT_PRI};font-size:1.4rem;font-weight:600;margin:0;">'
        f'{title}</h1>{sub}</div>',
        unsafe_allow_html=True,
    )


def card_wrap(html: str, padding: str = "1rem 1.25rem") -> str:
    """Wrap an HTML string in a Taplox card container."""
    return (
        f'<div style="background:{CARD_BG};border:1px solid {BORDER};'
        f'border-radius:8px;padding:{padding};margin-bottom:1rem;">'
        f'{html}</div>'
    )


def info_banner(text: str, accent: str = BLUE) -> str:
    """Inline info/regime banner styled for light mode."""
    bg = BLUE_LIGHT if accent == BLUE else f"{accent}18"
    return (
        f'<div style="background:{bg};border:1px solid {accent}44;'
        f'border-left:3px solid {accent};border-radius:6px;'
        f'padding:10px 14px;margin-bottom:12px;font-size:0.82rem;'
        f'color:{TEXT_PRI};">{text}</div>'
    )
