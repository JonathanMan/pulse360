"""
Pie360 Logo Helper
------------------
Drop this helper into your Streamlit pages to display the Pie360 logo.

Usage:
    from assets.logo_helper import show_logo, sidebar_logo

    show_logo(width=160)       # renders logo inline on the page
    sidebar_logo(width=120)    # renders logo in st.sidebar
"""

import base64
from pathlib import Path
import streamlit as st


def _load_logo(width: int = 140) -> str:
    """
    Returns an <img> tag with the logo embedded as base64.
    Prefers Pie360Logo.jpeg (original), falls back to SVG, then text-only.
    """
    assets_dir = Path(__file__).parent

    # Prefer the original JPEG from Ideogram
    for filename, mime in [
        ("Pie360Logo.jpeg", "image/jpeg"),
        ("pie360_logo.png", "image/png"),
        ("pie360_logo.svg", "image/svg+xml"),
    ]:
        path = assets_dir / filename
        if path.exists():
            data = path.read_bytes()
            b64 = base64.b64encode(data).decode()
            return f'<img src="data:{mime};base64,{b64}" width="{width}" style="display:block;"/>'

    # Final fallback: text-only brand mark
    return f'<span style="font-size:22px;font-weight:700;color:#1a2e4a;letter-spacing:2px;">PIE360</span>'


def show_logo(width: int = 160):
    """Render the Pie360 logo inline on the current page."""
    st.markdown(_load_logo(width), unsafe_allow_html=True)


def sidebar_logo(width: int = 120):
    """Render the Pie360 logo in the sidebar."""
    st.sidebar.markdown(_load_logo(width), unsafe_allow_html=True)


def header_with_logo(title: str = "Pie360", subtitle: str = "AI-Powered Economic Cycle Dashboard", logo_width: int = 60):
    """
    Render a branded page header: logo + title + subtitle side by side.

    Example:
        header_with_logo(
            title="Macro Pulse",
            subtitle="Real-time forecaster signals & consensus tracking"
        )
    """
    svg_path = Path(__file__).parent / "pie360_logo.svg"
    logo_html = _load_logo(logo_width)

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:8px;">
        {logo_html}
        <div>
            <div style="font-size:26px;font-weight:700;color:#1a2e4a;letter-spacing:1px;">{title}</div>
            <div style="font-size:13px;color:#5a7a99;margin-top:2px;">{subtitle}</div>
        </div>
    </div>
    <hr style="border:none;border-top:1px solid #e0e8f0;margin:8px 0 20px 0;"/>
    """, unsafe_allow_html=True)
