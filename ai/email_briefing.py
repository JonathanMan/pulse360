"""
Pulse360 — Email Briefing Module
===================================
Composes the daily macro briefing as a clean HTML email and sends it
via a pluggable transport layer.

Two entry points:
  • compose_briefing_html()  → converts briefing markdown to styled HTML email
  • send_briefing_email()    → sends via whichever transport is configured

Transport options (uncomment the one you want in _send_via_transport below):
  1. Gmail SMTP  — needs GMAIL_ADDRESS + GMAIL_APP_PASSWORD in st.secrets
  2. Resend API  — needs RESEND_API_KEY in st.secrets  (pip install resend)
  3. SendGrid    — needs SENDGRID_API_KEY in st.secrets (pip install sendgrid)

To activate a transport:
  1. Add the credentials to .streamlit/secrets.toml
  2. Uncomment the relevant block in _send_via_transport()
  3. Comment out the NotImplementedError line

Usage (in 0_Dashboard.py sidebar):
    from ai.email_briefing import send_briefing_email, compose_briefing_html
    if st.button("📧 Email me today's briefing"):
        html = compose_briefing_html(briefing_text, cycle_phase, probability, traffic_light)
        ok, msg = send_briefing_email(
            to      = st.secrets.get("BRIEFING_EMAIL", "jonathancyman@gmail.com"),
            subject = f"Pulse360 · {date.today():%d %b %Y} · {cycle_phase}",
            html    = html,
        )
        st.success(msg) if ok else st.error(msg)
"""

from __future__ import annotations

import logging
import textwrap
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# ── HTML email template ───────────────────────────────────────────────────────

_EMAIL_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pulse360 Daily Briefing</title>
<style>
  body {{
    margin: 0; padding: 0;
    background-color: #0e1117;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: #e0e0e0;
  }}
  .wrapper {{
    max-width: 640px;
    margin: 0 auto;
    padding: 24px 16px;
  }}
  .header {{
    background: #1a1a2e;
    border-left: 4px solid {tl_color};
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 24px;
  }}
  .header-title {{
    font-size: 1.4rem;
    font-weight: 700;
    color: #ffffff;
    margin: 0 0 4px 0;
  }}
  .header-sub {{
    font-size: 0.85rem;
    color: #888;
    margin: 0;
  }}
  .badges {{
    margin: 12px 0 0 0;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }}
  .badge {{
    font-size: 0.78rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 4px;
  }}
  .badge-phase {{
    background: #2a2a4a;
    color: #a0a0ff;
  }}
  .badge-prob {{
    background: {tl_bg};
    color: {tl_color};
  }}
  .content {{
    background: #1a1a2e;
    border-radius: 8px;
    padding: 20px 24px;
    line-height: 1.7;
    font-size: 0.92rem;
  }}
  .content h2 {{
    font-size: 1rem;
    font-weight: 600;
    color: #ffffff;
    border-bottom: 1px solid #2a2a4a;
    padding-bottom: 6px;
    margin: 20px 0 10px 0;
  }}
  .content h2:first-child {{
    margin-top: 0;
  }}
  .content ul {{
    margin: 0 0 12px 0;
    padding-left: 20px;
  }}
  .content li {{
    margin-bottom: 6px;
    color: #ccc;
  }}
  .content p {{
    color: #ccc;
    margin: 0 0 12px 0;
  }}
  .content strong {{
    color: #ffffff;
  }}
  .disclaimer {{
    font-size: 0.75rem;
    color: #555;
    margin-top: 20px;
    padding-top: 16px;
    border-top: 1px solid #2a2a4a;
    line-height: 1.5;
  }}
  .footer {{
    text-align: center;
    font-size: 0.75rem;
    color: #444;
    margin-top: 20px;
  }}
</style>
</head>
<body>
<div class="wrapper">

  <div class="header">
    <p class="header-title">📊 Pulse360 Daily Briefing</p>
    <p class="header-sub">{date_str}</p>
    <div class="badges">
      <span class="badge badge-phase">{cycle_phase}</span>
      <span class="badge badge-prob">{prob_label}</span>
    </div>
  </div>

  <div class="content">
    {body_html}
  </div>

  <div class="footer">
    Pulse360 · Personal macro dashboard · <a href="https://pulse360.streamlit.app" style="color:#555">Open app</a>
  </div>

</div>
</body>
</html>
"""


# ── Markdown → HTML converter (lightweight, no extra deps) ───────────────────

def _md_to_html(md: str) -> str:
    """
    Convert Pulse360 briefing markdown to email-safe HTML.
    Handles: ## headings, bullet lists, **bold**, *italic*, --- dividers,
    and the standard disclaimer block.
    Deliberately minimal — only what the briefing format actually uses.
    """
    lines   = md.splitlines()
    html    = []
    in_ul   = False

    for line in lines:
        stripped = line.strip()

        # Skip the auto-appended disclaimer separator — handled separately
        if stripped == "---":
            if in_ul:
                html.append("</ul>")
                in_ul = False
            continue

        # Headings
        if stripped.startswith("## "):
            if in_ul:
                html.append("</ul>")
                in_ul = False
            text = _inline_fmt(stripped[3:])
            html.append(f"<h2>{text}</h2>")
            continue

        if stripped.startswith("# "):
            if in_ul:
                html.append("</ul>")
                in_ul = False
            text = _inline_fmt(stripped[2:])
            html.append(f"<h2>{text}</h2>")
            continue

        # Bullet points
        if stripped.startswith("- ") or stripped.startswith("• "):
            if not in_ul:
                html.append("<ul>")
                in_ul = True
            text = _inline_fmt(stripped[2:])
            html.append(f"<li>{text}</li>")
            continue

        # Italic disclaimer line (starts with *)
        if stripped.startswith("*") and stripped.endswith("*") and len(stripped) > 2:
            if in_ul:
                html.append("</ul>")
                in_ul = False
            inner = stripped[1:-1]
            html.append(f'<p class="disclaimer"><em>{_inline_fmt(inner)}</em></p>')
            continue

        # Empty line
        if not stripped:
            if in_ul:
                html.append("</ul>")
                in_ul = False
            continue

        # Regular paragraph
        if in_ul:
            html.append("</ul>")
            in_ul = False
        html.append(f"<p>{_inline_fmt(stripped)}</p>")

    if in_ul:
        html.append("</ul>")

    return "\n".join(html)


def _inline_fmt(text: str) -> str:
    """Apply **bold** and *italic* inline formatting."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
    return text


# ── Public: compose email HTML ────────────────────────────────────────────────

def compose_briefing_html(
    briefing_md: str,
    cycle_phase: str,
    recession_probability: float,
    traffic_light: str,
    date_str: Optional[str] = None,
) -> str:
    """
    Convert a Pulse360 briefing markdown string into a styled HTML email.

    Args:
        briefing_md:           Output of get_daily_briefing() — markdown string
        cycle_phase:           e.g. "Late Expansion"
        recession_probability: 0–100 float
        traffic_light:         "green" | "yellow" | "red"
        date_str:              Optional date label; defaults to today

    Returns:
        Complete HTML string ready to send as email body.
    """
    tl_colors = {
        "green":  ("#2ecc71", "rgba(46,204,113,0.15)"),
        "yellow": ("#f39c12", "rgba(243,156,18,0.15)"),
        "red":    ("#e74c3c", "rgba(231,76,60,0.15)"),
    }
    tl_color, tl_bg = tl_colors.get(traffic_light, ("#888888", "rgba(128,128,128,0.15)"))

    tl_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(traffic_light, "⚪")
    prob_label = f"{tl_emoji} {recession_probability:.1f}% recession risk"

    body_html = _md_to_html(briefing_md)

    return _EMAIL_TEMPLATE.format(
        tl_color   = tl_color,
        tl_bg      = tl_bg,
        date_str   = date_str or date.today().strftime("%A, %-d %B %Y"),
        cycle_phase = cycle_phase,
        prob_label = prob_label,
        body_html  = body_html,
    )


# ── Public: send email ────────────────────────────────────────────────────────

def send_briefing_email(
    to: str,
    subject: str,
    html: str,
) -> tuple[bool, str]:
    """
    Send an HTML email. Transport is determined by which secrets are configured.

    Returns:
        (success: bool, message: str)
    """
    try:
        return _send_via_transport(to=to, subject=subject, html=html)
    except NotImplementedError as exc:
        return False, str(exc)
    except Exception as exc:
        logger.error("send_briefing_email failed: %s", exc)
        return False, f"Send failed: {exc}"


def _send_via_transport(to: str, subject: str, html: str) -> tuple[bool, str]:
    """
    Pluggable transport. Uncomment one of the blocks below to activate it,
    then add the matching credentials to .streamlit/secrets.toml.
    """
    import streamlit as st

    # ── Option 1: Gmail SMTP ──────────────────────────────────────────────────
    # Prerequisites:
    #   1. Enable 2FA on your Google account
    #   2. Create an App Password at myaccount.google.com/apppasswords
    #   3. Add to .streamlit/secrets.toml:
    #        GMAIL_ADDRESS      = "you@gmail.com"
    #        GMAIL_APP_PASSWORD = "xxxx xxxx xxxx xxxx"
    #        BRIEFING_EMAIL     = "you@gmail.com"   # recipient (can be same)
    #
    # if "GMAIL_ADDRESS" in st.secrets:
    #     import smtplib
    #     from email.mime.multipart import MIMEMultipart
    #     from email.mime.text import MIMEText
    #     msg = MIMEMultipart("alternative")
    #     msg["Subject"] = subject
    #     msg["From"]    = st.secrets["GMAIL_ADDRESS"]
    #     msg["To"]      = to
    #     msg.attach(MIMEText(html, "html"))
    #     with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    #         server.login(st.secrets["GMAIL_ADDRESS"], st.secrets["GMAIL_APP_PASSWORD"])
    #         server.sendmail(st.secrets["GMAIL_ADDRESS"], to, msg.as_string())
    #     return True, f"Briefing sent to {to} via Gmail ✓"

    # ── Option 2: Resend API ──────────────────────────────────────────────────
    # Prerequisites:
    #   1. Sign up at resend.com (free tier: 100 emails/day, 3k/month)
    #   2. Create an API key
    #   3. pip install resend
    #   4. Add to .streamlit/secrets.toml:
    #        RESEND_API_KEY = "re_xxxxxxxxxxxx"
    #        RESEND_FROM    = "Pulse360 <briefing@yourdomain.com>"
    #        BRIEFING_EMAIL = "you@gmail.com"
    #
    # if "RESEND_API_KEY" in st.secrets:
    #     import resend
    #     resend.api_key = st.secrets["RESEND_API_KEY"]
    #     resend.Emails.send({
    #         "from":    st.secrets.get("RESEND_FROM", "onboarding@resend.dev"),
    #         "to":      [to],
    #         "subject": subject,
    #         "html":    html,
    #     })
    #     return True, f"Briefing sent to {to} via Resend ✓"

    # ── Option 3: SendGrid ────────────────────────────────────────────────────
    # Prerequisites:
    #   1. Sign up at sendgrid.com (free tier: 100 emails/day)
    #   2. Create an API key with "Mail Send" permission
    #   3. pip install sendgrid
    #   4. Add to .streamlit/secrets.toml:
    #        SENDGRID_API_KEY  = "SG.xxxxxxxxxxxx"
    #        SENDGRID_FROM     = "you@yourdomain.com"
    #        BRIEFING_EMAIL    = "you@gmail.com"
    #
    # if "SENDGRID_API_KEY" in st.secrets:
    #     from sendgrid import SendGridAPIClient
    #     from sendgrid.helpers.mail import Mail
    #     message = Mail(
    #         from_email    = st.secrets.get("SENDGRID_FROM", "pulse360@yourdomain.com"),
    #         to_emails     = to,
    #         subject       = subject,
    #         html_content  = html,
    #     )
    #     sg = SendGridAPIClient(st.secrets["SENDGRID_API_KEY"])
    #     sg.send(message)
    #     return True, f"Briefing sent to {to} via SendGrid ✓"

    # ── No transport configured ───────────────────────────────────────────────
    raise NotImplementedError(
        "No email transport configured. "
        "Open ai/email_briefing.py and uncomment one of the transport blocks "
        "(Gmail SMTP, Resend, or SendGrid), then add the matching credentials "
        "to .streamlit/secrets.toml."
    )
