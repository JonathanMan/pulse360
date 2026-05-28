"""
components/observability.py
============================
T3-5: Centralised observability for Pie360.

Three layers
------------
1. Structured logging  — Python stdlib logging with JSON formatter
                         (writes to stderr so Streamlit Cloud captures it)
2. Sentry              — optional; activated when SENTRY_DSN env var is set
                         wraps exceptions at key call sites
3. Usage analytics     — fire-and-forget writes to the `user_analytics`
                         Supabase table; degraded gracefully when unavailable

Public API
----------
    from components.observability import log, track, capture_exception

    log.info("cycle_engine", "phase detected", phase="Mid / Expansion", conf=87)
    track("watchlist_rebalanced", {"cycle_phase": "Mid / Expansion"})
    capture_exception(exc, context={"page": "11_Watchlist"})
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import streamlit as st

# ── 1. Structured logger ──────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "ts":      datetime.now(timezone.utc).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        # Extra fields attached via log.info("name", "msg", key=val)
        for k, v in record.__dict__.items():
            if k not in (
                "args", "asctime", "created", "exc_info", "exc_text",
                "filename", "funcName", "id", "levelname", "levelno",
                "lineno", "message", "module", "msecs", "msg", "name",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "taskName", "thread", "threadName",
            ):
                obj[k] = v
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str)


class _StructuredLogger:
    """
    Thin wrapper so callers can write:
        log.info("cycle_engine", "phase detected", phase="Mid", conf=87)

    The first positional arg becomes the logger name (component scope).
    """

    _loggers: dict[str, logging.Logger] = {}

    def _get(self, name: str) -> logging.Logger:
        if name not in self._loggers:
            logger = logging.getLogger(f"pie360.{name}")
            logger.setLevel(logging.DEBUG)
            if not logger.handlers:
                h = logging.StreamHandler(sys.stderr)
                h.setFormatter(_JsonFormatter())
                logger.addHandler(h)
            logger.propagate = False
            self._loggers[name] = logger
        return self._loggers[name]

    def _emit(self, level: str, name: str, msg: str, **kwargs: Any) -> None:
        logger = self._get(name)
        method = getattr(logger, level)
        # Attach kwargs as LogRecord extras
        method(msg, extra=kwargs, stacklevel=3)

    def debug(self, name: str, msg: str, **kwargs: Any) -> None:
        self._emit("debug", name, msg, **kwargs)

    def info(self, name: str, msg: str, **kwargs: Any) -> None:
        self._emit("info", name, msg, **kwargs)

    def warning(self, name: str, msg: str, **kwargs: Any) -> None:
        self._emit("warning", name, msg, **kwargs)

    def error(self, name: str, msg: str, **kwargs: Any) -> None:
        self._emit("error", name, msg, **kwargs)


log = _StructuredLogger()


# ── 2. Sentry ─────────────────────────────────────────────────────────────────

_sentry_initialised = False

def _init_sentry() -> bool:
    """Initialise Sentry SDK once per process if SENTRY_DSN is set."""
    global _sentry_initialised
    if _sentry_initialised:
        return True

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk  # type: ignore[import]
        sentry_sdk.init(
            dsn=dsn,
            # Only send 10 % of performance traces (errors always sent)
            traces_sample_rate=0.1,
            # Human-readable release tag (set via env var in GH Actions)
            release=os.environ.get("GIT_COMMIT_SHA", "unknown"),
            environment=os.environ.get("PIE360_ENV", "production"),
        )
        _sentry_initialised = True
        log.info("observability", "Sentry initialised")
        return True
    except ImportError:
        log.warning("observability", "sentry_sdk not installed — Sentry disabled")
        return False
    except Exception as exc:
        log.warning("observability", "Sentry init failed", error=str(exc))
        return False


def capture_exception(
    exc: Exception,
    *,
    context: dict[str, Any] | None = None,
    reraise: bool = False,
) -> None:
    """
    Report an exception to Sentry (if configured) and write a structured
    error log line.

    Args:
        exc:      The caught exception.
        context:  Extra key-value pairs added as Sentry tags / log fields.
        reraise:  If True, re-raises the exception after capturing.

    Usage:
        try:
            risky_call()
        except Exception as e:
            capture_exception(e, context={"page": "3_Simulator"})
    """
    ctx = context or {}
    tb  = traceback.format_exc()

    log.error(
        "exception",
        str(exc),
        exc_type=type(exc).__name__,
        traceback=tb,
        **ctx,
    )

    if _init_sentry():
        try:
            import sentry_sdk  # type: ignore[import]
            with sentry_sdk.push_scope() as scope:
                for k, v in ctx.items():
                    scope.set_tag(k, str(v))
            sentry_sdk.capture_exception(exc)
        except Exception:
            pass  # never let observability crash the app

    if reraise:
        raise exc


# ── 3. Usage analytics ────────────────────────────────────────────────────────

_ANALYTICS_TABLE = "user_analytics"
_SESSION_KEY     = "_obs_session_start"


def _get_user_id() -> str | None:
    """Return authenticated user ID or None."""
    try:
        from components.auth import get_session_user
        u = get_session_user()
        return u.get("id") if u else None
    except Exception:
        return None


def _get_session_id() -> str:
    """Stable session ID (resets on browser refresh)."""
    if _SESSION_KEY not in st.session_state:
        import uuid
        st.session_state[_SESSION_KEY] = str(uuid.uuid4())
    return st.session_state[_SESSION_KEY]


def track(
    event: str,
    properties: dict[str, Any] | None = None,
    *,
    page: str | None = None,
) -> None:
    """
    Fire-and-forget analytics event to Supabase.

    Does NOT block the render loop — runs in a daemon thread.
    Never raises; all errors are silently logged.

    Args:
        event:      Snake_case event name, e.g. "page_view", "daily_briefing_generated"
        properties: Arbitrary metadata dict (JSON-serialisable).
        page:       Optional page name override; inferred from URL query params if omitted.

    Usage:
        track("watchlist_rebalanced", {"cycle_phase": "Mid / Expansion", "tickers": 5})
        track("page_view", page="Macro Pulse")
    """
    import threading

    props = dict(properties or {})

    # Auto-detect page from query params if not provided
    if page is None:
        try:
            qp = st.query_params
            page = qp.get("page", "unknown")
        except Exception:
            page = "unknown"
    props["page"] = page

    row = {
        "event":      event,
        "user_id":    _get_user_id(),
        "session_id": _get_session_id(),
        "properties": json.dumps(props, default=str),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }

    log.info("analytics", event, **{k: v for k, v in props.items()})

    def _write() -> None:
        try:
            from components.supabase_client import get_client
            get_client().table(_ANALYTICS_TABLE).insert(row).execute()
        except Exception as exc:
            # Don't surface analytics failures to users
            log.warning("analytics", "write failed", error=str(exc))

    t = threading.Thread(target=_write, daemon=True)
    t.start()


# ── 4. Page-view auto-tracker ─────────────────────────────────────────────────

def init_app() -> None:
    """
    Call once in app.py (the navigation router) immediately after inject_theme().
    - Initialises Sentry globally so all pages benefit from error capture
    - Does NOT fire a page_view event (use init_page() per page for that)
    - Safe to call multiple times — Sentry init is guarded by _sentry_initialised

    Usage (app.py):
        from components.observability import init_app
        init_app()
    """
    _init_sentry()


def init_page(page_name: str) -> None:
    """
    Call once at the top of each page after imports.
    - Initialises Sentry (no-op if SENTRY_DSN not set, no-op if already done)
    - Fires a "page_view" analytics event (deduplicated per session per page)
    - Returns immediately; all I/O is non-blocking

    Usage:
        from components.observability import init_page
        init_page("Macro Pulse")
    """
    _init_sentry()

    # Deduplicate: only track once per page per browser session
    seen_key = f"_obs_seen_{page_name}"
    if not st.session_state.get(seen_key):
        st.session_state[seen_key] = True
        track("page_view", page=page_name)
