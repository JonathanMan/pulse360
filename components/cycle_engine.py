"""
components/cycle_engine.py
===========================
Automated business cycle phase detection for Pie360.

Uses live FRED data to score each of the four macro cycle phases and return the
most likely phase with a confidence score and per-indicator signal breakdown.

Algorithm
---------
Five FRED indicators are scored across four phases. Each indicator contributes
positive score to the phase it most strongly implies. The phase with the highest
total score wins. Confidence = winner_score / (winner_score + runner_up_score).

FRED series used
----------------
  T10Y2Y   — 10-Year minus 2-Year Treasury Yield (yield curve)
  UNRATE   — Civilian Unemployment Rate
  INDPRO   — Industrial Production Index
  CPIAUCSL — CPI All Items (All Urban Consumers)
  ICSA     — Initial Jobless Claims (weekly)

Public API
----------
    from components.cycle_engine import detect_cycle_phase, CycleResult

    result = detect_cycle_phase(fred_key)
    print(result.phase)           # "Late / Peak"
    print(result.confidence)      # 68 (0–100)
    print(result.signals)         # {indicator: SignalReading, ...}
    print(result.summary)         # human-readable one-liner

    # Streamlit display helper
    result.render()               # renders phase badge + signal table in Streamlit
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd
import streamlit as st
from components.observability import log, capture_exception

from components.fred_utils import safe_get_series

logger = logging.getLogger(__name__)

# ── Phase definitions (match rebalancer.py) ───────────────────────────────────
Phase = Literal["Early / Recovery", "Mid / Expansion", "Late / Peak", "Contraction"]
PHASES: list[Phase] = ["Early / Recovery", "Mid / Expansion", "Late / Peak", "Contraction"]

_PHASE_COLORS: dict[Phase, str] = {
    "Early / Recovery": "#27ae60",   # green
    "Mid / Expansion":  "#2980b9",   # blue
    "Late / Peak":      "#c98800",   # amber
    "Contraction":      "#d92626",   # red
}

_PHASE_ICONS: dict[Phase, str] = {
    "Early / Recovery": "🌱",
    "Mid / Expansion":  "📈",
    "Late / Peak":      "🔔",
    "Contraction":      "🔻",
}

# ── Confidence buckets ────────────────────────────────────────────────────────
def _confidence_label(confidence: int) -> str:
    if confidence >= 75:
        return "High"
    if confidence >= 50:
        return "Moderate"
    if confidence >= 30:
        return "Low"
    return "Uncertain"


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class SignalReading:
    """One indicator's current reading and its cycle implication."""
    name: str                    # human-readable name
    series_id: str               # FRED series
    value: float | None          # latest value
    formatted: str               # e.g. "−0.42%"
    trend: str                   # "Rising" | "Falling" | "Flat"
    implied_phase: Phase | None  # strongest phase signal
    scores: dict[Phase, float]   # contribution to each phase score
    note: str = ""               # optional context


@dataclass
class CycleResult:
    """Full output of detect_cycle_phase()."""
    phase: Phase
    confidence: int                      # 0–100
    scores: dict[Phase, float]           # raw score per phase
    signals: dict[str, SignalReading]    # keyed by series_id
    as_of: datetime                      # data freshness
    summary: str                         # one-line narrative
    data_quality: str = "full"           # "full" | "partial" | "unavailable"

    @property
    def icon(self) -> str:
        return _PHASE_ICONS.get(self.phase, "📊")

    @property
    def color(self) -> str:
        return _PHASE_COLORS.get(self.phase, "#6b7280")

    @property
    def confidence_label(self) -> str:
        return _confidence_label(self.confidence)

    def render(self) -> None:
        """Render a compact cycle phase summary in Streamlit."""
        _render_cycle_card(self)


# ── Indicator scoring logic ───────────────────────────────────────────────────

def _score_yield_curve(
    series: pd.Series,
) -> SignalReading:
    """
    T10Y2Y — 10Y minus 2Y Treasury spread.
    Inversion → Contraction. Steep positive → Expansion/Recovery.
    """
    if series.empty:
        return SignalReading(
            name="Yield Curve (10Y−2Y)", series_id="T10Y2Y",
            value=None, formatted="N/A", trend="Unknown",
            implied_phase=None,
            scores={p: 0.0 for p in PHASES},
            note="Data unavailable",
        )

    latest   = float(series.dropna().iloc[-1])
    # 6-month trend: positive = steepening
    six_mo   = series.dropna().last("180D")
    trend_val = float(six_mo.iloc[-1] - six_mo.iloc[0]) if len(six_mo) >= 2 else 0.0
    trend    = "Steepening" if trend_val > 0.1 else ("Flattening" if trend_val < -0.1 else "Flat")

    scores: dict[Phase, float] = {p: 0.0 for p in PHASES}

    # Deep inversion → Contraction
    if latest < -0.75:
        scores["Contraction"]    += 3.0
        scores["Late / Peak"]    += 1.0
        implied = "Contraction"
    elif latest < -0.25:
        scores["Contraction"]    += 2.0
        scores["Late / Peak"]    += 1.5
        implied = "Contraction"
    elif latest < 0.25:
        # Flat/mildly inverted
        if trend_val > 0.15:
            # Steepening from inversion → early recovery signal
            scores["Early / Recovery"] += 2.0
            scores["Late / Peak"]       += 1.0
            implied = "Early / Recovery"
        else:
            scores["Late / Peak"]    += 2.0
            scores["Contraction"]    += 1.0
            implied = "Late / Peak"
    elif latest < 1.0:
        # Mildly positive
        scores["Mid / Expansion"]   += 1.5
        scores["Late / Peak"]        += 1.0
        implied = "Mid / Expansion"
    else:
        # Steep positive curve → early cycle / recovery
        scores["Early / Recovery"]  += 2.5
        scores["Mid / Expansion"]   += 1.0
        implied = "Early / Recovery"

    return SignalReading(
        name="Yield Curve (10Y−2Y)", series_id="T10Y2Y",
        value=latest,
        formatted=f"{latest:+.2f}%",
        trend=trend,
        implied_phase=implied,
        scores=scores,
        note="Inverted = recession risk · Steep positive = early recovery",
    )


def _score_unemployment(
    series: pd.Series,
) -> SignalReading:
    """
    UNRATE — Unemployment Rate.
    Rising sharply → Contraction. Falling from peak → Early. Near cyclical low → Late.
    """
    if series.empty:
        return SignalReading(
            name="Unemployment Rate", series_id="UNRATE",
            value=None, formatted="N/A", trend="Unknown",
            implied_phase=None, scores={p: 0.0 for p in PHASES},
        )

    latest     = float(series.dropna().iloc[-1])
    six_mo_ago = series.dropna().last("210D").iloc[0] if len(series.dropna().last("210D")) >= 1 else latest
    twelve_mo  = series.dropna().last("380D").iloc[0] if len(series.dropna().last("380D")) >= 1 else latest
    change_6m  = latest - float(six_mo_ago)
    change_12m = latest - float(twelve_mo)

    trend = "Rising" if change_6m > 0.2 else ("Falling" if change_6m < -0.2 else "Stable")
    scores: dict[Phase, float] = {p: 0.0 for p in PHASES}

    # Rising unemployment → recession
    if change_6m > 1.0 or change_12m > 1.5:
        scores["Contraction"]      += 3.0
        implied = "Contraction"
    elif change_6m > 0.4:
        scores["Contraction"]      += 1.5
        scores["Late / Peak"]      += 1.0
        implied = "Contraction"
    elif change_6m > 0.15:
        # Creeping up — late cycle
        scores["Late / Peak"]      += 2.0
        scores["Contraction"]      += 0.5
        implied = "Late / Peak"
    elif change_6m < -0.4 and latest > 5.0:
        # Falling from high level → early recovery
        scores["Early / Recovery"] += 2.5
        implied = "Early / Recovery"
    elif change_6m < -0.2:
        scores["Early / Recovery"] += 1.5
        scores["Mid / Expansion"]  += 1.0
        implied = "Early / Recovery"
    else:
        # Stable near lows
        scores["Mid / Expansion"]  += 2.0
        scores["Late / Peak"]      += 1.0
        implied = "Mid / Expansion"

    return SignalReading(
        name="Unemployment Rate", series_id="UNRATE",
        value=latest,
        formatted=f"{latest:.1f}%",
        trend=trend,
        implied_phase=implied,
        scores=scores,
        note=f"6m change: {change_6m:+.2f}pp",
    )


def _score_industrial_production(
    series: pd.Series,
) -> SignalReading:
    """
    INDPRO — Industrial Production (YoY % change).
    Negative YoY → Contraction. Strong positive → Mid/Expansion.
    """
    if series.empty:
        return SignalReading(
            name="Industrial Production (YoY)", series_id="INDPRO",
            value=None, formatted="N/A", trend="Unknown",
            implied_phase=None, scores={p: 0.0 for p in PHASES},
        )

    monthly = series.dropna().resample("MS").last()
    if len(monthly) < 13:
        yoy = 0.0
    else:
        yoy = float((monthly.iloc[-1] / monthly.iloc[-13] - 1) * 100)

    # 3-month trend
    three_mo = monthly.last("100D")
    if len(three_mo) >= 2:
        mom_trend = float(three_mo.iloc[-1] - three_mo.iloc[-2])
        trend = "Rising" if mom_trend > 0.2 else ("Falling" if mom_trend < -0.2 else "Flat")
    else:
        trend = "Unknown"

    scores: dict[Phase, float] = {p: 0.0 for p in PHASES}

    if yoy < -3.0:
        scores["Contraction"]       += 3.0
        implied = "Contraction"
    elif yoy < 0:
        scores["Contraction"]       += 1.5
        scores["Early / Recovery"]  += 0.5
        implied = "Contraction"
    elif yoy < 2.0:
        if trend == "Rising":
            scores["Early / Recovery"] += 2.0
            implied = "Early / Recovery"
        else:
            scores["Late / Peak"]      += 1.5
            scores["Contraction"]      += 0.5
            implied = "Late / Peak"
    elif yoy < 5.0:
        scores["Mid / Expansion"]   += 2.0
        scores["Early / Recovery"]  += 0.5
        implied = "Mid / Expansion"
    else:
        scores["Mid / Expansion"]   += 2.5
        implied = "Mid / Expansion"

    return SignalReading(
        name="Industrial Production (YoY)", series_id="INDPRO",
        value=yoy,
        formatted=f"{yoy:+.1f}%",
        trend=trend,
        implied_phase=implied,
        scores=scores,
        note="YoY % change in total industrial output",
    )


def _score_cpi(
    series: pd.Series,
) -> SignalReading:
    """
    CPIAUCSL — CPI All Items YoY.
    Elevated + rising → Late. Declining from peak → Contraction/Early.
    """
    if series.empty:
        return SignalReading(
            name="CPI Inflation (YoY)", series_id="CPIAUCSL",
            value=None, formatted="N/A", trend="Unknown",
            implied_phase=None, scores={p: 0.0 for p in PHASES},
        )

    monthly = series.dropna().resample("MS").last()
    if len(monthly) < 13:
        yoy = 0.0
    else:
        yoy = float((monthly.iloc[-1] / monthly.iloc[-13] - 1) * 100)

    # 3-month trend in YoY
    if len(monthly) >= 16:
        yoy_3m_ago = float((monthly.iloc[-4] / monthly.iloc[-16] - 1) * 100)
        trend_val  = yoy - yoy_3m_ago
    else:
        trend_val  = 0.0

    trend = "Rising" if trend_val > 0.3 else ("Falling" if trend_val < -0.3 else "Stable")
    scores: dict[Phase, float] = {p: 0.0 for p in PHASES}

    if yoy > 5.0 and trend == "Rising":
        scores["Late / Peak"]       += 2.5
        implied = "Late / Peak"
    elif yoy > 4.0:
        scores["Late / Peak"]       += 2.0
        scores["Contraction"]       += 0.5
        implied = "Late / Peak"
    elif yoy > 2.5:
        scores["Mid / Expansion"]   += 1.5
        scores["Late / Peak"]       += 1.0
        implied = "Mid / Expansion"
    elif yoy > 0:
        if trend == "Falling":
            scores["Early / Recovery"] += 1.5
            implied = "Early / Recovery"
        else:
            scores["Mid / Expansion"]  += 1.5
            implied = "Mid / Expansion"
    else:
        # Deflation → deep recession
        scores["Contraction"]       += 2.0
        implied = "Contraction"

    return SignalReading(
        name="CPI Inflation (YoY)", series_id="CPIAUCSL",
        value=yoy,
        formatted=f"{yoy:+.1f}%",
        trend=trend,
        implied_phase=implied,
        scores=scores,
        note=f"3m trend: {'+' if trend_val >= 0 else ''}{trend_val:.1f}pp",
    )


def _score_initial_claims(
    series: pd.Series,
) -> SignalReading:
    """
    ICSA — Initial Jobless Claims (4-week MA).
    Spiking claims → Contraction. Falling from spike → Early. Low and stable → Mid.
    """
    if series.empty:
        return SignalReading(
            name="Initial Claims (4-wk MA)", series_id="ICSA",
            value=None, formatted="N/A", trend="Unknown",
            implied_phase=None, scores={p: 0.0 for p in PHASES},
        )

    weekly  = series.dropna()
    ma4     = weekly.rolling(4).mean().dropna()
    if ma4.empty:
        latest_ma = float(weekly.iloc[-1])
    else:
        latest_ma = float(ma4.iloc[-1])

    # 8-week trend in 4-week MA
    if len(ma4) >= 9:
        eight_wk_ago = float(ma4.iloc[-9])
        pct_change   = (latest_ma / eight_wk_ago - 1) * 100
    else:
        pct_change = 0.0

    trend = "Rising" if pct_change > 10 else ("Falling" if pct_change < -10 else "Stable")
    scores: dict[Phase, float] = {p: 0.0 for p in PHASES}

    # Absolute level matters + rate of change
    if latest_ma > 350_000:
        scores["Contraction"]       += 3.0
        implied = "Contraction"
    elif latest_ma > 280_000:
        scores["Contraction"]       += 1.5
        scores["Early / Recovery"]  += 0.5
        implied = "Contraction"
    elif latest_ma > 240_000:
        if pct_change > 15:
            scores["Late / Peak"]       += 2.0
            implied = "Late / Peak"
        elif pct_change < -10:
            scores["Early / Recovery"]  += 1.5
            implied = "Early / Recovery"
        else:
            scores["Mid / Expansion"]   += 1.0
            implied = "Mid / Expansion"
    else:
        # Low claims
        if pct_change > 15:
            scores["Late / Peak"]       += 1.5
            implied = "Late / Peak"
        else:
            scores["Mid / Expansion"]   += 2.5
            scores["Late / Peak"]       += 0.5
            implied = "Mid / Expansion"

    return SignalReading(
        name="Initial Claims (4-wk MA)", series_id="ICSA",
        value=latest_ma,
        formatted=f"{int(latest_ma):,}",
        trend=trend,
        implied_phase=implied,
        scores=scores,
        note=f"8w change: {pct_change:+.1f}%",
    )


# ── Indicator weights ─────────────────────────────────────────────────────────
# Yield curve and unemployment are the most historically reliable cycle signals.
_WEIGHTS: dict[str, float] = {
    "T10Y2Y":   1.5,   # yield curve — most forward-looking
    "UNRATE":   1.3,   # labour market — coincident/lagging but high signal
    "INDPRO":   1.0,   # industrial activity
    "CPIAUCSL": 0.9,   # inflation — more relevant at cycle extremes
    "ICSA":     1.0,   # claims — leading indicator of labour market
}


# ── Summary narratives ────────────────────────────────────────────────────────

_SUMMARIES: dict[Phase, str] = {
    "Early / Recovery": (
        "Leading indicators are turning up after a contraction: claims falling, "
        "industrial production recovering, and the yield curve steepening. "
        "Cyclical assets typically outperform in this phase."
    ),
    "Mid / Expansion": (
        "The economy is firing on most cylinders: low unemployment, solid industrial "
        "output, moderate inflation, and a healthy yield curve. Broad equity exposure "
        "is rewarded."
    ),
    "Late / Peak": (
        "Growth is slowing and financial conditions are tightening: the yield curve "
        "is flat or inverting, inflation remains elevated, and labour market slack is "
        "minimal. Rotate toward defensives and duration."
    ),
    "Contraction": (
        "Recessionary signals dominate: inverted yield curve, rising jobless claims, "
        "declining industrial output. Capital preservation is the priority — long bonds, "
        "gold, and cash typically outperform."
    ),
}


# ── Main detector ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def detect_cycle_phase(fred_key: str) -> CycleResult:
    """
    Detect the current business cycle phase using live FRED data.

    Fetches 5 FRED series, scores each against 4 cycle phases using
    a weighted rule-based model, and returns the winning phase with
    confidence score and per-indicator signal breakdown.

    Cached for 1 hour (FRED data doesn't update more frequently).
    Returns a fallback CycleResult with phase="Late / Peak" if all
    FRED calls fail (conservative default for risk management).

    Args:
        fred_key: FRED API key string (from st.secrets or env var)

    Returns:
        CycleResult
    """
    # ── Fetch all series ──────────────────────────────────────────────────────
    start = "2015-01-01"   # 10 years of data — enough for all trend calculations
    series_map = {
        "T10Y2Y":   safe_get_series("T10Y2Y",   fred_key, observation_start=start, warn=False),
        "UNRATE":   safe_get_series("UNRATE",   fred_key, observation_start=start, warn=False),
        "INDPRO":   safe_get_series("INDPRO",   fred_key, observation_start=start, warn=False),
        "CPIAUCSL": safe_get_series("CPIAUCSL", fred_key, observation_start=start, warn=False),
        "ICSA":     safe_get_series("ICSA",     fred_key, observation_start=start, warn=False),
    }

    n_available = sum(1 for s in series_map.values() if not s.empty)
    if n_available == 0:
        return CycleResult(
            phase="Late / Peak",
            confidence=0,
            scores={p: 0.0 for p in PHASES},
            signals={},
            as_of=datetime.now(),
            summary="FRED data unavailable — defaulting to Late / Peak (conservative).",
            data_quality="unavailable",
        )

    data_quality = "full" if n_available == 5 else "partial"

    # ── Score each indicator ──────────────────────────────────────────────────
    scorers = {
        "T10Y2Y":   _score_yield_curve(series_map["T10Y2Y"]),
        "UNRATE":   _score_unemployment(series_map["UNRATE"]),
        "INDPRO":   _score_industrial_production(series_map["INDPRO"]),
        "CPIAUCSL": _score_cpi(series_map["CPIAUCSL"]),
        "ICSA":     _score_initial_claims(series_map["ICSA"]),
    }

    # ── Aggregate weighted scores ─────────────────────────────────────────────
    totals: dict[Phase, float] = {p: 0.0 for p in PHASES}
    for sid, reading in scorers.items():
        w = _WEIGHTS.get(sid, 1.0)
        for phase, score in reading.scores.items():
            totals[phase] += score * w

    # ── Determine winner and confidence ───────────────────────────────────────
    ranked     = sorted(totals.items(), key=lambda kv: -kv[1])
    winner     = ranked[0][0]
    top_score  = ranked[0][1]
    runner_up  = ranked[1][1] if len(ranked) > 1 else 0.0

    if top_score + runner_up > 0:
        confidence = int(round((top_score / (top_score + runner_up)) * 100))
        confidence = max(0, min(100, confidence))
    else:
        confidence = 0

    # Determine data freshness
    last_dates = [
        s.dropna().index[-1]
        for s in series_map.values()
        if not s.empty and len(s.dropna()) > 0
    ]
    as_of = max(last_dates) if last_dates else datetime.now()
    if hasattr(as_of, "to_pydatetime"):
        as_of = as_of.to_pydatetime()

    return CycleResult(
        phase=winner,
        confidence=confidence,
        scores=totals,
        signals=scorers,
        as_of=as_of,
        summary=_SUMMARIES.get(winner, ""),
        data_quality=data_quality,
    )


# ── Streamlit rendering ───────────────────────────────────────────────────────

def _render_cycle_card(result: CycleResult) -> None:
    """
    Render a compact cycle phase card with indicator signal table.
    Designed to embed in any Streamlit page.
    """
    color = result.color
    icon  = result.icon

    # Phase badge
    st.markdown(f"""
<div style="display:flex;align-items:center;gap:16px;padding:16px 20px;
  background:{color}12;border:1.5px solid {color}40;border-radius:10px;margin-bottom:12px;">
  <div style="font-size:2rem;">{icon}</div>
  <div>
    <div style="font-size:0.65rem;font-weight:700;letter-spacing:.1em;
      text-transform:uppercase;color:{color};margin-bottom:2px;">
      Detected Cycle Phase
    </div>
    <div style="font-size:1.35rem;font-weight:800;color:{color};letter-spacing:-0.02em;">
      {result.phase}
    </div>
    <div style="font-size:0.78rem;color:#6b7280;margin-top:2px;">
      {result.confidence_label} confidence ({result.confidence}%) ·
      Data as of {result.as_of.strftime('%b %-d, %Y') if result.as_of else 'N/A'}
      {'· ⚠️ Partial data' if result.data_quality == 'partial' else ''}
      {'· ❌ No data' if result.data_quality == 'unavailable' else ''}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    # Summary
    st.caption(result.summary)

    # Indicator signal table
    if result.signals:
        with st.expander("📡 View indicator signals", expanded=False):
            rows = []
            for reading in result.signals.values():
                implied = reading.implied_phase or "—"
                phase_color = _PHASE_COLORS.get(implied, "#6b7280")
                rows.append({
                    "Indicator":     reading.name,
                    "Value":         reading.formatted,
                    "Trend":         reading.trend,
                    "Signal":        f'<span style="color:{phase_color};font-weight:600;">{implied}</span>',
                    "Note":          reading.note,
                })
            import pandas as _pd
            df = _pd.DataFrame(rows)
            st.markdown(
                df.to_html(escape=False, index=False, classes="cycle-signals"),
                unsafe_allow_html=True,
            )
            st.markdown("""
<style>
.cycle-signals { width:100%;border-collapse:collapse;font-size:0.78rem; }
.cycle-signals th { border-bottom:2px solid #dee2e6;padding:6px 10px;text-align:left;
  color:#6a6a6a;font-size:0.65rem;text-transform:uppercase;letter-spacing:.05em; }
.cycle-signals td { border-bottom:1px solid #f0f0f0;padding:6px 10px; }
</style>""", unsafe_allow_html=True)

    # Score breakdown bar chart
    if result.scores and any(v > 0 for v in result.scores.values()):
        with st.expander("📊 Score breakdown", expanded=False):
            import plotly.graph_objects as go
            phases   = list(result.scores.keys())
            scores   = list(result.scores.values())
            colors   = [_PHASE_COLORS[p] for p in phases]
            fig = go.Figure(go.Bar(
                x=scores, y=phases, orientation="h",
                marker_color=colors,
                text=[f"{s:.1f}" for s in scores],
                textposition="outside",
            ))
            fig.update_layout(
                margin=dict(l=0, r=40, t=10, b=0),
                height=160,
                xaxis=dict(showgrid=False, visible=False),
                yaxis=dict(autorange="reversed"),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
