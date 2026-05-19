"""
components/rebalancer.py
=========================
Cycle-informed portfolio rebalancing engine for Pie360.

Given a user's current portfolio weights, their ticker classifications
(sector + asset class), and the current macro cycle phase, this module
computes cycle-aligned suggested weights and produces a structured
rebalancing plan.

Algorithm
---------
Each ticker is assigned a tilt multiplier based on:
  1. Its asset class (Equity, Bond, Commodity, Cash, Real Estate, Crypto)
  2. Within Equity — whether the sector is cyclical, defensive, or neutral

Suggested weight = current weight × tilt multiplier
Then all suggested weights are normalised to sum to 100%.

This approach naturally preserves relative ordering within groups and
produces proportionate, actionable deltas regardless of portfolio shape.

Public API
----------
    from components.rebalancer import CYCLE_PHASES, compute_plan, plan_to_dataframe

    plan = compute_plan(weights, classifications, "Late / Peak")
    df   = plan_to_dataframe(plan)
"""

from __future__ import annotations

import pandas as pd

# ── Cycle phase options ───────────────────────────────────────────────────────

CYCLE_PHASES: list[str] = [
    "Early / Recovery",
    "Mid / Expansion",
    "Late / Peak",
    "Contraction",
]

# ── Sector taxonomy ───────────────────────────────────────────────────────────
# Used to route equity positions into cyclical / defensive / neutral buckets.

CYCLICAL_SECTORS: frozenset[str] = frozenset({
    "Technology",
    "Consumer Discretionary",
    "Consumer Cyclical",
    "Industrials",
    "Materials",
    "Basic Materials",
    "Energy",
    "Financials",
    "Financial Services",
    "Disruptive Innovation",
    "Next Generation Internet",
    "Genomics",
    "China Technology",
    "China Equity",
    "Emerging Markets",       # higher beta, treated as cyclical
    "Small Cap Equity",
    "Mid Cap Equity",
})

DEFENSIVE_SECTORS: frozenset[str] = frozenset({
    "Healthcare",
    "Utilities",
    "Consumer Staples",
    "Consumer Defensive",
    "Communication Services",
    "Communication",
    "Real Estate",             # REIT income stream is defensive-ish
    "Aggregate Bonds",
    "Investment Grade Bonds",
    "Inflation-Protected Bonds",
})

# Everything else (Broad Equity, International Developed, etc.) is "neutral"


def _equity_bucket(sector: str) -> str:
    """Return 'cyclical', 'defensive', or 'neutral' for an equity sector."""
    if sector in CYCLICAL_SECTORS:
        return "cyclical"
    if sector in DEFENSIVE_SECTORS:
        return "defensive"
    return "neutral"


# ── Tilt multiplier tables ────────────────────────────────────────────────────
# Each multiplier is applied to the current weight before normalisation.
#
# Calibration notes
# -----------------
# Multipliers are set so that a 60/40 portfolio in Contraction shifts to
# roughly 45/47/8 (equity/bond/cash), matching typical recession playbooks.
# Late/Peak equity cyclicals land ~15% below current weight after normalisation
# — consistent with a "reduce overweights, add defensives" tilt.
#
# Keys: asset class strings (exact matches from ticker_classifier.py) plus
# three special equity sub-keys: Equity_cyclical, Equity_defensive, Equity_neutral.

_TILTS: dict[str, dict[str, float]] = {
    "Early / Recovery": {
        "Equity_cyclical":         1.15,   # add cyclicals — early upturn benefits
        "Equity_defensive":        0.88,   # trim defensives — expensive in recovery
        "Equity_neutral":          1.05,
        "Bond":                    0.88,   # bonds less attractive as risk appetite rises
        "Commodity":               1.12,   # commodities re-price in recovery
        "Cash":                    0.82,   # deploy cash
        "Real Estate":             1.02,
        "Crypto":                  1.08,   # high-beta assets benefit
    },
    "Mid / Expansion": {
        "Equity_cyclical":         1.08,
        "Equity_defensive":        0.94,
        "Equity_neutral":          1.03,
        "Bond":                    0.94,
        "Commodity":               1.06,
        "Cash":                    0.86,
        "Real Estate":             1.06,
        "Crypto":                  1.04,
    },
    "Late / Peak": {
        "Equity_cyclical":         0.84,   # trim cyclicals — margin pressure approaching
        "Equity_defensive":        1.16,   # rotate into defensives
        "Equity_neutral":          0.95,
        "Bond":                    1.14,   # duration starts to pay as growth slows
        "Commodity":               1.10,   # inflation hedge, especially gold
        "Cash":                    1.12,   # rebuild dry powder
        "Real Estate":             0.90,   # cap-rate risk as rates stay high
        "Crypto":                  0.84,
    },
    "Contraction": {
        "Equity_cyclical":         0.68,   # sharp reduction in cyclicals
        "Equity_defensive":        1.10,   # defensives hold up; don't overcrowd
        "Equity_neutral":          0.80,
        "Bond":                    1.32,   # flight to quality — long bonds rally
        "Commodity":               1.15,   # gold as safe haven
        "Cash":                    1.28,   # maximum dry powder
        "Real Estate":             0.75,   # credit tightening hits REITs
        "Crypto":                  0.68,
    },
}

# ── Public aliases (imported by pages/11_Watchlist.py) ───────────────────────

#: Public view of the tilt multiplier table — keyed by cycle phase, then bucket.
TILT_MULTIPLIERS: dict[str, dict[str, float]] = _TILTS

#: Human-readable labels for each bucket key used in TILT_MULTIPLIERS.
TILT_BUCKET_LABELS: dict[str, str] = {
    "Equity_cyclical":  "Equity – Cyclical",
    "Equity_defensive": "Equity – Defensive",
    "Equity_neutral":   "Equity – Neutral",
    "Bond":             "Bonds",
    "Commodity":        "Commodities",
    "Cash":             "Cash & T-bills",
    "Real Estate":      "Real Estate / REITs",
    "Crypto":           "Crypto",
}

# ── Action thresholds ─────────────────────────────────────────────────────────

_ACTION_REQUIRED_THRESHOLD = 5.0    # |delta| ≥ this → Action Required
_MINOR_MOVE_THRESHOLD      = 2.0    # |delta| ≥ this → Minor move


def _action_tag(delta: float) -> str:
    """Return a human-readable action tag for a given weight delta."""
    if delta >= _ACTION_REQUIRED_THRESHOLD:
        return "🟢 Add"
    if delta <= -_ACTION_REQUIRED_THRESHOLD:
        return "🔴 Trim"
    if delta >= _MINOR_MOVE_THRESHOLD:
        return "🟡 Minor add"
    if delta <= -_MINOR_MOVE_THRESHOLD:
        return "🟡 Minor trim"
    return "⚪ Hold"


# ── Core engine ───────────────────────────────────────────────────────────────

def compute_plan(
    weights: dict[str, float],
    classifications: dict[str, dict[str, str]],
    cycle_phase: str,
) -> dict[str, dict]:
    """
    Compute cycle-informed suggested weights for each position.

    Args:
        weights:         {ticker: current_weight_pct}  — must sum to ~100.
        classifications: {ticker: {"sector": ..., "asset_class": ...}}
        cycle_phase:     One of CYCLE_PHASES.

    Returns:
        {
          ticker: {
            "current":     float,   # original weight %
            "suggested":   float,   # cycle-adjusted weight %
            "delta":       float,   # suggested - current
            "action":      str,     # e.g. "🔴 Trim"
            "sector":      str,
            "asset_class": str,
            "bucket":      str,     # "cyclical" | "defensive" | "neutral" | asset_class
          }
        }
    """
    tilts = _TILTS.get(cycle_phase, {})
    if not tilts:
        # Unknown phase — return unchanged
        return {
            t: {
                "current":     round(w, 1),
                "suggested":   round(w, 1),
                "delta":       0.0,
                "action":      "⚪ Hold",
                "sector":      classifications.get(t, {}).get("sector", "Unknown"),
                "asset_class": classifications.get(t, {}).get("asset_class", "Equity"),
                "bucket":      "neutral",
            }
            for t, w in weights.items()
        }

    # ── Pass 1: apply tilt multipliers ───────────────────────────────────────
    raw: dict[str, float] = {}
    meta: dict[str, dict] = {}

    for ticker, current_w in weights.items():
        clf       = classifications.get(ticker, {})
        ac        = clf.get("asset_class", "Equity")
        sector    = clf.get("sector", "Unknown")

        if ac == "Equity":
            bucket     = _equity_bucket(sector)
            tilt_key   = f"Equity_{bucket}"
        else:
            bucket     = ac
            tilt_key   = ac

        multiplier = tilts.get(tilt_key, 1.0)
        raw[ticker] = max(0.0, current_w * multiplier)
        meta[ticker] = {"sector": sector, "asset_class": ac, "bucket": bucket}

    # ── Pass 2: normalise to 100 % ────────────────────────────────────────────
    total_raw = sum(raw.values())
    if total_raw <= 0:
        # Edge case: all weights are zero — return as-is
        return {t: {"current": 0.0, "suggested": 0.0, "delta": 0.0,
                    "action": "⚪ Hold", **meta.get(t, {})} for t in weights}

    scale = 100.0 / total_raw

    # ── Pass 3: build result ──────────────────────────────────────────────────
    result: dict[str, dict] = {}
    for ticker, current_w in weights.items():
        suggested = round(raw[ticker] * scale, 1)
        delta     = round(suggested - current_w, 1)
        result[ticker] = {
            "current":     round(current_w, 1),
            "suggested":   suggested,
            "delta":       delta,
            "action":      _action_tag(delta),
            **meta[ticker],
        }

    # ── Pass 4: fix rounding so suggested weights sum exactly to 100.0 ────────
    total_suggested = sum(r["suggested"] for r in result.values())
    rounding_error  = round(100.0 - total_suggested, 1)
    if rounding_error != 0.0 and result:
        # Apply the residual to the largest position
        largest = max(result, key=lambda t: result[t]["suggested"])
        result[largest]["suggested"] = round(
            result[largest]["suggested"] + rounding_error, 1
        )
        result[largest]["delta"] = round(
            result[largest]["suggested"] - result[largest]["current"], 1
        )
        result[largest]["action"] = _action_tag(result[largest]["delta"])

    return result


# ── DataFrame helper ──────────────────────────────────────────────────────────

def plan_to_dataframe(plan: dict[str, dict]) -> pd.DataFrame:
    """
    Convert a rebalancing plan dict to a display-ready DataFrame.
    Sorted by action priority: Trims first, then Adds, then Holds.
    """
    rows = []
    for ticker, p in plan.items():
        rows.append({
            "Ticker":       ticker,
            "Sector":       p.get("sector", "—"),
            "Asset Class":  p.get("asset_class", "—"),
            "Current %":    p.get("current", 0.0),
            "Suggested %":  p.get("suggested", 0.0),
            "Δ":            p.get("delta", 0.0),
            "Action":       p.get("action", "⚪ Hold"),
        })

    df = pd.DataFrame(rows)

    # Sort: action-required first (|delta| largest), then minor, then holds
    df["_abs_delta"] = df["Δ"].abs()
    df = df.sort_values("_abs_delta", ascending=False).drop(columns=["_abs_delta"])
    df = df.reset_index(drop=True)
    return df


# ── Cycle phase rationale ─────────────────────────────────────────────────────
# Short text displayed alongside the plan to explain the tilt logic.

PHASE_RATIONALE: dict[str, str] = {
    "Early / Recovery": (
        "**Early / Recovery** — Risk appetite is returning. Cyclical sectors "
        "(technology, industrials, materials) historically outperform as earnings "
        "surprise to the upside. Reduce defensive positioning and deploy cash into "
        "higher-beta assets."
    ),
    "Mid / Expansion": (
        "**Mid / Expansion** — The cycle's sweet spot. Broad equity exposure is "
        "rewarded; commodities benefit from rising demand. Modest reduction in "
        "defensive bond positions as growth expectations remain elevated."
    ),
    "Late / Peak": (
        "**Late / Peak** — Growth is slowing, margins are compressing, and the "
        "Fed is restrictive. Rotate out of cyclicals (technology, industrials) into "
        "defensives (healthcare, utilities, staples). Add duration via bonds and "
        "rebuild cash as a buffer."
    ),
    "Contraction": (
        "**Contraction** — Capital preservation is the priority. Sharply reduce "
        "cyclical equity exposure. Bonds (especially long-duration Treasuries) and "
        "gold typically outperform. Maximum cash provides optionality for the "
        "eventual recovery."
    ),
}
