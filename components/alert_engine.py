"""
Pie360 — Alert Engine
========================
Rule-based alert system that watches any FRED series (or the blended
recession probability) and fires in-app banners + optional email when
a threshold is crossed.

Rule schema (stored as JSON):
    {
      "id":             str  — uuid4 hex,
      "name":           str  — human label,
      "series_id":      str  — FRED series ID or "RECESSION_PROB",
      "operator":       str  — one of >, <, >=, <=, crosses_above, crosses_below,
      "threshold":      float,
      "email":          str | null  — send to this address if set,
      "active":         bool,
      "last_value":     float | null  — value at last check (for crossing detection),
      "last_triggered": str | null  — ISO date of last fire,
      "created_at":     str  — ISO datetime,
    }

Public API:
    load_rules()               → list[dict]
    save_rules(rules)
    add_rule(...)              → dict
    delete_rule(rule_id)
    evaluate_rule(rule, current_value)  → bool
    check_rules(live_values, model_output) → list[dict]   (triggered rules)
    send_email_alert(rule, current_value)
    check_and_render_alerts(live_values, model_output)   → call from app.py
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

import streamlit as st

from components.supabase_client import get_client, get_user_email

logger = logging.getLogger(__name__)


# ── Operators ─────────────────────────────────────────────────────────────────
OPERATORS: list[str] = [">", "<", ">=", "<=", "crosses_above", "crosses_below"]

OPERATOR_LABELS: dict[str, str] = {
    ">":             "is greater than",
    "<":             "is less than",
    ">=":            "is ≥",
    "<=":            "is ≤",
    "crosses_above": "crosses above",
    "crosses_below": "crosses below",
}

# ── Preset series for the UI ──────────────────────────────────────────────────
SERIES_PRESETS: dict[str, str] = {
    "RECESSION_PROB":  "Recession Probability (%)",
    "T10Y3M":          "10Y–3M Treasury Spread (%)",
    "SAHMREALTIME":    "Sahm Rule (real-time)",
    "NFCI":            "Chicago Fed NFCI",
    "BAMLH0A0HYM2":   "High-Yield OAS (bps)",
    "FEDFUNDS":        "Fed Funds Rate (%)",
    "CPIAUCSL":        "CPI (YoY %)",
    "UNRATE":          "Unemployment Rate (%)",
    "T10Y2Y":          "10Y–2Y Treasury Spread (%)",
    "VIXCLS":          "VIX (Volatility Index)",
}


# ── Persistence ───────────────────────────────────────────────────────────────

def load_rules() -> list[dict]:
    """Load the current user's rules from Supabase."""
    try:
        rows = (
            get_client()
            .table("alert_rules")
            .select("*")
            .eq("user_email", get_user_email())
            .order("created_at")
            .execute()
        )
        return rows.data or []
    except Exception as exc:
        logger.warning("alert_engine: could not load rules: %s", exc)
        return []


def save_rules(rules: list[dict]) -> None:
    """Upsert all rules for the current user. Used by check_rules to persist state."""
    client = get_client()
    email = get_user_email()
    for rule in rules:
        try:
            client.table("alert_rules").upsert({
                "id":             rule["id"],
                "user_email":     email,
                "name":           rule["name"],
                "series_id":      rule["series_id"],
                "operator":       rule["operator"],
                "threshold":      rule["threshold"],
                "email":          rule.get("email"),
                "active":         rule.get("active", True),
                "last_value":     rule.get("last_value"),
                "last_triggered": rule.get("last_triggered"),
                "created_at":     rule["created_at"],
            }).execute()
        except Exception as exc:
            logger.error("alert_engine: could not save rule %s: %s", rule.get("id"), exc)


# ── Rule CRUD ─────────────────────────────────────────────────────────────────

def add_rule(
    name: str,
    series_id: str,
    operator: str,
    threshold: float,
    email: str | None = None,
) -> dict:
    """Create a new rule, persist it, and return it."""
    rule: dict[str, Any] = {
        "id":             uuid.uuid4().hex,
        "user_email":     get_user_email(),
        "name":           name.strip(),
        "series_id":      series_id.upper().strip(),
        "operator":       operator,
        "threshold":      float(threshold),
        "email":          email.strip() if email else None,
        "active":         True,
        "last_value":     None,
        "last_triggered": None,
        "created_at":     datetime.utcnow().isoformat(),
    }
    try:
        get_client().table("alert_rules").insert(rule).execute()
    except Exception as exc:
        logger.error("alert_engine: could not insert rule: %s", exc)
    return rule


def delete_rule(rule_id: str) -> None:
    """Remove rule by id."""
    try:
        get_client().table("alert_rules").delete().eq("id", rule_id).eq(
            "user_email", get_user_email()
        ).execute()
    except Exception as exc:
        logger.error("alert_engine: could not delete rule %s: %s", rule_id, exc)


def toggle_rule(rule_id: str) -> None:
    """Flip the active flag on a rule."""
    rules = load_rules()
    for r in rules:
        if r.get("id") == rule_id:
            new_active = not r.get("active", True)
            try:
                get_client().table("alert_rules").update({"active": new_active}).eq(
                    "id", rule_id
                ).eq("user_email", get_user_email()).execute()
            except Exception as exc:
                logger.error("alert_engine: could not toggle rule %s: %s", rule_id, exc)
            break


def _update_rule(rule_id: str, **kwargs) -> None:
    """Patch any field on a rule by id."""
    try:
        get_client().table("alert_rules").update(kwargs).eq("id", rule_id).eq(
            "user_email", get_user_email()
        ).execute()
    except Exception as exc:
        logger.error("alert_engine: could not update rule %s: %s", rule_id, exc)


# ── Rule evaluation ───────────────────────────────────────────────────────────

def evaluate_rule(rule: dict, current_value: float) -> bool:
    """
    Return True if the rule fires for current_value.

    Crossing operators also use rule["last_value"] to detect edge transitions.
    """
    op        = rule.get("operator", ">")
    threshold = float(rule.get("threshold", 0))
    last      = rule.get("last_value")

    if op == ">":
        return current_value > threshold
    if op == "<":
        return current_value < threshold
    if op == ">=":
        return current_value >= threshold
    if op == "<=":
        return current_value <= threshold
    if op == "crosses_above":
        if last is None:
            return False
        return float(last) <= threshold < current_value
    if op == "crosses_below":
        if last is None:
            return False
        return float(last) >= threshold > current_value
    return False


# ── Email dispatch ────────────────────────────────────────────────────────────

def send_email_alert(rule: dict, current_value: float) -> bool:
    """
    Send an alert email via Resend.

    Requires RESEND_API_KEY in st.secrets (same key used by the daily briefing).
    Optional: RESEND_FROM  — defaults to "onboarding@resend.dev".

    Returns True on success, False on any failure (never raises).
    """
    recipient = rule.get("email")
    if not recipient:
        return False

    try:
        if "RESEND_API_KEY" not in st.secrets:
            logger.info("alert_engine: RESEND_API_KEY not configured — skipping email")
            return False

        import resend
        resend.api_key = st.secrets["RESEND_API_KEY"]

        series_label = SERIES_PRESETS.get(rule["series_id"], rule["series_id"])
        op_label     = OPERATOR_LABELS.get(rule["operator"], rule["operator"])
        subject      = f"🚨 Pie360 Alert: {rule['name']}"
        body_html    = f"""
<html><body style="font-family:sans-serif;color:#0a0a0a;max-width:560px;margin:auto;">
  <div style="background:#0a0a0a;padding:18px 24px;">
    <h2 style="color:#fff;margin:0;font-size:1.1rem;">📊 Pie360 Alert Fired</h2>
  </div>
  <div style="background:#f4f4f4;padding:20px 24px;border:1px solid #ececec;border-top:none;">
    <h3 style="margin-top:0;color:#0a0a0a;">{rule['name']}</h3>
    <table style="border-collapse:collapse;width:100%;margin-bottom:14px;">
      <tr>
        <td style="padding:6px 10px;color:#6a6a6a;white-space:nowrap;">Series</td>
        <td style="padding:6px 10px;font-weight:600;">{series_label}</td>
      </tr>
      <tr style="background:#fff;">
        <td style="padding:6px 10px;color:#6a6a6a;">Condition</td>
        <td style="padding:6px 10px;font-weight:600;">
          {series_label} {op_label} {rule['threshold']}
        </td>
      </tr>
      <tr>
        <td style="padding:6px 10px;color:#6a6a6a;">Current value</td>
        <td style="padding:6px 10px;font-weight:700;color:#d92626;">
          {current_value:.2f}
        </td>
      </tr>
      <tr style="background:#fff;">
        <td style="padding:6px 10px;color:#6a6a6a;">Triggered at</td>
        <td style="padding:6px 10px;">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</td>
      </tr>
    </table>
    <p style="font-size:0.82rem;color:#6a6a6a;border-top:1px solid #ececec;
              padding-top:12px;margin-bottom:0;">
      This is an automated alert from <strong>Pie360</strong>. Not personalised
      investment advice. Manage your alerts on the
      <a href="https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app/Alerts"
         style="color:#1f6feb;">Alerts page</a>.
    </p>
  </div>
</body></html>
"""
        from_addr = st.secrets.get("RESEND_FROM", "onboarding@resend.dev")
        resend.Emails.send({
            "from":    from_addr,
            "to":      [recipient],
            "subject": subject,
            "html":    body_html,
        })

        logger.info("alert_engine: email sent to %s for rule '%s'", recipient, rule["name"])
        return True

    except Exception as exc:
        logger.warning("alert_engine: email failed for rule '%s': %s", rule.get("name"), exc)
        return False


# ── Main check function ───────────────────────────────────────────────────────

def check_rules(
    live_values: dict[str, float],
    recession_probability: float | None = None,
) -> list[dict]:
    """
    Evaluate all active rules against the provided values.

    live_values: dict mapping series_id → latest float value (from FRED).
    recession_probability: blended probability from RecessionModelOutput, 0-100.

    Returns a list of triggered rule dicts (enriched with 'current_value').
    Always persists updated last_value and last_triggered back to disk.
    """
    all_values = dict(live_values)
    if recession_probability is not None:
        all_values["RECESSION_PROB"] = float(recession_probability)

    rules    = load_rules()
    triggered: list[dict] = []

    for rule in rules:
        if not rule.get("active", True):
            continue

        sid = rule.get("series_id", "")
        current = all_values.get(sid)
        if current is None:
            continue

        fired = evaluate_rule(rule, current)

        if fired:
            # Avoid re-triggering on the same day
            today = date.today().isoformat()
            if rule.get("last_triggered") != today:
                triggered.append({**rule, "current_value": current})
                rule["last_triggered"] = today
                send_email_alert(rule, current)

        rule["last_value"] = current

    save_rules(rules)
    return triggered


def check_and_render_alerts(
    live_values: dict[str, float],
    recession_probability: float | None = None,
) -> None:
    """
    Top-level function for app.py to call once per page load.

    Evaluates all active rules and renders Streamlit alert banners for
    any that fire.  Silently no-ops if no rules are defined.
    """
    try:
        triggered = check_rules(live_values, recession_probability)
    except Exception as exc:
        logger.warning("alert_engine: check_rules failed: %s", exc)
        return

    if not triggered:
        return

    for rule in triggered:
        series_label = SERIES_PRESETS.get(rule["series_id"], rule["series_id"])
        op_label     = OPERATOR_LABELS.get(rule["operator"], rule["operator"])
        val          = rule.get("current_value", rule.get("last_value"))
        val_str      = f"{val:.2f}" if val is not None else "—"

        st.warning(
            f"🚨 **Alert:** {rule['name']}  — "
            f"{series_label} {op_label} {rule['threshold']} "
            f"(current: **{val_str}**)",
            icon="🚨",
        )
