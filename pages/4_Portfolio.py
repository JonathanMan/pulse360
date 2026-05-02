"""
Pulse360 — Investment Analyser
================================
Upload any investment document — a broker screenshot, a fund brochure, a factsheet,
or a CSV export — and get a plain-English macro-aware analysis flagging concentration
risks, cycle sensitivity, and what the current Pulse360 model state means for the holdings.

Two upload paths:
  📸 Screenshot  — drag-and-drop a broker portfolio screenshot or fund brochure/factsheet; Claude reads it via vision
  📄 CSV         — export from IBKR / Schwab / Fidelity and upload

The analysis streams in real time using Claude Sonnet with vision.

Macro context is pulled from session state (set by the Dashboard page).
If the dashboard hasn't been loaded yet, sensible fallback values are used.
"""

from __future__ import annotations

import io
import pandas as pd
import streamlit as st

from ai.portfolio_analyzer import (
    stream_portfolio_from_screenshot,
    stream_portfolio_from_positions,
    stream_portfolio_chat,
    parse_portfolio_csv,
)

# ── Page config & styles ──────────────────────────────────────────────────────

from components.pulse360_theme import inject_theme, BORDER, CARD_BG, PAGE_BG, TEXT_PRI, TEXT_SEC, TEXT_MUT, BLUE
inject_theme()
st.markdown(f"""
<style>
    .main .block-container {{ padding-top: 1rem; max-width: 1100px; }}
    /* Upload zone styling */
    div[data-testid="stFileUploader"] {{
        border: 2px dashed {BORDER} !important;
        border-radius: 12px !important;
        padding: 8px !important;
        background: {PAGE_BG} !important;
    }}
    div[data-testid="stFileUploader"]:hover {{
        border-color: {BLUE} !important;
        background: #e8f1fb !important;
    }}
    .upload-tip {{
        font-size: 0.85rem;
        color: {TEXT_SEC};
        margin-top: 6px;
        line-height: 1.5;
    }}
    .macro-badge {{
        display: inline-block;
        padding: 3px 10px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 600;
        margin-right: 8px;
    }}
    .macro-green  {{ background: #e8f8ee; color: #1a5c30; border: 1px solid #28a745; }}
    .macro-yellow {{ background: #fff8e5; color: #7a5000; border: 1px solid #c98800; }}
    .macro-red    {{ background: #fde8e8; color: #8b1a1a; border: 1px solid #d92626; }}
    .analysis-box {{
        background: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 20px 24px;
        margin-top: 16px;
        line-height: 1.7;
    }}
    /* ── Portfolio chat panel ── */
    .portfolio-chat {{
        background: {PAGE_BG};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 16px 20px;
        margin-top: 24px;
    }}
    .chat-msg-user {{
        background: #e8f1fb;
        border-radius: 8px;
        padding: 10px 14px;
        margin: 8px 0;
        color: {TEXT_PRI};
        font-size: 0.9rem;
    }}
    .chat-msg-ai {{
        background: {CARD_BG};
        border-left: 3px solid {BLUE};
        border-radius: 0 8px 8px 0;
        padding: 10px 14px;
        margin: 8px 0;
        color: {TEXT_PRI};
        font-size: 0.9rem;
        line-height: 1.6;
    }}
</style>
""", unsafe_allow_html=True)

# ── Analysis text helpers ─────────────────────────────────────────────────────

import re as _re

def _fix_dollars(text: str) -> str:
    """Escape $ before numbers so Streamlit doesn't render them as LaTeX."""
    return _re.sub(r'\$(\d)', r'\\$\1', text)

def _colorize_analysis(text: str) -> str:
    """
    Post-process the completed analysis to add 🔴🟡🟢 colour indicators
    to bullet points in Risk flags and What to watch sections.
    Also escapes dollar signs.
    """
    text = _fix_dollars(text)
    lines = text.split('\n')
    out   = []
    section = None

    _DANGER  = ['extreme', 'highly sensitive', 'amplifies', 'directly tied',
                'inversion', 'jump toward', 'sell off', 'sharp reversal',
                'crossing 35', 'crashing', 'collapse']
    _GOOD    = ['hedge', 'diversif', 'resilient', 'protective', 'cash buffer',
                'provides modest']

    for line in lines:
        stripped = line.strip()

        # Track which section we're in
        if stripped.startswith('## '):
            heading = stripped[3:].lower()
            section = (
                'risk'      if 'risk'     in heading else
                'watch'     if 'watch'    in heading else
                'positions' if 'position' in heading else
                None
            )
            out.append(line)
            continue

        # Colour-code bullets in Risk flags and What to watch
        if stripped.startswith('- ') and section in ('risk', 'watch'):
            sl = stripped.lower()
            is_danger = any(w in sl for w in _DANGER)
            is_good   = any(w in sl for w in _GOOD)
            prefix    = '- 🔴 ' if is_danger else ('- 🟢 ' if is_good else '- 🟡 ')
            line      = line.replace('- ', prefix, 1)

        out.append(line)

    return '\n'.join(out)

def render_portfolio_chat(analysis_key: str) -> None:
    """
    Render a follow-up chat panel below a completed portfolio analysis.

    Args:
        analysis_key: session_state key holding the analysis text
                      ("screenshot_analysis_result" or "csv_analysis_result")
    """
    analysis_text = st.session_state.get(analysis_key, "")
    if not analysis_text:
        return

    chat_key      = f"chat_history_{analysis_key}"
    input_key     = f"chat_input_{analysis_key}"
    submitting_key = f"chat_submitting_{analysis_key}"

    if chat_key not in st.session_state:
        st.session_state[chat_key] = []

    st.markdown("---")
    st.markdown("### 💬 Ask a follow-up question")
    st.caption("Ask anything about your portfolio — Claude has the full analysis as context.")

    # ── Suggested prompts ─────────────────────────────────────────────────────
    suggestions = [
        "Which position is most exposed to a recession?",
        "What would happen if NVDA dropped 30%?",
        "How should I think about my semiconductor concentration?",
        "What defensive positions would balance this portfolio?",
    ]
    sug_cols = st.columns(2)
    for i, sug in enumerate(suggestions):
        with sug_cols[i % 2]:
            if st.button(sug, key=f"sug_{analysis_key}_{i}", use_container_width=True):
                st.session_state[submitting_key] = sug

    # ── Chat history display ──────────────────────────────────────────────────
    history = st.session_state[chat_key]
    if history:
        for msg in history:
            if msg["role"] == "user":
                st.markdown(
                    f'<div class="chat-msg-user">🙋 {msg["content"]}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="chat-msg-ai">{msg["content"]}</div>',
                    unsafe_allow_html=True,
                )
        if st.button("🗑️ Clear chat", key=f"clear_{analysis_key}"):
            st.session_state[chat_key] = []
            st.rerun()

    # ── Input form ────────────────────────────────────────────────────────────
    with st.form(key=f"chat_form_{analysis_key}", clear_on_submit=True):
        user_input = st.text_input(
            label       = "Your question",
            placeholder = "e.g. What's my biggest macro risk right now?",
            key         = input_key,
            label_visibility = "collapsed",
        )
        submitted = st.form_submit_button("Send ↗", use_container_width=True)

    # Handle form submission or suggested prompt click
    question = (
        st.session_state.pop(submitting_key, None)
        or (user_input if submitted else None)
    )

    if question:
        history = st.session_state[chat_key]
        history.append({"role": "user", "content": question})

        st.markdown(
            f'<div class="chat-msg-user">🙋 {question}</div>',
            unsafe_allow_html=True,
        )

        placeholder = st.empty()
        response    = ""

        with st.spinner(""):
            for chunk in stream_portfolio_chat(
                user_message          = question,
                chat_history          = history[:-1],   # exclude the just-added user msg
                analysis_text         = analysis_text,
                cycle_phase           = cycle_phase,
                recession_probability = recession_probability,
                traffic_light         = traffic_light,
            ):
                response += chunk
                placeholder.markdown(
                    f'<div class="chat-msg-ai">{response}▌</div>',
                    unsafe_allow_html=True,
                )

        placeholder.markdown(
            f'<div class="chat-msg-ai">{response}</div>',
            unsafe_allow_html=True,
        )
        history.append({"role": "assistant", "content": response})
        st.session_state[chat_key] = history


DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Pulse360 is not a Registered Investment Advisor. "
    "Consult a licensed financial advisor before making investment decisions.*"
)

# ── Pull macro state from session (populated by Dashboard) ────────────────────

cycle_phase           = st.session_state.get("cycle_phase",           "Mid Expansion")
recession_probability = st.session_state.get("recession_probability",  25.0)
traffic_light         = st.session_state.get("traffic_light",          "green")
feature_summary       = st.session_state.get("feature_summary",        [])

tl_class = f"macro-{traffic_light}"
tl_label = {
    "green":  f"🟢 {recession_probability:.0f}% recession risk — Low",
    "yellow": f"🟡 {recession_probability:.0f}% recession risk — Elevated",
    "red":    f"🔴 {recession_probability:.0f}% recession risk — High",
}.get(traffic_light, f"{recession_probability:.0f}% recession risk")

# ── Page header ───────────────────────────────────────────────────────────────

st.markdown("# 🗂️ Investment Analyser")
st.markdown(
    "Upload any investment document — a **broker portfolio screenshot**, **fund brochure**, "
    "**factsheet**, or **CSV export** — and get a plain-English breakdown of the holdings, "
    "risk flags, and what the current macro environment means for each position."
)

# ── Macro context banner ──────────────────────────────────────────────────────

st.markdown(
    f'<span class="macro-badge {tl_class}">{tl_label}</span>'
    f'<span style="color:#6a6a6a; font-size:0.85rem;">Cycle phase: <b style="color:#0a0a0a">{cycle_phase}</b> '
    f'· Analysis is contextualised to current Pulse360 model state</span>',
    unsafe_allow_html=True,
)

st.markdown("---")

# ── Two upload tabs ───────────────────────────────────────────────────────────

tab_screenshot, tab_csv = st.tabs(["📸  Screenshot", "📄  CSV export"])


# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — Screenshot upload
# ═════════════════════════════════════════════════════════════════════════════

with tab_screenshot:

    st.markdown("#### Drag and drop a screenshot of your portfolio")

    col_tip, col_hint = st.columns([3, 2])
    with col_tip:
        st.markdown("""
<div class="upload-tip">
Works with <b>broker portfolios</b> (IBKR, Schwab, Fidelity, Robinhood, eToro) and <b>fund documents</b> (brochures, factsheets, prospectuses).<br>
For portfolios: navigate to your Positions page, take a screenshot (phone or desktop), and drop it below.<br>
For funds: drop a brochure or factsheet page — Claude will extract holdings, strategy, and risk profile.<br>
<b>Multiple screenshots</b> are supported — upload them all and Claude reads them together.<br>
<em>Tip: landscape / desktop screenshots show more columns and give better results.</em>
</div>
""", unsafe_allow_html=True)

    with col_hint:
        st.info(
            "**IBKR mobile:** Portfolio → Positions\n\n"
            "**IBKR desktop:** Account → Portfolio\n\n"
            "**Schwab:** Positions tab\n\n"
            "**Robinhood:** Investing → Portfolio",
            icon="📱",
        )

    uploaded_images = st.file_uploader(
        label       = "Drop your screenshot(s) here",
        type        = ["png", "jpg", "jpeg", "webp"],
        accept_multiple_files = True,
        key         = "portfolio_screenshots",
        label_visibility = "collapsed",
        help        = "PNG, JPG, JPEG or WebP — phone screenshots and desktop captures both work",
    )

    if uploaded_images:
        # Preview uploaded images
        st.markdown(f"**{len(uploaded_images)} screenshot(s) uploaded**")
        preview_cols = st.columns(min(len(uploaded_images), 3))
        for i, img_file in enumerate(uploaded_images):
            with preview_cols[i % 3]:
                st.image(img_file, use_container_width=True, caption=img_file.name)

        st.markdown("")

        if st.button(
            "🤖 Analyse my portfolio",
            use_container_width = True,
            type                = "primary",
            key                 = "btn_analyse_screenshot",
        ):
            st.session_state["screenshot_analysis_requested"] = True

    # Run analysis (separated from button so it survives reruns)
    if st.session_state.get("screenshot_analysis_requested") and uploaded_images:
        st.session_state.pop("screenshot_analysis_requested", None)
        st.session_state.pop("screenshot_analysis_result", None)

        st.markdown("---")
        st.markdown("### Analysis")
        st.caption(
            f"Cycle phase: **{cycle_phase}** · "
            f"Recession probability: **{recession_probability:.1f}%** · "
            f"Traffic light: **{traffic_light.upper()}**"
        )

        placeholder = st.empty()
        full_text   = ""

        with st.spinner("Reading your portfolio and connecting to macro data…"):
            # For multi-screenshot: analyse each image and combine
            # (single call per image; Claude handles context internally)
            for i, img_file in enumerate(uploaded_images):
                img_bytes  = img_file.read()
                media_type = img_file.type or "image/jpeg"

                if len(uploaded_images) > 1:
                    full_text += f"\n\n---\n*Screenshot {i + 1} of {len(uploaded_images)}: {img_file.name}*\n\n"
                    placeholder.markdown(full_text + "▌")

                for chunk in stream_portfolio_from_screenshot(
                    image_bytes           = img_bytes,
                    image_media_type      = media_type,
                    cycle_phase           = cycle_phase,
                    recession_probability = recession_probability,
                    traffic_light         = traffic_light,
                    feature_summary       = feature_summary,
                ):
                    full_text += chunk
                    placeholder.markdown(_fix_dollars(full_text) + "▌")

        colorized = _colorize_analysis(full_text)
        placeholder.markdown(colorized)
        st.session_state["screenshot_analysis_result"] = colorized

    elif "screenshot_analysis_result" in st.session_state and not uploaded_images:
        # Clear cached result if files removed
        st.session_state.pop("screenshot_analysis_result", None)

    # Re-display cached result if images are still present
    elif "screenshot_analysis_result" in st.session_state and uploaded_images:
        st.markdown("---")
        st.markdown("### Analysis")
        st.markdown(st.session_state["screenshot_analysis_result"])
        if st.button("🔄 Re-run analysis", key="rerun_screenshot"):
            st.session_state.pop("screenshot_analysis_result", None)
            st.rerun()

    # Follow-up chat (shown whenever an analysis result exists)
    render_portfolio_chat("screenshot_analysis_result")

    if not uploaded_images:
        st.markdown("""
---
<div style="text-align:center; color:#6a6a6a; padding: 24px 0; font-size:0.9rem;">
    Upload one or more screenshots above to get started
</div>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — CSV upload
# ═════════════════════════════════════════════════════════════════════════════

with tab_csv:

    st.markdown("#### Upload a CSV export from your broker")

    col_tip2, col_hint2 = st.columns([3, 2])
    with col_tip2:
        st.markdown("""
<div class="upload-tip">
Download a positions CSV from your broker and drop it here. <br>
Pulse360 automatically maps the columns — no manual formatting needed.<br>
Works best with <b>IBKR, Schwab, Fidelity</b> and most standard broker exports.
</div>
""", unsafe_allow_html=True)

    with col_hint2:
        st.info(
            "**IBKR:** Reports → Activity → Positions → Download\n\n"
            "**Schwab:** Accounts → Positions → Export\n\n"
            "**Fidelity:** Portfolio → Positions → Download\n\n"
            "**Robinhood:** Account → Statements → Positions",
            icon="📥",
        )

    uploaded_csv = st.file_uploader(
        label      = "Drop your CSV here",
        type       = ["csv"],
        key        = "portfolio_csv",
        label_visibility = "collapsed",
        help       = "CSV format — any standard broker export works",
    )

    if uploaded_csv:
        try:
            raw_df = pd.read_csv(io.StringIO(uploaded_csv.read().decode("utf-8", errors="replace")))
            positions, total_value = parse_portfolio_csv(raw_df)

            if not positions:
                st.error(
                    "No positions found in this CSV. "
                    "Please check that it contains a Ticker/Symbol column. "
                    "You can also try the Screenshot tab instead."
                )
            else:
                # Build preview dataframe
                preview_rows = []
                for p in positions:
                    preview_rows.append({
                        "Ticker":        p["ticker"],
                        "Name":          p.get("name", ""),
                        "Qty":           p.get("quantity", ""),
                        "Avg cost":      f"${p['avg_price']:,.2f}"   if p.get("avg_price")   else "",
                        "Last price":    f"${p['last_price']:,.2f}"  if p.get("last_price")  else "",
                        "Unrealised %":  f"{p['pnl_pct']:+.1f}%"    if p.get("pnl_pct")     else "",
                        "Mkt value":     f"${p['market_value']:,.0f}" if p.get("market_value") else "",
                    })

                preview_df = pd.DataFrame(preview_rows)

                col_m1, col_m2, col_m3 = st.columns(3)
                with col_m1:
                    st.metric("Positions detected", len(positions))
                with col_m2:
                    if total_value:
                        st.metric("Total market value", f"${total_value:,.0f}")
                with col_m3:
                    gainers = sum(1 for p in positions if (p.get("pnl_pct") or 0) > 0)
                    st.metric("Positions in profit", f"{gainers} / {len(positions)}")

                st.markdown("**Detected positions:**")
                st.dataframe(
                    preview_df,
                    use_container_width = True,
                    hide_index          = True,
                )

                if total_value:
                    st.caption(f"Total portfolio value: **${total_value:,.2f}**")

                # Warn about unrecognised tickers
                from ai.portfolio_analyzer import TICKER_SECTORS
                unknown = [p["ticker"] for p in positions if p["ticker"] not in TICKER_SECTORS]
                if unknown:
                    st.warning(
                        f"**{len(unknown)} ticker(s) not in the built-in sector map:** "
                        f"{', '.join(unknown[:10])}{'…' if len(unknown) > 10 else ''}. "
                        "Claude will still analyse them — sector labels may be inferred from context.",
                        icon="⚠️",
                    )

                st.markdown("")

                if st.button(
                    "🤖 Analyse my portfolio",
                    use_container_width = True,
                    type                = "primary",
                    key                 = "btn_analyse_csv",
                ):
                    st.session_state["csv_analysis_requested"] = {
                        "positions":   positions,
                        "total_value": total_value,
                    }

        except Exception as exc:
            st.error(f"Could not parse CSV: {exc}. Try the Screenshot tab instead.")

    # Run CSV analysis
    if st.session_state.get("csv_analysis_requested"):
        snap = st.session_state.pop("csv_analysis_requested")
        st.session_state.pop("csv_analysis_result", None)

        st.markdown("---")
        st.markdown("### Analysis")
        st.caption(
            f"Cycle phase: **{cycle_phase}** · "
            f"Recession probability: **{recession_probability:.1f}%** · "
            f"Traffic light: **{traffic_light.upper()}** · "
            f"{len(snap['positions'])} positions"
        )

        placeholder = st.empty()
        full_text   = ""

        with st.spinner("Connecting your portfolio to macro data…"):
            for chunk in stream_portfolio_from_positions(
                positions             = snap["positions"],
                total_value           = snap["total_value"],
                cycle_phase           = cycle_phase,
                recession_probability = recession_probability,
                traffic_light         = traffic_light,
                feature_summary       = feature_summary,
            ):
                full_text += chunk
                placeholder.markdown(_fix_dollars(full_text) + "▌")

        colorized = _colorize_analysis(full_text)
        placeholder.markdown(colorized)
        st.session_state["csv_analysis_result"] = colorized

    elif "csv_analysis_result" in st.session_state and uploaded_csv:
        st.markdown("---")
        st.markdown("### Analysis")
        st.markdown(st.session_state["csv_analysis_result"])
        if st.button("🔄 Re-run analysis", key="rerun_csv"):
            st.session_state.pop("csv_analysis_result", None)
            st.rerun()

    elif not uploaded_csv:
        st.session_state.pop("csv_analysis_result", None)
        st.markdown("""
---
<div style="text-align:center; color:#6a6a6a; padding: 24px 0; font-size:0.9rem;">
    Upload a CSV export above to get started
</div>
""", unsafe_allow_html=True)

    # Follow-up chat (shown whenever an analysis result exists)
    render_portfolio_chat("csv_analysis_result")


# ── Footer ────────────────────────────────────────────────────────────────────

st.markdown("---")
st.caption(DISCLAIMER)
