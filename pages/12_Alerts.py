"""
Pulse360 — Alerts
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
from components.pulse360_theme import (
    BORDER, BORDER_MUT, CARD_BG, DANGER, FG_MUTED, FG_PRIMARY, FG_SEC,
    PAGE_BG, SUBTLE_BG, SUCCESS, WARNING,
    inject_theme,
)

inject_theme()

st.markdown(f"""
<style>
    .main .block-container {{ padding-top: 1rem; max-width: 1100px; }}

    /* ── Page header band ─────────────────────────────────────────────── */
    .al-header {{
        display: flex;
        align-items: flex-start;
        gap: 16px;
        padding: 22px 0 18px;
        border-bottom: 1px solid {BORDER};
        margin-bottom: 22px;
    }}
    .al-icon-wrap {{
        width: 40px; height: 40px;
        background: {SUBTLE_BG};
        border: 1px solid {BORDER};
        border-radius: 6px;
        display: flex; align-items: center; justify-content: center;
        flex: 0 0 auto;
        font-size: 18px; line-height: 1;
    }}
    .al-title {{
        font-size: 1.55rem;
        font-weight: 700;
        color: {FG_PRIMARY};
        letter-spacing: -0.03em;
        margin: 0 0 5px 0;
        line-height: 1.15;
    }}
    .al-subtitle {{
        font-size: 0.82rem;
        color: {FG_SEC};
        margin: 0;
        line-height: 1.6;
        max-width: 600px;
    }}
    .al-stats {{
        margin-left: auto;
        display: flex;
        align-items: center;
        border: 1px solid {BORDER};
        overflow: hidden;
        border-radius: 2px;
        align-self: center;
    }}
    .al-stat {{
        display: flex; flex-direction: column; align-items: center;
        padding: 7px 18px;
        background: {CARD_BG};
        gap: 2px;
    }}
    .al-stat-sep {{ width: 1px; background: {BORDER}; align-self: stretch; }}
    .al-stat-val {{
        font-size: 1.2rem; font-weight: 600;
        font-family: 'Geist Mono', monospace;
        line-height: 1; letter-spacing: -0.02em;
    }}
    .al-stat-lbl {{
        font-size: 0.6rem; text-transform: uppercase;
        letter-spacing: 0.1em; color: {FG_MUTED};
        font-weight: 600; font-family: 'Geist Mono', monospace;
    }}

    /* ── Alert list rows ──────────────────────────────────────────────── */
    .al-row {{
        display: grid;
        grid-template-columns: 78px 1fr;
        gap: 14px;
        padding: 14px 0 12px;
        border-top: 1px solid {BORDER};
        align-items: start;
    }}
    .al-row:first-child {{ border-top: none; padding-top: 6px; }}
    .al-badge {{
        display: inline-flex; align-items: center; gap: 5px;
        font-size: 0.6rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.09em;
        font-family: 'Geist Mono', monospace;
        padding-top: 3px;
    }}
    .al-dot {{
        width: 6px; height: 6px; border-radius: 999px; flex: 0 0 auto;
    }}
    .al-badge--armed {{ color: {SUCCESS}; }}
    .al-badge--paused {{ color: {FG_MUTED}; }}
    .al-badge--fired  {{ color: {FG_MUTED}; }}
    .al-dot--armed  {{ background: {SUCCESS}; }}
    .al-dot--paused {{ background: {FG_MUTED}; }}
    .al-dot--fired  {{ background: {FG_MUTED}; }}
    .al-name {{
        font-size: 0.88rem; font-weight: 700;
        color: {FG_PRIMARY}; letter-spacing: -0.01em;
        margin-bottom: 3px;
    }}
    .al-detail {{
        font-size: 0.72rem; color: {FG_SEC};
        font-family: 'Geist Mono', monospace;
        line-height: 1.5;
    }}
    .al-meta {{
        font-size: 0.68rem; color: {FG_MUTED};
        font-family: 'Geist Mono', monospace;
        margin-top: 3px;
    }}

    /* ── Section separator ────────────────────────────────────────────── */
    .al-sep {{
        height: 1px; background: {BORDER};
        margin: 20px 0 18px;
    }}
</style>
""", unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────────────────────

rules = load_rules()
armed_count = sum(1 for r in rules if r.get("active", True))
fired_count = sum(1 for r in rules if r.get("last_triggered"))

stats_html = ""
if rules:
    stats_html = f"""
    <div class="al-stats">
        <div class="al-stat">
            <span class="al-stat-val" style="color:{SUCCESS};">{armed_count}</span>
            <span class="al-stat-lbl">Armed</span>
        </div>
        <div class="al-stat-sep"></div>
        <div class="al-stat">
            <span class="al-stat-val" style="color:{FG_MUTED};">{fired_count}</span>
            <span class="al-stat-lbl">Fired</span>
        </div>
    </div>
    """

st.markdown(f"""
<div class="al-header">
    <div class="al-icon-wrap">🔔</div>
    <div>
        <div class="al-title">Alerts</div>
        <div class="al-subtitle">
            Set threshold rules on any macro indicator or the blended recession
            probability. Alerts appear as banners on the Dashboard when the
            condition is met — and can optionally send you an email.
        </div>
    </div>
    {stats_html}
</div>
""", unsafe_allow_html=True)

# ── Create new rule ────────────────────────────────────────────────────────────

with st.expander("➕  Create a new alert", expanded=True):
    c1, c2, c3 = st.columns([2, 2, 1.5])

    with c1:
        rule_name = st.text_input(
            "Alert name",
            placeholder="e.g. Recession risk elevated",
            key="alert_name",
        )
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

# ── Active rules list ──────────────────────────────────────────────────────────

st.markdown("<div class='al-sep'></div>", unsafe_allow_html=True)

if not rules:
    st.info(
        "You don't have any alert rules yet. Use the form above to create one.",
        icon="🔔",
    )
else:
    st.markdown(
        f'<div style="font-size:0.66rem;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.12em;color:{FG_MUTED};font-family:\'Geist Mono\',monospace;'
        f'margin-bottom:4px;">Active alerts · {len(rules)} total</div>',
        unsafe_allow_html=True,
    )

    rows_html = ""
    for rule in rules:
        sid          = rule.get("series_id", "")
        series_label = SERIES_PRESETS.get(sid, sid)
        op_label     = OPERATOR_LABELS.get(rule.get("operator", ">"), rule.get("operator", ">"))
        is_active    = rule.get("active", True)
        last_val     = rule.get("last_value")
        last_trig    = rule.get("last_triggered")
        email_set    = bool(rule.get("email"))

        badge_cls = "armed" if is_active else "paused"
        badge_txt = "Armed" if is_active else "Paused"

        meta_parts = []
        if last_val is not None:
            meta_parts.append(f"Last value: {last_val:.2f}")
        if last_trig:
            meta_parts.append(f"Last fired: {last_trig}")
            badge_cls = "fired"
            badge_txt = "Fired"
        elif not last_trig:
            meta_parts.append("Never fired")
        if email_set:
            meta_parts.append("email on")

        meta_str = " · ".join(meta_parts)
        detail_str = f"{series_label} {op_label} {rule.get('threshold')}"

        rows_html += f"""
        <div class="al-row">
            <span class="al-badge al-badge--{badge_cls}">
                <span class="al-dot al-dot--{badge_cls}"></span>{badge_txt}
            </span>
            <div>
                <div class="al-name">{rule.get('name', 'Unnamed')}</div>
                <div class="al-detail">{detail_str}</div>
                <div class="al-meta">{meta_str}</div>
            </div>
        </div>
        """

    st.markdown(rows_html, unsafe_allow_html=True)

    st.markdown("<div class='al-sep'></div>", unsafe_allow_html=True)

    # Controls row: one st.container per rule (keeps Streamlit buttons working)
    for rule in rules:
        rule_id   = rule.get("id", "")
        is_active = rule.get("active", True)
        with st.container():
            col_name, col_toggle, col_del = st.columns([4, 1, 1])
            with col_name:
                st.markdown(
                    f'<span style="font-size:0.82rem;color:{FG_SEC};'
                    f'font-family:\'Geist Mono\',monospace;">'
                    f'{rule.get("name", "Unnamed")}</span>',
                    unsafe_allow_html=True,
                )
            with col_toggle:
                if st.button(
                    "Pause" if is_active else "Resume",
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

with st.expander("ℹ️  How alerts work", expanded=False):
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

The special series `RECESSION_PROB` tracks the blended probability (0–100%)
from the five-factor recession model. Useful trigger: `crosses_above 25` for
an early warning.
""")

st.markdown(
    f'<div style="margin-top:28px;padding-top:16px;border-top:1px solid {BORDER};'
    f'font-size:0.72rem;color:{FG_MUTED};font-family:\'Geist Mono\',monospace;'
    f'text-transform:uppercase;letter-spacing:0.06em;line-height:1.6;">'
    f'Alerts are informational only — not personalised investment advice. '
    f'Pulse360 is not a Registered Investment Advisor.</div>',
    unsafe_allow_html=True,
)
