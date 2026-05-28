"""
components/prompts.py — DEPRECATED SHIM
=========================================
Renamed to components/forecaster_prompts.py (2026-05-28).
This file re-exports everything so any stale import keeps working.
Remove this file once all callers are updated.
"""
from components.forecaster_prompts import (  # noqa: F401
    REFRESH_PROMPT,
    REFRESH_TIMEOUT_SECS,
    STALE_DAYS,
    build_review_prompt,
    run_deep_dive,
    stream_review,
    refresh_signals,
)
