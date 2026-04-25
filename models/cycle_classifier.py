"""
Pulse360 Cycle Phase Classifier
=================================
6-state rule-based classifier. Requires ≥2 confirming indicators to assign
a phase — never flips on a single noisy print.

States: Early Expansion · Mid Expansion · Late Expansion · Peak · Contraction · Trough

Inputs: recession probability (from model), LEI growth, UNRATE trend, NBER flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from models.recession_model import RecessionModelOutput


# ---------------------------------------------------------------------------
# Display constants
# ---------------------------------------------------------------------------

PHASE_COLORS: dict[str, str] = {
    "Early Expansion": "#2ecc71",
    "Mid Expansion":   "#27ae60",
    "Late Expansion":  "#f39c12",
    "Peak":            "#e67e22",
    "Contraction":     "#e74c3c",
    "Trough":          "#3498db",
}

PHASE_EMOJIS: dict[str, str] = {
    "Early Expansion": "🟢",
    "Mid Expansion":   "🟢",
    "Late Expansion":  "🟡",
    "Peak":            "🟠",
    "Contraction":     "🔴",
    "Trough":          "🔵",
}


# ---------------------------------------------------------------------------
# Output data class
# ---------------------------------------------------------------------------

@dataclass
class CyclePhaseOutput:
    phase:                str
    color:                str
    emoji:                str
    confidence:           str            # "High" | "Medium" | "Low"
    confirming_indicators: list = field(default_factory=list)   # list[str]
    notes:                str = ""

    @property
    def confidence_color(self) -> str:
        return {"High": "#2ecc71", "Medium": "#f39c12", "Low": "#e74c3c"}.get(
            self.confidence, "#888888"
        )


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify_cycle_phase(
    model_output:  RecessionModelOutput,
    lei_growth:    Optional[float],
    unrate_data:   Optional[pd.Series],
    nber_active:   bool = False,
) -> CyclePhaseOutput:
    """
    Classify the current business cycle phase.

    Rules require ≥2 confirming indicators before committing to a phase.
    When evidence is thin, the classifier defaults to Mid Expansion with Low confidence.

    Data quality: confidence is capped if high-weight features (≥10%) are stale.
    1 stale high-weight feature  → cap at Medium
    2+ stale high-weight features → cap at Low

    Args:
        model_output: output from run_recession_model()
        lei_growth:   LEI 6-month annualised growth (%), or None
        unrate_data:  UNRATE time series, or None
        nber_active:  True if NBER has declared an active recession

    Returns:
        CyclePhaseOutput with phase, colors, confidence, and confirming indicators
    """
    prob = model_output.probability

    # ── Derived indicator flags ──────────────────────────────────────────────
    lei_positive = lei_growth is not None and lei_growth > 0.0
    lei_negative = lei_growth is not None and lei_growth < 0.0

    unrate_rising = unrate_falling = unrate_stable = None
    if unrate_data is not None and not unrate_data.empty:
        monthly = unrate_data.resample("MS").last().dropna()
        if len(monthly) >= 4:
            change_3m      = float(monthly.iloc[-1] - monthly.iloc[-4])
            unrate_rising  = change_3m > 0.3
            unrate_falling = change_3m < -0.2
            unrate_stable  = not unrate_rising and not unrate_falling

    yield_inverted = any(
        f.series_id == "T10Y3M" and f.current_value is not None and f.current_value < 0
        for f in model_output.features
    )

    # ── Classification logic (high → low priority) ───────────────────────────

    # ── helper: run classification then apply data quality cap ─────────────────
    def _classify() -> CyclePhaseOutput:

        # CONTRACTION — NBER declared (authoritative, single indicator is sufficient)
        if nber_active:
            confirming = ["NBER recession declared"]
            if unrate_rising:
                confirming.append("Unemployment rising")
            if lei_negative:
                confirming.append("LEI contracting")
            return _make(
                "Contraction", "High", confirming,
                "NBER has officially declared a recession. Dashboard in contraction mode.",
            )

        # CONTRACTION — model + labor + LEI all agree
        if prob > 70 and (unrate_rising or lei_negative):
            confirming = [f"Recession probability {prob:.0f}%"]
            if unrate_rising:
                confirming.append("Unemployment rising")
            if lei_negative:
                confirming.append("LEI contracting")
            if len(confirming) >= 2:
                return _make(
                    "Contraction", "High", confirming,
                    "Multiple indicators confirm economic contraction.",
                )

        # PEAK — probability above 50%, LEI turning negative
        if prob > 50 and lei_negative:
            confirming = [f"Recession probability {prob:.0f}%", "LEI contracting"]
            if yield_inverted:
                confirming.append("Yield curve inverted")
            confidence = "High" if len(confirming) >= 3 else "Medium"
            return _make(
                "Peak", confidence, confirming,
                "Conditions consistent with a cycle peak. Risk elevated; contraction signal accumulating.",
            )

        # PEAK — probability above 50%, yield inverted (2 signals)
        if prob > 50 and yield_inverted:
            confirming = [f"Recession probability {prob:.0f}%", "Yield curve inverted"]
            return _make(
                "Peak", "Medium", confirming,
                "Probability elevated and yield curve inverted. LEI confirmation would strengthen call.",
            )

        # LATE EXPANSION — probability 30–50%, at least one other signal
        if prob > 30:
            confirming = [f"Recession probability {prob:.0f}%"]
            if yield_inverted:
                confirming.append("Yield curve inverted")
            if lei_negative:
                confirming.append("LEI turning negative")
            if len(confirming) >= 2:
                confidence = "High" if len(confirming) >= 3 else "Medium"
                return _make(
                    "Late Expansion", confidence, confirming,
                    "Late-cycle characteristics. Risk building but contraction not yet confirmed.",
                )
            return _make(
                "Late Expansion", "Low", confirming,
                "Probability elevated but few confirming signals. Monitor closely.",
            )

        # EARLY EXPANSION — low probability, LEI positive, unemployment falling
        if prob < 20 and lei_positive and unrate_falling:
            confirming = [
                f"Recession probability {prob:.0f}%",
                "LEI expanding",
                "Unemployment falling",
            ]
            return _make(
                "Early Expansion", "High", confirming,
                "Strong expansion signals: low recession risk, positive LEI, improving labor market.",
            )

        # EARLY EXPANSION — low probability, LEI positive
        if prob < 20 and lei_positive:
            confirming = [f"Recession probability {prob:.0f}%", "LEI expanding"]
            if unrate_stable:
                confirming.append("Unemployment stable")
            confidence = "High" if len(confirming) >= 3 else "Medium"
            return _make(
                "Early Expansion", confidence, confirming,
                "Early expansion: low recession risk and positive LEI momentum.",
            )

        # EARLY EXPANSION — low probability only
        if prob < 20:
            confirming = [f"Recession probability {prob:.0f}%"]
            if unrate_stable:
                confirming.append("Labor market stable")
            return _make(
                "Early Expansion", "Low", confirming,
                "Low recession risk, but LEI confirmation would strengthen the expansion call.",
            )

        # MID EXPANSION — probability 20–30%, LEI positive
        if prob < 30 and lei_positive:
            confirming = [f"Recession probability {prob:.0f}%", "LEI expanding"]
            if unrate_stable:
                confirming.append("Unemployment stable")
            confidence = "High" if len(confirming) >= 2 else "Medium"
            return _make(
                "Mid Expansion", confidence, confirming,
                "Mid-cycle expansion: healthy conditions, no near-term recession risk.",
            )

        # DEFAULT
        return _make(
            "Mid Expansion", "Low",
            [f"Recession probability {prob:.0f}%"],
            "Default mid-expansion assignment. Additional confirming data would raise confidence.",
        )

    result = _classify()

    return _apply_data_quality_cap(result, model_output)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make(
    phase: str,
    confidence: str,
    confirming: list[str],
    notes: str,
) -> CyclePhaseOutput:
    return CyclePhaseOutput(
        phase                 = phase,
        color                 = PHASE_COLORS.get(phase, "#95a5a6"),
        emoji                 = PHASE_EMOJIS.get(phase, "⚪"),
        confidence            = confidence,
        confirming_indicators = confirming,
        notes                 = notes,
    )


# High-weight threshold: features at or above this weight are considered
# material enough to degrade confidence if stale.
_HIGH_WEIGHT_THRESHOLD = 0.10

_CONFIDENCE_RANK = {"High": 2, "Medium": 1, "Low": 0}
_CONFIDENCE_LABEL = {2: "High", 1: "Medium", 0: "Low"}


def _apply_data_quality_cap(
    result: CyclePhaseOutput,
    model_output: RecessionModelOutput,
) -> CyclePhaseOutput:
    """
    Cap phase confidence based on how many high-weight features are stale.

    Rules:
      - 1 stale high-weight feature  → cap confidence at Medium
      - 2+ stale high-weight features → cap confidence at Low
      - Appends a data-quality note when a cap is applied.
      - NBER-declared contractions are exempt (authoritative single signal).
    """
    if result.phase == "Contraction" and "NBER recession declared" in result.confirming_indicators:
        return result  # NBER is authoritative — no cap needed

    stale_high_weight = [
        f.name for f in model_output.features
        if f.is_stale and f.weight >= _HIGH_WEIGHT_THRESHOLD
    ]

    if not stale_high_weight:
        return result

    n_stale = len(stale_high_weight)
    cap_rank = 1 if n_stale == 1 else 0   # 1 stale → Medium cap; 2+ → Low cap
    current_rank = _CONFIDENCE_RANK.get(result.confidence, 1)

    if current_rank <= cap_rank:
        return result  # already at or below the cap — no change needed

    capped_confidence = _CONFIDENCE_LABEL[cap_rank]
    stale_names = ", ".join(stale_high_weight)
    data_note = (
        f" ⚠️ Confidence capped at {capped_confidence}: "
        f"{n_stale} high-weight input{'s' if n_stale > 1 else ''} "
        f"{'are' if n_stale > 1 else 'is'} stale ({stale_names})."
    )

    return CyclePhaseOutput(
        phase                 = result.phase,
        color                 = result.color,
        emoji                 = result.emoji,
        confidence            = capped_confidence,
        confirming_indicators = result.confirming_indicators,
        notes                 = result.notes + data_note,
    )
