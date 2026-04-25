"""
Pulse360 Recession Probability Model
=====================================
7-factor weighted logit model. Weights match briefing.md §4 exactly.
Each feature produces a stress score (0 = no stress, 1 = maximum stress)
via a logistic function calibrated to historical recession thresholds.

Output: probability 0–100% + feature contributions visible on screen.
Traffic lights: green <25%, yellow 25–50%, red ≥50%.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np

from data.fred_client import compute_cfnai_signal, compute_icsa_yoy, compute_lei_growth

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FeatureContribution:
    name:              str
    series_id:         str
    weight:            float
    current_value:     Optional[float]   # raw value (units depend on feature)
    stress_score:      float             # 0.0 (calm) → 1.0 (full stress)
    contribution:      float             # weight × stress × 100  (percentage points)
    signal_description: str
    last_date:         Optional[date]
    is_stale:          bool = False
    stale_message:     Optional[str] = None


@dataclass
class RecessionModelOutput:
    probability:    float          # 0–100
    traffic_light:  str            # "green" | "yellow" | "red"
    features:       list = field(default_factory=list)   # list[FeatureContribution]
    data_as_of:     Optional[date] = None
    has_stale_data: bool = False
    stale_features: list = field(default_factory=list)   # list[str]

    @property
    def color(self) -> str:
        return {"green": "#2ecc71", "yellow": "#f39c12", "red": "#e74c3c"}.get(
            self.traffic_light, "#95a5a6"
        )

    @property
    def emoji(self) -> str:
        return {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(self.traffic_light, "⚪")


# ---------------------------------------------------------------------------
# Logistic helper
# ---------------------------------------------------------------------------

def _logistic(x: float, k: float = 1.0) -> float:
    """Standard logistic function, result in [0, 1]."""
    return float(1.0 / (1.0 + np.exp(-k * x)))


# ---------------------------------------------------------------------------
# Per-feature stress functions
# Each returns (stress: float [0-1], description: str)
# ---------------------------------------------------------------------------

def _stress_t10y3m(value: float) -> tuple[float, str]:
    """10Y–3M Treasury spread. Deep inversion → high stress."""
    stress = _logistic(-value / 0.5)
    if value < -0.75:
        desc = f"Deeply inverted ({value:+.2f}%): strong recession signal"
    elif value < 0.0:
        desc = f"Inverted ({value:+.2f}%): recession signal active"
    elif value < 0.5:
        desc = f"Near flat ({value:+.2f}%): mildly cautionary"
    else:
        desc = f"Positive ({value:+.2f}%): no inversion signal"
    return round(stress, 3), desc


def _stress_sahm(value: float) -> tuple[float, str]:
    """Sahm Rule. Trigger at 0.50; stress rises sharply near trigger."""
    stress = _logistic((value - 0.25) / 0.12)
    if value >= 0.50:
        desc = f"Triggered ({value:.2f} ≥ 0.50): recession underway signal"
    elif value >= 0.30:
        desc = f"Elevated ({value:.2f}): approaching 0.50 trigger"
    else:
        desc = f"Benign ({value:.2f}): well below trigger"
    return round(stress, 3), desc


def _stress_cfnai(value: float) -> tuple[float, str]:
    """
    Chicago Fed National Activity Index (3-month avg).
    Threshold: <-0.7 historically associated with recession onset.
    Stress rises as value falls below 0; peaks at -0.7 and below.
    """
    stress = _logistic((-value - 0.1) / 0.3)
    if value < -0.70:
        desc = f"CFNAI {value:+.2f}: below −0.70 recession threshold"
    elif value < -0.35:
        desc = f"CFNAI {value:+.2f}: weakening, approaching recession zone"
    elif value < 0.0:
        desc = f"CFNAI {value:+.2f}: below-trend growth, moderately weak"
    elif value < 0.20:
        desc = f"CFNAI {value:+.2f}: near trend growth"
    else:
        desc = f"CFNAI {value:+.2f}: above-trend growth, expansionary"
    return round(stress, 3), desc


def _stress_nfci(value: float) -> tuple[float, str]:
    """NFCI. Above 0 = tighter-than-average → stress."""
    stress = _logistic(value / 0.25)
    if value > 0.50:
        desc = f"Tight ({value:+.2f}): significantly tightened financial conditions"
    elif value > 0.0:
        desc = f"Slightly tight ({value:+.2f}): modestly tightened"
    elif value > -0.5:
        desc = f"Near neutral ({value:+.2f}): normal conditions"
    else:
        desc = f"Loose ({value:+.2f}): accommodative conditions"
    return round(stress, 3), desc


def _stress_claims_yoy(yoy_pct: float) -> tuple[float, str]:
    """Initial claims YoY %. Rising >15% → high stress."""
    stress = _logistic((yoy_pct - 5.0) / 8.0)
    if yoy_pct > 20.0:
        desc = f"Surging ({yoy_pct:+.1f}% YoY): significant labor market deterioration"
    elif yoy_pct > 10.0:
        desc = f"Rising ({yoy_pct:+.1f}% YoY): elevated and climbing"
    elif yoy_pct > 0.0:
        desc = f"Modest increase ({yoy_pct:+.1f}% YoY): within normal range"
    else:
        desc = f"Declining ({yoy_pct:+.1f}% YoY): improving labor market signal"
    return round(stress, 3), desc


def _stress_hy_oas(value_bps: float) -> tuple[float, str]:
    """HY OAS in basis points. Wide spreads → high stress. Threshold: 700 bps."""
    stress = _logistic((value_bps - 450.0) / 80.0)
    if value_bps > 700:
        desc = f"{value_bps:.0f} bps: at/above recession threshold (700 bps)"
    elif value_bps > 550:
        desc = f"{value_bps:.0f} bps: elevated; approaching stress levels"
    elif value_bps > 400:
        desc = f"{value_bps:.0f} bps: moderate; within normal range"
    else:
        desc = f"{value_bps:.0f} bps: tight; risk-on environment"
    return round(stress, 3), desc


def _stress_ism(value: float) -> tuple[float, str]:
    """ISM Manufacturing PMI. Below 45 → high stress; below 50 = contraction."""
    stress = _logistic((50.0 - value) / 2.5)
    if value < 45.0:
        desc = f"{value:.1f}: deep contraction (below 45 threshold)"
    elif value < 50.0:
        desc = f"{value:.1f}: contraction territory (below 50)"
    elif value < 55.0:
        desc = f"{value:.1f}: modest expansion"
    else:
        desc = f"{value:.1f}: strong expansion"
    return round(stress, 3), desc


# ---------------------------------------------------------------------------
# Feature configuration
# Weights must sum to exactly 1.0 — matches briefing.md §4
# ---------------------------------------------------------------------------

_FEATURES = [
    {
        "name":      "10Y–3M Treasury Spread",
        "series_id": "T10Y3M",
        "weight":    0.30,
        "stress_fn": _stress_t10y3m,
        "get_value": lambda inp: inp["T10Y3M"]["last_value"],
        "get_date":  lambda inp: inp["T10Y3M"]["last_date"],
        "get_stale": lambda inp: (inp["T10Y3M"]["is_stale"], inp["T10Y3M"].get("stale_message")),
    },
    {
        "name":      "Sahm Rule",
        "series_id": "SAHMREALTIME",
        "weight":    0.20,
        "stress_fn": _stress_sahm,
        "get_value": lambda inp: inp["SAHMREALTIME"]["last_value"],
        "get_date":  lambda inp: inp["SAHMREALTIME"]["last_date"],
        "get_stale": lambda inp: (inp["SAHMREALTIME"]["is_stale"], inp["SAHMREALTIME"].get("stale_message")),
    },
    {
        "name":      "CFNAI (Activity Index)",
        "series_id": "CFNAI",
        "weight":    0.15,
        "stress_fn": _stress_cfnai,
        "get_value": lambda inp: compute_cfnai_signal(inp["CFNAI"]["data"]),
        "get_date":  lambda inp: inp["CFNAI"]["last_date"],
        "get_stale": lambda inp: (inp["CFNAI"]["is_stale"], inp["CFNAI"].get("stale_message")),
    },
    {
        "name":      "Chicago Fed NFCI",
        "series_id": "NFCI",
        "weight":    0.10,
        "stress_fn": _stress_nfci,
        "get_value": lambda inp: inp["NFCI"]["last_value"],
        "get_date":  lambda inp: inp["NFCI"]["last_date"],
        "get_stale": lambda inp: (inp["NFCI"]["is_stale"], inp["NFCI"].get("stale_message")),
    },
    {
        "name":      "Initial Claims YoY",
        "series_id": "ICSA",
        "weight":    0.10,
        "stress_fn": _stress_claims_yoy,
        "get_value": lambda inp: compute_icsa_yoy(inp["ICSA"]["data"]),
        "get_date":  lambda inp: inp["ICSA"]["last_date"],
        "get_stale": lambda inp: (inp["ICSA"]["is_stale"], inp["ICSA"].get("stale_message")),
    },
    {
        "name":      "High-Yield OAS",
        "series_id": "BAMLH0A0HYM2",
        "weight":    0.10,
        "stress_fn": _stress_hy_oas,
        "get_value": lambda inp: inp["BAMLH0A0HYM2"]["last_value"],
        "get_date":  lambda inp: inp["BAMLH0A0HYM2"]["last_date"],
        "get_stale": lambda inp: (inp["BAMLH0A0HYM2"]["is_stale"], inp["BAMLH0A0HYM2"].get("stale_message")),
    },
    {
        "name":      "ISM Manufacturing PMI",
        "series_id": "NAPM",
        "weight":    0.05,
        "stress_fn": _stress_ism,
        "get_value": lambda inp: inp["NAPM"]["last_value"],
        "get_date":  lambda inp: inp["NAPM"]["last_date"],
        "get_stale": lambda inp: (inp["NAPM"]["is_stale"], inp["NAPM"].get("stale_message")),
    },
]

assert abs(sum(f["weight"] for f in _FEATURES) - 1.0) < 1e-9, "Feature weights must sum to 1.0"


# ---------------------------------------------------------------------------
# Model entry point
# ---------------------------------------------------------------------------

def run_recession_model(inputs: dict) -> RecessionModelOutput:
    """
    Run the 7-factor weighted logit recession probability model.

    Args:
        inputs: dict of series_id → fetch_series() result (from fetch_model_inputs())

    Returns:
        RecessionModelOutput with probability, traffic light, and full feature breakdown.

    Notes:
        - If a feature value is unavailable, the model substitutes neutral stress (0.5)
          and flags the feature as uncertain.
        - Weights are locked per briefing.md §4 — do not change without updating that doc.
    """
    features:       list[FeatureContribution] = []
    weighted_stress: float = 0.0
    stale_features: list[str] = []
    dates:          list[date] = []

    for cfg in _FEATURES:
        value      = cfg["get_value"](inputs)
        last_date  = cfg["get_date"](inputs)
        is_stale, stale_msg = cfg["get_stale"](inputs)

        if value is None:
            stress = 0.5
            desc   = "Data unavailable — neutral (0.5) stress assumed"
        else:
            stress, desc = cfg["stress_fn"](float(value))

        contribution   = cfg["weight"] * stress * 100
        weighted_stress += cfg["weight"] * stress

        if last_date:
            dates.append(last_date)
        if is_stale:
            stale_features.append(cfg["name"])

        features.append(FeatureContribution(
            name               = cfg["name"],
            series_id          = cfg["series_id"],
            weight             = cfg["weight"],
            current_value      = value,
            stress_score       = stress,
            contribution       = round(contribution, 2),
            signal_description = desc,
            last_date          = last_date,
            is_stale           = is_stale,
            stale_message      = stale_msg,
        ))

    probability = round(weighted_stress * 100, 1)

    if probability < 25.0:
        traffic_light = "green"
    elif probability < 50.0:
        traffic_light = "yellow"
    else:
        traffic_light = "red"

    return RecessionModelOutput(
        probability    = probability,
        traffic_light  = traffic_light,
        features       = features,
        data_as_of     = max(dates) if dates else None,
        has_stale_data = bool(stale_features),
        stale_features = stale_features,
    )
