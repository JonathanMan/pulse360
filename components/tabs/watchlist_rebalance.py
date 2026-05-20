"""
components/tabs/watchlist_rebalance.py
=======================================
Rebalancing Plan section extracted from pages/11_Watchlist.py.

Public API
----------
    from components.tabs.watchlist_rebalance import render_rebalancing_section

    render_rebalancing_section(
        weights_cache=st.session_state.get("_weights_cache", {}),
        classifications=st.session_state.get("_classifications", {}),
    )
"""

from __future__ import annotations

import io
import os

import anthropic
import streamlit as st

from components.rebalancer import (
    CYCLE_PHASES,
    PHASE_RATIONALE,
    TILT_BUCKET_LABELS,
    TILT_MULTIPLIERS,
    compute_plan,
    plan_to_dataframe,
)
from components.ticker_classifier import ASSET_CLASS_COLORS


# ── AI memo generator ─────────────────────────────────────────────────────────

def _generate_rebalancing_memo(plan: dict, cycle_phase: str) -> str:
    """
    Call Claude synchronously to generate a 4-part rebalancing memo.
    Returns the full memo text, or an error string on failure.
    """
    positions_lines = []
    for ticker, p in sorted(plan.items(), key=lambda x: -abs(x[1]["delta"])):
        sign = "+" if p["delta"] >= 0 else ""
        positions_lines.append(
            f"  {ticker} ({p['sector']} · {p['asset_class']}): "
            f"{p['current']}% → {p['suggested']}% ({sign}{p['delta']}%) {p['action']}"
        )
    positions_str = "\n".join(positions_lines)

    trims = [
        f"{t} ({p['delta']:+.1f}%)" for t, p in plan.items()
        if p["delta"] <= -2.0
    ]
    adds = [
        f"{t} ({p['delta']:+.1f}%)" for t, p in plan.items()
        if p["delta"] >= 2.0
    ]

    prompt = f"""You are a senior macro strategist at Pie360 writing a concise rebalancing memo for a professional investor.

CYCLE PHASE: {cycle_phase}

FULL PORTFOLIO REBALANCING PLAN:
{positions_str}

KEY TRIMS: {', '.join(trims) if trims else 'None'}
KEY ADDS: {', '.join(adds) if adds else 'None'}

Write a tight 4-part investment memo. Use **bold headers** exactly as shown:

**Macro Context**
2–3 sentences on the {cycle_phase} phase: what it means for growth, rates, and earnings. Be specific — reference yield curves, PMI direction, credit spreads, or Fed policy as relevant.

**Portfolio Assessment**
1 paragraph. Assess how this specific portfolio is currently positioned for the {cycle_phase} phase. Name the biggest exposure mismatches. Be direct — don't hedge everything.

**Key Actions**
3–5 bullet points. Each bullet = one concrete change with a one-line rationale. Name specific tickers or sectors. Format: "• Trim [TICKER/SECTOR] — [reason]" or "• Add [TICKER/SECTOR] — [reason]".

**Risk Flags**
1–2 sentences. What data or events would invalidate this cycle phase call and force a reversal? Be specific (e.g. "ISM Manufacturing rebounds above 52", "10-year yield breaks below 3.8%").

Total length: 280–360 words. Write for a sophisticated investor. No disclaimers or boilerplate."""

    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
        client  = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        return f"⚠️ Could not generate memo: {e}"


# ── HTML helpers ──────────────────────────────────────────────────────────────

_ROW_PAD  = "6px 10px"
_ROW_FONT = "0.82rem"


def _delta_html(delta: float) -> str:
    sign = "+" if delta >= 0 else ""
    if delta >= 5.0:
        col, wt = "#059669", "700"
    elif delta <= -5.0:
        col, wt = "#dc2626", "700"
    elif abs(delta) >= 2.0:
        col, wt = "#d97706", "600"
    else:
        col, wt = "#6b7280", "400"
    return f'<span style="color:{col};font-weight:{wt};">{sign}{delta:.1f}%</span>'


def _action_html(action: str) -> str:
    if "Add" in action and "Minor" not in action:
        return f'<span style="color:#059669;font-weight:700;">{action}</span>'
    if "Trim" in action and "Minor" not in action:
        return f'<span style="color:#dc2626;font-weight:700;">{action}</span>'
    if "Minor" in action:
        return f'<span style="color:#d97706;font-weight:600;">{action}</span>'
    return f'<span style="color:#9ca3af;">{action}</span>'


# ── Main render function ───────────────────────────────────────────────────────

def render_rebalancing_section(
    weights_cache: dict[str, float],
    classifications: dict[str, dict[str, str]],
) -> None:
    """
    Render the full Rebalancing Plan section.

    Args:
        weights_cache:   dict of {ticker: weight_pct} from session state.
        classifications: dict of {ticker: {"sector": ..., "asset_class": ...}}
                         from session state.
    """
    _saved_total   = sum(float(v) for v in weights_cache.values()) if weights_cache else 0.0
    _weights_ready = abs(_saved_total - 100.0) < 0.5 and len(weights_cache) > 0

    st.markdown("")
    rb_left, rb_right = st.columns([2, 3])

    with rb_left:
        cycle_phase = st.selectbox(
            "Current cycle phase",
            options=CYCLE_PHASES,
            index=2,
            help=(
                "Select the macro cycle phase that best matches current conditions. "
                "Check the Dashboard and Macro Pulse pages for guidance."
            ),
            key="rebalancer_cycle_phase",
        )

    with rb_right:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        if _weights_ready:
            if st.button(
                "📊 Generate Rebalancing Plan",
                type="primary",
                help="Computes cycle-aligned suggested weights for each position.",
            ):
                plan = compute_plan(
                    weights=dict(weights_cache),
                    classifications=classifications,
                    cycle_phase=cycle_phase,
                )
                st.session_state["_rebalancing_plan"]  = plan
                st.session_state["_rebalancing_phase"] = cycle_phase
                st.rerun()
        else:
            st.button(
                "📊 Generate Rebalancing Plan",
                type="primary",
                disabled=True,
                help="Save weights that sum to 100% to unlock this.",
            )

    # ── Render plan if it exists ───────────────────────────────────────────────
    _plan = st.session_state.get("_rebalancing_plan")
    if not _plan:
        return

    _phase = st.session_state.get("_rebalancing_phase", cycle_phase)
    st.markdown("---")
    st.markdown(f"### 📊 Rebalancing Plan — {_phase}")

    st.info(PHASE_RATIONALE.get(_phase, ""), icon="🔭")
    st.markdown("")

    # HTML table
    _sorted_plan = sorted(
        _plan.items(), key=lambda kv: abs(kv[1]["delta"]), reverse=True
    )
    _plan_rows_html = ""
    for ticker, p in _sorted_plan:
        delta  = p["delta"]
        ac_col = ASSET_CLASS_COLORS.get(p["asset_class"], "#6b7280")
        if delta >= 5.0:
            row_bg = "#f0fff8"
        elif delta <= -5.0:
            row_bg = "#fff5f5"
        else:
            row_bg = "#ffffff"

        _plan_rows_html += (
            f'<tr style="border-bottom:1px solid #ececec;background:{row_bg};">'
            f'<td style="color:#3498db;font-weight:700;padding:{_ROW_PAD};'
            f'font-size:{_ROW_FONT};">{ticker}</td>'
            f'<td style="color:#495057;padding:{_ROW_PAD};font-size:{_ROW_FONT};">'
            f'{p["sector"]}</td>'
            f'<td style="padding:{_ROW_PAD};font-size:0.72rem;">'
            f'<span style="color:{ac_col};font-weight:600;">{p["asset_class"]}</span></td>'
            f'<td style="text-align:right;padding:{_ROW_PAD};font-size:{_ROW_FONT};'
            f'color:#495057;">{p["current"]:.1f}%</td>'
            f'<td style="text-align:right;padding:{_ROW_PAD};font-size:{_ROW_FONT};'
            f'font-weight:600;color:#0a0a0a;">{p["suggested"]:.1f}%</td>'
            f'<td style="text-align:right;padding:{_ROW_PAD};">'
            f'{_delta_html(delta)}</td>'
            f'<td style="padding:{_ROW_PAD};font-size:{_ROW_FONT};">'
            f'{_action_html(p["action"])}</td>'
            f'</tr>'
        )

    _plan_thead = (
        f'<div style="overflow-x:auto;margin:12px 0;">'
        f'<table style="width:100%;border-collapse:collapse;background:#fff;'
        f'font-size:{_ROW_FONT};border-radius:6px;overflow:hidden;'
        f'box-shadow:0 1px 3px rgba(0,0,0,0.06);">'
        f'<thead><tr style="border-bottom:2px solid #dee2e6;background:#f8f9fa;'
        f'color:#6a6a6a;font-size:0.65rem;text-transform:uppercase;letter-spacing:.05em;">'
        f'<th style="padding:{_ROW_PAD};text-align:left;">Ticker</th>'
        f'<th style="padding:{_ROW_PAD};text-align:left;">Sector</th>'
        f'<th style="padding:{_ROW_PAD};text-align:left;">Asset Class</th>'
        f'<th style="padding:{_ROW_PAD};text-align:right;">Current</th>'
        f'<th style="padding:{_ROW_PAD};text-align:right;">Suggested</th>'
        f'<th style="padding:{_ROW_PAD};text-align:right;">Δ</th>'
        f'<th style="padding:{_ROW_PAD};text-align:left;">Action</th>'
        f'</tr></thead><tbody>'
    )
    st.markdown(
        _plan_thead + _plan_rows_html + "</tbody></table></div>",
        unsafe_allow_html=True,
    )

    # CSV export
    df = plan_to_dataframe(_plan)
    _csv_buf = io.StringIO()
    df.to_csv(_csv_buf, index=False)
    _csv_col, _ = st.columns([1, 4])
    with _csv_col:
        st.download_button(
            label="📥 Export CSV",
            data=_csv_buf.getvalue(),
            file_name=(
                f"rebalancing_{_phase.replace(' / ', '_').replace(' ', '_').lower()}.csv"
            ),
            mime="text/csv",
            key="plan_csv_download",
        )

    # Summary metrics
    actions_required = sum(
        1 for p in _plan.values() if "Add" in p["action"] or "Trim" in p["action"]
    )
    total_trim = sum(p["delta"] for p in _plan.values() if p["delta"] < -2.0)
    total_add  = sum(p["delta"] for p in _plan.values() if p["delta"] >  2.0)

    sm1, sm2, sm3 = st.columns(3)
    sm1.metric("Positions to act on", actions_required)
    sm2.metric("Total to trim", f"{abs(total_trim):.1f}%", delta_color="inverse")
    sm3.metric("Total to add",  f"{total_add:.1f}%")

    st.caption(
        "Suggested weights are generated by a quantitative tilt model — not personalised "
        "investment advice. Verify against your own risk tolerance and tax situation "
        "before trading."
    )

    # Rebalancing math expander
    with st.expander("🔢 Show rebalancing math", expanded=False):
        tilts = TILT_MULTIPLIERS.get(_phase, {})
        st.markdown(f"""
**Algorithm — how the {_phase} tilt is computed**

1. Each position is mapped to a *bucket* (Equity-cyclical, Bond, Cash, etc.)
2. Its current weight is multiplied by the bucket's tilt factor
3. All raw tilted weights are normalised so the portfolio still sums to 100%
4. The suggested weight minus the current weight gives **Δ**

| Bucket | Tilt factor | Direction |
|---|---|---|""")

        for bucket, mult in sorted(tilts.items(), key=lambda kv: -kv[1]):
            label     = TILT_BUCKET_LABELS.get(bucket, bucket)
            direction = (
                "↑ Overweight" if mult > 1.02
                else ("↓ Underweight" if mult < 0.98 else "→ Neutral")
            )
            st.markdown(f"| {label} | **{mult:.2f}×** | {direction} |")

        st.markdown("""
**Action thresholds** (applied after normalisation)

| |Δ|| Tag | Meaning |
|---|---|---|
| ≥ 5% | 🟢 Add / 🔴 Trim | Action Required — rebalance now |
| 2–5% | 🟡 Minor add/trim | Optional — worth reviewing |
| < 2% | ⚪ Hold | Within tolerance — no trade needed |

**Calibration note:** Multipliers are set so that a 60/40 portfolio in *Contraction* shifts
to roughly 45/47/8 (equity/bond/cash), consistent with typical recession playbooks.
Late/Peak cyclical equities land ~15% below their current weight post-normalisation —
matching a "reduce overweights, rotate to defensives" tilt.
""")

    # AI Memo
    st.markdown("---")
    memo_state = st.session_state.get("_memo_state")

    if memo_state == "run":
        with st.spinner("Writing rebalancing memo…"):
            memo_text = _generate_rebalancing_memo(_plan, _phase)
        st.session_state["_memo_state"] = memo_text
        st.rerun()
    elif memo_state and memo_state != "run":
        st.markdown("#### 📝 AI Rebalancing Memo")
        with st.container(border=True):
            st.markdown(memo_state)
        with st.expander("📋 Copy memo text", expanded=False):
            st.code(memo_state, language=None)
        if st.button("✕ Close memo", key="close_memo"):
            del st.session_state["_memo_state"]
            st.rerun()
    else:
        if st.button(
            "📝 Generate AI Memo",
            help="Claude writes a plain-English macro rationale and action plan.",
        ):
            st.session_state["_memo_state"] = "run"
            st.rerun()

    st.markdown("")
    if st.button("✕ Close plan", key="close_rebalancing_plan"):
        del st.session_state["_rebalancing_plan"]
        for _k in ("_rebalancing_phase", "_memo_state"):
            st.session_state.pop(_k, None)
        st.rerun()
