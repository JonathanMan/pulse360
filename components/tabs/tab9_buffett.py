"""
Pulse360 — Tab 9: Buffett Indicator
=====================================
The Warren Buffett Indicator: Total US Market Cap / GDP ratio.
Buffett called it "probably the best single measure of where
valuations stand at any given moment."

Data sources:
  NCBEILQ027S — Fed Z.1 Nonfinancial Corporate Equities (millions USD, quarterly)
  GDP         — US Nominal GDP (billions USD, quarterly)
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def _hex_rgba(hex_color: str, alpha: float) -> str:
    """Convert a 6-char hex color to an rgba() string (Plotly-compatible)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

from ai.claude_client import get_buffett_analysis
from components.chart_utils import add_nber, dark_layout, render_action_item
from data.fred_client import fetch_series

DISCLAIMER = (
    "*Educational macro analysis only — not personalised investment advice. "
    "Consult a licensed financial advisor before making investment decisions. "
    "Pulse360 is not a Registered Investment Advisor.*"
)

# ── Valuation zones ───────────────────────────────────────────────────────────
_ZONES = [
    (0,    75,  "Significantly Undervalued", "#2ecc71"),
    (75,  100,  "Modestly Undervalued",      "#27ae60"),
    (100, 115,  "Fair Value",                "#f1c40f"),
    (115, 135,  "Modestly Overvalued",       "#e67e22"),
    (135, 165,  "Overvalued",                "#e74c3c"),
    (165, 999,  "Significantly Overvalued",  "#c0392b"),
]

def _get_zone(ratio: float) -> tuple[str, str]:
    for lo, hi, label, color in _ZONES:
        if lo <= ratio < hi:
            return label, color
    return "Extremely Overvalued", "#8e0000"


# ── Correction analysis helpers ───────────────────────────────────────────────

def _find_sp500_corrections(
    sp_monthly: pd.Series,
    drawdown_threshold: float = -0.10,
) -> list[dict]:
    """
    Identify S&P 500 correction periods using a 12-month rolling peak.
    A correction starts when the index falls >= |drawdown_threshold|% from its
    rolling 12-month high, and ends when it recovers back above that threshold.

    Returns list of dicts: {start, end, trough_date, max_drawdown}.
    """
    rolling_peak = sp_monthly.rolling(12, min_periods=1).max()
    drawdown     = (sp_monthly - rolling_peak) / rolling_peak

    in_corr    = False
    corr_start = None
    trough_val = 0.0
    trough_dt  = None
    results: list[dict] = []

    for dt, dd in drawdown.items():
        if not in_corr:
            if dd <= drawdown_threshold:
                in_corr    = True
                corr_start = dt
                trough_val = float(dd)
                trough_dt  = dt
        else:
            if dd < trough_val:
                trough_val = float(dd)
                trough_dt  = dt
            if dd > drawdown_threshold:          # recovered above threshold
                results.append({
                    "start":        corr_start,
                    "end":          dt,
                    "trough_date":  trough_dt,
                    "max_drawdown": trough_val,
                })
                in_corr = False

    # Ongoing correction at end of data
    if in_corr:
        results.append({
            "start":        corr_start,
            "end":          sp_monthly.index[-1],
            "trough_date":  trough_dt,
            "max_drawdown": trough_val,
        })

    return results


def _breach_to_correction_lags(
    ratio:          pd.Series,
    corrections:    list[dict],
    threshold:      float = 115.0,
    reset_margin:   float = 10.0,      # re-arm once indicator drops this many pp below threshold
    horizon_months: int   = 36,        # ignore corrections more than this far away
) -> list[dict]:
    """
    For each time the quarterly Buffett Indicator first crosses above `threshold`
    (after resetting `reset_margin` pp below it), find the next S&P 500 correction
    (≥10% drawdown) within `horizon_months` and return the lag.

    Returns list of dicts ready for a DataFrame.
    """
    reset_level = threshold - reset_margin
    armed       = True
    rows: list[dict] = []

    for dt, val in ratio.items():
        # Breach: cross above threshold while armed
        if armed and val >= threshold:
            armed     = False
            breach_dt = dt

            upcoming = [c for c in corrections if c["start"] > breach_dt]
            if upcoming:
                c = upcoming[0]
                lag_mo = (
                    (c["start"].year  - breach_dt.year)  * 12 +
                    (c["start"].month - breach_dt.month)
                )
                if lag_mo <= horizon_months:
                    rows.append({
                        "Buffett Breach":    breach_dt,
                        "Level (%)":         round(float(val), 1),
                        "Correction Start":  c["start"],
                        "Max Drawdown":      c["max_drawdown"],
                        "Lag (months)":      lag_mo,
                    })

        # Re-arm once indicator drops sufficiently below threshold
        if not armed and val <= reset_level:
            armed = True

    return rows


def render_tab9(model_output, phase_output) -> None:
    st.subheader("Buffett Indicator")
    st.caption(
        "The Warren Buffett Indicator measures total US stock market capitalisation "
        "relative to US GDP — Buffett's preferred gauge of market valuation. "
        "He called it 'probably the best single measure of where valuations stand at any given moment.' "
        "Market cap sourced from the Federal Reserve Z.1 Flow of Funds "
        "(NCBEILQ027S — Nonfinancial Corporate Equities at Market Value, billions USD) "
        "against nominal GDP (billions USD). Both series are quarterly and in identical units."
    )

    # ── Fetch data ────────────────────────────────────────────────────────────
    # Primary: Fed Z.1 Flow of Funds — Nonfinancial Corporate Equities at Market Value
    # (WILL5000INDFC was discontinued by Wilshire Associates and removed from FRED)
    # NCBEILQ027S is in billions USD; GDP is also in billions USD → ratio is directly comparable
    with st.spinner("Loading market cap and GDP data…"):
        wilshire = fetch_series("NCBEILQ027S", start_date="1945-01-01")
        gdp      = fetch_series("GDP",         start_date="1945-01-01")

    if wilshire["data"].empty or gdp["data"].empty:
        st.error("Unable to fetch required data — check FRED API connection.")
        return

    # ── Compute ratio ─────────────────────────────────────────────────────────
    # NCBEILQ027S is in MILLIONS of USD; GDP is in BILLIONS of USD
    # → divide market cap by 1000 to convert millions → billions before computing ratio
    # ratio = (market_cap_billions / GDP_billions) × 100  →  Buffett Indicator %
    w_q = (wilshire["data"] / 1000).resample("QE").last().dropna()   # millions → billions
    g_q = gdp["data"].resample("QE").last().ffill().dropna()

    common = w_q.index.intersection(g_q.index)
    w_q = w_q.loc[common]
    g_q = g_q.loc[common]

    ratio = (w_q / g_q * 100).dropna()
    if ratio.empty:
        st.error("Could not compute Buffett Indicator — data alignment failed.")
        return

    current_ratio  = float(ratio.iloc[-1])
    hist_mean      = float(ratio.mean())
    hist_pct       = float((ratio < current_ratio).mean() * 100)
    premium        = current_ratio - hist_mean
    zone_label, zone_color = _get_zone(current_ratio)

    # ── Metric row ────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    qoq_delta = current_ratio - float(ratio.iloc[-2]) if len(ratio) >= 2 else None
    with c1:
        st.metric(
            "Buffett Indicator",
            f"{current_ratio:.1f}%",
            delta=f"{qoq_delta:+.1f}pp QoQ" if qoq_delta is not None else None,
        )
    with c2:
        st.metric("Historical Average", f"{hist_mean:.1f}%")
    with c3:
        delta_color = "normal" if abs(premium) < 5 else "inverse" if premium > 0 else "normal"
        st.metric("Premium / Discount to Avg", f"{premium:+.1f}pp")
    with c4:
        st.metric("Historical Percentile", f"{hist_pct:.0f}th")

    # ── Zone badge ────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="text-align:center; margin:10px 0 18px; '
        f'background:{_hex_rgba(zone_color, 0.13)}; border:2px solid {_hex_rgba(zone_color, 0.4)}; '
        f'border-radius:10px; padding:12px; font-weight:700; '
        f'color:{zone_color}; font-size:1.15rem;">'
        f'⚖️ Market Valuation: {zone_label} ({current_ratio:.1f}% of GDP)</div>',
        unsafe_allow_html=True,
    )

    # ── Action item ───────────────────────────────────────────────────────────
    if current_ratio > 165:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — significantly overvalued; "
            f"Buffett historically accumulates cash and avoids crowded markets at these levels; "
            f"consider reducing equity allocation and raising quality bar.",
            "#e74c3c",
        )
    elif current_ratio > 135:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — overvalued; "
            f"favour quality and value over growth; avoid leverage; hold above-average cash.",
            "#e74c3c",
        )
    elif current_ratio > 115:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — modestly overvalued; "
            f"maintain strategic allocation but avoid aggressive new equity purchases at elevated prices.",
            "#f39c12",
        )
    elif current_ratio > 100:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — near fair value; "
            f"standard strategic allocation supported; no major over/underweight warranted.",
            "#f39c12",
        )
    elif current_ratio > 75:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — modestly undervalued; "
            f"equities offer reasonable long-term value; incremental equity overweight supported.",
            "#2ecc71",
        )
    else:
        render_action_item(
            f"Buffett Indicator at {current_ratio:.1f}% — significantly undervalued; "
            f"Buffett would be buying aggressively; strong long-term entry opportunity.",
            "#2ecc71",
        )

    st.markdown("---")

    # ── Historical chart ──────────────────────────────────────────────────────
    st.markdown("##### Buffett Indicator — Historical (1945–Present)")
    st.caption(
        "Each quarterly data point shows US nonfinancial corporate equity market cap as a % of nominal GDP. "
        "Grey shading = NBER recessions. "
        "Coloured bands show Buffett's own valuation zones. "
        "The dotted line is the long-run average."
    )

    fig = go.Figure()

    # Background zone bands
    for lo, hi, label, color in _ZONES:
        fig.add_hrect(
            y0=lo, y1=min(hi, 300),
            fillcolor=_hex_rgba(color, 0.08),
            line_width=0, layer="below",
            annotation_text=label,
            annotation_position="right",
            annotation_font_color=color,
            annotation_font_size=9,
        )

    # Main ratio line
    fig.add_trace(go.Scatter(
        x=ratio.index, y=ratio.values,
        mode="lines",
        line={"color": zone_color, "width": 2.5},
        name="Buffett Indicator (%)",
        fill="tozeroy", fillcolor=_hex_rgba(zone_color, 0.10),
        hovertemplate="%{x|%b %Y}: <b>%{y:.1f}%</b><extra></extra>",
    ))

    # Historical mean
    fig.add_hline(
        y=hist_mean, line_dash="dot", line_color="#888", line_width=1.5,
        annotation_text=f"Avg {hist_mean:.0f}%",
        annotation_font_color="#888", annotation_position="top left",
    )

    # Key thresholds
    for thresh, label, color in [
        (75,  "75% Undervalued",  "#2ecc71"),
        (100, "100% Fair Value",  "#f1c40f"),
        (135, "135% Overvalued",  "#e74c3c"),
    ]:
        fig.add_hline(
            y=thresh, line_dash="dash", line_color=color, line_width=1,
            annotation_text=label, annotation_font_color=color,
            annotation_position="top right", annotation_font_size=9,
        )

    fig = add_nber(fig, start_date="1945-01-01")
    fig = dark_layout(fig, yaxis_title="Market Cap / GDP (%)")
    fig.update_layout(
        height=440,
        yaxis={"range": [0, min(300, max(ratio.values) * 1.15)]},
    )
    st.plotly_chart(fig, use_container_width=True, key="tab9_buffett_main")

    # ── Market cap vs GDP divergence chart ────────────────────────────────────
    st.markdown("##### Market Cap vs GDP — Divergence (Rebased to 100 at Start)")
    st.caption(
        "When the blue line (nonfinancial corporate equity market cap) diverges above the green line (GDP), "
        "the Buffett Indicator rises — prices are growing faster than the real economy. "
        "Sustained divergence historically signals stretched valuations."
    )

    w_norm = (w_q / w_q.iloc[0] * 100)
    g_norm = (g_q / g_q.iloc[0] * 100)

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=w_norm.index, y=w_norm.values,
        mode="lines", line={"color": "#3498db", "width": 2},
        name="Nonfinancial Corp. Market Cap (rebased to 100)",
        hovertemplate="%{x|%b %Y}: <b>%{y:.0f}</b><extra></extra>",
    ))
    fig2.add_trace(go.Scatter(
        x=g_norm.index, y=g_norm.values,
        mode="lines", line={"color": "#2ecc71", "width": 2, "dash": "dot"},
        name="Nominal GDP (rebased to 100)",
        hovertemplate="%{x|%b %Y}: <b>%{y:.0f}</b><extra></extra>",
    ))
    fig2 = add_nber(fig2, start_date="1945-01-01")
    fig2 = dark_layout(fig2, yaxis_title="Index (1945 = 100)")
    fig2.update_layout(height=300)
    st.plotly_chart(fig2, use_container_width=True, key="tab9_buffett_diverge")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    # CORRECTIONS OVERLAY + LAG ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════

    st.markdown("##### Buffett Indicator vs S&P 500 Corrections")
    st.caption(
        "Red shading marks S&P 500 corrections (≥10% drawdown from rolling 12-month high). "
        "Grey shading = NBER recessions. Dashed lines show key overvaluation thresholds. "
        "Use the lag table below to see how many months elapsed between each Buffett breach "
        "and the next market correction."
    )

    with st.spinner("Loading S&P 500 correction data…"):
        sp_result = fetch_series("SP500", start_date="1950-01-01")

    if sp_result["data"].empty:
        st.warning("S&P 500 data unavailable — corrections overlay skipped.")
    else:
        sp_monthly  = sp_result["data"].resample("ME").last().dropna()
        corrections = _find_sp500_corrections(sp_monthly, drawdown_threshold=-0.10)

        # ── Overlay chart ─────────────────────────────────────────────────────
        fig_c = go.Figure()

        # Valuation zone bands (lighter than main chart — corrections dominate)
        for lo, hi, label, color in _ZONES:
            fig_c.add_hrect(
                y0=lo, y1=min(hi, 300),
                fillcolor=_hex_rgba(color, 0.05),
                line_width=0, layer="below",
            )

        # S&P 500 correction shading — intensity scales with drawdown depth
        for c in corrections:
            depth     = abs(c["max_drawdown"])
            intensity = min(0.08 + depth * 0.6, 0.28)
            fig_c.add_vrect(
                x0=c["start"], x1=c["end"],
                fillcolor=f"rgba(231,76,60,{intensity:.2f})",
                line_width=0, layer="below",
            )
            # Label deeper corrections
            if depth >= 0.15:
                fig_c.add_annotation(
                    x=c["trough_date"], y=ratio.max() * 1.05,
                    text=f"-{depth:.0%}",
                    showarrow=False,
                    font={"color": "#e74c3c", "size": 8},
                    xanchor="center",
                )

        # Buffett Indicator line
        fig_c.add_trace(go.Scatter(
            x=ratio.index, y=ratio.values,
            mode="lines",
            line={"color": zone_color, "width": 2.5},
            name="Buffett Indicator (%)",
            hovertemplate="%{x|%b %Y}: <b>%{y:.1f}%</b><extra></extra>",
        ))

        # Historical mean
        fig_c.add_hline(
            y=hist_mean, line_dash="dot", line_color="#888", line_width=1.5,
            annotation_text=f"Avg {hist_mean:.0f}%",
            annotation_font_color="#888", annotation_position="top left",
        )

        # Overvaluation threshold lines
        for thresh, label, color in [
            (115, "115% Modestly OV",       "#e67e22"),
            (135, "135% Overvalued",         "#e74c3c"),
            (165, "165% Significantly OV",   "#c0392b"),
        ]:
            fig_c.add_hline(
                y=thresh, line_dash="dash", line_color=color, line_width=1,
                annotation_text=label, annotation_font_color=color,
                annotation_position="top right", annotation_font_size=9,
            )

        # Legend proxy for correction shading
        fig_c.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker={"color": "rgba(231,76,60,0.35)", "size": 12, "symbol": "square"},
            name="S&P 500 Correction (≥10%)",
        ))

        fig_c = add_nber(fig_c, start_date="1945-01-01")
        fig_c = dark_layout(fig_c, yaxis_title="Market Cap / GDP (%)")
        fig_c.update_layout(
            height=480,
            yaxis={"range": [0, min(300, float(ratio.max()) * 1.15)]},
            legend={"orientation": "h", "y": -0.08},
        )
        st.plotly_chart(fig_c, use_container_width=True, key="tab9_corrections_overlay")

        # ── Lag analysis ──────────────────────────────────────────────────────
        st.markdown("##### Avg Time: Buffett Breach → Next Market Correction")
        st.caption(
            "Select a valuation threshold. Each row shows the first time the Buffett Indicator "
            "crossed that level, and the next S&P 500 correction (≥10%) that followed within "
            "36 months. 'Lag' = months between the breach date and the correction start."
        )

        thresh_options = {
            "115% — Modestly Overvalued":       115.0,
            "135% — Overvalued":                135.0,
            "165% — Significantly Overvalued":  165.0,
        }
        thresh_label = st.selectbox(
            "Overvaluation threshold",
            options=list(thresh_options.keys()),
            key="tab9_thresh_select",
        )
        thresh_val = thresh_options[thresh_label]

        rows = _breach_to_correction_lags(
            ratio, corrections,
            threshold=thresh_val,
            reset_margin=10.0,
            horizon_months=36,
        )

        if rows:
            avg_lag = sum(r["Lag (months)"] for r in rows) / len(rows)
            min_lag = min(r["Lag (months)"] for r in rows)
            max_lag = max(r["Lag (months)"] for r in rows)
            med_lag = sorted(r["Lag (months)"] for r in rows)[len(rows) // 2]

            # Summary metrics
            mc1, mc2, mc3, mc4 = st.columns(4)
            with mc1:
                st.metric("Avg Lag", f"{avg_lag:.1f} mo")
            with mc2:
                st.metric("Median Lag", f"{med_lag} mo")
            with mc3:
                st.metric("Fastest", f"{min_lag} mo")
            with mc4:
                st.metric("Slowest", f"{max_lag} mo")

            # Format table
            df_rows = []
            for r in rows:
                df_rows.append({
                    "Buffett Breach":    r["Buffett Breach"].strftime("%b %Y"),
                    "Level (%)":         f"{r['Level (%)']:.1f}%",
                    "Correction Start":  r["Correction Start"].strftime("%b %Y"),
                    "Max Drawdown":      f"{r['Max Drawdown']:.1%}",
                    "Lag (months)":      r["Lag (months)"],
                })
            df = pd.DataFrame(df_rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Callout
            color = "#e74c3c" if avg_lag < 6 else "#f39c12" if avg_lag < 18 else "#2ecc71"
            render_action_item(
                f"Since 1950, when the Buffett Indicator first crossed {thresh_val:.0f}%, "
                f"a market correction (≥10%) followed on average {avg_lag:.1f} months later "
                f"(median: {med_lag} months, range: {min_lag}–{max_lag} months across "
                f"{len(rows)} episodes). "
                f"The indicator can remain elevated for extended periods — this is a valuation "
                f"signal, not a timing tool.",
                color,
            )
        else:
            st.info(
                f"No qualifying breach → correction pairs found for {thresh_val:.0f}% "
                f"within the available data window."
            )

    st.markdown("---")

    # ── AI Daily Brief ────────────────────────────────────────────────────────
    st.markdown("### 🤖 Buffett Indicator — AI Analysis")
    st.caption("Claude Sonnet · Cached 6 hours · Answers: what does the Buffett Indicator say today?")

    if st.button("📊 Generate Buffett Analysis", use_container_width=True, key="buffett_brief_btn"):
        st.session_state["show_buffett_brief"] = True
        st.session_state.pop("buffett_brief_text", None)

    if st.session_state.get("show_buffett_brief"):
        if "buffett_brief_text" not in st.session_state:
            placeholder = st.empty()
            full_text   = ""
            for chunk in get_buffett_analysis(
                current_ratio         = round(current_ratio, 1),
                historical_avg        = round(hist_mean, 1),
                historical_percentile = round(hist_pct, 0),
                zone_label            = zone_label,
                cycle_phase           = phase_output.phase,
                recession_probability = round(model_output.probability, 1),
                traffic_light         = model_output.traffic_light,
                premium_to_avg        = round(premium, 1),
            ):
                full_text += chunk
                placeholder.markdown(full_text + "▌")
            placeholder.markdown(full_text)
            st.session_state["buffett_brief_text"] = full_text
        else:
            st.markdown(st.session_state["buffett_brief_text"])

    st.markdown("---")
    st.caption(DISCLAIMER)
