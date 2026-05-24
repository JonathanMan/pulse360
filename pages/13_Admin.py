"""
Pie360 — Admin Analytics
=========================
Usage dashboard for admins only. Gated to emails listed in the
ADMIN_EMAILS Streamlit secret (comma-separated).

Shows data from the `usage_events` Supabase table written by
components/analytics.py (log_page_view, log_login).

To grant yourself access, add to Streamlit Cloud secrets:
    ADMIN_EMAILS = "yourname@example.com"
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone

from components.pulse360_theme import inject_theme, PAGE_BG, CARD_BG, BORDER, FG_PRIMARY, FG_SEC, FG_MUTED, SUCCESS, DANGER, WARNING, CHART_BLUE
from components.analytics import is_admin
from components.supabase_client import get_client

inject_theme()

# ── Access gate ───────────────────────────────────────────────────────────────
if not is_admin():
    st.title("🔒 Admin only")
    st.info("This page is restricted. Ask Jonathan to add your email to `ADMIN_EMAILS` in Streamlit Cloud secrets.")
    st.stop()

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="margin-bottom:1.5rem;">
  <div style="font-size:0.72rem;font-weight:700;color:{FG_SEC};
              text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;
              font-family:'Geist Mono',monospace;">Admin</div>
  <h1 style="font-size:1.8rem;font-weight:800;color:{FG_PRIMARY};margin:0 0 4px 0;">
    Usage Analytics
  </h1>
  <div style="font-size:0.9rem;color:{FG_SEC};">
    Who's using Pie360 and what they're doing.
  </div>
</div>
""", unsafe_allow_html=True)

# ── Date range filter ─────────────────────────────────────────────────────────
col_range, col_refresh = st.columns([3, 1])
with col_range:
    days_back = st.selectbox(
        "Time window",
        options=[7, 14, 30, 90],
        format_func=lambda d: f"Last {d} days",
        index=1,
        label_visibility="collapsed",
    )
with col_refresh:
    if st.button("↺ Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── Data fetch ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _fetch_events(days: int) -> pd.DataFrame:
    """Pull usage_events from Supabase for the last N days."""
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        resp = (
            get_client()
            .table("usage_events")
            .select("*")
            .gte("created_at", since)
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        if not resp.data:
            return pd.DataFrame()
        df = pd.DataFrame(resp.data)
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        df["date"] = df["created_at"].dt.date
        df["hour"] = df["created_at"].dt.hour
        df["user_email"] = df["user_email"].fillna("(guest)")
        return df
    except Exception as e:
        st.error(f"Could not fetch events: {e}")
        return pd.DataFrame()

df = _fetch_events(days_back)

if df.empty:
    st.info("No events recorded yet. Make sure `usage_events` table exists in Supabase and the app has been visited since analytics was wired up.")
    st.stop()

# ── Split by event type ────────────────────────────────────────────────────────
page_views = df[df["event_type"] == "page_view"]
logins     = df[df["event_type"] == "login"]
all_users  = df[df["user_email"] != "(guest)"]["user_email"].unique()
guests     = df[df["user_email"] == "(guest)"]

# ── KPI row ───────────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)

def _kpi(col, label, value, note="", color=FG_PRIMARY):
    col.markdown(f"""
<div style="border:1px solid {BORDER};padding:16px 18px;background:{CARD_BG};">
  <div style="font-size:0.68rem;font-weight:700;color:{FG_SEC};
              text-transform:uppercase;letter-spacing:.07em;
              font-family:'Geist Mono',monospace;margin-bottom:6px;">{label}</div>
  <div style="font-size:2rem;font-weight:800;color:{color};
              font-family:'Geist Mono',monospace;line-height:1;">{value}</div>
  <div style="font-size:0.75rem;color:{FG_MUTED};margin-top:4px;">{note}</div>
</div>
""", unsafe_allow_html=True)

_kpi(k1, "Page Views",     len(page_views),   f"last {days_back} days")
_kpi(k2, "Unique Users",   len(all_users),     "signed-in accounts",  color=CHART_BLUE)
_kpi(k3, "Logins",         len(logins),        "auth events",         color=SUCCESS)
_kpi(k4, "Guest Sessions", len(df[df["user_email"]=="(guest)"]["date"].unique()), "days with guest traffic", color=WARNING)

st.markdown("<div style='margin:1.5rem 0'></div>", unsafe_allow_html=True)

# ── Page popularity ───────────────────────────────────────────────────────────
st.markdown(f"#### Page popularity")
if not page_views.empty:
    page_counts = (
        page_views.groupby("page")
        .size()
        .reset_index(name="views")
        .sort_values("views", ascending=False)
    )

    import plotly.express as px
    fig = px.bar(
        page_counts,
        x="views",
        y="page",
        orientation="h",
        color_discrete_sequence=[CHART_BLUE],
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Geist, sans-serif", color=FG_PRIMARY, size=12),
        xaxis=dict(gridcolor=BORDER, title="Views"),
        yaxis=dict(title="", autorange="reversed"),
        margin=dict(l=0, r=0, t=10, b=10),
        height=max(250, len(page_counts) * 32),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.caption("No page view events yet.")

# ── Daily activity trend ───────────────────────────────────────────────────────
st.markdown(f"#### Daily activity")
daily = (
    df.groupby(["date", "event_type"])
    .size()
    .reset_index(name="count")
)
if not daily.empty:
    import plotly.express as px
    fig2 = px.line(
        daily,
        x="date",
        y="count",
        color="event_type",
        color_discrete_map={"page_view": CHART_BLUE, "login": SUCCESS},
        markers=True,
    )
    fig2.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Geist, sans-serif", color=FG_PRIMARY, size=12),
        xaxis=dict(gridcolor=BORDER, title=""),
        yaxis=dict(gridcolor=BORDER, title="Events"),
        margin=dict(l=0, r=0, t=10, b=10),
        height=280,
        legend=dict(title="", orientation="h", y=1.1),
    )
    st.plotly_chart(fig2, use_container_width=True)

# ── User activity table ────────────────────────────────────────────────────────
st.markdown(f"#### User activity")
if not page_views.empty:
    user_stats = (
        page_views[page_views["user_email"] != "(guest)"]
        .groupby("user_email")
        .agg(
            page_views=("event_type", "count"),
            first_seen=("created_at", "min"),
            last_seen=("created_at", "max"),
            pages_visited=("page", lambda x: ", ".join(sorted(x.unique()))),
        )
        .reset_index()
        .sort_values("last_seen", ascending=False)
    )
    user_stats["first_seen"] = user_stats["first_seen"].dt.strftime("%Y-%m-%d %H:%M")
    user_stats["last_seen"]  = user_stats["last_seen"].dt.strftime("%Y-%m-%d %H:%M")
    user_stats = user_stats.rename(columns={
        "user_email": "User",
        "page_views": "Views",
        "first_seen": "First seen",
        "last_seen":  "Last seen",
        "pages_visited": "Pages visited",
    })
    st.dataframe(user_stats, use_container_width=True, hide_index=True)
else:
    st.caption("No signed-in user activity yet.")

# ── Login method breakdown ─────────────────────────────────────────────────────
if not logins.empty:
    st.markdown(f"#### Login methods")
    try:
        login_meta = logins["metadata"].apply(
            lambda x: x.get("method", "unknown") if isinstance(x, dict) else "unknown"
        )
        method_counts = login_meta.value_counts().reset_index()
        method_counts.columns = ["Method", "Count"]
        st.dataframe(method_counts, use_container_width=True, hide_index=True)
    except Exception:
        pass

# ── Raw event log ─────────────────────────────────────────────────────────────
with st.expander("Raw event log"):
    display_cols = [c for c in ["created_at", "user_email", "event_type", "page", "metadata"] if c in df.columns]
    st.dataframe(
        df[display_cols].head(500),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"Showing up to 500 of {len(df)} events")
