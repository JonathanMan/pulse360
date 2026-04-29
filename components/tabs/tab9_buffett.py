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


def _months_since_breach(ratio: pd.Series, threshold: float) -> tuple[int, pd.Timestamp] | None:
    """
    If the indicator is currently at or above `threshold`, find the quarter when
    the most recent continuous run above that level started and return
    (months_elapsed_since_breach, breach_date).
    Returns None if the indicator is currently below `threshold`.
    """
    if float(ratio.iloc[-1]) < threshold:
        return None

    # Walk backwards to find the last time ratio dipped below threshold
    breach_idx = 0
    for i in range(len(ratio) - 1, -1, -1):
        if float(ratio.iloc[i]) < threshold:
            breach_idx = i + 1
            break

    breach_date = ratio.index[breach_idx]
    today       = pd.Timestamp.today()
    months      = (today.year - breach_date.year) * 12 + (today.month - breach_date.month)
    return months, breach_date


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


_ZONE_ORDER = [
    "Significantly Undervalued",
    "Modestly Undervalued",
    "Fair Value",
    "Modestly Overvalued",
    "Overvalued",
    "Significantly Overvalued",
]
_ZONE_COLORS = {z: c for _, _, z, c in _ZONES}

_ZONE_RANGES = {
    "Significantly Undervalued": "< 75%",
    "Modestly Undervalued":      "75–100%",
    "Fair Value":                "100–115%",
    "Modestly Overvalued":       "115–135%",
    "Overvalued":                "135–165%",
    "Significantly Overvalued":  "> 165%",
}

# Hardcoded historical overvaluation anchors (context beyond FRED data window)
_HIST_SELL_ANCHORS = [
    {"Period": "1968–1970",  "Peak BI": "~105%", "S&P Drawdown": "−36%",
     "Context": "Go-Go era. Vietnam war spending. Fed tightening cycle."},
    {"Period": "1972–1974",  "Peak BI": "~107%", "S&P Drawdown": "−48%",
     "Context": "Nifty Fifty bubble. OPEC oil shock. Stagflation."},
    {"Period": "1999–2002",  "Peak BI": "~183%", "S&P Drawdown": "−49%",
     "Context": "Dot-com bubble peak. NASDAQ fell −78%. Record BI at the time."},
    {"Period": "2007–2009",  "Peak BI": "~115%", "S&P Drawdown": "−57%",
     "Context": "Pre-GFC. Housing collapse, Lehman. Lower BI, deeper damage."},
    {"Period": "2021–2022",  "Peak BI": "~215%", "S&P Drawdown": "−25%",
     "Context": "Post-COVID bubble. Fed pivot QE→QT. Rate shock repricing."},
]

# Hardcoded historical buy anchors (great entry points across full history)
_HIST_BUY_ANCHORS = [
    {"Date": "Dec 1974", "BI Level": "~37%",  "Fwd 1Y": "+37%", "Fwd 3Y": "+56%",  "Fwd 5Y": "+86%",
     "Context": "Post-OPEC crash. Market at 37% of GDP. Stagflation trough."},
    {"Date": "Aug 1982", "BI Level": "~33%",  "Fwd 1Y": "+63%", "Fwd 3Y": "+99%",  "Fwd 5Y": "+183%",
     "Context": "Volcker rate peak. S&P 500 began 18-year bull run."},
    {"Date": "Mar 2009", "BI Level": "~57%",  "Fwd 1Y": "+68%", "Fwd 3Y": "+87%",  "Fwd 5Y": "+178%",
     "Context": "GFC trough. NCBEILQ027S hit multi-decade low vs. GDP."},
    {"Date": "Mar 2020", "BI Level": "~140%", "Fwd 1Y": "+75%", "Fwd 3Y": "+34%",  "Fwd 5Y": "N/A",
     "Context": "COVID crash. Not in classic buy zone but recovery speed was exceptional."},
]


def _dca_analysis(ratio: pd.Series, sp_monthly: pd.Series) -> pd.DataFrame:
    """
    For every quarterly Buffett Indicator observation, simulate:
      - Monthly DCA: invest $1 each month for 12 / 36 / 60 months, measure
        annualised return on total capital deployed.
      - Lump Sum: invest everything at t=0, measure return at end of horizon.

    Returns one row per quarter with columns:
      date, buffett_pct, zone,
      dca_1Y, lump_1Y,
      dca_3Y, lump_3Y,
      dca_5Y, lump_5Y
    """
    records: list[dict] = []
    for dt, bval in ratio.items():
        sp_t = sp_monthly.asof(dt)
        if pd.isna(sp_t) or sp_t <= 0:
            continue
        zone_label, _ = _get_zone(float(bval))
        row: dict = {"date": dt, "buffett_pct": round(float(bval), 1), "zone": zone_label}

        for months, col in [(12, "1Y"), (36, "3Y"), (60, "5Y")]:
            # Gather monthly prices inside the DCA window
            prices = []
            for m in range(1, months + 1):
                p = sp_monthly.asof(dt + pd.DateOffset(months=m))
                if not pd.isna(p) and p > 0:
                    prices.append(float(p))

            # Require ≥ 80 % of months to be present
            if len(prices) < months * 0.8:
                row[f"dca_{col}"]  = None
                row[f"lump_{col}"] = None
                continue

            final_price = prices[-1]
            n = len(prices)

            # DCA: invest $1/month → total invested = n, shares = Σ(1/price_i)
            shares    = sum(1.0 / p for p in prices)
            dca_ret   = (shares * final_price / n - 1) * 100

            # Lump sum: invest n dollars at t=0
            lump_ret  = (final_price / sp_t - 1) * 100

            row[f"dca_{col}"]  = round(dca_ret,  1)
            row[f"lump_{col}"] = round(lump_ret, 1)

        records.append(row)

    cols = ["date", "buffett_pct", "zone",
            "dca_1Y", "lump_1Y", "dca_3Y", "lump_3Y", "dca_5Y", "lump_5Y"]
    return pd.DataFrame(records) if records else pd.DataFrame(columns=cols)


def _entry_exit_analysis(
    ratio:     pd.Series,
    sp_monthly: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Returns three DataFrames:
      fwd_df  — one row per Buffett quarter with 1Y/3Y/5Y forward S&P 500 returns
      buy_df  — trough of each episode where ratio < 100% (best historical entry points)
      sell_df — first crossing above 135% per overvaluation episode (sell signals)
    """
    # ── Forward returns for every quarterly observation ───────────────────────
    records: list[dict] = []
    for dt, bval in ratio.items():
        sp_t = sp_monthly.asof(dt)
        if pd.isna(sp_t) or sp_t <= 0:
            continue
        zone_label, _ = _get_zone(float(bval))
        row: dict = {"date": dt, "buffett_pct": round(float(bval), 1), "zone": zone_label}
        for col, months in [("1Y", 12), ("3Y", 36), ("5Y", 60)]:
            sp_f = sp_monthly.asof(dt + pd.DateOffset(months=months))
            row[col] = round((sp_f / sp_t - 1) * 100, 1) if (not pd.isna(sp_f) and sp_f > 0) else None
        records.append(row)

    fwd_df = pd.DataFrame(records) if records else pd.DataFrame(
        columns=["date", "buffett_pct", "zone", "1Y", "3Y", "5Y"]
    )

    # ── Buy episodes: trough of each run below 100% ───────────────────────────
    buy_records: list[dict] = []
    in_buy   = False
    episode: list[dict] = []
    for _, row in fwd_df.iterrows():
        if row["buffett_pct"] < 100:
            in_buy = True
            episode.append(row.to_dict())
        elif in_buy:
            buy_records.append(min(episode, key=lambda r: r["buffett_pct"]))
            episode = []
            in_buy  = False
    if in_buy and episode:
        buy_records.append(min(episode, key=lambda r: r["buffett_pct"]))
    buy_df = pd.DataFrame(buy_records) if buy_records else pd.DataFrame(
        columns=["date", "buffett_pct", "zone", "1Y", "3Y", "5Y"]
    )

    # ── Sell episodes: first crossing above 135% per episode ─────────────────
    sell_records: list[dict] = []
    armed = True
    for _, row in fwd_df.iterrows():
        if armed and row["buffett_pct"] >= 135:
            sell_records.append(row.to_dict())
            armed = False
        if not armed and row["buffett_pct"] < 120:
            armed = True
    sell_df = pd.DataFrame(sell_records) if sell_records else pd.DataFrame(
        columns=["date", "buffett_pct", "zone", "1Y", "3Y", "5Y"]
    )

    return fwd_df, buy_df, sell_df


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
    # NCBEILQ027S is in MILLIONS USD; GDP in BILLIONS USD; SP500 daily → resampled monthly
    with st.spinner("Loading economic data…"):
        wilshire  = fetch_series("NCBEILQ027S", start_date="1945-01-01")
        gdp       = fetch_series("GDP",         start_date="1945-01-01")
        sp_result = fetch_series("SP500",       start_date="1950-01-01")

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

    # Pre-compute SP500 monthly early so it's available anywhere on the page
    sp_monthly = (
        sp_result["data"].resample("ME").last().dropna()
        if not sp_result["data"].empty else pd.Series(dtype=float)
    )

    current_ratio  = float(ratio.iloc[-1])
    hist_mean      = float(ratio.mean())
    hist_pct       = float((ratio < current_ratio).mean() * 100)
    premium        = current_ratio - hist_mean
    zone_label, zone_color = _get_zone(current_ratio)

    # ── Time window selector ──────────────────────────────────────────────────
    _TW_OPTIONS = ["10Y", "20Y", "30Y", "50Y", "All"]
    _tw_col, _ = st.columns([3, 5])
    with _tw_col:
        tw_choice = st.radio(
            "Time window",
            options=_TW_OPTIONS,
            index=2,                      # default: 30Y
            horizontal=True,
            key="tab9_time_window",
            label_visibility="collapsed",
            help="Adjust the x-axis range across all charts on this page",
        )
    _today = pd.Timestamp.today()
    _offsets = {"10Y": 10, "20Y": 20, "30Y": 30, "50Y": 50}
    x_start = (
        str((_today - pd.DateOffset(years=_offsets[tw_choice])).date())
        if tw_choice != "All" else "1945-01-01"
    )
    x_end   = str(_today.date())
    x_range = [x_start, x_end]

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

    # ── Breach clock — months above 165% ─────────────────────────────────────
    breach_165 = _months_since_breach(ratio, 165.0)
    if breach_165 is not None:
        breach_months, breach_date = breach_165
        # Historical average lag at 165% (hard to compute here without corrections data,
        # so we display the raw month count with context)
        st.markdown(
            f"""
            <div style="
                display:flex; align-items:center; gap:18px;
                background: rgba(192,57,43,0.12);
                border: 2px solid rgba(192,57,43,0.55);
                border-radius:10px; padding:14px 20px; margin:10px 0 16px;
            ">
                <div style="font-size:2.4rem; line-height:1;">🕐</div>
                <div>
                    <div style="color:#e74c3c; font-size:0.75rem; font-weight:700;
                                letter-spacing:.08em; text-transform:uppercase; margin-bottom:4px;">
                        Currently Above 165% Threshold
                    </div>
                    <div style="color:#ffffff; font-size:1.05rem; line-height:1.5;">
                        The Buffett Indicator has been in <strong style="color:#e74c3c;">
                        Significantly Overvalued</strong> territory for
                        <strong style="color:#ffffff; font-size:1.35rem;">
                        &nbsp;{breach_months}&nbsp;months</strong>
                        &nbsp;— since <strong>{breach_date.strftime("%b %Y")}</strong>.
                    </div>
                    <div style="color:#aaa; font-size:0.8rem; margin-top:6px;">
                        Historically, a ≥10% correction has followed a 165% breach by an average
                        of ~6–18 months. See the lag table below for full historical episodes.
                    </div>
                </div>
            </div>
            """,
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

    # ══════════════════════════════════════════════════════════════════════════
    # ENTRY & EXIT FRAMEWORK — rebuilt: multi-factor, statistically robust
    # ══════════════════════════════════════════════════════════════════════════

    st.markdown("### 📊 Entry & Exit Framework")
    st.caption(
        "A statistically robust, multi-factor framework. "
        "Composite Score (0–100) blends Buffett Indicator (40pts), recession probability (35pts), "
        "and yield-curve / financial conditions (25pts). "
        "The Risk/Reward Matrix shows median S&P 500 returns and probability of a positive return "
        "across all six valuation zones. Historical anchors included where FRED data is limited."
    )

    # ── Component 1 — Buffett Indicator (40 pts max) ──────────────────────────
    if current_ratio < 75:
        bi_pts, bi_signal, bi_color = 40, "Significantly Undervalued", "#2ecc71"
    elif current_ratio < 100:
        bi_pts, bi_signal, bi_color = 32, "Modestly Undervalued",      "#27ae60"
    elif current_ratio < 115:
        bi_pts, bi_signal, bi_color = 22, "Fair Value",                "#f1c40f"
    elif current_ratio < 135:
        bi_pts, bi_signal, bi_color = 14, "Neutral / Modestly OV",     "#e67e22"
    elif current_ratio < 165:
        bi_pts, bi_signal, bi_color =  6, "Overvalued",                "#e74c3c"
    else:
        bi_pts, bi_signal, bi_color =  0, "Significantly Overvalued",  "#c0392b"

    # ── Component 2 — Recession Probability (35 pts max) ─────────────────────
    rec_prob = model_output.probability
    if rec_prob < 5:
        rp_pts, rp_signal, rp_color = 35, "Very Low",  "#2ecc71"
    elif rec_prob < 15:
        rp_pts, rp_signal, rp_color = 25, "Low",       "#27ae60"
    elif rec_prob < 30:
        rp_pts, rp_signal, rp_color = 15, "Moderate",  "#f39c12"
    elif rec_prob < 50:
        rp_pts, rp_signal, rp_color =  7, "Elevated",  "#e67e22"
    else:
        rp_pts, rp_signal, rp_color =  0, "High",      "#e74c3c"

    # ── Component 3 — Yield Curve / Financial Conditions (25 pts max) ────────
    yc_val: float | None = None
    yc_label = "Fin. Conditions"
    try:
        for f in model_output.features:
            sid = (
                str(getattr(f, "series_id", ""))
                if not isinstance(f, dict)
                else str(f.get("series_id", ""))
            )
            if "T10Y2Y" in sid or "T10Y3M" in sid:
                raw = (
                    getattr(f, "value", None)
                    if not isinstance(f, dict)
                    else f.get("value")
                )
                if raw is not None:
                    yc_val  = float(raw)
                    yc_label = "10Y–2Y Spread"
                    break
    except Exception:
        pass

    if yc_val is not None:
        if yc_val > 1.0:
            yc_pts, yc_sig, yc_color = 25, f"+{yc_val:.2f}pp Steep",      "#2ecc71"
        elif yc_val > 0.0:
            yc_pts, yc_sig, yc_color = 17, f"+{yc_val:.2f}pp Flat",       "#f1c40f"
        elif yc_val > -0.5:
            yc_pts, yc_sig, yc_color =  8, f"{yc_val:.2f}pp Inverted",    "#e67e22"
        else:
            yc_pts, yc_sig, yc_color =  0, f"{yc_val:.2f}pp Deep Inv.",   "#e74c3c"
    else:
        tl = model_output.traffic_light
        if tl == "green":
            yc_pts, yc_sig, yc_color = 25, "Green",  "#2ecc71"
        elif tl == "yellow":
            yc_pts, yc_sig, yc_color = 12, "Yellow", "#f39c12"
        else:
            yc_pts, yc_sig, yc_color =  0, "Red",    "#e74c3c"

    composite_score = bi_pts + rp_pts + yc_pts  # 0–100

    if composite_score >= 70:
        cs_label, cs_color = "Strong Buy Environment", "#2ecc71"
        cs_action = "Macro backdrop supports equity overweight. Long-term entry conditions favourable."
    elif composite_score >= 55:
        cs_label, cs_color = "Broadly Favourable",     "#27ae60"
        cs_action = "Reasonable conditions for full strategic equity allocation."
    elif composite_score >= 40:
        cs_label, cs_color = "Neutral / Cautious",     "#f1c40f"
        cs_action = "Hold strategic allocation; avoid leverage; tilt toward quality."
    elif composite_score >= 25:
        cs_label, cs_color = "Elevated Risk",          "#e67e22"
        cs_action = "Reduce equity exposure; raise cash; increase quality and defensive tilt."
    else:
        cs_label, cs_color = "Strong Caution",         "#e74c3c"
        cs_action = "Defensive posture warranted. Buffett-style cash accumulation historically optimal."

    # ── Composite score card ───────────────────────────────────────────────────
    st.markdown(
        f"""
        <div style="background:#1a1a2e;border:2px solid {_hex_rgba(cs_color, 0.55)};
                    border-radius:12px;padding:18px 22px;margin-bottom:16px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;
                      flex-wrap:wrap;gap:16px;margin-bottom:14px;">
            <div>
              <div style="color:#888;font-size:0.7rem;font-weight:700;letter-spacing:.08em;
                          text-transform:uppercase;margin-bottom:6px;">Composite Macro Score</div>
              <div style="color:{cs_color};font-size:2.6rem;font-weight:800;line-height:1;">
                {composite_score}
                <span style="font-size:1rem;color:#555;font-weight:400;"> / 100</span>
              </div>
              <div style="color:{cs_color};font-size:1rem;font-weight:700;margin-top:5px;">
                {cs_label}
              </div>
              <div style="color:#aaa;font-size:0.78rem;margin-top:4px;max-width:320px;">
                {cs_action}
              </div>
            </div>
            <div style="font-size:0.8rem;line-height:2.1;padding-top:4px;">
              <div>
                <span style="color:#888;">⚖️ Buffett Indicator</span>
                &nbsp;<span style="color:{bi_color};font-weight:700;">{bi_pts}/40</span>
                &nbsp;<span style="color:#555;">{bi_signal} · {current_ratio:.1f}% of GDP</span>
              </div>
              <div>
                <span style="color:#888;">📉 Recession Probability</span>
                &nbsp;<span style="color:{rp_color};font-weight:700;">{rp_pts}/35</span>
                &nbsp;<span style="color:#555;">{rp_signal} · {rec_prob:.1f}%</span>
              </div>
              <div>
                <span style="color:#888;">📈 {yc_label}</span>
                &nbsp;<span style="color:{yc_color};font-weight:700;">{yc_pts}/25</span>
                &nbsp;<span style="color:#555;">{yc_sig}</span>
              </div>
            </div>
          </div>
          <div style="position:relative;margin-bottom:5px;">
            <div style="background:#0e1117;border-radius:6px;height:10px;overflow:hidden;">
              <div style="background:linear-gradient(90deg,#c0392b 0%,#e74c3c 15%,
                          #e67e22 28%,#f39c12 42%,#f1c40f 55%,#27ae60 70%,#2ecc71 100%);
                          width:100%;height:100%;border-radius:6px;"></div>
            </div>
            <div style="position:absolute;top:-3px;left:{composite_score}%;
                        transform:translateX(-50%);height:16px;width:3px;
                        background:#fff;border-radius:2px;
                        box-shadow:0 0 6px rgba(255,255,255,.6);"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:0.65rem;color:#444;
                      margin-top:4px;">
            <span>0 — Caution</span><span>25</span>
            <span>50 — Neutral</span><span>75</span><span>100 — Buy</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Risk / Reward Matrix ───────────────────────────────────────────────────
    if not sp_monthly.empty:
        fwd_df, buy_df, sell_df = _entry_exit_analysis(ratio, sp_monthly)

        st.markdown("#### 🗺️ Risk / Reward Matrix")
        st.caption(
            "Each row = one valuation zone. Columns show median S&P 500 forward return and the "
            "probability of a positive return at 1Y, 3Y, and 5Y horizons, "
            "computed from all quarterly observations since 1950. "
            "The neutral zone (100–135%) is split into 'Fair Value' and 'Modestly Overvalued' "
            "to avoid the binary buy/sell framing. n = quarterly observations in that zone."
        )

        if not fwd_df.empty:
            def _ret_color(v: float | None) -> tuple[str, str]:
                if v is None:
                    return "#555", "—"
                txt = f"{v:+.1f}%"
                if v >= 20:   return "#2ecc71", txt
                if v >= 10:   return "#27ae60", txt
                if v >=  0:   return "#f1c40f", txt
                if v >= -10:  return "#e67e22", txt
                return "#e74c3c", txt

            def _prob_color(v: float | None) -> tuple[str, str]:
                if v is None:
                    return "#555", "—"
                txt = f"{v:.0f}%"
                if v >= 75:  return "#2ecc71", txt
                if v >= 60:  return "#27ae60", txt
                if v >= 50:  return "#f1c40f", txt
                if v >= 35:  return "#e67e22", txt
                return "#e74c3c", txt

            th = ("background:#1a1a2e;color:#aaa;font-size:0.72rem;font-weight:700;"
                  "letter-spacing:.04em;text-transform:uppercase;padding:7px 10px;"
                  "border-bottom:1px solid #333;white-space:nowrap;")
            th_r = th + "text-align:right;"
            th_l = th + "text-align:left;"
            td   = "padding:7px 10px;font-size:0.82rem;border-bottom:1px solid #1e1e2e;"

            rows_html = ""
            for zone in _ZONE_ORDER:
                z_color = _ZONE_COLORS.get(zone, "#888")
                rng     = _ZONE_RANGES.get(zone, "")
                mask    = fwd_df["zone"] == zone
                n       = int(mask.sum())
                if n < 2:
                    continue
                sub = fwd_df[mask]
                cells = (
                    f'<td style="{td}text-align:left;">'
                    f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
                    f'background:{z_color};margin-right:6px;vertical-align:middle;"></span>'
                    f'<span style="color:#fff;font-weight:600;">{zone}</span></td>'
                    f'<td style="{td}color:#aaa;">{rng}</td>'
                    f'<td style="{td}color:#888;text-align:right;">{n}</td>'
                )
                for col in ["1Y", "3Y", "5Y"]:
                    vals = sub[col].dropna()
                    med  = float(round(vals.median(), 1)) if len(vals) >= 2 else None
                    prob = float(round((vals > 0).mean() * 100, 0)) if len(vals) >= 2 else None
                    rc, rv = _ret_color(med)
                    pc, pv = _prob_color(prob)
                    cells += (
                        f'<td style="{td}color:{rc};font-weight:600;text-align:right;">{rv}</td>'
                        f'<td style="{td}color:{pc};text-align:right;">{pv}</td>'
                    )
                rows_html += f"<tr>{cells}</tr>"

            st.markdown(
                f"""
                <div style="overflow-x:auto;margin:8px 0 4px;">
                  <table style="width:100%;border-collapse:collapse;background:#0e1117;
                                border-radius:8px;overflow:hidden;">
                    <thead><tr>
                      <th style="{th_l}">Zone</th>
                      <th style="{th_l}">BI Range</th>
                      <th style="{th_r}">n</th>
                      <th style="{th_r}">1Y Med</th><th style="{th_r}">1Y P(+)</th>
                      <th style="{th_r}">3Y Med</th><th style="{th_r}">3Y P(+)</th>
                      <th style="{th_r}">5Y Med</th><th style="{th_r}">5Y P(+)</th>
                    </tr></thead>
                    <tbody>{rows_html}</tbody>
                  </table>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(
                "Med = median S&P 500 total return from signal date. "
                "P(+) = % of observations where forward return was positive. "
                "Zones with fewer than 2 observations are hidden."
            )

        # ── Sell Signals ───────────────────────────────────────────────────────
        st.markdown("#### 🔴 Historical Sell Signals — When to Reduce Equity")
        st.caption(
            "FRED-computed sell signals (first crossing of 135% per overvaluation episode) plus "
            "well-documented historical anchors for context. "
            "Sell signals are rare — the Buffett Indicator is a long-cycle tool, not a market timer."
        )

        sell_c1, sell_c2 = st.columns(2)

        with sell_c1:
            st.markdown("**📊 FRED Sell Signals (135%+ episode crossings)**")
            if not sell_df.empty:
                s1, s2, s3 = st.columns(3)
                s1.metric("Avg 1Y Return",
                          f"{sell_df['1Y'].dropna().mean():+.1f}%", delta_color="inverse")
                s2.metric("Avg 3Y Return",
                          f"{sell_df['3Y'].dropna().mean():+.1f}%", delta_color="inverse")
                s3.metric("Avg 5Y Return",
                          f"{sell_df['5Y'].dropna().mean():+.1f}%", delta_color="inverse")
                dsell = sell_df[["date", "buffett_pct", "1Y", "3Y", "5Y"]].copy()
                dsell["Date"]       = pd.to_datetime(dsell["date"]).dt.strftime("%b %Y")
                dsell["BI (% GDP)"] = dsell["buffett_pct"].map(lambda x: f"{x:.1f}%")
                for c in ["1Y", "3Y", "5Y"]:
                    dsell[c] = dsell[c].map(lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
                st.dataframe(
                    dsell[["Date", "BI (% GDP)", "1Y", "3Y", "5Y"]],
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info("No 135%+ episode crossings found in available FRED data.")

        with sell_c2:
            st.markdown("**📚 Historical Overvaluation Anchors**")
            st.caption(
                "Major documented episodes with approximate S&P 500 peak-trough drawdowns."
            )
            st.dataframe(
                pd.DataFrame(_HIST_SELL_ANCHORS),
                use_container_width=True, hide_index=True,
            )

        # ── Buy Signals ────────────────────────────────────────────────────────
        st.markdown("#### 🟢 Historical Buy Signals — Best Entry Points")
        st.caption(
            "FRED-computed buy signals (trough of each episode below 100%) plus hardcoded "
            "anchors for the great buying opportunities of 1974, 1982, and 2009 — "
            "periods that predate FRED coverage or the current data window."
        )

        buy_c1, buy_c2 = st.columns(2)

        with buy_c1:
            st.markdown("**📊 FRED Undervalued Troughs (<100% of GDP)**")
            if not buy_df.empty:
                b1, b2, b3 = st.columns(3)
                b1.metric("Avg 1Y Return", f"{buy_df['1Y'].dropna().mean():+.1f}%")
                b2.metric("Avg 3Y Return", f"{buy_df['3Y'].dropna().mean():+.1f}%")
                b3.metric("Avg 5Y Return", f"{buy_df['5Y'].dropna().mean():+.1f}%")
                dbuy = buy_df[["date", "buffett_pct", "1Y", "3Y", "5Y"]].copy()
                dbuy["Date"]       = pd.to_datetime(dbuy["date"]).dt.strftime("%b %Y")
                dbuy["BI (% GDP)"] = dbuy["buffett_pct"].map(lambda x: f"{x:.1f}%")
                for c in ["1Y", "3Y", "5Y"]:
                    dbuy[c] = dbuy[c].map(lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
                st.dataframe(
                    dbuy[["Date", "BI (% GDP)", "1Y", "3Y", "5Y"]],
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info(
                    "No undervalued episodes (<100%) in current FRED window. "
                    "See historical anchors for the great buying opportunities. →"
                )

        with buy_c2:
            st.markdown("**📚 Historical Buy Anchors (1950–present)**")
            st.caption("Approx. S&P 500 total returns from each signal date.")
            st.dataframe(
                pd.DataFrame(_HIST_BUY_ANCHORS),
                use_container_width=True, hide_index=True,
            )

        # ── Forward Return by Zone chart ───────────────────────────────────────
        if not fwd_df.empty:
            st.markdown("---")
            st.markdown("##### Median S&P 500 Forward Returns by Buffett Indicator Zone")
            st.caption(
                "Median return over the next 1, 3, and 5 years from each quarterly Buffett "
                "observation grouped by valuation zone. Shows the statistical decay in expected "
                "returns as valuations rise. Only zones with ≥3 observations included."
            )

            zone_stats = (
                fwd_df.groupby("zone")[["1Y", "3Y", "5Y"]]
                .median()
                .reindex([z for z in _ZONE_ORDER if z in fwd_df["zone"].unique()])
            )
            zone_counts = fwd_df.groupby("zone").size()
            zone_stats  = zone_stats[zone_counts[zone_stats.index] >= 3]

            if not zone_stats.empty:
                fig_z = go.Figure()
                for col, line_color in [("1Y", "#3498db"), ("3Y", "#9b59b6"), ("5Y", "#1abc9c")]:
                    if col not in zone_stats.columns:
                        continue
                    fig_z.add_trace(go.Bar(
                        name=f"{col} Median Return",
                        x=zone_stats.index.tolist(),
                        y=zone_stats[col].tolist(),
                        marker_color=[
                            _hex_rgba("#2ecc71", 0.85) if v >= 0 else _hex_rgba("#e74c3c", 0.85)
                            for v in zone_stats[col].tolist()
                        ],
                        marker_line_color=line_color,
                        marker_line_width=1.5,
                        hovertemplate=(
                            f"<b>%{{x}}</b><br>{col} median: <b>%{{y:+.1f}}%</b>"
                            "<extra></extra>"
                        ),
                    ))

                fig_z.add_hline(y=0, line_dash="dash", line_color="#555", line_width=1)
                fig_z = dark_layout(fig_z, yaxis_title="Median Forward Return (%)")
                fig_z.update_layout(
                    height=380, barmode="group",
                    xaxis={"tickangle": -20},
                    legend={"orientation": "h", "y": -0.28},
                )
                st.plotly_chart(fig_z, use_container_width=True, key="tab9_zone_returns")

    else:
        st.info("S&P 500 data unavailable — forward return analysis skipped.")

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
        yaxis ={"range": [0, min(300, max(ratio.values) * 1.15)]},
        xaxis ={"range": x_range},
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
    fig2.update_layout(height=300, xaxis={"range": x_range})
    st.plotly_chart(fig2, use_container_width=True, key="tab9_buffett_diverge")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    # CORRECTIONS OVERLAY + LAG ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════

    st.markdown("##### Buffett Indicator vs S&P 500")
    st.caption(
        "Left axis: Buffett Indicator (%) with valuation zone bands. "
        "Right axis: S&P 500 price (log scale). "
        "Red shading = corrections ≥10% from rolling 12-month high. "
        "Grey shading = NBER recessions."
    )

    if sp_result["data"].empty:
        st.warning("S&P 500 data unavailable — overlay skipped.")
    else:
        sp_monthly  = sp_result["data"].resample("ME").last().dropna()
        corrections = _find_sp500_corrections(sp_monthly, drawdown_threshold=-0.10)

        # ── Overlay chart ─────────────────────────────────────────────────────
        fig_c = go.Figure()

        # Valuation zone bands on left axis
        for lo, hi, label, color in _ZONES:
            fig_c.add_hrect(
                y0=lo, y1=min(hi, 300),
                fillcolor=_hex_rgba(color, 0.05),
                line_width=0, layer="below",
            )

        # S&P 500 correction shading — intensity scales with drawdown depth
        for c in corrections:
            depth     = abs(c["max_drawdown"])
            intensity = min(0.07 + depth * 0.5, 0.22)
            fig_c.add_vrect(
                x0=c["start"], x1=c["end"],
                fillcolor=f"rgba(231,76,60,{intensity:.2f})",
                line_width=0, layer="below",
            )
            if depth >= 0.15:
                fig_c.add_annotation(
                    x=c["trough_date"], y=float(ratio.max()) * 1.04,
                    text=f"-{depth:.0%}",
                    showarrow=False,
                    font={"color": "#e74c3c", "size": 8},
                    xanchor="center",
                    yref="y",
                )

        # Buffett Indicator — left y-axis (y)
        fig_c.add_trace(go.Scatter(
            x=ratio.index, y=ratio.values,
            mode="lines",
            line={"color": zone_color, "width": 2.5},
            name="Buffett Indicator (%)",
            yaxis="y",
            hovertemplate="%{x|%b %Y} — Buffett: <b>%{y:.1f}%</b><extra></extra>",
        ))

        # S&P 500 price — right y-axis (y2), log scale
        fig_c.add_trace(go.Scatter(
            x=sp_monthly.index, y=sp_monthly.values,
            mode="lines",
            line={"color": "#3498db", "width": 1.8, "dash": "dot"},
            name="S&P 500 (right axis)",
            yaxis="y2",
            opacity=0.85,
            hovertemplate="%{x|%b %Y} — S&P 500: <b>%{y:,.0f}</b><extra></extra>",
        ))

        # Historical mean line
        fig_c.add_hline(
            y=hist_mean, line_dash="dot", line_color="#888", line_width=1.5,
            annotation_text=f"Avg {hist_mean:.0f}%",
            annotation_font_color="#888", annotation_position="top left",
        )

        # Overvaluation threshold lines
        for thresh, label, color in [
            (115, "115% Modestly OV",      "#e67e22"),
            (135, "135% Overvalued",        "#e74c3c"),
            (165, "165% Significantly OV",  "#c0392b"),
        ]:
            fig_c.add_hline(
                y=thresh, line_dash="dash", line_color=color, line_width=1,
                annotation_text=label, annotation_font_color=color,
                annotation_position="top right", annotation_font_size=9,
            )

        fig_c = add_nber(fig_c, start_date="1945-01-01")
        fig_c = dark_layout(fig_c, yaxis_title="Buffett Indicator (%)")
        fig_c.update_layout(
            height=500,
            yaxis={
                "range": [0, min(300, float(ratio.max()) * 1.15)],
                "title": "Buffett Indicator (%)",
            },
            yaxis2={
                "title":      {"text": "S&P 500 (log)", "font": {"color": "#3498db"}},
                "overlaying": "y",
                "side":       "right",
                "type":       "log",
                "showgrid":   False,
                "tickfont":   {"color": "#3498db"},
            },
            xaxis ={"range": x_range},
            legend={"orientation": "h", "y": -0.10},
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

    # ══════════════════════════════════════════════════════════════════════════
    # BOTTOM LINE — single decisive action
    # ══════════════════════════════════════════════════════════════════════════

    # Derive action from composite score + current valuation
    if composite_score >= 70:
        action_verb  = "BUY / OVERWEIGHT"
        action_color = "#2ecc71"
        action_body  = (
            f"The Buffett Indicator ({current_ratio:.1f}% of GDP) sits in favourable territory "
            f"and macro conditions support it. Add equity exposure — Buffett would be deploying capital."
        )
    elif composite_score >= 55:
        action_verb  = "HOLD — FULL ALLOCATION"
        action_color = "#27ae60"
        action_body  = (
            f"Valuation is reasonable and macro backdrop is supportive. "
            f"Maintain your strategic equity allocation. No urgency to buy or sell."
        )
    elif composite_score >= 40:
        action_verb  = "HOLD — RAISE QUALITY BAR"
        action_color = "#f1c40f"
        action_body  = (
            f"At {current_ratio:.1f}% of GDP the market is modestly stretched. "
            f"Hold existing positions but avoid new equity risk at elevated prices. "
            f"Tilt toward quality, profitable businesses trading at reasonable multiples."
        )
    elif composite_score >= 25:
        action_verb  = "REDUCE — RAISE CASH"
        action_color = "#e67e22"
        action_body  = (
            f"At {current_ratio:.1f}% of GDP ({premium:+.1f}pp above the {hist_mean:.0f}% "
            f"historical average) and a recession probability of {rec_prob:.1f}%, "
            f"the risk/reward skews unfavourable. "
            f"Trim equity exposure, raise above-average cash, and wait for better entry points."
        )
    else:
        action_verb  = "DEFENSIVE — ACCUMULATE CASH"
        action_color = "#e74c3c"
        action_body  = (
            f"At {current_ratio:.1f}% of GDP ({hist_pct:.0f}th historical percentile), "
            f"this is among the most overvalued readings on record. "
            f"Buffett's playbook at these levels: stop buying, let cash build, be patient. "
            f"'The price you pay determines your return.' Every dollar deployed here "
            f"buys less future earnings power."
        )

    st.markdown(
        f"""
        <div style="
            background: {_hex_rgba(action_color, 0.10)};
            border: 2px solid {_hex_rgba(action_color, 0.65)};
            border-left: 6px solid {action_color};
            border-radius: 10px;
            padding: 20px 24px;
            margin: 8px 0 20px;
        ">
          <div style="color: #888; font-size: 0.7rem; font-weight: 700;
                      letter-spacing: .09em; text-transform: uppercase; margin-bottom: 8px;">
            ⚡ Bottom Line — What Should You Do?
          </div>
          <div style="color: {action_color}; font-size: 1.55rem; font-weight: 800;
                      letter-spacing: .02em; margin-bottom: 10px; line-height: 1.1;">
            {action_verb}
          </div>
          <div style="color: #e0e0e0; font-size: 0.92rem; line-height: 1.65; max-width: 820px;">
            {action_body}
          </div>
          <div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid {_hex_rgba(action_color, 0.25)};
                      display: flex; gap: 24px; font-size: 0.75rem; color: #888;">
            <span>Score <strong style="color: {action_color};">{composite_score}/100</strong></span>
            <span>BI <strong style="color: {action_color};">{current_ratio:.1f}% GDP</strong></span>
            <span>Rec. Risk <strong style="color: {action_color};">{rec_prob:.1f}%</strong></span>
            <span>Phase <strong style="color: {action_color};">{phase_output.phase}</strong></span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # DOLLAR COST AVERAGING ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════

    st.markdown("### 💰 Does Dollar Cost Averaging Still Make Sense?")
    st.caption(
        "DCA into the S&P 500 is analysed across all six Buffett Indicator valuation zones "
        "since 1950. For each quarterly observation, a monthly DCA strategy is simulated over "
        "1, 3, and 5 years and compared to an equivalent lump-sum investment. "
        "Key insight: DCA doesn't eliminate valuation risk — it mitigates entry-timing risk."
    )

    if not sp_monthly.empty:
        with st.spinner("Computing DCA scenarios…"):
            dca_df = _dca_analysis(ratio, sp_monthly)

        if not dca_df.empty:
            cur_zone_mask = dca_df["zone"] == zone_label
            cur_zone_data = dca_df[cur_zone_mask]

            # ── DCA verdict card ──────────────────────────────────────────────
            # Probability of positive 5Y DCA return at current zone
            dca_5y_vals = cur_zone_data["dca_5Y"].dropna()
            lump_5y_vals = cur_zone_data["lump_5Y"].dropna()

            p_dca_pos  = float((dca_5y_vals > 0).mean() * 100)   if len(dca_5y_vals)  >= 3 else None
            p_dca_wins = float((
                (dca_df.loc[cur_zone_mask, "dca_5Y"].dropna() >
                 dca_df.loc[cur_zone_mask, "lump_5Y"].dropna())
            ).mean() * 100) if len(dca_5y_vals) >= 3 else None
            med_dca_5y = float(dca_5y_vals.median()) if len(dca_5y_vals) >= 3 else None

            if p_dca_pos is None:
                verdict       = "INSUFFICIENT DATA"
                verdict_color = "#888"
                verdict_body  = "Not enough historical observations at this valuation level."
            elif p_dca_pos >= 85 and current_ratio < 135:
                verdict       = "YES — CONTINUE OR INCREASE DCA"
                verdict_color = "#2ecc71"
                verdict_body  = (
                    f"At {current_ratio:.1f}% of GDP, historical data shows a {p_dca_pos:.0f}% "
                    f"probability of a positive 5-year DCA return. "
                    f"Conditions strongly support continuing or increasing a regular S&P 500 DCA programme."
                )
            elif p_dca_pos >= 70:
                verdict       = "YES — CONTINUE WITH NORMAL CADENCE"
                verdict_color = "#27ae60"
                verdict_body  = (
                    f"At {current_ratio:.1f}% of GDP, {p_dca_pos:.0f}% of historical DCA "
                    f"starting points at this zone produced positive 5-year returns. "
                    f"DCA still makes sense — maintain your regular schedule but temper return expectations."
                )
            elif p_dca_pos >= 55:
                verdict       = "YES — BUT REDUCE SIZE OR EXTEND HORIZON"
                verdict_color = "#f39c12"
                verdict_body  = (
                    f"At {current_ratio:.1f}% of GDP, the probability of positive 5Y DCA returns "
                    f"is {p_dca_pos:.0f}% historically. DCA is still rational but expected returns "
                    f"are meaningfully below average. Consider reducing monthly contribution size "
                    f"or extending your investment horizon to 7–10 years."
                )
            else:
                verdict       = "CONTINUE — BUT EXPECT MUTED RETURNS"
                verdict_color = "#e74c3c"
                verdict_body  = (
                    f"At {current_ratio:.1f}% of GDP ({hist_pct:.0f}th percentile), "
                    f"only {p_dca_pos:.0f}% of historical DCA starting points at this zone "
                    f"produced positive 5-year returns. "
                    f"DCA still reduces timing risk vs. a lump sum, but the return headwind from "
                    f"elevated valuations is significant. Consider holding a larger cash reserve "
                    f"and deploying it if/when the indicator pulls back toward fair value."
                )

            # Build the key stats
            p_dca_wins_str = f"{p_dca_wins:.0f}%" if p_dca_wins is not None else "—"
            med_dca_5y_str = f"{med_dca_5y:+.1f}%" if med_dca_5y is not None else "—"

            st.markdown(
                f"""
                <div style="
                    background: {_hex_rgba(verdict_color, 0.09)};
                    border: 2px solid {_hex_rgba(verdict_color, 0.55)};
                    border-radius: 10px;
                    padding: 18px 22px;
                    margin: 8px 0 18px;
                ">
                  <div style="color: #888; font-size: 0.7rem; font-weight: 700;
                              letter-spacing: .08em; text-transform: uppercase; margin-bottom: 8px;">
                    💰 DCA Verdict at {zone_label} ({current_ratio:.1f}% of GDP)
                  </div>
                  <div style="color: {verdict_color}; font-size: 1.4rem; font-weight: 800;
                              margin-bottom: 10px; line-height: 1.15;">
                    {verdict}
                  </div>
                  <div style="color: #ddd; font-size: 0.88rem; line-height: 1.65; max-width: 820px;
                              margin-bottom: 14px;">
                    {verdict_body}
                  </div>
                  <div style="display: flex; gap: 28px; flex-wrap: wrap;">
                    <div style="text-align: center;">
                      <div style="color: {verdict_color}; font-size: 1.5rem; font-weight: 800;">
                        {p_dca_pos:.0f}%
                      </div>
                      <div style="color: #888; font-size: 0.7rem; text-transform: uppercase;
                                  letter-spacing: .05em;">P(5Y DCA&nbsp;>&nbsp;0)</div>
                    </div>
                    <div style="text-align: center;">
                      <div style="color: {verdict_color}; font-size: 1.5rem; font-weight: 800;">
                        {med_dca_5y_str}
                      </div>
                      <div style="color: #888; font-size: 0.7rem; text-transform: uppercase;
                                  letter-spacing: .05em;">Median 5Y DCA Return</div>
                    </div>
                    <div style="text-align: center;">
                      <div style="color: {verdict_color}; font-size: 1.5rem; font-weight: 800;">
                        {p_dca_wins_str}
                      </div>
                      <div style="color: #888; font-size: 0.7rem; text-transform: uppercase;
                                  letter-spacing: .05em;">P(DCA beats Lump Sum, 5Y)</div>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ── DCA vs Lump Sum by zone table ─────────────────────────────────
            st.markdown("##### DCA vs Lump Sum — All Valuation Zones (Historical, 1950–present)")
            st.caption(
                "P(DCA>0) = probability that a 5-year DCA programme produces a positive return. "
                "P(DCA>LS) = probability that DCA outperforms an equivalent lump-sum investment "
                "(DCA wins when the market falls after the initial investment date)."
            )

            th = ("background:#1a1a2e;color:#aaa;font-size:0.72rem;font-weight:700;"
                  "letter-spacing:.04em;text-transform:uppercase;padding:7px 10px;"
                  "border-bottom:1px solid #333;white-space:nowrap;")
            th_r = th + "text-align:right;"
            th_l = th + "text-align:left;"
            td   = "padding:7px 10px;font-size:0.82rem;border-bottom:1px solid #1e1e2e;"

            def _dca_color(v: float | None) -> tuple[str, str]:
                if v is None:
                    return "#555", "—"
                t = f"{v:+.1f}%"
                if v >= 30:   return "#2ecc71", t
                if v >= 10:   return "#27ae60", t
                if v >=  0:   return "#f1c40f", t
                return "#e74c3c", t

            def _pct_color(v: float | None) -> tuple[str, str]:
                if v is None:
                    return "#555", "—"
                t = f"{v:.0f}%"
                if v >= 80:  return "#2ecc71", t
                if v >= 65:  return "#27ae60", t
                if v >= 50:  return "#f1c40f", t
                return "#e74c3c", t

            zone_rows_html = ""
            for zone in _ZONE_ORDER:
                z_color = _ZONE_COLORS.get(zone, "#888")
                mask    = dca_df["zone"] == zone
                n       = int(mask.sum())
                if n < 3:
                    continue
                sub = dca_df[mask]
                is_current = zone == zone_label
                row_bg = f"background:{_hex_rgba(z_color, 0.07)};" if is_current else ""
                cur_tag = (
                    f' <span style="font-size:0.65rem;background:{z_color};color:#000;'
                    f'border-radius:3px;padding:1px 5px;font-weight:700;">NOW</span>'
                ) if is_current else ""

                cells = (
                    f'<td style="{td}{row_bg}text-align:left;">'
                    f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
                    f'background:{z_color};margin-right:6px;vertical-align:middle;"></span>'
                    f'<span style="color:#fff;font-weight:{"800" if is_current else "500"};">'
                    f'{zone}</span>{cur_tag}</td>'
                    f'<td style="{td}{row_bg}color:#888;text-align:right;">{n}</td>'
                )

                for col in ["1Y", "3Y", "5Y"]:
                    dv = sub[f"dca_{col}"].dropna()
                    lv = sub[f"lump_{col}"].dropna()
                    med_d = float(round(dv.median(), 1)) if len(dv) >= 3 else None
                    med_l = float(round(lv.median(), 1)) if len(lv) >= 3 else None

                    both  = sub[[f"dca_{col}", f"lump_{col}"]].dropna()
                    p_pos  = float((both[f"dca_{col}"] > 0).mean() * 100) if len(both) >= 3 else None
                    p_wins = float((both[f"dca_{col}"] > both[f"lump_{col}"]).mean() * 100) if len(both) >= 3 else None

                    dc, dv_s = _dca_color(med_d)
                    lc, lv_s = _dca_color(med_l)
                    ppc, ppv = _pct_color(p_pos)
                    pwc, pwv = _pct_color(p_wins)
                    cells += (
                        f'<td style="{td}{row_bg}color:{dc};font-weight:600;text-align:right;">{dv_s}</td>'
                        f'<td style="{td}{row_bg}color:{lc};text-align:right;">{lv_s}</td>'
                        f'<td style="{td}{row_bg}color:{ppc};text-align:right;">{ppv}</td>'
                        f'<td style="{td}{row_bg}color:{pwc};text-align:right;">{pwv}</td>'
                    )
                zone_rows_html += f"<tr>{cells}</tr>"

            st.markdown(
                f"""
                <div style="overflow-x:auto;margin:8px 0 12px;">
                  <table style="width:100%;border-collapse:collapse;background:#0e1117;
                                border-radius:8px;overflow:hidden;">
                    <thead>
                      <tr>
                        <th style="{th_l}" rowspan="2">Zone</th>
                        <th style="{th_r}" rowspan="2">n</th>
                        <th style="{th_r}" colspan="4">1-Year Horizon</th>
                        <th style="{th_r}" colspan="4">3-Year Horizon</th>
                        <th style="{th_r}" colspan="4">5-Year Horizon</th>
                      </tr>
                      <tr>
                        <th style="{th_r}">DCA Med</th><th style="{th_r}">LS Med</th>
                        <th style="{th_r}">P(DCA>0)</th><th style="{th_r}">P(DCA>LS)</th>
                        <th style="{th_r}">DCA Med</th><th style="{th_r}">LS Med</th>
                        <th style="{th_r}">P(DCA>0)</th><th style="{th_r}">P(DCA>LS)</th>
                        <th style="{th_r}">DCA Med</th><th style="{th_r}">LS Med</th>
                        <th style="{th_r}">P(DCA>0)</th><th style="{th_r}">P(DCA>LS)</th>
                      </tr>
                    </thead>
                    <tbody>{zone_rows_html}</tbody>
                  </table>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(
                "DCA Med = median return of monthly DCA strategy. LS Med = median lump-sum return. "
                "P(DCA>0) = % of starting points where DCA produced positive returns. "
                "P(DCA>LS) = % of starting points where DCA outperformed lump sum. "
                "Highlighted row = current valuation zone. Zones with <3 observations hidden."
            )

            # ── DCA vs Lump Sum chart ──────────────────────────────────────────
            fig_dca = go.Figure()

            zone_order_present = [z for z in _ZONE_ORDER if z in dca_df["zone"].unique()]
            dca_med_5y   = []
            lump_med_5y  = []
            p_dca_pos_5y = []
            zone_labels_chart = []
            zone_colors_chart = []

            for z in zone_order_present:
                sub = dca_df[dca_df["zone"] == z]
                dv  = sub["dca_5Y"].dropna()
                lv  = sub["lump_5Y"].dropna()
                if len(dv) < 3:
                    continue
                zone_labels_chart.append(z)
                zone_colors_chart.append(_ZONE_COLORS.get(z, "#888"))
                dca_med_5y.append(float(round(dv.median(), 1)))
                lump_med_5y.append(float(round(lv.median(), 1)))
                p_dca_pos_5y.append(float(round((dv > 0).mean() * 100, 1)))

            if zone_labels_chart:
                fig_dca.add_trace(go.Bar(
                    name="DCA Median 5Y Return",
                    x=zone_labels_chart,
                    y=dca_med_5y,
                    marker_color=[
                        _hex_rgba("#2ecc71", 0.85) if v >= 0 else _hex_rgba("#e74c3c", 0.85)
                        for v in dca_med_5y
                    ],
                    marker_line_color="#3498db",
                    marker_line_width=1.5,
                    hovertemplate="<b>%{x}</b><br>DCA median 5Y: <b>%{y:+.1f}%</b><extra></extra>",
                ))
                fig_dca.add_trace(go.Bar(
                    name="Lump Sum Median 5Y Return",
                    x=zone_labels_chart,
                    y=lump_med_5y,
                    marker_color=[
                        _hex_rgba("#9b59b6", 0.55) if v >= 0 else _hex_rgba("#e74c3c", 0.55)
                        for v in lump_med_5y
                    ],
                    marker_line_color="#9b59b6",
                    marker_line_width=1.5,
                    hovertemplate="<b>%{x}</b><br>Lump sum median 5Y: <b>%{y:+.1f}%</b><extra></extra>",
                ))
                fig_dca.add_trace(go.Scatter(
                    name="P(DCA > 0) — right axis",
                    x=zone_labels_chart,
                    y=p_dca_pos_5y,
                    mode="lines+markers",
                    yaxis="y2",
                    line={"color": "#f39c12", "width": 2, "dash": "dot"},
                    marker={"size": 8, "color": "#f39c12"},
                    hovertemplate="<b>%{x}</b><br>P(DCA>0): <b>%{y:.1f}%</b><extra></extra>",
                ))

                fig_dca.add_hline(y=0,  line_dash="dash", line_color="#555", line_width=1)
                fig_dca.add_hline(
                    y=50, line_dash="dot", line_color="#f39c12", line_width=1,
                    yref="y2",
                    annotation_text="50% breakeven",
                    annotation_font_color="#f39c12",
                    annotation_position="top right",
                    annotation_font_size=9,
                )

                fig_dca = dark_layout(fig_dca, yaxis_title="Median 5Y Return (%)")
                fig_dca.update_layout(
                    height=420,
                    barmode="group",
                    xaxis={"tickangle": -20},
                    yaxis2={
                        "title":      {"text": "P(DCA > 0) %", "font": {"color": "#f39c12"}},
                        "overlaying": "y",
                        "side":       "right",
                        "range":      [0, 110],
                        "showgrid":   False,
                        "tickfont":   {"color": "#f39c12"},
                    },
                    legend={"orientation": "h", "y": -0.28},
                )
                st.plotly_chart(fig_dca, use_container_width=True, key="tab9_dca_chart")

        else:
            st.info("Insufficient data to compute DCA analysis.")
    else:
        st.info("S&P 500 data unavailable — DCA analysis skipped.")

    st.markdown("---")
    st.caption(DISCLAIMER)
