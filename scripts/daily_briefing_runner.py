#!/usr/bin/env python3
"""
scripts/daily_briefing_runner.py
---------------------------------
Runs in GitHub Actions at 07:00 UTC weekdays.

Steps:
  1. Fetch 5 FRED indicators
  2. Detect cycle phase + recession probability (via cycle_engine)
  3. Generate briefing via Claude Sonnet
  4. Send HTML email via Resend
  5. Post to Confluence (optional — skipped if CONFLUENCE_API_TOKEN not set)

All config comes from environment variables (GitHub Actions secrets).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ── Required env vars ─────────────────────────────────────────────────────────
def _require(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        log.error("Missing required env var: %s", key)
        sys.exit(1)
    return val

ANTHROPIC_KEY    = _require("ANTHROPIC_API_KEY")
FRED_KEY         = _require("FRED_API_KEY")
RESEND_KEY       = _require("RESEND_API_KEY")
# Supabase creds are not used by this script — kept as optional for future use
SUPABASE_URL     = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY     = os.environ.get("SUPABASE_KEY", "")
CONFLUENCE_TOKEN = os.environ.get("CONFLUENCE_API_TOKEN", "")

BRIEFING_EMAIL = os.environ.get("BRIEFING_EMAIL", "jonathancyman@gmail.com")
RESEND_FROM    = os.environ.get("RESEND_FROM", "onboarding@resend.dev")

# Confluence config (mono360.atlassian.net)
CONFLUENCE_BASE    = "https://mono360.atlassian.net/wiki"
CONFLUENCE_USER    = os.environ.get("CONFLUENCE_USER", "jonathancyman@gmail.com")
CONFLUENCE_PAGE_ID = os.environ.get("CONFLUENCE_BRIEFING_PAGE_ID", "23101690")

# ── Stub streamlit so cycle_engine can be imported without a running app ──────
def _make_st_stub() -> ModuleType:
    stub = ModuleType("streamlit")
    stub.secrets  = {}   # not used in detect_cycle_phase() body
    stub.session_state = {}
    def _passthrough(*a, **kw):
        """Decorator that returns the function unchanged."""
        if a and callable(a[0]):
            return a[0]
        return lambda f: f
    stub.cache_data     = _passthrough
    stub.cache_resource = _passthrough
    stub.error = lambda *a, **kw: None
    stub.warning = lambda *a, **kw: None
    stub.info = lambda *a, **kw: None
    return stub

sys.modules.setdefault("streamlit", _make_st_stub())

# Add repo root to path so components/ is importable
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

# ── Import repo modules (after st stub is in place) ───────────────────────────
try:
    from components.cycle_engine import detect_cycle_phase, CycleResult
    from components.fred_utils import safe_get_series
except Exception as exc:
    log.error("Failed to import cycle_engine: %s", exc)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. FETCH MACRO DATA
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_macro_data() -> dict:
    """Fetch key FRED indicators. Returns dict with latest values."""
    log.info("Fetching FRED macro data…")
    start = "2020-01-01"
    data  = {}

    for sid in ["UNRATE", "T10Y2Y", "USSLIND", "CPIAUCSL", "INDPRO"]:
        try:
            s = safe_get_series(sid, FRED_KEY, observation_start=start, warn=False)
            if s is not None and not s.empty:
                data[sid] = float(s.dropna().iloc[-1])
                log.info("  %s = %.2f", sid, data[sid])
        except Exception as exc:
            log.warning("  %s unavailable: %s", sid, exc)

    return data


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DETECT CYCLE PHASE
# ═══════════════════════════════════════════════════════════════════════════════

def get_cycle(fred_data: dict) -> CycleResult:
    """Run cycle detection. Falls back gracefully on FRED errors."""
    log.info("Running cycle engine…")
    try:
        result = detect_cycle_phase(FRED_KEY)
        log.info(
            "  Phase: %s | Confidence: %d | Recession prob: %.1f%%",
            result.phase, result.confidence, _recession_prob(result),
        )
        return result
    except Exception as exc:
        log.warning("Cycle engine failed (%s) — using fallback", exc)
        # Return a minimal stub so the briefing still generates
        from components.cycle_engine import CycleResult
        from datetime import datetime
        return CycleResult(
            phase="Late / Peak",
            confidence=40,
            scores={},
            signals={},
            as_of=datetime.now(),
            summary="Cycle engine unavailable — using conservative default.",
            data_quality="unavailable",
        )


def _recession_prob(result: CycleResult) -> float:
    """Derive a 0–100 recession probability from cycle scores."""
    contraction_score = result.scores.get("Contraction", 0)
    total = sum(result.scores.values()) or 1
    return round(100.0 * contraction_score / total, 1)


def _traffic_light(prob: float) -> str:
    if prob >= 50:
        return "red"
    if prob >= 25:
        return "yellow"
    return "green"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GENERATE BRIEFING VIA CLAUDE
# ═══════════════════════════════════════════════════════════════════════════════

BRIEFING_SYSTEM = """You are the analytical engine behind Pie360, an AI-powered economic cycle \
dashboard. Your job is to write a concise, investment-actionable daily macro briefing for a \
sophisticated personal investor (Jonathan) who monitors the economic cycle daily and makes \
active asset allocation decisions.

RULES — follow all of them precisely:
1. Write in plain analyst English. No jargon for its own sake. No hype. No clickbait headlines.
2. Be probabilistic. Say "risk is elevated" not "recession is coming". Name the degree of uncertainty.
3. Be specific and quantitative wherever possible — name indicators, exact values, and thresholds.
4. Never fabricate data. Only cite numbers explicitly provided in the input. If a figure is missing, say "N/A".
5. Keep the total output under ~900 words across all sections.
6. Use the section headers exactly as specified. Do not add, rename, or remove any section.
7. Bullets only within sections that call for bullets. The Tail Risks and Confidence Score sections are single paragraphs.
8. The Asset Class Tilts section must use the exact signal labels: OVERWEIGHT, NEUTRAL, or UNDERWEIGHT. Format as a plain-text aligned table (no markdown table syntax).
9. Never give personalised investment advice ("you should buy X"). Frame all signals in general, historical, cycle-framework terms.
10. End every briefing with this exact disclaimer on its own line: "This is educational macro commentary, not investment advice."
11. Do not write any other disclaimer — only the one specified in rule 10."""


def build_briefing_prompt(
    today: str,
    phase: str,
    confidence: str,
    recession_prob: float,
    traffic_light: str,
    fred_data: dict,
    signals_summary: str,
) -> str:
    tl_text = {"green": "GREEN (<25%)", "yellow": "YELLOW (25–50%)", "red": "RED (≥50%)"}.get(
        traffic_light, traffic_light
    )
    unrate = fred_data.get("UNRATE")
    t10y2y = fred_data.get("T10Y2Y")
    cpi    = fred_data.get("CPIAUCSL")
    indpro = fred_data.get("INDPRO")
    lei    = fred_data.get("USSLIND")

    def fmt(v, suffix=""):
        return f"{v:.2f}{suffix}" if v is not None else "N/A"

    return f"""Date: {today}

═══ MODEL OUTPUT ════════════════════════════════════════════
Cycle Phase:           {phase} ({confidence} confidence)
Recession Probability: {recession_prob:.1f}%  →  {tl_text}

Key Indicators (latest FRED readings):
  Unemployment Rate (UNRATE):     {fmt(unrate, '%')}
  Yield Curve 10Y−2Y (T10Y2Y):   {fmt(t10y2y, ' pp')}
  Industrial Production (INDPRO): {fmt(indpro, ' index')}
  CPI (CPIAUCSL):                 {fmt(cpi, ' index')}
  LEI (USSLIND):                  {fmt(lei)}

Cycle model signal breakdown:
{signals_summary}
═════════════════════════════════════════════════════════════

Using ONLY the data above, write the Pie360 daily macro briefing with EXACTLY these seven \
sections in this order. Use the section headers verbatim. Do not add, rename, or remove any section.

## Cycle Phase Declaration
State the current cycle phase, a confidence percentage (0–100%), and which 2–3 specific \
indicators drove the phase call. Reference exact values from the data provided. \
Flag any indicator that is near a phase-transition threshold and what crossing it would mean. \
Format: one sentence declaring the phase + confidence, then 2–3 bullets naming the driving indicators.

## Recession Probability
State the current recession probability score and its traffic-light status. Describe the trend \
direction (rising / falling / stable) based on the signal breakdown provided. Then state \
2 specific things that would need to change in the indicator readings to move the probability \
materially higher (toward RED) and 1 thing that would move it materially lower (toward GREEN). \
Reference specific indicator thresholds. One compact paragraph.

## Asset Class Tilts
Based on the current cycle phase and indicator readings, provide an explicit positioning signal \
for each asset class below. Format as a plain-text table with three aligned columns — \
Asset Class | Signal | Rationale — where Signal must be exactly one of: OVERWEIGHT, NEUTRAL, \
or UNDERWEIGHT. One concise rationale sentence per row, grounded in the provided data. \
Use exactly these rows in this order:
  US Large Cap Equities
  US Small Cap Equities
  International Developed Equities
  Emerging Market Equities
  Long-Duration Bonds
  Investment-Grade Credit
  High-Yield Credit
  Commodities — Energy
  Commodities — Metals
  Cash
Base every call on the provided data and well-established historical cycle patterns for this phase. \
Do not invent signals that contradict the indicators.

## Sector Rotation Signals
Apply the standard economic-cycle sector rotation framework to the current phase and indicator \
readings. List the top 2 sectors to favour and the top 2 sectors to avoid. \
One bullet per sector. Each bullet: sector name, signal (FAVOUR / AVOID), and the single \
indicator from the data above that most strongly drives the call. \
Reference the phase-framework rationale (e.g. early cycle → financials/industrials favour; \
late cycle → energy/materials favour; contraction → utilities/staples favour). \
Example: "- FAVOUR Industrials: INDPRO at {fmt(indpro, ' index')} and LEI at {fmt(lei)} signal early-cycle expansion."

## Top 3 Macro Observations
The three most important data points or signals from the provided readings, ranked by investment \
significance. One bullet per observation. Each bullet: name the data point with its exact value, \
describe why it matters in the current cycle context, then add one explicit investment implication \
sentence (what this historically suggests for positioning). Be specific — "yield curve at \
{fmt(t10y2y, ' pp')} implies historically that duration extension has outperformed over the \
next 6 months" is good; "the yield curve is concerning" is not.

## Tail Risks
One paragraph of 3–4 sentences. Identify 2–3 specific, named risks that could cause a cycle \
phase reassessment within 30 days. For each risk: name it explicitly, identify the indicator \
that would confirm it is materialising, and state the threshold or reading that would trigger \
a phase downgrade. Conclude with which of these risks currently has the highest probability \
of occurring based on the data provided.

## Confidence Score
State the overall confidence in the current cycle call as exactly one of: HIGH, MEDIUM, or LOW. \
Follow with one sentence justifying the rating by citing the degree of agreement or conflict \
across the model signals provided (e.g. how many indicators align vs conflict with the declared \
phase, whether recent trends support or contradict the call). One sentence only — be direct.

---
This is educational macro commentary, not investment advice."""


def generate_briefing(
    phase: str,
    confidence: str,
    recession_prob: float,
    traffic_light: str,
    fred_data: dict,
    signals_summary: str,
) -> str:
    log.info("Generating briefing via Claude…")
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    today  = date.today().isoformat()

    prompt = build_briefing_prompt(
        today          = today,
        phase          = phase,
        confidence     = confidence,
        recession_prob = recession_prob,
        traffic_light  = traffic_light,
        fred_data      = fred_data,
        signals_summary = signals_summary,
    )

    response = client.messages.create(
        model      = "claude-sonnet-4-6",
        max_tokens = 2200,
        system     = BRIEFING_SYSTEM,
        messages   = [{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    log.info("  Briefing generated (%d chars)", len(text))
    return text


# ═══════════════════════════════════════════════════════════════════════════════
# 4. COMPOSE HTML EMAIL
# ═══════════════════════════════════════════════════════════════════════════════

_TL_COLORS = {"green": "#00a35a", "yellow": "#c98800", "red": "#d92626"}
_TL_BG     = {"green": "#0e2a1a", "yellow": "#2a1e00", "red": "#2a0a0a"}


def _md_to_html(md: str) -> str:
    """Convert simple markdown briefing to HTML (no external deps)."""
    import re
    lines   = md.split("\n")
    out     = []
    in_list = False

    for raw in lines:
        line = raw.rstrip()
        # H2 section header
        if line.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            heading = line[3:].strip()
            out.append(
                f'<h3 style="color:#c8d3f0;font-size:0.95rem;font-weight:700;'
                f'margin:20px 0 6px 0;letter-spacing:.03em;">{heading}</h3>'
            )
        # Bullet
        elif line.startswith("- ") or line.startswith("• "):
            if not in_list:
                out.append('<ul style="margin:0;padding-left:18px;color:#c0c8d8;">')
                in_list = True
            content = line[2:].strip()
            # Bold **text**
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)
            out.append(f'<li style="margin-bottom:5px;line-height:1.5;">{content}</li>')
        # Blank line
        elif not line:
            if in_list:
                out.append("</ul>")
                in_list = False
        # Plain paragraph
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            line = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", line)
            out.append(f'<p style="margin:6px 0;color:#c0c8d8;line-height:1.6;">{line}</p>')

    if in_list:
        out.append("</ul>")

    return "\n".join(out)


def compose_html_email(
    briefing_md: str,
    phase: str,
    recession_prob: float,
    traffic_light: str,
) -> str:
    tl_color = _TL_COLORS.get(traffic_light, "#6b7280")
    tl_bg    = _TL_BG.get(traffic_light, "#1a1a2a")
    body_html = _md_to_html(briefing_md)
    today_str = date.today().strftime("%A, %d %B %Y")
    prob_pct  = f"{recession_prob:.0f}%"

    disclaimer = (
        "<p style='color:#555;font-size:0.75rem;margin-top:24px;line-height:1.5;'>"
        "This briefing is generated by an AI model and is for informational purposes only. "
        "It is not financial advice. Always do your own research before making investment decisions."
        "</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pie360 Daily Briefing · {today_str}</title>
</head>
<body style="margin:0;padding:0;background:#0e1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#e0e0e0;">
<div style="max-width:640px;margin:0 auto;padding:24px 16px;">

  <!-- Header -->
  <div style="background:#1a1a2e;border-left:4px solid {tl_color};border-radius:8px;padding:16px 20px;margin-bottom:24px;">
    <p style="margin:0 0 2px 0;font-size:0.72rem;color:#888;text-transform:uppercase;letter-spacing:.08em;">PIE360 · DAILY BRIEFING</p>
    <h1 style="margin:0 0 4px 0;font-size:1.3rem;font-weight:700;color:#fff;">{today_str}</h1>
    <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
      <span style="font-size:0.78rem;font-weight:600;padding:3px 10px;border-radius:4px;background:#2a2a4a;color:#a0a0ff;">{phase}</span>
      <span style="font-size:0.78rem;font-weight:600;padding:3px 10px;border-radius:4px;background:{tl_bg};color:{tl_color};">Recession Risk {prob_pct}</span>
    </div>
  </div>

  <!-- Briefing body -->
  <div style="background:#151520;border-radius:8px;padding:20px 22px;margin-bottom:20px;">
    {body_html}
  </div>

  <!-- Footer -->
  <div style="text-align:center;padding:12px 0;">
    <a href="https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app"
       style="display:inline-block;padding:10px 24px;background:#1f6feb;color:#fff;
              font-weight:600;font-size:0.85rem;border-radius:6px;text-decoration:none;">
      Open Pie360 Dashboard →
    </a>
  </div>

  {disclaimer}
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SEND EMAIL VIA RESEND
# ═══════════════════════════════════════════════════════════════════════════════

def send_email(html: str, phase: str, recession_prob: float) -> None:
    import resend

    resend.api_key = RESEND_KEY
    today_str = date.today().strftime("%d %b %Y")
    subject   = f"Pie360 · {today_str} · {phase} · Recession Risk {recession_prob:.0f}%"

    log.info("Sending email to %s via Resend…", BRIEFING_EMAIL)
    resp = resend.Emails.send({
        "from":    RESEND_FROM,
        "to":      [BRIEFING_EMAIL],
        "subject": subject,
        "html":    html,
    })
    log.info("  Email sent — ID: %s", resp.get("id", "unknown"))


# ═══════════════════════════════════════════════════════════════════════════════
# 6. POST TO CONFLUENCE
# ═══════════════════════════════════════════════════════════════════════════════

def post_to_confluence(briefing_md: str, phase: str, recession_prob: float) -> None:
    """Append today's briefing as a new child page under CONFLUENCE_PAGE_ID."""
    if not CONFLUENCE_TOKEN:
        log.info("CONFLUENCE_API_TOKEN not set — skipping Confluence post")
        return

    import base64
    import requests

    today_str = date.today().strftime("%d %B %Y")
    title     = f"Daily Briefing · {today_str}"

    # Convert markdown to Confluence storage format (simple HTML subset)
    html_body = _md_to_html(briefing_md).replace("\n", "")
    meta_html = (
        f"<p><strong>Phase:</strong> {phase} | "
        f"<strong>Recession Risk:</strong> {recession_prob:.0f}% | "
        f"<strong>Generated:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>"
        "<hr/>"
    )
    full_body = meta_html + html_body

    auth = base64.b64encode(f"{CONFLUENCE_USER}:{CONFLUENCE_TOKEN}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type":  "application/json",
    }

    payload = {
        "type":      "page",
        "title":     title,
        "ancestors": [{"id": CONFLUENCE_PAGE_ID}],
        "space":     {"key": "PULSE360"},
        "body": {
            "storage": {
                "value":          full_body,
                "representation": "storage",
            }
        },
    }

    url  = f"{CONFLUENCE_BASE}/rest/api/content"
    resp = requests.post(url, headers=headers, json=payload, timeout=15)

    if resp.status_code in (200, 201):
        page_id = resp.json().get("id", "?")
        log.info("  Confluence page created — ID: %s | Title: %s", page_id, title)
    else:
        log.warning(
            "  Confluence post failed (%d): %s",
            resp.status_code, resp.text[:200],
        )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info("=== Pie360 Daily Briefing Runner — %s ===", date.today().isoformat())

    # 1. Fetch FRED data
    fred_data = fetch_macro_data()

    # 2. Detect cycle
    result   = get_cycle(fred_data)
    phase    = result.phase
    conf_lbl = result.confidence_label
    rec_prob = _recession_prob(result)
    tl       = _traffic_light(rec_prob)

    # Build signal summary for the prompt
    signals_summary = result.summary or "No detailed signal breakdown available."
    if result.signals:
        lines = []
        for sig in result.signals.values():
            lines.append(
                f"  {sig.name}: {sig.formatted} ({sig.trend})"
                + (f" → {sig.implied_phase}" if sig.implied_phase else "")
                + (f" — {sig.note}" if sig.note else "")
            )
        signals_summary = "\n".join(lines)

    # 3. Generate briefing
    briefing_md = generate_briefing(
        phase          = phase,
        confidence     = conf_lbl,
        recession_prob = rec_prob,
        traffic_light  = tl,
        fred_data      = fred_data,
        signals_summary= signals_summary,
    )

    # 4. Compose HTML email
    html = compose_html_email(
        briefing_md    = briefing_md,
        phase          = phase,
        recession_prob = rec_prob,
        traffic_light  = tl,
    )

    # 5. Send email
    try:
        send_email(html, phase, rec_prob)
    except Exception as exc:
        log.error("Email send failed: %s", exc)
        sys.exit(1)

    # 6. Post to Confluence (optional — never fails the job)
    try:
        post_to_confluence(briefing_md, phase, rec_prob)
    except Exception as exc:
        log.warning("Confluence post failed (non-fatal): %s", exc)

    log.info("=== Daily briefing complete ===")


if __name__ == "__main__":
    main()
