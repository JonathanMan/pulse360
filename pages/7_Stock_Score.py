"""
Pulse360 — Buffett Stock Score
================================
100-point single-stock quality analysis implementing the Buffett / Munger
investment framework.

  1. Sector-relative benchmarking  — margins vs industry median
  2. Piotroski F-Score             — 9-point financial-strength signal
  3. Altman Z-Score                — bankruptcy / distress risk
  4. Owner Earnings DCF            — intrinsic value per share
  5. Share count trend             — buyback detection
  6. 200-day MA momentum filter    — avoids falling knives
  7. FCF yield & valuation context
  8. Sector warnings               — Financials / REITs flagged

All shared utilities live in components/stock_score_utils.py.
The bulk screener has moved to pages/8_Screener.py.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.chart_utils import dark_layout
from components.stock_score_utils import (
    DISCLAIMER,
    _SECTOR_GM_STD,
    _SECTOR_NM_STD,
    _SECTOR_ROE_MEDIAN,
    _SECTOR_ROE_STD,
    _compute_score,
    _fundamentals_trend,
    _get_sbc,
    _hex_rgba,
    _is_special_sector,
    _owner_earnings_dcf,
    _percentile_badge,
    _score_color,
    _score_label,
    _sector_percentile,
    _sf,
    fetch_stock_data,
)

# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .main .block-container { padding-top: 1rem; max-width: 1200px; }
    div[data-testid="metric-container"] {
        background: #1a1a2e; border-radius: 8px;
        padding: 12px 16px; border: 1px solid #333;
    }
    .stTabs [data-baseweb="tab"] { background-color: #1a1a2e;
                                   border-radius: 6px 6px 0 0; padding: 8px 14px; }
    .stTabs [aria-selected="true"] { background-color: #2a2a4a; }
</style>
""", unsafe_allow_html=True)


# ── UI helpers ─────────────────────────────────────────────────────────────────

def _render_section_items(items: list[dict]) -> None:
    for item in items:
        earned = item["earned"]
        pts    = item["pts"]
        pct    = earned / pts if pts > 0 else 0
        if pct >= 0.8:
            icon, color = "✅", "#2ecc71"
        elif pct >= 0.4:
            icon, color = "🟡", "#f39c12"
        elif item.get("pass") is None:
            icon, color = "⬜", "#555"
        else:
            icon, color = "❌", "#e74c3c"

        tip_html = (
            f'<span style="font-size:0.72rem;color:#888;margin-left:8px;">ℹ {item["tip"]}</span>'
            if item.get("tip") else ""
        )
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
            f'padding:6px 10px;border-bottom:1px solid #1e1e2e;">'
            f'<span style="color:#ccc;font-size:0.85rem;">{icon} {item["name"]}{tip_html}</span>'
            f'<span style="font-size:0.8rem;">'
            f'<span style="color:#888;">{item["detail"]}&nbsp;&nbsp;</span>'
            f'<span style="color:{color};font-weight:700;">{earned}/{pts}</span>'
            f'</span></div>',
            unsafe_allow_html=True,
        )


# ── Page header ────────────────────────────────────────────────────────────────
st.markdown("# 🔍 Buffett Stock Score")
st.caption(
    "A 100-point stock screen implementing the Buffett / Munger quality framework. "
    "Sector-relative benchmarks · Piotroski F-Score · Altman Z-Score · "
    "Owner Earnings DCF · 200-day MA momentum · Share buyback detection."
)

col_inp, col_tip = st.columns([2, 3])
with col_inp:
    ticker_input = st.text_input(
        "Enter stock ticker",
        placeholder="e.g. AAPL, MSFT, KO, BRK-B",
        key="stock_score_ticker",
        help="Any ticker listed on US exchanges (yfinance). "
             "International tickers: append exchange suffix (e.g. SHEL.L)",
    ).strip().upper()

with col_tip:
    st.info(
        "**How scoring works:** 100pts across five dimensions — "
        "Quality Moat (40) · Financial Fortress (25) · Valuation (20) · "
        "Momentum (10) · Shareholder Alignment (5). "
        "Margins are benchmarked vs sector medians, not flat thresholds.",
        icon="📐",
    )

if not ticker_input:
    st.markdown("""
---
<div style="text-align:center; color:#555; padding:16px 0 8px; font-size:0.95rem;">
    Enter a ticker above to run the full Buffett Score analysis.
</div>
""", unsafe_allow_html=True)

# ── Load data ──────────────────────────────────────────────────────────────────
if ticker_input:
    with st.spinner(f"Loading fundamentals for {ticker_input}…"):
        raw = fetch_stock_data(ticker_input)

    if raw.get("error") or not raw.get("info"):
        err_msg = raw.get("error", "No data returned")
        is_rate_limit = any(x in err_msg.lower() for x in ["too many", "rate limit", "429"])
        if is_rate_limit:
            st.warning(
                f"⏱️ **Yahoo Finance is rate-limiting requests for {ticker_input}.** "
                "This is temporary — wait 15–30 seconds then click **Retry** below.",
                icon="🔄",
            )
        else:
            st.error(
                f"Could not load data for **{ticker_input}**. "
                f"Error: {err_msg}. Check the ticker is correct and try again."
            )
        col_retry, _ = st.columns([1, 5])
        with col_retry:
            if st.button("🔄 Retry", key="retry_ticker"):
                st.cache_data.clear()
                st.rerun()
        ticker_input = ""


if ticker_input:
    info      = raw["info"]
    long_name = info.get("longName") or info.get("shortName") or ticker_input
    sector    = info.get("sector")   or info.get("sectorDisp") or "Unknown"
    industry  = info.get("industry") or info.get("industryDisp") or "Unknown"
    cur_price = _sf(info.get("currentPrice") or info.get("regularMarketPrice"))
    mktcap    = _sf(info.get("marketCap"))

    # ── Company header ────────────────────────────────────────────────────────
    st.markdown("---")
    hc1, hc2, hc3, hc4 = st.columns([3, 1, 1, 1])
    with hc1:
        st.markdown(f"## {long_name}")
        st.caption(f"{ticker_input} · {sector} · {industry}")
    with hc2:
        if cur_price:
            st.metric("Price", f"${cur_price:,.2f}")
    with hc3:
        if mktcap:
            st.metric("Market Cap", f"${mktcap/1e9:.1f}B")
    with hc4:
        ma200 = _sf(info.get("twoHundredDayAverage"))
        if cur_price and ma200:
            pct = (cur_price - ma200) / ma200 * 100
            st.metric("vs 200-day MA", f"{pct:+.1f}%",
                      delta_color="normal" if pct > 0 else "inverse")

    if _is_special_sector(sector, industry):
        st.warning(
            f"⚠️ **{sector} / {industry}** — Financial or REIT sector. "
            "Standard Buffett rules (D/E, Gross Margin) are **not directly applicable**. "
            "Treat the score directionally. Piotroski F-Score and ROE remain meaningful.",
            icon="🏦",
        )

    # ── Price chart ───────────────────────────────────────────────────────────
    hist = raw.get("history", pd.DataFrame())
    if not hist.empty and len(hist) >= 20:
        close        = hist["Close"]
        ma50_series  = close.rolling(50).mean()
        ma200_series = close.rolling(200).mean()

        fig_price = go.Figure()

        if {"Open", "High", "Low", "Close"}.issubset(hist.columns):
            fig_price.add_trace(go.Candlestick(
                x=hist.index,
                open=hist["Open"], high=hist["High"],
                low=hist["Low"],   close=hist["Close"],
                name="Price",
                increasing_line_color="#2ecc71", decreasing_line_color="#e74c3c",
                increasing_fillcolor="#2ecc71",  decreasing_fillcolor="#e74c3c",
                line={"width": 1}, showlegend=False,
            ))
        else:
            fig_price.add_trace(go.Scatter(
                x=close.index, y=close.values,
                name="Price", line={"color": "#3498db", "width": 1.5},
            ))

        # 200-day MA: solid weight-2 (primary trend reference)
        fig_price.add_trace(go.Scatter(
            x=ma200_series.index, y=ma200_series.values,
            name="200-day MA", line={"color": "#e74c3c", "width": 2},
            hovertemplate="200MA: $%{y:.2f}<extra></extra>",
        ))
        # 50-day MA: dotted (short-term momentum)
        fig_price.add_trace(go.Scatter(
            x=ma50_series.index, y=ma50_series.values,
            name="50-day MA", line={"color": "#f39c12", "width": 1.5, "dash": "dot"},
            hovertemplate="50MA: $%{y:.2f}<extra></extra>",
        ))

        # Technical trend label
        last_close = float(close.iloc[-1])
        last_ma200 = float(ma200_series.dropna().iloc[-1]) if not ma200_series.dropna().empty else None
        last_ma50  = float(ma50_series.dropna().iloc[-1])  if not ma50_series.dropna().empty  else None
        if last_ma200:
            if last_close < last_ma200 * 0.97:
                tech_label, tech_color = "⚠ Technical Downtrend", "#e74c3c"
            elif last_close > last_ma200 * 1.03 and last_ma50 and last_ma50 > last_ma200:
                tech_label, tech_color = "✓ Technical Uptrend", "#2ecc71"
            else:
                tech_label, tech_color = "→ Near 200-day MA", "#f39c12"
        else:
            tech_label, tech_color = "", "#888"

        fig_price = dark_layout(fig_price, yaxis_title="Price (USD)")
        fig_price.update_layout(
            height=400,
            title=dict(
                text=f"{ticker_input} — 2-Year Price History  |  {tech_label}",
                font=dict(size=13, color=tech_color if tech_label else "#ccc"),
            ),
            legend=dict(orientation="h", y=-0.15, font=dict(size=11, color="#aaa")),
            xaxis=dict(rangeslider=dict(visible=False), type="date"),
            margin=dict(t=40, b=0, l=0, r=0),
        )
        if last_ma200 and last_close < last_ma200:
            fig_price.add_hrect(
                y0=last_close * 0.85, y1=last_ma200,
                fillcolor="rgba(231,76,60,0.05)", line_width=0,
                annotation_text="Below 200MA", annotation_position="top left",
                annotation_font={"size": 10, "color": "#e74c3c"},
            )
        st.plotly_chart(fig_price, use_container_width=True, key="header_price_chart")

    # ── Compute scores ────────────────────────────────────────────────────────
    with st.spinner("Computing scores…"):
        score_data = _compute_score(raw)

    total       = score_data["total"]
    s_color     = _score_color(total)
    s_label, s_emoji = _score_label(total)
    trend_arrow, trend_color, trend_tip = _fundamentals_trend(raw)
    secs        = score_data["sections"]
    moat        = secs["moat"]
    fortress    = secs["fortress"]
    valuation   = secs["valuation"]
    momentum    = secs["momentum"]
    shareholder = secs["shareholder"]

    # ── Composite score card ──────────────────────────────────────────────────
    st.markdown(
        f"""
        <div style="background:#1a1a2e;border:2px solid {_hex_rgba(s_color, 0.6)};
                    border-radius:12px;padding:20px 24px;margin:12px 0;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;
                      flex-wrap:wrap;gap:16px;margin-bottom:14px;">
            <div>
              <div style="color:#888;font-size:0.7rem;font-weight:700;letter-spacing:.08em;
                          text-transform:uppercase;margin-bottom:6px;">
                Buffett Score — {long_name}
              </div>
              <div style="display:flex;align-items:baseline;gap:10px;">
                <div style="color:{s_color};font-size:3rem;font-weight:900;line-height:1;">
                  {total}
                  <span style="font-size:1rem;color:#555;font-weight:400;"> / 100</span>
                </div>
                <div title="{trend_tip}" style="color:{trend_color};font-size:1.8rem;
                     font-weight:700;line-height:1;">{trend_arrow}</div>
              </div>
              <div style="color:{s_color};font-size:1rem;font-weight:700;margin-top:6px;">
                {s_emoji} {s_label}
                <span style="color:{trend_color};font-size:0.72rem;font-weight:400;
                      margin-left:8px;">{trend_tip}</span>
              </div>
            </div>
            <div style="font-size:0.8rem;line-height:2.1;padding-top:4px;">
        """,
        unsafe_allow_html=True,
    )

    for sec_key, sec_name in [
        ("moat",        "⚔️  Quality Moat"),
        ("fortress",    "🏰  Financial Fortress"),
        ("valuation",   "💰  Valuation"),
        ("momentum",    "📈  Momentum"),
        ("shareholder", "🤝  Shareholder Alignment"),
    ]:
        sec = secs[sec_key]
        pct = sec["score"] / sec["max"] * 100
        sc  = _score_color(int(pct))
        st.markdown(
            f'<div style="font-size:0.8rem;line-height:2.0;">'
            f'<span style="color:#888;">{sec_name}</span>'
            f'&nbsp;<span style="color:{sc};font-weight:700;">{sec["score"]}/{sec["max"]}</span>'
            f'&nbsp;<span style="color:#555;font-size:0.72rem;">'
            f'{"▓" * int(pct // 10)}{"░" * (10 - int(pct // 10))}'
            f'</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown("</div></div>", unsafe_allow_html=True)

    # ── Divergence Alerts ─────────────────────────────────────────────────────
    moat_pct = moat["score"]      / moat["max"]
    val_pct  = valuation["score"] / valuation["max"]
    mom_pct  = momentum["score"]  / momentum["max"]

    _alerts = []
    if moat_pct >= 0.70 and mom_pct <= 0.30:
        _alerts.append((
            "💎 Value Opportunity",
            f"High-quality moat ({moat['score']}/{moat['max']}) with weak momentum "
            f"({momentum['score']}/{momentum['max']}). "
            "Fundamentals lead price — Buffett's preferred setup.",
            "#2ecc71", "#0d2b1d",
        ))
    if mom_pct >= 0.70 and val_pct <= 0.40:
        _alerts.append((
            "⚠️ FOMO Risk",
            f"Strong momentum ({momentum['score']}/{momentum['max']}) but expensive "
            f"valuation ({valuation['score']}/{valuation['max']}). "
            "Price has likely run ahead of fundamentals.",
            "#e67e22", "#2b1a0d",
        ))
    if moat_pct >= 0.80 and val_pct <= 0.25:
        _alerts.append((
            "⏳ Quality at a Premium",
            f"Exceptional moat ({moat['score']}/{moat['max']}) but stretched valuation "
            f"({valuation['score']}/{valuation['max']}). "
            "Great business, wrong price. Add to watchlist and wait.",
            "#9b59b6", "#1e0d2b",
        ))
    if moat_pct >= 0.70 and val_pct >= 0.60 and mom_pct >= 0.60:
        _alerts.append((
            "🏆 Ideal Alignment",
            f"Quality ({moat['score']}/{moat['max']}), value ({valuation['score']}/{valuation['max']}), "
            f"and momentum ({momentum['score']}/{momentum['max']}) all aligned. "
            "Rare convergence — high-conviction setup.",
            "#f1c40f", "#2b2500",
        ))
    if moat_pct <= 0.40 and mom_pct <= 0.30 and val_pct <= 0.40:
        _alerts.append((
            "🔻 Value Trap Risk",
            f"Weak moat ({moat['score']}/{moat['max']}), deteriorating momentum, "
            "and poor valuation context. "
            "Cheap can always get cheaper.",
            "#e74c3c", "#2b0d0d",
        ))

    for _title, _body, _accent, _bg in _alerts:
        st.markdown(
            f'<div style="background:{_bg};border:1px solid {_accent}55;border-left:4px solid {_accent};'
            f'border-radius:8px;padding:12px 16px;margin:6px 0;">'
            f'<span style="color:{_accent};font-weight:700;font-size:0.9rem;">{_title}</span>'
            f'<span style="color:#ccc;font-size:0.82rem;margin-left:12px;">{_body}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Five section tabs ─────────────────────────────────────────────────────
    t1, t2, t3, t4, t5 = st.tabs([
        "⚔️ Quality Moat",
        "🏰 Financial Fortress",
        "💰 Valuation & DCF",
        "📈 Momentum",
        "🤝 Shareholder Alignment",
    ])

    # ── TAB 1: Quality Moat ───────────────────────────────────────────────────
    with t1:
        st.markdown(f"#### Quality Moat — {moat['score']}/{moat['max']} pts")
        st.caption(
            "Gross Margin and Net Margin are benchmarked against the **sector median**, "
            "not a flat 40% threshold. Avoids unfairly penalising high-quality tech / "
            "healthcare and rewarding low-margin commodity businesses."
        )
        med_gm = score_data["med_gm"]
        med_nm = score_data["med_nm"]

        gm_pct  = (_sf(info.get("grossMargins", 0) or 0) or 0) * 100
        nm_pct  = (_sf(info.get("profitMargins", 0) or 0) or 0) * 100
        roe_val = ((_sf(info.get("returnOnEquity")) or 0)) * 100
        gm_std  = _SECTOR_GM_STD.get(sector, 12.0)
        nm_std  = _SECTOR_NM_STD.get(sector, 6.0)
        roe_med = _SECTOR_ROE_MEDIAN.get(sector, 15.0)
        roe_std = _SECTOR_ROE_STD.get(sector, 12.0)

        prank_gm  = _sector_percentile(gm_pct,  med_gm,  gm_std)  if gm_pct  else ""
        prank_nm  = _sector_percentile(nm_pct,  med_nm,  nm_std)  if nm_pct  else ""
        prank_roe = _sector_percentile(roe_val, roe_med, roe_std) if roe_val else ""

        rank_html = ""
        for label, value, unit, prank, median in [
            ("Gross Margin",     gm_pct,  "%", prank_gm,  med_gm),
            ("Net Margin",       nm_pct,  "%", prank_nm,  med_nm),
            ("Return on Equity", roe_val, "%", prank_roe, roe_med),
        ]:
            if value:
                badge = _percentile_badge(prank) if prank else ""
                rank_html += (
                    f'<div style="display:inline-block;background:#161b27;border:1px solid #333;'
                    f'border-radius:6px;padding:8px 14px;margin:0 6px 8px 0;">'
                    f'<div style="color:#666;font-size:0.68rem;text-transform:uppercase;'
                    f'letter-spacing:.04em;">{label}</div>'
                    f'<div style="color:#fff;font-weight:700;font-size:1.1rem;">'
                    f'{value:.1f}{unit}{badge}</div>'
                    f'<div style="color:#555;font-size:0.7rem;">'
                    f'sector median {median:.0f}{unit}</div>'
                    f'</div>'
                )
        if rank_html:
            st.markdown(f'<div style="margin:10px 0 14px;">{rank_html}</div>',
                        unsafe_allow_html=True)
        _render_section_items(moat["items"])

    # ── TAB 2: Financial Fortress ─────────────────────────────────────────────
    with t2:
        st.markdown(f"#### Financial Fortress — {fortress['score']}/{fortress['max']} pts")

        col_f, col_z = st.columns(2)

        with col_f:
            f_score = fortress.get("piotroski_score", 0)
            f_color = "#2ecc71" if f_score >= 7 else "#f39c12" if f_score >= 4 else "#e74c3c"
            st.markdown(
                f'<div style="background:#1a1a2e;border:1px solid {_hex_rgba(f_color,0.4)};'
                f'border-radius:8px;padding:14px;text-align:center;margin-bottom:12px;">'
                f'<div style="color:#888;font-size:0.7rem;font-weight:700;letter-spacing:.06em;'
                f'text-transform:uppercase;">Piotroski F-Score</div>'
                f'<div style="color:{f_color};font-size:2.5rem;font-weight:800;">'
                f'{f_score}<span style="font-size:1rem;color:#555;">/9</span></div>'
                f'<div style="color:{f_color};font-size:0.8rem;">'
                f'{"Strong 🟢" if f_score >= 7 else "Neutral 🟡" if f_score >= 4 else "Weak 🔴"}'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            st.caption("9 binary signals across profitability, leverage, operating efficiency. "
                       "F ≥ 7 = strengthening fundamentals; F ≤ 3 = deteriorating.")
            for sig in fortress.get("piotroski_signals", []):
                icon = "✅" if sig["pass"] is True else ("❌" if sig["pass"] is False else "⬜")
                st.markdown(
                    f'<div style="padding:4px 8px;border-bottom:1px solid #1e1e2e;font-size:0.82rem;">'
                    f'{icon} <span style="color:#ccc;">{sig["name"]}</span>'
                    f'<span style="color:#666;font-size:0.75rem;float:right;">{sig["detail"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        with col_z:
            z_val  = fortress.get("altman_z")
            z_zone = fortress.get("altman_zone", "N/A")
            z_color = "#2ecc71" if (z_val and z_val > 2.99) else "#f39c12" if (z_val and z_val > 1.81) else "#e74c3c"
            st.markdown(
                f'<div style="background:#1a1a2e;border:1px solid {_hex_rgba(z_color,0.4)};'
                f'border-radius:8px;padding:14px;text-align:center;margin-bottom:12px;">'
                f'<div style="color:#888;font-size:0.7rem;font-weight:700;letter-spacing:.06em;'
                f'text-transform:uppercase;">Altman Z-Score</div>'
                f'<div style="color:{z_color};font-size:2.5rem;font-weight:800;">'
                f'{f"{z_val:.2f}" if z_val else "N/A"}</div>'
                f'<div style="color:{z_color};font-size:0.8rem;">{z_zone}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "Bankruptcy risk indicator. "
                "> 2.99: Safe zone. 1.81–2.99: Grey zone. < 1.81: Distress. "
                "Note: less reliable for financial/REIT sectors."
            )
            for item in fortress["items"]:
                if "Altman" not in item["name"] and "Piotroski" not in item["name"]:
                    _render_section_items([item])

    # ── TAB 3: Valuation & DCF ────────────────────────────────────────────────
    with t3:
        st.markdown(f"#### Valuation & DCF — {valuation['score']}/{valuation['max']} pts")
        st.caption(
            "A great company is only a great investment at the right price. "
            "P/E is benchmarked against the sector median. FCF Yield is Buffett's "
            "preferred metric. Owner Earnings DCF estimates intrinsic value per share."
        )
        _render_section_items(valuation["items"])

        st.markdown("---")
        st.markdown("##### 📐 Owner Earnings DCF — Intrinsic Value Estimate")

        # ── DCF controls row ───────────────────────────────────────────────────
        # Sector-default maintenance CapEx fractions
        _sector_maint_default = {
            "Utilities": 0.85, "Energy": 0.80, "Industrials": 0.75,
            "Basic Materials": 0.75, "Materials": 0.75,
            "Consumer Defensive": 0.65, "Consumer Staples": 0.65,
            "Healthcare": 0.60, "Consumer Cyclical": 0.60, "Financial Services": 0.55,
            "Communication Services": 0.55, "Real Estate": 0.70,
            "Technology": 0.40, "Software—Application": 0.30,
        }
        _maint_default = _sector_maint_default.get(sector, 0.60)

        dcf_ctrl1, dcf_ctrl2, dcf_ctrl3 = st.columns([3, 2, 2])
        with dcf_ctrl1:
            maint_pct = st.select_slider(
                "Maintenance CapEx %",
                options=[0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00],
                value=_maint_default,
                format_func=lambda v: f"{int(v*100)}%",
                key="dcf_maint_capex",
                help=(
                    "What % of CapEx is 'maintenance' vs 'growth'? "
                    "Only maintenance CapEx reduces Owner Earnings. "
                    f"Sector default for {sector}: {int(_maint_default*100)}%"
                ),
            )
        with dcf_ctrl2:
            capex_mode = ("Conservative (all CapEx)" if maint_pct == 1.0
                          else "Growth-adjusted" if maint_pct < 0.60 else "Standard")
            st.markdown(
                f'<div style="background:#161b27;border:1px solid #333;border-radius:6px;'
                f'padding:10px 14px;margin-top:4px;">'
                f'<div style="color:#888;font-size:0.68rem;text-transform:uppercase;">Mode</div>'
                f'<div style="color:#3498db;font-weight:700;font-size:0.9rem;">{capex_mode}</div>'
                f'<div style="color:#666;font-size:0.72rem;">Growth CapEx excluded: '
                f'{int((1-maint_pct)*100)}% of total CapEx</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with dcf_ctrl3:
            # SBC toggle — default ON (institutional standard)
            sbc_amount = _get_sbc(raw.get("cashflow"))
            sbc_label  = (
                f"SBC ${sbc_amount/1e9:.2f}B" if sbc_amount and sbc_amount > 1e8
                else f"SBC ${sbc_amount/1e6:.0f}M" if sbc_amount
                else "SBC (no data)"
            )
            deduct_sbc = st.toggle(
                f"Deduct {sbc_label}",
                value=True,
                key="dcf_deduct_sbc",
                help=(
                    "Stock-Based Compensation is a real cost to shareholders — it dilutes ownership "
                    "even though it doesn't appear in GAAP cash flow. "
                    "Toggle OFF to see the traditional Buffett OE (pre-SBC awareness)."
                ),
            )
            sbc_note = (
                f'<div style="color:#{"e74c3c" if deduct_sbc and sbc_amount else "555"};'
                f'font-size:0.7rem;margin-top:4px;">'
                + (f"−{sbc_label} deducted" if deduct_sbc and sbc_amount
                   else "SBC not deducted" if not deduct_sbc
                   else "No SBC data")
                + '</div>'
            )
            st.markdown(sbc_note, unsafe_allow_html=True)

        # Recompute DCF with selected settings
        oe_adj, iv_adj = _owner_earnings_dcf(
            raw.get("financials"), raw.get("cashflow"),
            info, maint_capex_pct=maint_pct, deduct_sbc=deduct_sbc,
        )
        cp_adj  = _sf(info.get("currentPrice") or info.get("regularMarketPrice"))
        mos_adj = ((iv_adj - cp_adj) / iv_adj * 100) if (iv_adj and cp_adj and iv_adj > 0) else None

        dcf_c1, dcf_c2, dcf_c3, dcf_c4 = st.columns(4)
        with dcf_c1:
            if oe_adj is not None:
                sbc_delta = (f"−SBC {sbc_label}" if deduct_sbc and sbc_amount
                             else f"Maint. CapEx {int(maint_pct*100)}%")
                st.metric("Owner Earnings",
                          f"${oe_adj/1e9:.2f}B" if abs(oe_adj) > 1e8 else f"${oe_adj/1e6:.0f}M",
                          delta=sbc_delta)
            else:
                st.metric("Owner Earnings", "N/A")
        with dcf_c2:
            if sbc_amount:
                sbc_pct_rev = None
                rev_row = None
                try:
                    fin_df = raw.get("financials")
                    if fin_df is not None and not fin_df.empty:
                        rev_row = fin_df.loc[[i for i in fin_df.index
                                              if "revenue" in str(i).lower()][0]]
                        rev_val = float(rev_row.iloc[0])
                        sbc_pct_rev = sbc_amount / rev_val * 100 if rev_val > 0 else None
                except Exception:
                    pass
                sbc_display = (f"${sbc_amount/1e9:.2f}B" if sbc_amount > 1e8
                               else f"${sbc_amount/1e6:.0f}M")
                st.metric("SBC (annual)",
                          sbc_display,
                          delta=f"{sbc_pct_rev:.1f}% of revenue" if sbc_pct_rev else "of revenue",
                          delta_color="inverse" if sbc_amount and sbc_amount > 0 else "off")
            else:
                st.metric("SBC (annual)", "N/A")
        with dcf_c3:
            st.metric("DCF Intrinsic Value / Share", f"${iv_adj:.2f}" if iv_adj else "N/A")
        with dcf_c4:
            if mos_adj is not None:
                st.metric("Margin of Safety", f"{mos_adj:.0f}%",
                          delta="Undervalued" if mos_adj > 0 else "Overvalued",
                          delta_color="normal" if mos_adj > 0 else "inverse")
            else:
                st.metric("Margin of Safety", "N/A")

        st.caption(
            "Buffett's 1986 definition: OE = Net Income + D&A − Maintenance CapEx. "
            "**SBC toggle** (default ON): subtracts stock-based comp — a real dilution cost "
            "omitted from GAAP cash flow. Projected 10 years (8% growth yr 1–5, 4% yr 6–10), "
            "discounted at 10%. Terminal value at 3% perpetuity. "
            "⚠️ Directional guide only — highly sensitive to growth assumptions."
        )
        if not (iv_adj and cp_adj):
            st.info("Insufficient data to compute DCF. "
                    "Check that the company has positive net income and CapEx on yfinance.", icon="ℹ️")

    # ── TAB 4: Momentum ───────────────────────────────────────────────────────
    with t4:
        st.markdown(f"#### Momentum & Trend — {momentum['score']}/{momentum['max']} pts")
        st.caption(
            "Addresses the 'value trap' problem: a fundamentally strong company in a "
            "sustained downtrend may be experiencing structural deterioration. "
            "The 200-day MA is a useful filter for avoiding falling knives."
        )
        _render_section_items(momentum["items"])

        hist = raw.get("history", pd.DataFrame())
        if not hist.empty and len(hist) >= 60:
            close        = hist["Close"]
            ma200_series = close.rolling(200).mean()
            ma50_series  = close.rolling(50).mean()

            fig_p = go.Figure()
            fig_p.add_trace(go.Scatter(
                x=close.index, y=close.values,
                name="Price", line={"color": "#3498db", "width": 1.5},
                hovertemplate="%{x|%b %Y}: $%{y:.2f}<extra></extra>",
            ))
            fig_p.add_trace(go.Scatter(
                x=ma200_series.index, y=ma200_series.values,
                name="200-day MA", line={"color": "#e74c3c", "width": 2},
                hovertemplate="200MA: $%{y:.2f}<extra></extra>",
            ))
            fig_p.add_trace(go.Scatter(
                x=ma50_series.index, y=ma50_series.values,
                name="50-day MA", line={"color": "#f39c12", "width": 1.5, "dash": "dot"},
                hovertemplate="50MA: $%{y:.2f}<extra></extra>",
            ))
            fig_p = dark_layout(fig_p, yaxis_title="Price (USD)")
            fig_p.update_layout(
                height=360,
                title=dict(text=f"{ticker_input} — Price vs Moving Averages (2Y)",
                           font=dict(size=13, color="#ccc")),
                legend={"orientation": "h", "y": -0.2},
            )
            st.plotly_chart(fig_p, use_container_width=True, key="stock_score_price_chart")

    # ── TAB 5: Shareholder Alignment ──────────────────────────────────────────
    with t5:
        st.markdown(f"#### Shareholder Alignment — {shareholder['score']}/{shareholder['max']} pts")
        st.caption(
            "Buffett: management quality is revealed by capital allocation. "
            "Buybacks at fair prices are the single best use of excess capital. "
            "A declining share count is one of the strongest signals of a "
            "shareholder-friendly team."
        )
        _render_section_items(shareholder["items"])

        bs     = raw.get("balance_sheet")
        sh_row = None
        if bs is not None:
            for col_name in ["Ordinary Shares Number", "Share Issued",
                             "Common Stock Shares Outstanding"]:
                try:
                    idx_lower = {str(i).lower(): i for i in bs.index}
                    if col_name.lower() in idx_lower:
                        sh_row = bs.loc[idx_lower[col_name.lower()]]
                        break
                except Exception:
                    pass

        if sh_row is not None:
            sh_data = sh_row.dropna()
            if len(sh_data) >= 2:
                sh_df = pd.DataFrame({
                    "Year": [str(d.year) for d in sh_data.index[::-1]],
                    "Shares (B)": [float(v) / 1e9 for v in sh_data.values[::-1]],
                })
                fig_sh = go.Figure()
                fig_sh.add_trace(go.Bar(
                    x=sh_df["Year"], y=sh_df["Shares (B)"],
                    marker_color=[
                        "#2ecc71" if i == 0 or sh_df["Shares (B)"].iloc[i] <= sh_df["Shares (B)"].iloc[i - 1]
                        else "#e74c3c"
                        for i in range(len(sh_df))
                    ],
                    hovertemplate="<b>%{x}</b>: %{y:.3f}B shares<extra></extra>",
                    name="Shares Outstanding",
                ))
                fig_sh = dark_layout(fig_sh, yaxis_title="Shares Outstanding (B)")
                fig_sh.update_layout(
                    height=280,
                    title=dict(text="Shares Outstanding — Annual Trend",
                               font=dict(size=13, color="#ccc")),
                )
                st.plotly_chart(fig_sh, use_container_width=True, key="stock_score_shares_chart")
                st.caption("Green bars = share count fell or held flat (buybacks/neutral). "
                           "Red bars = share count rose (dilution).")

    # ── Bottom Line verdict ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### ⚡ Bottom Line")

    if total >= 75:
        verdict_title = "STRONG BUY CANDIDATE"
        verdict_color = "#2ecc71"
        verdict_body  = (
            f"{long_name} scores {total}/100 — clearing the bar for exceptional quality. "
            "Wide moat fundamentals, strong financial health, and reasonable valuation all align. "
            "Conduct deeper qualitative research on the durability of the competitive advantage."
        )
    elif total >= 60:
        verdict_title = "WORTH DEEPER ANALYSIS"
        verdict_color = "#27ae60"
        verdict_body  = (
            f"{long_name} scores {total}/100. Strong across most dimensions with some weaknesses. "
            "Review the failing checks above — are they structural or cyclical?"
        )
    elif total >= 45:
        verdict_title = "PROCEED WITH CAUTION"
        verdict_color = "#f1c40f"
        verdict_body  = (
            f"{long_name} scores {total}/100. Passes some key tests but shows meaningful weaknesses. "
            "Consider whether a lower entry price (higher margin of safety) compensates."
        )
    elif total >= 30:
        verdict_title = "SIGNIFICANT RED FLAGS"
        verdict_color = "#e67e22"
        verdict_body  = (
            f"{long_name} scores {total}/100. Multiple fundamental weaknesses present. "
            "Does not meet Buffett's quality threshold as currently measured."
        )
    else:
        verdict_title = "DOES NOT PASS SCREEN"
        verdict_color = "#e74c3c"
        verdict_body  = (
            f"{long_name} scores {total}/100 — failing across most Buffett criteria. "
            "Buffett: 'It's far better to buy a wonderful company at a fair price "
            "than a fair company at a wonderful price.'"
        )

    st.markdown(
        f"""
        <div style="background:{_hex_rgba(verdict_color, 0.10)};
                    border:2px solid {_hex_rgba(verdict_color, 0.65)};
                    border-left:6px solid {verdict_color};
                    border-radius:10px;padding:20px 24px;margin:8px 0 20px;">
          <div style="color:#888;font-size:0.7rem;font-weight:700;letter-spacing:.09em;
                      text-transform:uppercase;margin-bottom:8px;">
            Buffett Score Verdict — {long_name}
          </div>
          <div style="color:{verdict_color};font-size:1.55rem;font-weight:800;
                      margin-bottom:10px;line-height:1.1;">
            {verdict_title}
          </div>
          <div style="color:#e0e0e0;font-size:0.9rem;line-height:1.65;max-width:820px;">
            {verdict_body}
          </div>
          <div style="margin-top:12px;padding-top:10px;border-top:1px solid {_hex_rgba(verdict_color, 0.25)};
                      display:flex;gap:24px;font-size:0.75rem;color:#888;flex-wrap:wrap;">
            <span>Score <strong style="color:{verdict_color};">{total}/100</strong></span>
            <span>Moat <strong style="color:{_score_color(int(moat['score']/moat['max']*100))};">{moat['score']}/{moat['max']}</strong></span>
            <span>Fortress <strong style="color:{_score_color(int(fortress['score']/fortress['max']*100))};">{fortress['score']}/{fortress['max']}</strong></span>
            <span>Valuation <strong style="color:{_score_color(int(valuation['score']/valuation['max']*100))};">{valuation['score']}/{valuation['max']}</strong></span>
            <span>Momentum <strong style="color:{_score_color(int(momentum['score']/momentum['max']*100))};">{momentum['score']}/{momentum['max']}</strong></span>
            <span>Shareholder <strong style="color:{_score_color(int(shareholder['score']/shareholder['max']*100))};">{shareholder['score']}/{shareholder['max']}</strong></span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ── Link to Screener ───────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    """
<div style="background:#161b27;border:1px solid #2a2a4a;border-radius:8px;
            padding:16px 20px;display:flex;align-items:center;gap:16px;">
  <div style="font-size:2rem;">🏆</div>
  <div>
    <div style="color:#fff;font-weight:700;font-size:0.95rem;margin-bottom:3px;">
      Want to find the best-ranked stocks?
    </div>
    <div style="color:#888;font-size:0.82rem;">
      The <strong style="color:#3498db;">Buffett Stock Screener</strong> scores ~80 US large-caps
      on this same framework and ranks them — with an optional macro-regime overlay.
      Navigate using the sidebar → <em>🏆 Stock Screener</em>.
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown("")
st.caption(DISCLAIMER)
