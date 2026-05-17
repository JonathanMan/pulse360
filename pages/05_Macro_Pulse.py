"""
pages/05_Macro_Pulse.py
========================
Macro Pulse page — thin render wrapper.
All business logic lives in components/forecasters.py and components/prompts.py.
"""

import streamlit as st
from datetime import date

from assets.logo_helper import header_with_logo

from components.observability import init_page, log, track, capture_exception
init_page("Macro Pulse")
from components.forecasters import (
    get_signals,
    save_signals,
    compute_consensus,
    SIGNAL_STYLES,
    BIAS_STYLES,
    SIGNAL_ORDER,
    GROUP_LABELS,
    is_stale,
)
from components.forecaster_weights import (
    load_weights, save_weights, reset_weights,
    is_equal_weighted, DEFAULT_WEIGHT, MAX_WEIGHT,
    FORECASTER_NAMES,
)
from components.prompts import (
    run_deep_dive,
    build_review_prompt,
    stream_review,
    refresh_signals,
)

header_with_logo("Macro Pulse", "Real-time Forecaster Signals & Consensus Tracking")

# Constrain to a readable width (app.py uses layout="wide")
st.markdown(
    "<style>.main .block-container{max-width:860px;padding-top:1.2rem;}</style>",
    unsafe_allow_html=True,
)

# ── CSS ───────────────────────────────────────────────────────────────────────
MP_CSS = """
<style>
  .mp-section-label { font-size: 11px; font-weight: 500; letter-spacing: 0.08em;
    text-transform: uppercase; color: #888780; margin: 0 0 6px; }
  .mp-section-title { font-size: 20px; font-weight: 500; color: #1a1a18; margin: 0 0 4px; }
  .mp-section-sub { font-size: 13px; color: #5f5e5a; line-height: 1.5; margin: 0 0 10px; }
  .mp-auto-badge { display: inline-flex; align-items: center; gap: 5px; font-size: 11px;
    color: #3B6D11; background: #EAF3DE; border-radius: 20px; padding: 3px 8px;
    margin-bottom: 10px; }
  .mp-auto-dot { width: 6px; height: 6px; border-radius: 50%; background: #639922;
    display: inline-block; }
  .mp-update-time { font-size: 12px; color: #888780; margin-bottom: 14px; }
  .mp-consensus-box { background: #f5f5f3; border: 0.5px solid rgba(0,0,0,0.1);
    border-radius: 10px; padding: 12px 14px; margin-bottom: 18px; }
  .mp-consensus-label { font-size: 12px; color: #5f5e5a; margin: 0 0 8px; }
  .mp-bar-track { border-radius: 4px; height: 6px; width: 100%; margin-bottom: 8px;
    overflow: hidden; display: flex; }
  .mp-bar-legend { display: flex; gap: 14px; }
  .mp-legend-item { font-size: 11px; color: #5f5e5a; display: flex;
    align-items: center; gap: 4px; }
  .mp-legend-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
    display: inline-block; }
  .mp-consensus-verdict { font-size: 13px; font-weight: 500; color: #1a1a18; margin: 8px 0 0; }
  .mp-group-label { font-size: 11px; font-weight: 500; letter-spacing: 0.06em;
    text-transform: uppercase; margin: 16px 0 8px 2px; }
  .mp-fcard { background: #ffffff; border: 0.5px solid rgba(0,0,0,0.12);
    border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; }
  .mp-fcard-top { display: flex; align-items: flex-start; justify-content: space-between;
    margin-bottom: 10px; gap: 8px; }
  .mp-fname { font-size: 15px; font-weight: 500; color: #1a1a18; margin: 0 0 2px; }
  .mp-fspecialty { font-size: 12px; color: #5f5e5a; margin: 0; }
  .mp-signal-badge { font-size: 11px; font-weight: 500; padding: 3px 10px;
    border-radius: 20px; white-space: nowrap; flex-shrink: 0; margin-top: 2px; }
  .mp-fread { font-size: 13px; color: #5f5e5a; line-height: 1.55; margin: 0;
    border-left: 2px solid rgba(0,0,0,0.15); padding-left: 10px; }
  .mp-bias-tag { font-size: 10px; font-weight: 500; padding: 2px 7px;
    border-radius: 20px; white-space: nowrap; letter-spacing: 0.02em; }
  .mp-source-meta { font-size: 11px; color: #888780; margin: 6px 0 0; display: flex;
    align-items: center; gap: 6px; flex-wrap: wrap; }
  .mp-source-link { color: #2a6ebb !important; text-decoration: none !important; }
  .mp-source-link:hover { text-decoration: underline !important; }
  .mp-stale-badge { color: #854F0B; font-weight: 600; }
  .mp-meta-sep { color: #d0cfc9; }
</style>
"""


# ── Card renderers ────────────────────────────────────────────────────────────

def _render_forecaster_card(f: dict) -> None:
    """Render a single forecaster card with source meta and deep-dive CTA."""
    card_key = f["name"].replace(" ", "_").lower()
    dd_key   = f"deep_dive_{card_key}"

    s  = SIGNAL_STYLES.get(f["signal"], SIGNAL_STYLES["Caution"])
    bs = BIAS_STYLES.get(f.get("bias", ""), {"color": "#888", "bg": "#f0f0f0"})
    bias_html = (
        f'<span class="mp-bias-tag" style="color:{bs["color"]};background:{bs["bg"]};">'
        f'{f.get("bias", "")}</span>'
    ) if f.get("bias") else ""

    with st.container(border=True):
        col_info, col_badge = st.columns([5, 1])
        with col_info:
            st.markdown(f"""
              <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-bottom:2px;">
                <p class="mp-fname" style="margin:0;">{f['name']}</p>{bias_html}
              </div>
              <p class="mp-fspecialty">{f['specialty']}</p>
            """, unsafe_allow_html=True)
        with col_badge:
            st.markdown(
                f'<div style="text-align:right;margin-top:4px;">'
                f'<span class="mp-signal-badge" style="background:{s["bg"]};color:{s["text"]};">'
                f'{f["signal"]}</span></div>',
                unsafe_allow_html=True,
            )

        st.markdown(f'<p class="mp-fread">{f["summary"]}</p>', unsafe_allow_html=True)

        # Source / date metadata
        source_url = f.get("source_url", "")
        stmt_date  = f.get("statement_date", "")
        stale      = is_stale(stmt_date)
        meta_parts = []
        if stmt_date:
            stale_html = ' <span class="mp-stale-badge">⚠️ Review needed</span>' if stale else ""
            meta_parts.append(f"{stmt_date}{stale_html}")
        if source_url:
            meta_parts.append(
                f'<span class="mp-meta-sep">·</span> '
                f'<a class="mp-source-link" href="{source_url}" target="_blank">Source ↗</a>'
            )
        if meta_parts:
            st.markdown(
                f'<p class="mp-source-meta">{"  ".join(meta_parts)}</p>',
                unsafe_allow_html=True,
            )

        # Deep-dive state machine
        dd_state = st.session_state.get(dd_key)
        if dd_state == "run":
            st.divider()
            with st.spinner(f"Analysing {f['name'].split()[0]}…"):
                result = run_deep_dive(f)
            st.session_state[dd_key] = result
            st.rerun()
        elif dd_state:
            st.divider()
            st.markdown(dd_state)
            if st.button("✕ Close", key=f"close_{card_key}"):
                del st.session_state[dd_key]
                st.rerun()
        else:
            if st.button(f"Deep dive: {f['name'].split()[0]} ↗", key=f"btn_{card_key}"):
                st.session_state[dd_key] = "run"
                st.rerun()


# ── Main render ───────────────────────────────────────────────────────────────

def render_macro_pulse(signals: dict, weights: dict | None = None) -> None:
    forecasters  = signals["forecasters"]
    last_updated = signals.get("last_updated", str(date.today()))
    counts       = compute_consensus(forecasters, weights=weights)
    total        = len(forecasters)

    pct_off  = round(counts["Risk off"] / total * 100) if total else 0
    pct_caut = round(counts["Caution"]  / total * 100) if total else 0
    pct_on   = 100 - pct_off - pct_caut

    if counts["Risk off"] > counts["Risk on"] and counts["Risk off"] > counts["Caution"]:
        verdict = "Bearish lean — most forecasters signaling caution or risk off"
    elif counts["Risk on"] > counts["Risk off"] and counts["Risk on"] > counts["Caution"]:
        verdict = "Bullish lean — most forecasters constructive on equities"
    else:
        verdict = "Mixed signals — bulls and bears nearly split"

    st.markdown(MP_CSS, unsafe_allow_html=True)

    st.markdown(f"""
      <p class="mp-section-label">Macro pulse</p>
      <p class="mp-section-title">What the top forecasters see</p>
      <p class="mp-section-sub">Signals refreshed weekly from public statements, interviews, and investor letters.</p>
      <span class="mp-auto-badge"><span class="mp-auto-dot"></span>Auto-refreshes every Monday at 8am</span>
      <p class="mp-update-time">Last updated: {last_updated}</p>
    """, unsafe_allow_html=True)

    # ── Credibility weight editor ──────────────────────────────────────────────
    with st.expander("⚖️ Forecaster credibility weights", expanded=False):
        st.caption(
            "Adjust how much weight each forecaster carries in the consensus bar. "
            "1.0 = normal · 0.0 = ignore · 3.0 = triple conviction. "
            "Weights are saved to your account."
        )
        _w_edited: dict[str, float] = {}
        _cols = st.columns(3)
        for _idx, _name in enumerate(FORECASTER_NAMES):
            with _cols[_idx % 3]:
                _w_edited[_name] = st.slider(
                    _name.split()[-1],   # last name only — saves space
                    min_value=0.0,
                    max_value=MAX_WEIGHT,
                    value=float((weights or {}).get(_name, DEFAULT_WEIGHT)),
                    step=0.25,
                    key=f"fw_{_name.replace(' ', '_').lower()}",
                    help=_name,
                )
        _sc, _rc = st.columns([1, 1])
        with _sc:
            if st.button("💾 Save weights", key="fw_save", use_container_width=True, type="primary"):
                save_weights(_w_edited)
                st.success("Weights saved.")
                st.rerun()
        with _rc:
            if st.button("↺ Reset to equal", key="fw_reset", use_container_width=True):
                reset_weights()
                st.success("Reset to equal weights.")
                st.rerun()

    st.markdown(f"""
      <div class="mp-consensus-box">
        <p class="mp-consensus-label">
          {'⚖️ Weighted consensus' if weights and not is_equal_weighted(weights) else 'Macro consensus'}
          across {total} forecasters
        </p>
        <div class="mp-bar-track">
          <div style="background:#E24B4A;height:6px;width:{pct_off}%;"></div>
          <div style="background:#EF9F27;height:6px;width:{pct_caut}%;"></div>
          <div style="background:#639922;height:6px;width:{pct_on}%;"></div>
        </div>
        <div class="mp-bar-legend">
          <span class="mp-legend-item">
            <span class="mp-legend-dot" style="background:#E24B4A;"></span>Risk off ({int(counts["Risk off"])})
          </span>
          <span class="mp-legend-item">
            <span class="mp-legend-dot" style="background:#EF9F27;"></span>Caution ({int(counts["Caution"])})
          </span>
          <span class="mp-legend-item">
            <span class="mp-legend-dot" style="background:#639922;"></span>Risk on ({int(counts["Risk on"])})
          </span>
        </div>
        <p class="mp-consensus-verdict">{verdict}</p>
      </div>
    """, unsafe_allow_html=True)

    grouped: dict[str, list] = {s: [] for s in SIGNAL_ORDER}
    for f in forecasters:
        sig = f.get("signal", "Caution")
        if sig in grouped:
            grouped[sig].append(f)

    for sig in SIGNAL_ORDER:
        group = grouped[sig]
        if not group:
            continue
        lc = SIGNAL_STYLES[sig]["label_color"]
        st.markdown(
            f'<p class="mp-group-label" style="color:{lc};">{GROUP_LABELS[sig]}</p>',
            unsafe_allow_html=True,
        )
        for f in group:
            _render_forecaster_card(f)


# ── Page entrypoint ───────────────────────────────────────────────────────────

if "portfolio_review" not in st.session_state:
    st.session_state.portfolio_review = None

signals      = get_signals()
user_weights = load_weights()   # T3-3: per-user credibility weights
render_macro_pulse(signals, weights=user_weights)

st.divider()

col1, col2 = st.columns([2, 1])
with col2:
    if st.button("↻ Refresh signals", use_container_width=True):
        refresh_signals()
        st.session_state.portfolio_review = None
        st.rerun()

with col1:
    run_review = st.button(
        "Run full macro-adjusted portfolio review ↗",
        use_container_width=True,
        type="primary",
    )

if run_review:
    prompt = build_review_prompt(signals)
    st.markdown("---")
    st.markdown("#### Macro-Adjusted Portfolio Review")
    try:
        result = st.write_stream(stream_review(prompt))
        st.session_state.portfolio_review = result
    except Exception as exc:
        st.error(f"Review failed: {exc}")
elif st.session_state.portfolio_review:
    st.markdown("---")
    st.markdown("#### Macro-Adjusted Portfolio Review")
    st.markdown(st.session_state.portfolio_review)
