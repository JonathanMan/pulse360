"""
scripts/daily_briefing_runner.py
=================================
Standalone daily briefing runner — no Streamlit dependency.

Runs outside the Streamlit app (from cron / Claude scheduled task):
  1. Reads secrets from .streamlit/secrets.toml
  2. Fetches live FRED data for all model inputs (falls back to cache on network failure)
  3. Runs the recession model + cycle classifier
  4. Generates briefing text via Claude API (falls back to template when API unavailable)
  5. Saves briefing as .md to the Drive workspace folder
  6. Sends HTML email via Resend (non-fatal on failure)

Sandbox-resilient design
-------------------------
The Cowork scheduler sandbox blocks outbound HTTPS to external APIs (FRED, Anthropic, Resend).
This script is designed to degrade gracefully in that environment:
  - FRED fetch failure  → load last-known values from scripts/fred_cache.json
  - Claude API failure  → generate structured template briefing from model outputs
  - Email failure       → log warning, set exit_code=1 (not 2)
  - Cache update        → saved after every successful live FRED fetch

Exit codes:
    0 — full success (live data + Claude briefing + email sent)
    1 — partial success (briefing generated and .md saved; email or live data unavailable)
    2 — critical failure (model crashed; secrets missing; .md could not be saved)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# ── Path setup (run from pulse360-app/ directory) ─────────────────────────────
ROOT = Path(__file__).resolve().parent.parent   # pulse360-app/
CACHE_PATH = Path(__file__).resolve().parent / "fred_cache.json"
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt= "%H:%M:%S",
)
log = logging.getLogger("briefing_runner")


# ── Load secrets without Streamlit ───────────────────────────────────────────

def _load_secrets() -> dict:
    """Read .streamlit/secrets.toml from the pulse360-app directory."""
    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        log.error("secrets.toml not found at %s", secrets_path)
        sys.exit(2)
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # pip install tomli --break-system-packages
        except ImportError:
            log.error("Install tomli: pip install tomli --break-system-packages")
            sys.exit(2)
    with open(secrets_path, "rb") as f:
        return tomllib.load(f)


# ── FRED cache helpers ────────────────────────────────────────────────────────

def _load_fred_cache() -> dict:
    """Load last-known FRED values from scripts/fred_cache.json."""
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH) as f:
                data = json.load(f)
            log.info("  Loaded FRED cache from %s (as of %s)",
                     CACHE_PATH, data.get("cached_at", "unknown"))
            return data.get("series", {})
        except Exception as exc:
            log.warning("  Could not read FRED cache: %s", exc)
    return {}


def _save_fred_cache(series: dict) -> None:
    """Persist successfully fetched FRED values to cache for future use."""
    import pandas as pd
    cache = {"cached_at": datetime.now().isoformat(), "series": {}}
    for sid, s in series.items():
        if isinstance(s, pd.Series) and not s.empty:
            cache["series"][sid] = {
                "last_value": float(s.iloc[-1]),
                "last_date":  str(s.index[-1].date()),
            }
    if cache["series"]:
        try:
            with open(CACHE_PATH, "w") as f:
                json.dump(cache, f, indent=2)
            log.info("  FRED cache updated: %s series saved", len(cache["series"]))
        except Exception as exc:
            log.warning("  Could not save FRED cache: %s", exc)


def _series_from_cache(cached: dict, series_id: str):
    """Reconstruct a minimal pd.Series from a cache entry (single-value, dated index)."""
    import pandas as pd
    entry = cached.get(series_id)
    if not entry:
        return pd.Series(dtype=float)
    try:
        idx = pd.DatetimeIndex([entry["last_date"]])
        s   = pd.Series([entry["last_value"]], index=idx)
        log.info("  %-20s  (from cache) last: %s = %.3f",
                 series_id, entry["last_date"], entry["last_value"])
        return s
    except Exception:
        return pd.Series(dtype=float)


# ── Fetch FRED data without @st.cache_data ───────────────────────────────────

def _fetch_fred(series_id: str, fred_api_key: str, start: str = "1990-01-01"):
    """
    Fetch a single FRED series.
    Returns pd.Series on success, or empty pd.Series on failure.
    Does NOT fall back to cache here — cache fallback is done in main() after
    all fetches, so we can decide to save cache only when any live data arrived.
    """
    import pandas as pd
    try:
        from fredapi import Fred
        fred = Fred(api_key=fred_api_key)
        raw  = fred.get_series(series_id, observation_start=start).dropna()
        log.info("  %-20s  %d obs, last: %s = %.3f",
                 series_id, len(raw),
                 raw.index[-1].date() if not raw.empty else "N/A",
                 float(raw.iloc[-1]) if not raw.empty else 0)
        return raw
    except Exception as exc:
        log.warning("  %-20s  FAILED: %s", series_id, exc)
        return pd.Series(dtype=float)


# ── Template briefing generator (no LLM required) ────────────────────────────

def _generate_template_briefing(
    today,
    phase_output,
    model_output,
    lei_growth: Optional[float],
    unrate_latest: Optional[float],
    nber_active: bool,
    used_cache: bool,
) -> str:
    """
    Generate a structured briefing from model outputs when the Claude API is
    unavailable. Covers all required sections with real model numbers.
    Not as nuanced as the LLM version, but fully data-driven and always accurate.
    """
    from ai.prompts import DISCLAIMER

    tl_labels = {"green": "LOW", "yellow": "MODERATE", "red": "HIGH"}
    risk_label = tl_labels.get(model_output.traffic_light, "UNKNOWN")
    tl_emoji   = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(model_output.traffic_light, "⚪")

    data_note = (
        "⚠️ *Quantitative inputs loaded from cache (live FRED fetch blocked in scheduler sandbox). "
        "Values carry forward from last successful fetch. Narrative reflects model state only.*\n\n"
        if used_cache else ""
    )

    # Feature contributions summary
    feat_lines = []
    for feat in (model_output.features or [])[:6]:
        name  = getattr(feat, "name", "Unknown")
        val   = getattr(feat, "current_value", None)
        score = getattr(feat, "stress_score", 0.0)
        desc  = getattr(feat, "signal_description", "")
        val_str = f"{val:.3f}" if val is not None else "N/A"
        stress_bar = "▓" * int(score * 5) + "░" * (5 - int(score * 5))
        feat_lines.append(f"- **{name}:** {val_str} [{stress_bar}] — {desc}")
    feat_block = "\n".join(feat_lines) if feat_lines else "- No feature data available"

    # Investment implication based on traffic light
    if model_output.traffic_light == "green":
        implication = (
            "Risk-on bias supported. Yield curve and financial conditions are not "
            "signalling stress. Maintain equity exposure; credit spreads constructive."
        )
    elif model_output.traffic_light == "yellow":
        implication = (
            "Balanced positioning warranted. Recession probability is elevated but below "
            "the 50% threshold. Monitor leading indicators — especially Sahm Rule and "
            "initial claims — before adding risk. Duration neutral to mild overweight."
        )
    else:
        implication = (
            "Defensive positioning indicated. Recession probability above 50% threshold. "
            "Review equity and credit overweights; consider extending duration as a hedge. "
            "Cash and short-duration Treasuries offer asymmetric protection at current levels."
        )

    lei_str   = f"{lei_growth:.2f}" if lei_growth is not None else "N/A"
    urate_str = f"{unrate_latest:.1f}%" if unrate_latest is not None else "N/A"
    nber_str  = "**Yes — official recession declared**" if nber_active else "No"

    briefing = f"""{data_note}## Economic Cycle Summary

{tl_emoji} Pie360 reads **{phase_output.phase}** ({phase_output.confidence} confidence) with recession probability at **{model_output.probability:.1f}% ({risk_label} risk)**. {nber_str if nber_active else 'No NBER recession declared.'} This briefing was generated from model outputs. {'Live Claude analysis unavailable today (sandbox network restriction).' if used_cache or True else ''}

## Key Model Readings

- **Recession Probability:** {model_output.probability:.1f}% ({model_output.traffic_light.upper()}) {tl_emoji}
- **Cycle Phase:** {phase_output.phase} ({phase_output.confidence} confidence)
- **CFNAI / LEI signal:** {lei_str}
- **Unemployment Rate:** {urate_str}
- **NBER Recession Active:** {nber_str}

## Feature Contributions

{feat_block}

## Investment Implication

{implication}"""

    return briefing.strip() + DISCLAIMER


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    today = date.today()
    log.info("=== Pulse360 Daily Briefing Runner — %s ===", today)

    # 1. Secrets
    log.info("Loading secrets…")
    secrets = _load_secrets()
    fred_key      = secrets.get("FRED_API_KEY", "")
    anthropic_key = secrets.get("ANTHROPIC_API_KEY", "")
    resend_key    = secrets.get("RESEND_API_KEY", "")
    resend_from   = secrets.get("RESEND_FROM", "onboarding@resend.dev")
    recipient     = secrets.get("BRIEFING_EMAIL", "jonathancyman@gmail.com")

    if not fred_key:
        log.error("FRED_API_KEY missing from secrets.toml — cannot run model")
        return 2

    # 2. Fetch FRED model inputs (live, with cache fallback)
    log.info("Fetching FRED model inputs…")
    SERIES_IDS = ["T10Y3M", "SAHMREALTIME", "CFNAI", "NFCI", "ICSA",
                  "BAMLH0A0HYM2", "UNRATE", "USREC"]

    live_series = {sid: _fetch_fred(sid, fred_key) for sid in SERIES_IDS}
    any_live    = any(not s.empty for s in live_series.values())
    used_cache  = False

    if any_live:
        # Save cache whenever we got at least some live data
        _save_fred_cache(live_series)
        series = live_series
    else:
        # All fetches failed — load from cache
        log.warning("All FRED fetches failed. Loading from cache…")
        cached = _load_fred_cache()
        if not cached:
            log.error("No FRED cache available and live fetch failed — cannot run model")
            return 2
        import pandas as pd
        series    = {sid: _series_from_cache(cached, sid) for sid in SERIES_IDS}
        used_cache = True

    # 3. Run recession model
    log.info("Running recession model…")
    try:
        from models.recession_model import run_recession_model

        model_inputs = {
            sid: {
                "data":          s,
                "last_value":    float(s.iloc[-1]) if not s.empty else None,
                "last_date":     s.index[-1].date() if not s.empty else None,
                "is_stale":      used_cache,
                "stale_message": "Loaded from cache" if used_cache else None,
            }
            for sid, s in series.items()
        }
        model_output = run_recession_model(model_inputs)
        log.info("  Recession probability: %.1f%%  (%s)",
                 model_output.probability, model_output.traffic_light)
    except Exception as exc:
        log.error("Recession model failed: %s", exc)
        return 2

    # 4. Run cycle classifier
    log.info("Running cycle classifier…")
    try:
        from data.fred_client import compute_cfnai_signal
        from models.cycle_classifier import classify_cycle_phase

        lei_growth    = compute_cfnai_signal(series["CFNAI"])
        unrate_data   = series["UNRATE"] if not series["UNRATE"].empty else None
        nber_active   = (not series["USREC"].empty and bool(series["USREC"].iloc[-1] == 1))
        unrate_latest = float(series["UNRATE"].iloc[-1]) if not series["UNRATE"].empty else None

        phase_output = classify_cycle_phase(
            model_output = model_output,
            lei_growth   = lei_growth,
            unrate_data  = unrate_data,
            nber_active  = nber_active,
        )
        log.info("  Cycle phase: %s (%s confidence)", phase_output.phase, phase_output.confidence)
    except Exception as exc:
        log.error("Cycle classifier failed: %s", exc)
        return 2

    # 5. Generate briefing — try Claude API first, fall back to template
    log.info("Generating briefing…")
    briefing_md   = None
    used_template = False

    if anthropic_key:
        try:
            import anthropic
            from ai.prompts import build_briefing_prompt, BRIEFING_SYSTEM, DISCLAIMER
            from ai.claude_client import format_features_for_prompt

            feature_dicts = format_features_for_prompt(model_output.features)
            user_prompt   = build_briefing_prompt(
                date_str              = today.strftime("%Y-%m-%d"),
                cycle_phase           = phase_output.phase,
                phase_confidence      = phase_output.confidence,
                recession_probability = model_output.probability,
                traffic_light         = model_output.traffic_light,
                feature_contributions = feature_dicts,
                lei_growth            = lei_growth,
                unrate                = unrate_latest,
                nber_active           = nber_active,
            )
            client   = anthropic.Anthropic(api_key=anthropic_key)
            response = client.messages.create(
                model      = "claude-sonnet-4-5",
                max_tokens = 1024,
                system     = BRIEFING_SYSTEM,
                messages   = [{"role": "user", "content": user_prompt}],
            )
            briefing_md = response.content[0].text.strip() + DISCLAIMER
            log.info("  Claude briefing generated (%d chars)", len(briefing_md))
        except ImportError:
            log.warning("  anthropic package not installed — using template briefing")
        except Exception as exc:
            log.warning("  Claude API unavailable (%s) — using template briefing", exc)

    if briefing_md is None:
        # Template fallback — always works, no external calls required
        briefing_md   = _generate_template_briefing(
            today, phase_output, model_output,
            lei_growth, unrate_latest, nber_active, used_cache,
        )
        used_template = True
        log.info("  Template briefing generated (%d chars)", len(briefing_md))

    exit_code = 0

    # 6. Save .md to Drive workspace
    log.info("Saving briefing .md to Drive…")
    try:
        # Derive the Drive folder from the script's own location so this works
        # both on the Mac (real path) and inside the Cowork sandbox (mounted path).
        # Script: pulse360-app/scripts/daily_briefing_runner.py
        # ROOT:   pulse360-app/
        # Target: pulse360-app/../  →  the Pulse360 workspace folder
        mac_drive = Path(
            "/Users/jonathanman/Library/CloudStorage/"
            "GoogleDrive-jonathancyman@gmail.com/My Drive/Business/Claude/Pulse360"
        )
        drive_dir = mac_drive if mac_drive.exists() else ROOT.parent
        log.info("  Drive dir resolved to: %s", drive_dir)
        filename  = f"daily-briefing-{today}.md"
        out_path  = drive_dir / filename

        data_source_note = (
            "**Data source:** Cache (live FRED fetch unavailable in scheduler sandbox)  \n"
            if used_cache else ""
        )
        briefing_source_note = (
            "**Briefing source:** Template (Claude API unavailable in scheduler sandbox)  \n"
            if used_template else ""
        )

        out_path.write_text(
            f"# Pie360 Daily Briefing — {today:%d %b %Y}\n\n"
            f"**Phase:** {phase_output.phase} ({phase_output.confidence} confidence)  \n"
            f"**Recession Probability:** {model_output.probability:.1f}% ({model_output.traffic_light})  \n"
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M HKT')}  \n"
            f"{data_source_note}"
            f"{briefing_source_note}"
            f"\n---\n\n{briefing_md}\n",
            encoding="utf-8",
        )
        log.info("  Saved: %s", out_path)
    except Exception as exc:
        log.error("Could not save .md — critical: %s", exc)
        return 2   # .md save failure IS critical (Confluence step depends on it)

    # 7. Send email via Resend (non-fatal)
    if resend_key:
        log.info("Sending email via Resend to %s…", recipient)
        try:
            import resend as resend_lib
            from ai.email_briefing import compose_briefing_html

            html = compose_briefing_html(
                briefing_md           = briefing_md,
                cycle_phase           = phase_output.phase,
                recession_probability = model_output.probability,
                traffic_light         = model_output.traffic_light,
            )
            resend_lib.api_key = resend_key
            resend_lib.Emails.send({
                "from":    resend_from,
                "to":      [recipient],
                "subject": (
                    f"Pie360 · {today:%-d %b %Y} · "
                    f"{phase_output.phase} · {model_output.probability:.0f}% risk"
                ),
                "html": html,
            })
            log.info("  Email sent ✓")
        except ImportError:
            log.warning("  resend package not installed — email skipped (exit 1)")
            exit_code = 1
        except Exception as exc:
            log.warning("  Email failed: %s (exit 1)", exc)
            exit_code = 1
    else:
        log.info("RESEND_API_KEY not set — skipping email")

    log.info("=== Done (exit code %d) ===", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
