"""
components/observability.py
============================
T3-5: Centralised observability for Pie360.

Four layers
-----------
1. Structured logging  — Python stdlib logging with JSON formatter
                         (writes to stderr so Streamlit Cloud captures it)
2. Sentry              — optional; activated when SENTRY_DSN env var is set
                         wraps exceptions at key call sites
3. Usage analytics     — fire-and-forget writes to the `user_analytics`
                         Supabase table; degraded gracefully when unavailable
4. Error email alerts  — real-time Resend email on unhandled exceptions;
                         rate-limited to 1 email per error type per 5 minutes

Public API
----------
    from components.observability import log, track, capture_exception, error_boundary

    log.info("cycle_engine", "phase detected", phase="Mid / Expansion", conf=87)
    track("watchlist_rebalanced", {"cycle_phase": "Mid / Expansion"})
    capture_exception(exc, context={"page": "11_Watchlist"})

    # Wrap page content to auto-report + email on crash:
    with error_boundary("Dashboard"):
        render_dashboard()
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

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


# ── 3. Error email alerts ─────────────────────────────────────────────────────

# Rate-limit: track last email time per error type to avoid floods.
# Key: exc type name, Value: unix timestamp of last email sent.
_error_email_cooldowns: dict[str, float] = {}
_ERROR_EMAIL_COOLDOWN_SECS = 300  # 5 minutes per error type

# Streamlit-internal exceptions that must never trigger alerts.
_STREAMLIT_INTERNAL_EXCEPTIONS = {
    "RerunException",
    "StopException",
    "StopIteration",
    "ScriptRunner",
}


def _send_error_email(
    exc: Exception,
    tb: str,
    context: dict[str, Any],
) -> None:
    """
    Fire-and-forget error notification via Resend.

    Rate-limited: same exception type can only trigger one email per
    _ERROR_EMAIL_COOLDOWN_SECS seconds. Runs in a daemon thread so it
    never blocks the render loop.
    """
    import threading

    exc_type = type(exc).__name__

    # Skip Streamlit-internal control-flow exceptions
    if any(name in exc_type for name in _STREAMLIT_INTERNAL_EXCEPTIONS):
        return

    # Rate-limit check
    now = time.time()
    last_sent = _error_email_cooldowns.get(exc_type, 0)
    if now - last_sent < _ERROR_EMAIL_COOLDOWN_SECS:
        log.info("observability", "error email suppressed (cooldown)", exc_type=exc_type)
        return
    _error_email_cooldowns[exc_type] = now

    def _send() -> None:
        try:
            import resend  # type: ignore[import]

            api_key = st.secrets.get("RESEND_API_KEY", "") or os.environ.get("RESEND_API_KEY", "")
            if not api_key:
                log.warning("observability", "RESEND_API_KEY not set — error email skipped")
                return

            resend.api_key = api_key
            from_addr = st.secrets.get("RESEND_FROM", "onboarding@resend.dev")
            page = context.get("page", "unknown")
            subject = f"[Pie360 🚨] {exc_type} on {page}: {str(exc)[:80]}"

            html_body = f"""
<div style="font-family:monospace;max-width:700px;">
  <h2 style="color:#d92626;">🚨 Pie360 Error Alert</h2>
  <table style="border-collapse:collapse;width:100%;">
    <tr><td style="padding:4px 8px;font-weight:bold;">Time</td>
        <td style="padding:4px 8px;">{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</td></tr>
    <tr><td style="padding:4px 8px;font-weight:bold;">Page</td>
        <td style="padding:4px 8px;">{page}</td></tr>
    <tr><td style="padding:4px 8px;font-weight:bold;">Error</td>
        <td style="padding:4px 8px;color:#d92626;">{exc_type}: {exc}</td></tr>
    <tr><td style="padding:4px 8px;font-weight:bold;">Context</td>
        <td style="padding:4px 8px;">{json.dumps(context, default=str)}</td></tr>
  </table>
  <h3 style="margin-top:16px;">Traceback</h3>
  <pre style="background:#f4f4f4;padding:12px;border-radius:4px;overflow-x:auto;font-size:12px;">{tb}</pre>
  <p style="color:#6a6a6a;font-size:12px;">
    Live app: <a href="https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app">
    pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app</a>
  </p>
</div>
"""
            resend.Emails.send({
                "from": from_addr,
                "to": ["jonathancyman@gmail.com"],
                "subject": subject,
                "html": html_body,
            })
            log.info("observability", "error email sent", exc_type=exc_type, page=page)

        except Exception as email_exc:
            # Never let error reporting crash the app
            log.warning("observability", "error email failed", error=str(email_exc))

    threading.Thread(target=_send, daemon=True).start()


@contextmanager
def error_boundary(page_name: str) -> Generator[None, None, None]:
    """
    Context manager that catches unhandled exceptions in a page, reports them
    via capture_exception + Resend email, then re-raises so Streamlit still
    shows the error UI to the user.

    Usage (add to every page after init_page()):
        from components.observability import init_page, error_boundary

        init_page("Dashboard")
        with error_boundary("Dashboard"):
            # all page rendering code here
            render_overview()
            render_charts()

    The page name is included in the email subject for fast triage.
    """
    try:
        yield
    except Exception as exc:
        tb = traceback.format_exc()
        ctx = {"page": page_name}
        capture_exception(exc, context=ctx)
        _send_error_email(exc, tb, ctx)
        raise  # re-raise so Streamlit renders its normal error UI


# ── 4. Usage analytics ────────────────────────────────────────────────────────

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

def _send_new_user_email(user_id: str, user_email: str | None) -> None:
    """
    Fire-and-forget notification email when a new user is detected.
    Runs in a daemon thread — never blocks the render loop.
    """
    import threading

    def _send() -> None:
        try:
            import resend  # type: ignore[import]

            api_key = st.secrets.get("RESEND_API_KEY", "") or os.environ.get("RESEND_API_KEY", "")
            if not api_key:
                return

            resend.api_key = api_key
            from_addr = st.secrets.get("RESEND_FROM", "onboarding@resend.dev")
            display = user_email or user_id
            subject = f"[Pie360 🎉] New user: {display}"

            html_body = f"""
<div style="font-family:sans-serif;max-width:600px;">
  <h2 style="color:#00a35a;">🎉 New Pie360 User</h2>
  <table style="border-collapse:collapse;width:100%;">
    <tr><td style="padding:6px 8px;font-weight:bold;">Time</td>
        <td style="padding:6px 8px;">{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</td></tr>
    <tr><td style="padding:6px 8px;font-weight:bold;">Email</td>
        <td style="padding:6px 8px;">{user_email or '—'}</td></tr>
    <tr><td style="padding:6px 8px;font-weight:bold;">User ID</td>
        <td style="padding:6px 8px;font-size:12px;color:#6a6a6a;">{user_id}</td></tr>
  </table>
  <p style="margin-top:16px;">
    <a href="https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app">Open Pie360</a>
  </p>
</div>
"""
            resend.Emails.send({
                "from": from_addr,
                "to": ["jonathancyman@gmail.com"],
                "subject": subject,
                "html": html_body,
            })
            log.info("observability", "new user notification sent", user_id=user_id)

        except Exception as exc:
            log.warning("observability", "new user email failed", error=str(exc))

    threading.Thread(target=_send, daemon=True).start()


def _check_and_notify_new_user(user_id: str) -> None:
    """
    Check whether this authenticated user has been seen before.
    If not: insert a 'first_visit' event and send a notification email.
    Runs in a daemon thread. Session-state guards prevent duplicate checks
    within the same browser session.
    """
    import threading

    # Deduplicate within the same browser session
    if st.session_state.get("_obs_new_user_checked"):
        return
    st.session_state["_obs_new_user_checked"] = True

    def _check() -> None:
        try:
            from components.supabase_client import get_client
            from components.auth import get_session_user

            sb = get_client()

            # Check for any prior first_visit event for this user
            result = (
                sb.table(_ANALYTICS_TABLE)
                .select("id")
                .eq("user_id", user_id)
                .eq("event", "first_visit")
                .limit(1)
                .execute()
            )

            if result.data:
                return  # returning user — nothing to do

            # New user: record it and notify
            sb.table(_ANALYTICS_TABLE).insert({
                "event":      "first_visit",
                "user_id":    user_id,
                "session_id": _get_session_id(),
                "properties": json.dumps({"source": "init_page"}),
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }).execute()

            user = get_session_user()
            user_email = user.get("email") if user else None
            _send_new_user_email(user_id, user_email)
            log.info("observability", "new user detected", user_id=user_id)

        except Exception as exc:
            log.warning("observability", "new user check failed", error=str(exc))

    threading.Thread(target=_check, daemon=True).start()


def _install_exception_reporter() -> None:
    """
    Monkey-patch st.exception so every unhandled page exception triggers
    a Resend email alert automatically — no per-page changes required.

    Streamlit calls st.exception(e) whenever a page script raises an
    unhandled exception, so patching it here gives global coverage.
    Safe to call multiple times (guarded by attribute flag).
    """
    if getattr(st, "_pie360_exc_reporter_installed", False):
        return

    _original_st_exception = st.exception

    def _patched_exception(exc: Exception) -> None:  # type: ignore[override]
        exc_type = type(exc).__name__
        if not any(name in exc_type for name in _STREAMLIT_INTERNAL_EXCEPTIONS):
            tb = traceback.format_exc()
            # Best-effort page name from query params
            try:
                page = st.query_params.get("page", "unknown")
            except Exception:
                page = "unknown"
            capture_exception(exc, context={"page": page, "source": "st.exception"})
            _send_error_email(exc, tb, {"page": page})
        return _original_st_exception(exc)

    st.exception = _patched_exception  # type: ignore[assignment]
    st._pie360_exc_reporter_installed = True  # type: ignore[attr-defined]
    log.info("observability", "exception reporter installed")


def init_app() -> None:
    """
    Call once in app.py (the navigation router) immediately after inject_theme().
    - Initialises Sentry globally so all pages benefit from error capture
    - Installs st.exception patch for automatic Resend email alerts
    - Does NOT fire a page_view event (use init_page() per page for that)
    - Safe to call multiple times — all inits are guarded by flags

    Usage (app.py):
        from components.observability import init_app
        init_app()
    """
    _init_sentry()
    _install_exception_reporter()


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

    # New-user detection: runs once per session for authenticated users
    user_id = _get_user_id()
    if user_id:
        _check_and_notify_new_user(user_id)
