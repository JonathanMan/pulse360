"""
components/friends_store.py
============================
Supabase-backed friends & portfolio sharing store for Pie360.

Tables
------
  friendships          — connection requests and accepted friendships
  invite_tokens        — shareable one-time invite links (7-day expiry)
  portfolio_snapshots  — user-published portfolio snapshots for comparison

All user identity is keyed on user_email (which may be a phone number E.164
string for phone-only accounts, matching the get_user_email() convention).

Public API
----------
  # Friendships
  send_friend_request(my_email, friend_email) -> tuple[bool, str]
  accept_request(my_email, requester_email) -> bool
  reject_request(my_email, requester_email) -> bool
  remove_friend(my_email, friend_email) -> bool
  get_friends(my_email) -> list[dict]            # accepted connections
  get_pending_incoming(my_email) -> list[dict]   # requests I received
  get_pending_outgoing(my_email) -> list[dict]   # requests I sent

  # Invite links
  create_invite_token(my_email) -> str           # returns the token UUID
  consume_invite_token(token, my_email) -> tuple[bool, str]
      # (success, message) — creates accepted friendship on success

  # Portfolio snapshots
  get_my_snapshot(my_email) -> dict
  save_snapshot(my_email, holdings, settings, cycle_phase, recession_prob) -> bool
  get_friend_snapshot(friend_email, my_email) -> dict | None
      # Returns None if friend hasn't published or hasn't shared with me
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

from components.supabase_client import get_client

# ── Table names ───────────────────────────────────────────────────────────────
_FS  = "friendships"
_IT  = "invite_tokens"
_PS  = "portfolio_snapshots"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _are_friends(email_a: str, email_b: str) -> bool:
    """Return True if email_a and email_b have an accepted friendship."""
    try:
        db = get_client()
        r1 = (
            db.table(_FS)
            .select("id")
            .eq("requester_email", email_a)
            .eq("recipient_email", email_b)
            .eq("status", "accepted")
            .maybe_single()
            .execute()
        )
        if r1 and r1.data:
            return True
        r2 = (
            db.table(_FS)
            .select("id")
            .eq("requester_email", email_b)
            .eq("recipient_email", email_a)
            .eq("status", "accepted")
            .maybe_single()
            .execute()
        )
        return bool(r2 and r2.data)
    except Exception:
        return False


def _existing_row(email_a: str, email_b: str) -> dict | None:
    """
    Return the friendships row between email_a and email_b (either direction),
    or None if no row exists.
    """
    try:
        db = get_client()
        for req, rec in [(email_a, email_b), (email_b, email_a)]:
            r = (
                db.table(_FS)
                .select("*")
                .eq("requester_email", req)
                .eq("recipient_email", rec)
                .maybe_single()
                .execute()
            )
            if r and r.data:
                return r.data
    except Exception:
        pass
    return None


# ── Friendship management ─────────────────────────────────────────────────────

def send_friend_request(my_email: str, friend_email: str) -> tuple[bool, str]:
    """
    Send a friend request from my_email to friend_email.

    Returns (True, "") on success.
    Returns (False, reason_message) on failure.
    """
    if not my_email or not friend_email:
        return False, "Missing email address."
    if my_email.lower() == friend_email.lower():
        return False, "You can't add yourself as a friend."

    existing = _existing_row(my_email, friend_email)
    if existing:
        status = existing.get("status", "")
        if status == "accepted":
            return False, "You're already friends."
        if status == "pending":
            if existing.get("requester_email") == my_email:
                return False, "You already sent them a request — waiting for them to accept."
            else:
                # They already requested me — auto-accept
                try:
                    get_client().table(_FS).update({"status": "accepted"}).eq(
                        "id", existing["id"]
                    ).execute()
                    return True, "auto_accepted"
                except Exception as exc:
                    return False, f"Could not accept existing request: {exc}"
        if status == "rejected":
            try:
                get_client().table(_FS).update({"status": "pending"}).eq(
                    "id", existing["id"]
                ).execute()
                return True, ""
            except Exception as exc:
                return False, f"Could not resend request: {exc}"

    try:
        get_client().table(_FS).insert(
            {
                "requester_email": my_email,
                "recipient_email": friend_email,
                "status": "pending",
            }
        ).execute()
        return True, ""
    except Exception as exc:
        msg = str(exc)
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            return False, "A request already exists between these accounts."
        return False, f"Could not send request: {exc}"


def accept_request(my_email: str, requester_email: str) -> bool:
    """Accept an incoming friend request from requester_email."""
    try:
        get_client().table(_FS).update({"status": "accepted"}).eq(
            "requester_email", requester_email
        ).eq("recipient_email", my_email).eq("status", "pending").execute()
        return True
    except Exception:
        return False


def reject_request(my_email: str, requester_email: str) -> bool:
    """Reject an incoming friend request from requester_email."""
    try:
        get_client().table(_FS).update({"status": "rejected"}).eq(
            "requester_email", requester_email
        ).eq("recipient_email", my_email).eq("status", "pending").execute()
        return True
    except Exception:
        return False


def remove_friend(my_email: str, friend_email: str) -> bool:
    """Remove an accepted friendship (deletes the row in either direction)."""
    try:
        db = get_client()
        for req, rec in [(my_email, friend_email), (friend_email, my_email)]:
            db.table(_FS).delete().eq("requester_email", req).eq(
                "recipient_email", rec
            ).execute()
        return True
    except Exception:
        return False


@st.cache_data(ttl=30, show_spinner=False)
def get_friends(my_email: str) -> list[dict]:
    """
    Return list of accepted friends for my_email.
    Each dict: {"email": str, "since": str}
    """
    try:
        db = get_client()
        r1 = (
            db.table(_FS)
            .select("recipient_email, updated_at")
            .eq("requester_email", my_email)
            .eq("status", "accepted")
            .execute()
        )
        r2 = (
            db.table(_FS)
            .select("requester_email, updated_at")
            .eq("recipient_email", my_email)
            .eq("status", "accepted")
            .execute()
        )
        friends = []
        for row in (r1.data or []):
            friends.append({"email": row["recipient_email"], "since": row.get("updated_at", "")})
        for row in (r2.data or []):
            friends.append({"email": row["requester_email"], "since": row.get("updated_at", "")})
        return friends
    except Exception:
        return []


@st.cache_data(ttl=15, show_spinner=False)
def get_pending_incoming(my_email: str) -> list[dict]:
    """Return pending requests sent TO me."""
    try:
        r = (
            get_client()
            .table(_FS)
            .select("requester_email, created_at")
            .eq("recipient_email", my_email)
            .eq("status", "pending")
            .execute()
        )
        return [
            {"email": row["requester_email"], "sent_at": row.get("created_at", "")}
            for row in (r.data or [])
        ]
    except Exception:
        return []


@st.cache_data(ttl=15, show_spinner=False)
def get_pending_outgoing(my_email: str) -> list[dict]:
    """Return pending requests I sent (awaiting their acceptance)."""
    try:
        r = (
            get_client()
            .table(_FS)
            .select("recipient_email, created_at")
            .eq("requester_email", my_email)
            .eq("status", "pending")
            .execute()
        )
        return [
            {"email": row["recipient_email"], "sent_at": row.get("created_at", "")}
            for row in (r.data or [])
        ]
    except Exception:
        return []


# ── Invite tokens ─────────────────────────────────────────────────────────────

def create_invite_token(my_email: str) -> str | None:
    """
    Create a new invite token for my_email and return it.
    Tokens expire after 7 days. Returns None on failure.
    """
    token = str(uuid.uuid4())
    expires = (_now_utc() + timedelta(days=7)).isoformat()
    try:
        get_client().table(_IT).insert(
            {"token": token, "created_by": my_email, "expires_at": expires}
        ).execute()
        return token
    except Exception:
        return None


def consume_invite_token(token: str, my_email: str) -> tuple[bool, str]:
    """
    Consume an invite token.

    If valid and unused, marks it as used and creates an accepted friendship
    between the token creator and my_email.

    Returns (True, creator_email) on success.
    Returns (False, reason_message) on failure.
    """
    try:
        db = get_client()
        row_resp = (
            db.table(_IT)
            .select("*")
            .eq("token", token)
            .maybe_single()
            .execute()
        )
        if not row_resp or not row_resp.data:
            return False, "Invite link not found or already used."

        row = row_resp.data
        creator_email = row["created_by"]

        if row.get("used_by"):
            return False, "This invite link has already been used."

        expires_str = row.get("expires_at", "")
        if expires_str:
            try:
                expires_dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                if _now_utc() > expires_dt:
                    return False, "This invite link has expired."
            except Exception:
                pass

        if creator_email.lower() == my_email.lower():
            return False, "You can't use your own invite link."

        db.table(_IT).update({"used_by": my_email}).eq("token", token).execute()

        ok, msg = send_friend_request(creator_email, my_email)

        existing = _existing_row(creator_email, my_email)
        if existing and existing.get("status") != "accepted":
            db.table(_FS).update({"status": "accepted"}).eq("id", existing["id"]).execute()
        elif not existing:
            try:
                db.table(_FS).insert(
                    {
                        "requester_email": creator_email,
                        "recipient_email": my_email,
                        "status": "accepted",
                    }
                ).execute()
            except Exception:
                pass

        return True, creator_email

    except Exception as exc:
        return False, f"Could not process invite: {exc}"


# ── Portfolio snapshots ───────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def get_my_snapshot(my_email: str) -> dict:
    """
    Return the current user's portfolio snapshot row, or sensible defaults.
    Always returns a dict (never None).
    """
    defaults: dict[str, Any] = {
        "user_email": my_email,
        "display_name": None,
        "holdings_json": [],
        "share_holdings": False,
        "share_performance": False,
        "share_risk_metrics": False,
        "cycle_phase": None,
        "recession_prob": None,
        "published_at": None,
    }
    try:
        r = (
            get_client()
            .table(_PS)
            .select("*")
            .eq("user_email", my_email)
            .maybe_single()
            .execute()
        )
        if r and r.data:
            return {**defaults, **r.data}
    except Exception:
        pass
    return defaults


def save_snapshot(
    my_email: str,
    holdings: list[dict],
    settings: dict,
    cycle_phase: str | None = None,
    recession_prob: float | None = None,
    display_name: str | None = None,
) -> bool:
    """
    Upsert the user's portfolio snapshot + sharing settings into Supabase.
    Also clears the cached snapshot for this user.
    """
    payload = {
        "user_email": my_email,
        "holdings_json": holdings,
        "share_holdings": bool(settings.get("share_holdings", False)),
        "share_performance": bool(settings.get("share_performance", False)),
        "share_risk_metrics": bool(settings.get("share_risk_metrics", False)),
        "published_at": _now_utc().isoformat(),
    }
    if cycle_phase is not None:
        payload["cycle_phase"] = cycle_phase
    if recession_prob is not None:
        payload["recession_prob"] = float(recession_prob)
    if display_name is not None:
        payload["display_name"] = display_name

    try:
        get_client().table(_PS).upsert(payload, on_conflict="user_email").execute()
        get_my_snapshot.clear()
        return True
    except Exception:
        return False


@st.cache_data(ttl=120, show_spinner=False)
def get_friend_snapshot(friend_email: str, viewer_email: str) -> dict | None:
    """
    Return the friend's published snapshot if:
      1. They have published one.
      2. viewer_email and friend_email are accepted friends.

    Returns None if either condition fails.
    Returns a dict with only the fields the friend has opted to share.
    """
    if not _are_friends(viewer_email, friend_email):
        return None

    try:
        r = (
            get_client()
            .table(_PS)
            .select("*")
            .eq("user_email", friend_email)
            .maybe_single()
            .execute()
        )
        if not r or not r.data:
            return None

        snap = r.data
        if not snap.get("published_at"):
            return None

        result: dict[str, Any] = {
            "user_email": friend_email,
            "display_name": snap.get("display_name"),
            "published_at": snap.get("published_at"),
            "cycle_phase": snap.get("cycle_phase"),
            "recession_prob": snap.get("recession_prob"),
            "share_holdings": snap.get("share_holdings", False),
            "share_performance": snap.get("share_performance", False),
            "share_risk_metrics": snap.get("share_risk_metrics", False),
        }

        if snap.get("share_holdings"):
            result["holdings_json"] = snap.get("holdings_json") or []
        else:
            result["holdings_json"] = None

        return result
    except Exception:
        return None
