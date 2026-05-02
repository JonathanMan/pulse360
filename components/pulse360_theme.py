"""
components/pulse360_theme.py
============================
Pulse360 — Terminal Light v2 visual theme.

Drop-in replacement for taplox_theme.py. Same public API:
    inject_theme()       — call once near top of each page
    page_header()        — page title + subtitle band
    card_wrap()          — wrap HTML in a card container
    info_banner()        — inline regime / info banner

Design system: Terminal Light v2
---------------------------------
  PAGE_BG     #fafafa   off-white canvas
  CARD_BG     #ffffff   card surface
  SUBTLE_BG   #f4f4f4   table headers, secondary panels
  BORDER      #ececec   hairline — replaces all shadows
  BORDER_DARK #d4d4d4
  BORDER_MUT  #b8b8b8   input borders
  FG_PRIMARY  #0a0a0a   primary text + primary action colour
  FG_SEC      #6a6a6a   secondary text / labels
  FG_MUTED    #a0a0a0   muted / placeholder
  SUCCESS     #00a35a   green signal
  WARNING     #c98800   amber signal
  DANGER      #d92626   red signal

Typography
-----------
  Sans  — Geist 400/500/600/700   (UI text)
  Mono  — Geist Mono 400/500/600  (ALL numbers, eyebrow labels, meta)

Rules enforced globally
------------------------
  • No box-shadow anywhere — borders do all elevation work
  • Card / tile border-radius: 2px (sharp aesthetic)
  • Pill border-radius: 999px (tabs, chips, status tags)
  • All numeric elements: Geist Mono + tabular-nums feature
  • Transitions: 120ms ease on interactive elements only
"""

from __future__ import annotations
import streamlit as st

# ── Public colour tokens ──────────────────────────────────────────────────────
PAGE_BG     = "#fafafa"
CARD_BG     = "#ffffff"
SUBTLE_BG   = "#f4f4f4"
BORDER      = "#ececec"
BORDER_DARK = "#d4d4d4"
BORDER_MUT  = "#b8b8b8"
FG_PRIMARY  = "#0a0a0a"
FG_SEC      = "#6a6a6a"
FG_MUTED    = "#a0a0a0"
SUCCESS     = "#00a35a"
WARNING     = "#c98800"
DANGER      = "#d92626"
CHART_BLUE  = "#1f6feb"
CHART_PURPLE = "#7c4dff"

# Legacy aliases — keeps any page that imported taplox tokens working
BLUE        = FG_PRIMARY
BLUE_LIGHT  = SUBTLE_BG
TEXT_PRI    = FG_PRIMARY
TEXT_SEC    = FG_SEC
TEXT_MUT    = FG_MUTED

# ── Google Fonts import ───────────────────────────────────────────────────────
_FONT_IMPORT = """
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap');
"""

# ── Master CSS ────────────────────────────────────────────────────────────────
_CSS = f"""
<style>
{_FONT_IMPORT}

/* ── Base / fonts ────────────────────────────────────────────────────────── */
html, body, [class*="css"] {{
    font-family: 'Geist', -apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif !important;
    -webkit-font-smoothing: antialiased;
    letter-spacing: -0.005em;
}}

/* Mono for all numbers and eyebrow labels */
[data-testid="stMetricValue"],
[data-testid="stMetricDelta"],
[data-testid="stCaptionContainer"],
.mono, .num, code, kbd, pre {{
    font-family: 'Geist Mono', 'SF Mono', ui-monospace, Menlo, Consolas, monospace !important;
    font-feature-settings: "tnum" 1, "ss01" 1;
}}

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
    box-shadow: none !important;
}}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] li,
[data-testid="stSidebar"] a {{
    color: {FG_SEC} !important;
    font-size: 0.85rem !important;
}}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{
    color: {FG_MUTED} !important;
    font-size: 0.66rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.14em !important;
    font-weight: 600 !important;
    font-family: 'Geist Mono', monospace !important;
}}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] b {{
    color: {FG_PRIMARY} !important;
    font-weight: 600 !important;
}}

/* Active nav item — left-border indicator */
[data-testid="stSidebar"] [aria-current="page"],
[data-testid="stSidebar"] [aria-selected="true"],
[data-testid="stSidebar"] .st-emotion-cache-active-nav {{
    background-color: {SUBTLE_BG} !important;
    border-left: 2px solid {FG_PRIMARY} !important;
    color: {FG_PRIMARY} !important;
    font-weight: 600 !important;
    border-radius: 0 !important;
}}

/* ── Body headings & text ─────────────────────────────────────────────────── */
h1, h2, h3, h4, h5, h6,
[data-testid="stHeadingWithActionElements"] span,
[data-testid="stHeadingWithActionElements"] h1,
[data-testid="stHeadingWithActionElements"] h2,
[data-testid="stHeadingWithActionElements"] h3,
[data-testid="stHeadingWithActionElements"] h4 {{
    color: {FG_PRIMARY} !important;
    letter-spacing: -0.02em !important;
    font-weight: 600 !important;
}}
h1 {{ font-size: 1.5rem !important; font-weight: 700 !important; letter-spacing: -0.03em !important; }}
h2 {{ font-size: 1.05rem !important; }}
h3 {{
    font-size: 0.92rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    color: {FG_SEC} !important;
    font-weight: 600 !important;
}}

.main p, .main li,
.main [data-testid="stMarkdownContainer"] p,
.main [data-testid="stMarkdownContainer"] li,
.main [data-testid="stMarkdownContainer"] span {{
    color: {FG_SEC} !important;
    font-size: 0.85rem !important;
    line-height: 1.55 !important;
}}
.main [data-testid="stMarkdownContainer"] strong,
.main [data-testid="stMarkdownContainer"] b {{
    color: {FG_PRIMARY} !important;
    font-weight: 600 !important;
}}
[data-testid="stCaptionContainer"] p,
.main small {{
    color: {FG_MUTED} !important;
    font-size: 0.72rem !important;
}}

/* ── Metric tiles ─────────────────────────────────────────────────────────── */
[data-testid="metric-container"] {{
    background: {CARD_BG} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 2px !important;
    padding: 14px 16px !important;
    box-shadow: none !important;
}}
[data-testid="stMetricValue"] {{
    color: {FG_PRIMARY} !important;
    font-size: 1.8rem !important;
    font-weight: 500 !important;
    letter-spacing: -0.01em !important;
    font-family: 'Geist Mono', monospace !important;
    font-feature-settings: "tnum" 1 !important;
}}
[data-testid="stMetricLabel"] label,
[data-testid="stMetricLabel"] p {{
    color: {FG_MUTED} !important;
    font-size: 0.66rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.12em !important;
    font-weight: 600 !important;
    font-family: 'Geist Mono', monospace !important;
}}
[data-testid="stMetricDelta"] {{
    font-size: 0.78rem !important;
    font-family: 'Geist Mono', monospace !important;
}}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.stButton > button[kind="primary"],
.stFormSubmitButton > button {{
    background-color: {FG_PRIMARY} !important;
    color: #ffffff !important;
    border: 1px solid {FG_PRIMARY} !important;
    border-radius: 0 !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    padding: 9px 18px !important;
    box-shadow: none !important;
    transition: background 0.12s, border-color 0.12s !important;
}}
.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button:hover {{
    background-color: {SUCCESS} !important;
    border-color: {SUCCESS} !important;
}}
.stButton > button:not([kind="primary"]) {{
    background-color: transparent !important;
    color: {FG_PRIMARY} !important;
    border: 1px solid {BORDER_MUT} !important;
    border-radius: 0 !important;
    font-size: 0.85rem !important;
    box-shadow: none !important;
    transition: border-color 0.12s !important;
}}
.stButton > button:not([kind="primary"]):hover {{
    border-color: {FG_PRIMARY} !important;
    color: {FG_PRIMARY} !important;
}}
[data-testid="stDownloadButton"] > button {{
    background-color: transparent !important;
    color: {FG_PRIMARY} !important;
    border: 1px solid {BORDER_MUT} !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}}

/* ── Form inputs ─────────────────────────────────────────────────────────── */
.stTextInput > div > div > input,
.stTextArea textarea,
[data-baseweb="select"] > div,
[data-baseweb="input"] > div {{
    background-color: {CARD_BG} !important;
    color: {FG_PRIMARY} !important;
    border: 1px solid {BORDER_MUT} !important;
    border-radius: 0 !important;
    font-size: 0.85rem !important;
    box-shadow: none !important;
}}
.stTextInput > div > div > input:focus,
.stTextArea textarea:focus {{
    border-color: {FG_PRIMARY} !important;
    box-shadow: 0 0 0 1px {FG_PRIMARY} !important;
}}
.stTextInput label, .stSelectbox label,
.stMultiSelect label, .stTextArea label,
.stSlider label, .stCheckbox label,
.stRadio label, .stNumberInput label {{
    color: {FG_SEC} !important;
    font-size: 0.85rem !important;
}}

/* ── Tabs — pill strip ───────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    background-color: {SUBTLE_BG} !important;
    border: 1px solid {BORDER} !important;
    border-bottom: 1px solid {BORDER} !important;
    border-radius: 999px !important;
    padding: 5px 7px !important;
    gap: 6px !important;
}}
.stTabs [data-baseweb="tab"] {{
    background-color: transparent !important;
    color: {FG_SEC} !important;
    border: none !important;
    border-radius: 999px !important;
    padding: 7px 18px !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    transition: background 120ms ease, color 120ms ease !important;
}}
.stTabs [aria-selected="true"] {{
    background-color: {FG_PRIMARY} !important;
    color: #ffffff !important;
    border: none !important;
}}
.stTabs [data-baseweb="tab"]:hover:not([aria-selected="true"]) {{
    background-color: {CARD_BG} !important;
    color: {FG_PRIMARY} !important;
}}
/* Hide the default tab underline indicator */
.stTabs [data-baseweb="tab-highlight"] {{
    display: none !important;
}}
.stTabs [data-baseweb="tab-border"] {{
    display: none !important;
}}

/* ── Expanders ───────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {{
    background-color: {CARD_BG} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    margin-bottom: 8px !important;
}}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p {{
    color: {FG_PRIMARY} !important;
    font-weight: 600 !important;
    font-size: 0.78rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.14em !important;
    font-family: 'Geist Mono', monospace !important;
}}

/* ── Alerts ──────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {{
    border-radius: 0 !important;
    box-shadow: none !important;
}}

/* ── DataFrames ──────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"],
[data-testid="stDataFrame"] table {{
    background-color: {CARD_BG} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 0 !important;
}}
[data-testid="stDataFrame"] th {{
    background-color: {SUBTLE_BG} !important;
    color: {FG_MUTED} !important;
    font-size: 0.66rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    font-family: 'Geist Mono', monospace !important;
    font-weight: 600 !important;
}}
[data-testid="stDataFrame"] td {{
    color: {FG_PRIMARY} !important;
    font-family: 'Geist Mono', monospace !important;
    font-size: 0.82rem !important;
}}

/* ── Plotly chart wrapper ─────────────────────────────────────────────────── */
[data-testid="stPlotlyChart"] > div {{
    border: 1px solid {BORDER} !important;
    border-radius: 0 !important;
    overflow: hidden;
    background: {CARD_BG} !important;
    box-shadow: none !important;
}}

/* ── Horizontal dividers ─────────────────────────────────────────────────── */
hr {{
    border-color: {BORDER} !important;
}}

/* ── Sidebar toggle ──────────────────────────────────────────────────────── */
[data-testid="stSidebarCollapseButton"] svg {{
    color: {FG_SEC} !important;
}}

/* ── Remove ALL box-shadows globally ─────────────────────────────────────── */
* {{
    box-shadow: none !important;
}}
/* Re-allow focus ring on inputs only */
.stTextInput > div > div > input:focus,
.stTextArea textarea:focus {{
    box-shadow: 0 0 0 1px {FG_PRIMARY} !important;
}}

/* ── Scrollbar ───────────────────────────────────────────────────────────── */
::-webkit-scrollbar {{ width: 4px; height: 4px; }}
::-webkit-scrollbar-track {{ background: {PAGE_BG}; }}
::-webkit-scrollbar-thumb {{ background: {BORDER_DARK}; border-radius: 0; }}
::-webkit-scrollbar-thumb:hover {{ background: {FG_MUTED}; }}

/* ── Selection ───────────────────────────────────────────────────────────── */
::selection {{ background: {SUCCESS}; color: #fff; }}

/* ── Aggressive border-radius reset on Streamlit containers ──────────────── */
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stHorizontalBlock"] > div,
[data-testid="column"] > div > div,
[data-testid="stMetricLabel"],
[data-testid="metric-container"],
[data-testid="stAlert"],
[data-testid="stExpander"],
[data-testid="stForm"],
[data-baseweb="card"],
[data-baseweb="notification"],
div[class*="stContainer"],
div[class*="stColumn"] {{
    border-radius: 0 !important;
}}

/* ── st.container(border=True) — remove rounded corners ─────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] > div {{
    border-radius: 0 !important;
    border-color: {BORDER} !important;
}}
[data-testid="stVerticalBlockBorderWrapper"] > div:first-child {{
    border-radius: 0 !important;
}}
section[data-testid="stSidebar"] ~ div [data-testid="stVerticalBlockBorderWrapper"] > div {{
    border-radius: 0 !important;
}}

/* ── Stale / warning pills to p360 style ────────────────────────────────── */
[data-testid="stAlert"] [data-baseweb="notification"] {{
    border-radius: 0 !important;
    border-left-width: 2px !important;
}}
</style>
"""


# ── Public API ────────────────────────────────────────────────────────────────

def inject_theme() -> None:
    """Inject Terminal Light v2 CSS. Call once near top of each page."""
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    """Render a Terminal Light v2 page header with optional subtitle."""
    sub_html = (
        f'<p style="color:{FG_MUTED};font-size:0.78rem;margin:4px 0 0;'
        f'font-family:\'Geist Mono\',monospace;text-transform:uppercase;'
        f'letter-spacing:0.08em;">{subtitle}</p>'
        if subtitle else ""
    )
    st.markdown(
        f'<div style="margin-bottom:1.25rem;padding-bottom:1rem;'
        f'border-bottom:1px solid {BORDER};">'
        f'<h1 style="color:{FG_PRIMARY};font-size:1.5rem;font-weight:700;'
        f'margin:0;letter-spacing:-0.03em;">{title}</h1>{sub_html}</div>',
        unsafe_allow_html=True,
    )


def card_wrap(html: str, padding: str = "16px 20px") -> str:
    """Wrap HTML in a Terminal Light v2 card (sharp corners, hairline border)."""
    return (
        f'<div style="background:{CARD_BG};border:1px solid {BORDER};'
        f'border-radius:2px;padding:{padding};margin-bottom:12px;">'
        f'{html}</div>'
    )


def eyebrow(text: str) -> str:
    """Render an eyebrow label (uppercase mono, muted)."""
    return (
        f'<div style="font-family:\'Geist Mono\',monospace;font-size:0.66rem;'
        f'font-weight:600;color:{FG_MUTED};text-transform:uppercase;'
        f'letter-spacing:0.14em;margin-bottom:6px;">{text}</div>'
    )


def info_banner(text: str, accent: str = FG_PRIMARY) -> str:
    """Inline info / regime banner — left-border accent style."""
    bg = f"{accent}0d"  # ~5% opacity tint
    return (
        f'<div style="background:{bg};border:1px solid {BORDER};'
        f'border-left:2px solid {accent};border-radius:0;'
        f'padding:10px 14px;margin-bottom:12px;font-size:0.82rem;'
        f'color:{FG_PRIMARY};font-family:\'Geist Mono\',monospace;">'
        f'{text}</div>'
    )


def signal_pill(text: str, kind: str = "neutral") -> str:
    """
    Render a coloured status pill.
    kind: 'ow' | 'uw' | 'neutral' | 'watch' | 'green' | 'amber' | 'red'
    """
    styles = {
        "ow":      (f"rgba(0,163,90,0.10)",        SUCCESS,  "OVERWEIGHT"),
        "uw":      (f"rgba(217,38,38,0.10)",        DANGER,   "UNDERWEIGHT"),
        "neutral": (SUBTLE_BG,                      FG_SEC,   "NEUTRAL"),
        "watch":   (f"rgba(201,136,0,0.12)",        WARNING,  "WATCH"),
        "green":   (f"rgba(0,163,90,0.10)",         SUCCESS,  text),
        "amber":   (f"rgba(201,136,0,0.12)",        WARNING,  text),
        "red":     (f"rgba(217,38,38,0.10)",        DANGER,   text),
    }
    bg, color, label = styles.get(kind, (SUBTLE_BG, FG_SEC, text))
    return (
        f'<span style="display:inline-flex;align-items:center;'
        f'padding:3px 9px;border-radius:4px;font-size:0.66rem;'
        f'font-weight:700;text-transform:uppercase;letter-spacing:0.06em;'
        f'background:{bg};color:{color};font-family:\'Geist Mono\',monospace;">'
        f'{label}</span>'
    )
