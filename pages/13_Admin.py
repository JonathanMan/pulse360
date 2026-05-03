"""
pages/13_Admin.py
==================
Internal analytics dashboard — ADMIN_EMAILS only.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from components.analytics import is_admin
from components.supabase_client import get_client

# ── Access control ─────────────────────────────────────────────────────────────
if not is_admin():
    st.error("Access denied.")
    st.stop()

# ── Page header ────────────────────────────────────────────────────────────────
st.markdown("## 📡 Usage Analytics")
st.caption("Internal view — not visible to other users.")

days = st.select_slider("Time window", options=[7, 14, 30, 60, 90], value=30, label_visibility="collapsed")
st.caption(f"Showing last **{days} days**.")

st.markdown("---")


# ── Data fetch ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=120, show_spinner=False)
def _fetch(days: int) -> pd.DataFrame:
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    resp = (
        get_client()
        .table("usage_events")
        .select("id, user_email, event_type, page, metadata, created_at")
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(10_000)
        .execute()
    )
    if not resp.data:
        return pd.DataFrame()
    df = pd.DataFrame(resp.data)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    df["date"] = df["created_at"].dt.date
    return df


df = _fetch(days)

if df.empty:
    st.info("No events yet — analytics will appear as users interact with the app.")
    st.stop()

pv = df[df["event_type"] == "page_view"]
lg = df[df["event_type"] == "login"]

# ── Summary metrics ────────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Page views", len(pv))
with m2:
    st.metric("Logins", len(lg))
with m3:
    st.metric("Unique users", df["user_email"].nunique())
with m4:
    last = df["created_at"].max()
    st.metric("Last activity", last.strftime("%d %b %H:%M UTC") if pd.notna(last) else "—")

st.markdown("")

# ── Charts ─────────────────────────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.markdown("#### Most visited pages")
    if not pv.empty:
        counts = (
            pv.groupby("page")
            .size()
            .reset_index(name="views")
            .sort_values("views", ascending=False)
        )
        st.bar_chart(counts, x="page", y="views", x_label="", y_label="Views")
    else:
        st.caption("No page view data yet.")

with right:
    st.markdown("#### Daily activity")
    daily = (
        df.groupby(["date", "event_type"])
        .size()
        .unstack(fill_value=0)
    )
    # ensure both columns exist even if one event type never occurred
    for col in ("page_view", "login"):
        if col not in daily.columns:
            daily[col] = 0
    st.line_chart(daily[["page_view", "login"]].rename(columns={"page_view": "Page views", "login": "Logins"}))

# ── Per-user summary ───────────────────────────────────────────────────────────
st.markdown("#### Users")

user_tbl = (
    df.groupby("user_email")
    .agg(
        Logins=("event_type", lambda x: (x == "login").sum()),
        **{"Page views": ("event_type", lambda x: (x == "page_view").sum())},
        **{"Last seen": ("created_at", "max")},
        **{"First seen": ("created_at", "min")},
    )
    .reset_index()
    .rename(columns={"user_email": "User"})
)
user_tbl["Last seen"] = user_tbl["Last seen"].dt.strftime("%d %b %Y %H:%M UTC")
user_tbl["First seen"] = user_tbl["First seen"].dt.strftime("%d %b %Y")
user_tbl = user_tbl.sort_values("Last seen", ascending=False)
st.dataframe(user_tbl, use_container_width=True, hide_index=True)

# ── Login method breakdown ─────────────────────────────────────────────────────
if not lg.empty:
    st.markdown("#### Login method breakdown")
    try:
        methods = lg["metadata"].dropna().apply(
            lambda m: m.get("method", "unknown") if isinstance(m, dict) else "unknown"
        ).value_counts().reset_index()
        methods.columns = ["Method", "Count"]
        st.dataframe(methods, use_container_width=True, hide_index=True)
    except Exception:
        pass

# ── Recent events ──────────────────────────────────────────────────────────────
st.markdown("#### Recent events")
recent = df.head(100)[["created_at", "user_email", "event_type", "page"]].copy()
recent["created_at"] = recent["created_at"].dt.strftime("%d %b %H:%M UTC")
recent.columns = ["Time", "User", "Event", "Page"]
st.dataframe(recent, use_container_width=True, hide_index=True)
