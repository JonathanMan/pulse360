"""
Pie360 — Alerts
==================
Rule management UI for the in-app alert system.

Users can:
  • Create rules on any supported FRED series or the blended recession
    probability — threshold + operator (>, <, crosses_above, …)
  • Optionally attach an email address to receive a notification
  • Toggle rules on/off, delete, view last-triggered date
  • See which rules fired in the current session
"""

from __future__ import annotations

import streamlit as st

from components.alert_engine import (
    OPERATOR_LABELS,
    OPERATORS,
    SERIES_PRESETS,
    add_rule,
    delete_rule,
    load_rules,
    toggle_rule,
)
from components.pulse360_theme import inject_theme

inject_theme()

st.markdown("""
<style>
    .main .block-container { padding-top: 1rem; max-width: 1100px; }
</style>
""", unsafe_allow_html=True)

st.markdown("# 🔔 Alerts")
st.caption(
    "Set threshold rules on any macro indicator or the blended recession "
    "probability. Alerts appear as banners on the Dashboard when the "
    "condition is met — and can optionally send you an email."
)

# ── Guest gate ────────────────────────────────────────────────────────────────
from components.auth import render_login_gate  # noqa: E402
if not render_login_gate(
    title="Sign in to use Alerts",
    body="Create custom rules on macro indicators and get notified when conditions are met.",
    feature_bullets=[
        "Rules on any FRED series or the blended recession probability",
        "Dashboard banners fire automatically when a threshold is crossed",
        "Optional email notifications",
    ],
    return_page="pages/12_Alerts.py",
):
    st.stop()

DISCLAIMER = (
    "*Alerts are informational only — not personalised investment advice. "
    "Pie360 is not a Registered Investment Advisor.*"
)

# ── Create new rule ────────────────────────────────────────────────────────────

with st.expander("➕ Create a new alert", expanded=True):
    c1, c2, c3 = st.columns([2, 2, 1.5])

    with c1:
        rule_name = st.text_input(
            "Alert name",
            placeholder="e.g. Recession risk elevated",
            key="alert_name",
        )
        # Series selector — preset list or free text
        series_choice = st.selectbox(
            "Series / Indicator",
            options=list(SERIES_PRESETS.keys()),
            format_func=lambda k: f"{k}  —  {SERIES_PRESETS[k]}",
            key="alert_series",
        )

    with c2:
        operator = st.selectbox(
            "Operator",
            options=OPERATORS,
            format_func=lambda o: OPERATOR_LABELS[o],
            key="alert_operator",
        )
        threshold = st.number_input(
            "Threshold value",
            value=25.0,
            step=0.5,
            key="alert_threshold",
        )

    with c3:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        email_addr = st.text_input(
            "Email (optional)",
            placeholder="you@example.com",
            key="alert_email",
        )

    # Crossing operator hint
    if operator in ("crosses_above", "crosses_below"):
        st.info(
            "ℹ️  Crossing operators fire **once** when the value crosses the threshold "
            "(edge-trigger, not level-trigger). The first check after adding the rule "
            "won't fire — it needs a before/after pair to detect the crossing.",
            icon="ℹ️",
        )

    if st.button("Add alert", type="primary", key="alert_add"):
        if not rule_name.strip():
            st.error("Please enter a name for the alert.")
        else:
            add_rule(
                name=rule_name,
                series_id=series_choice,
                operator=operator,
                threshold=threshold,
                email=email_addr or None,
            )
            st.success(f"✅ Alert '{rule_name}' created.")
            st.rerun()

st.markdown("---")

# ── Active rules table ─────────────────────────────────────────────────────────

rules = load_rules()

if not rules:
    st.info(
        "You don't have any alert rules yet. Use the form above to create one.",
        icon="🔔",
    )
else:
    st.markdown(f"#### Your alerts ({len(rules)} total)")

    for rule in rules:
        sid          = rule.get("series_id", "")
        series_label = SERIES_PRESETS.get(sid, sid)
        op_label     = OPERATOR_LABELS.get(rule.get("operator", ">"), rule.get("operator", ">"))
        is_active    = rule.get("active", True)
        last_val     = rule.get("last_value")
        last_trig    = rule.get("last_triggered")
        email_set    = bool(rule.get("email"))

        # Status badge
        if is_active:
            status_html = (
                '<span style="display:inline-block;padding:1px 8px;border-radius:10px;'
                'font-size:0.7rem;font-weight:700;background:#e8f8ee;color:#1a5c30;">'
                '● ACTIVE</span>'
            )
        else:
            status_html = (
                '<span style="display:inline-block;padding:1px 8px;border-radius:10px;'
                'font-size:0.7rem;font-weight:700;background:#f0f2f5;color:#6a6a6a;">'
                '○ PAUSED</span>'
            )

        email_html = (
            '<span style="font-size:0.72rem;color:#0a0a0a;">📧 email</span>'
            if email_set else ""
        )
        last_trig_html = (
            f'<span style="font-size:0.72rem;color:#6a6a6a;">Last fired: {last_trig}</span>'
            if last_trig
            else '<span style="font-size:0.72rem;color:#a0a0a0;">Never fired</span>'
        )
        last_val_html = (
            f'<span style="font-size:0.72rem;color:#6a6a6a;">'
            f'Last value: <strong>{last_val:.2f}</strong></span>'
            if last_val is not None
            else ""
        )

        rule_id = rule.get("id", "")
        with st.container(border=True):
            left, right = st.columns([5, 2])

            with left:
                st.markdown(
                    f'<div style="margin-bottom:2px;">'
                    f'<span style="font-size:1rem;font-weight:700;color:#0a0a0a;">'
                    f'{rule.get("name", "Unnamed")}</span>&nbsp;{status_html}&nbsp;{email_html}'
                    f'</div>'
                    f'<div style="font-size:0.82rem;color:#6a6a6a;margin-bottom:4px;">'
                    f'{series_label} <strong>{op_label}</strong> {rule.get("threshold")}'
                    f'</div>'
                    f'<div style="display:flex;gap:14px;flex-wrap:wrap;">'
                    f'{last_val_html}&nbsp;&nbsp;{last_trig_html}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            with right:
                col_toggle, col_del = st.columns(2)
                with col_toggle:
                    toggle_label = "Pause" if is_active else "Resume"
                    if st.button(
                        toggle_label,
                        key=f"toggle_{rule_id}",
                        use_container_width=True,
                    ):
                        toggle_rule(rule_id)
                        st.rerun()

                with col_del:
                    if st.button(
                        "Delete",
                        key=f"del_{rule_id}",
                        use_container_width=True,
                        type="secondary",
                    ):
                        delete_rule(rule_id)
                        st.rerun()

# ── How it works ──────────────────────────────────────────────────────────────

st.markdown("---")
with st.expander("ℹ️ How alerts work", expanded=False):
    st.markdown("""
**Check frequency**

Alerts are evaluated once per dashboard page load against the latest cached
FRED data. If data is cached (typically 1 hour), the check uses the cached
value. Alerts do not poll continuously in the background.

**Operators explained**

| Operator | Fires when… |
|---|---|
| `>` / `<` | Value is above / below threshold on every check |
| `>=` / `<=` | Same but inclusive of the threshold |
| `crosses_above` | Value was ≤ threshold last check, now > threshold |
| `crosses_below` | Value was ≥ threshold last check, now < threshold |

**De-duplication**

Level-based operators (>, <, >=, <=) are de-duplicated to fire **at most
once per calendar day** for the same rule. Crossing operators fire only on
the crossing edge.

**Email**

To receive email alerts, configure your SMTP credentials in
`.streamlit/secrets.toml`:

```toml
[smtp]
host     = "smtp.gmail.com"
port     = 587
username = "your@gmail.com"
password = "your_app_password"
```

For Gmail, use an [App Password](https://myaccount.google.com/apppasswords)
rather than your main account password.

**Recession Probability**

The special series `RECESSION_PROB` tracks the blended probability (0-100%)
from the five-factor recession model. Useful trigger: `crosses_above 25` for

from assets.logo_helper import header_with_logo
header_with_logo("12 Alerts", "Pie360 — AI-Powered Economic Cycle Dashboard")

an early warning.
""")

st.markdown("---")
st.caption(DISCLAIMER)
