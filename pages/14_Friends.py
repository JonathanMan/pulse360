"""
Pie360 — Friends & Portfolio Comparison
=========================================
Compare your portfolio positioning with friends.

Features
--------
• Add friends by email or shareable invite link
• Accept / reject incoming friend requests
• Per-metric privacy toggles + one-click "Publish snapshot"
  (pushes your current watchlist + weights to Supabase so friends can see it)
• Side-by-side portfolio comparison: holdings overlap, allocation bars,
  cycle positioning

Architecture note
-----------------
Watchlist + weights live in localStorage (browser-only). To compare with
friends, a user must explicitly publish a snapshot to Supabase via the
"Share Settings" tab. Friends never see anything until you publish.
"""

from __future__ import annotations

import streamlit as st

from components.pulse360_theme import (
    inject_theme, page_header,
    BORDER, CARD_BG, FG_MUTED, FG_PRIMARY, FG_SEC, PAGE_BG,
    SUBTLE_BG, SUCCESS, WARNING, DANGER, CHART_BLUE,
)
from components.auth import render_login_gate
from components.supabase_client import get_user_email
from components.friends_store import (
    send_friend_request,
    accept_request,
    reject_request,
    remove_friend,
    get_friends,
    get_pending_incoming,
    get_pending_outgoing,
    create_invite_token,
    consume_invite_token,
    get_my_snapshot,
    save_snapshot,
    get_friend_snapshot,
)

# ── Page setup ────────────────────────────────────────────────────────────────
inject_theme()
st.markdown(
    f"""
    <style>
      .main .block-container {{ padding-top: 1rem; max-width: 1050px; }}

      .f-card {{
        background: {CARD_BG};
        border: 1px solid {BORDER};
        padding: 16px 20px;
        margin-bottom: 12px;
      }}
      .f-card-header {{
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: {FG_MUTED};
        font-family: 'Geist Mono', monospace;
        margin-bottom: 10px;
      }}
      .friend-email {{
        font-size: 0.9rem;
        font-weight: 600;
        color: {FG_PRIMARY};
      }}
      .friend-since {{
        font-size: 0.72rem;
        color: {FG_MUTED};
        font-family: 'Geist Mono', monospace;
      }}
      .pill {{
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }}
      .pill-green  {{ background: #e6f7ed; color: {SUCCESS}; border: 1px solid {SUCCESS}; }}
      .pill-amber  {{ background: #fff8e5; color: {WARNING}; border: 1px solid {WARNING}; }}
      .pill-red    {{ background: #fde8e8; color: {DANGER};  border: 1px solid {DANGER};  }}
      .pill-blue   {{ background: #e8f1fb; color: {CHART_BLUE}; border: 1px solid {CHART_BLUE}; }}
      .pill-muted  {{ background: {SUBTLE_BG}; color: {FG_MUTED}; border: 1px solid {BORDER}; }}
      .invite-box {{
        background: {SUBTLE_BG};
        border: 1px solid {BORDER};
        padding: 12px 16px;
        font-family: 'Geist Mono', monospace;
        font-size: 0.82rem;
        color: {FG_PRIMARY};
        word-break: break-all;
      }}
      .toggle-desc {{
        font-size: 0.8rem;
        color: {FG_SEC};
        line-height: 1.4;
        margin-top: 2px;
      }}
      .empty-state {{
        text-align: center;
        padding: 40px 20px;
        color: {FG_MUTED};
        font-size: 0.88rem;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Auth gate ─────────────────────────────────────────────────────────────────
if not render_login_gate(
    title="Friends & Portfolio Comparison",
    body="Sign in to add friends, share your portfolio, and compare performance.",
    feature_bullets=[
        "Add friends by email or invite link",
        "Control exactly what you share with per-metric toggles",
        "Side-by-side portfolio comparison",
    ],
):
    st.stop()

# ── Invite token handling (from ?invite=TOKEN URL param) ─────────────────────
_my_email = get_user_email()

_pending_invite = st.session_state.pop("_pending_invite_token", None)
if _pending_invite:
    ok, result = consume_invite_token(_pending_invite, _my_email)
    if ok:
        st.success(f"You're now friends with **{result}**!")
        get_friends.clear()
        get_pending_incoming.clear()
        get_pending_outgoing.clear()
    else:
        st.warning(f"Invite link: {result}")

# ── Page header ───────────────────────────────────────────────────────────────
page_header("Friends", "Compare portfolios and cycle positioning with your network")

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_network, tab_add, tab_compare, tab_privacy = st.tabs(
    ["My Network", "Add Friends", "Compare", "Share Settings"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — My Network
# ══════════════════════════════════════════════════════════════════════════════
with tab_network:
    friends  = get_friends(_my_email)
    incoming = get_pending_incoming(_my_email)
    outgoing = get_pending_outgoing(_my_email)

    if incoming:
        st.markdown(
            f'<div class="f-card-header">Pending requests — {len(incoming)}</div>',
            unsafe_allow_html=True,
        )
        for req in incoming:
            col_email, col_acc, col_rej = st.columns([5, 1, 1])
            with col_email:
                st.markdown(
                    f'<div class="friend-email">{req["email"]}</div>'
                    f'<div class="friend-since">wants to connect</div>',
                    unsafe_allow_html=True,
                )
            with col_acc:
                if st.button("Accept", key=f"acc_{req['email']}", type="primary", use_container_width=True):
                    accept_request(_my_email, req["email"])
                    st.cache_data.clear()
                    st.success(f"Connected with {req['email']}!")
                    st.rerun()
            with col_rej:
                if st.button("Decline", key=f"rej_{req['email']}", use_container_width=True):
                    reject_request(_my_email, req["email"])
                    st.cache_data.clear()
                    st.rerun()
        st.divider()

    if friends:
        st.markdown(
            f'<div class="f-card-header">Friends — {len(friends)}</div>',
            unsafe_allow_html=True,
        )
        for f in friends:
            col_info, col_compare, col_remove = st.columns([5, 1, 1])
            since_str = ""
            if f.get("since"):
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(f["since"].replace("Z", "+00:00"))
                    since_str = dt.strftime("Connected %b %d, %Y")
                except Exception:
                    since_str = ""
            with col_info:
                st.markdown(
                    f'<div class="friend-email">{f["email"]}</div>'
                    f'<div class="friend-since">{since_str}</div>',
                    unsafe_allow_html=True,
                )
            with col_compare:
                if st.button("Compare", key=f"cmp_{f['email']}", use_container_width=True):
                    st.session_state["_compare_friend"] = f["email"]
                    st.rerun()
            with col_remove:
                if st.button("Remove", key=f"rem_{f['email']}", use_container_width=True):
                    remove_friend(_my_email, f["email"])
                    st.cache_data.clear()
                    st.rerun()
    else:
        if not incoming:
            st.markdown(
                '<div class="empty-state">'
                'No friends yet.<br>'
                'Head to <strong>Add Friends</strong> to get started.'
                '</div>',
                unsafe_allow_html=True,
            )

    if outgoing:
        st.divider()
        st.markdown(
            f'<div class="f-card-header">Awaiting response — {len(outgoing)}</div>',
            unsafe_allow_html=True,
        )
        for req in outgoing:
            col_email, col_cancel = st.columns([6, 1])
            with col_email:
                st.markdown(
                    f'<div class="friend-email">{req["email"]}</div>'
                    f'<span class="pill pill-amber">Request sent</span>',
                    unsafe_allow_html=True,
                )
            with col_cancel:
                if st.button("Cancel", key=f"cancel_{req['email']}", use_container_width=True):
                    reject_request(req["email"], _my_email)
                    st.cache_data.clear()
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Add Friends
# ══════════════════════════════════════════════════════════════════════════════
with tab_add:
    st.markdown(
        '<div class="f-card-header">Add by email</div>',
        unsafe_allow_html=True,
    )
    with st.form("add_friend_form"):
        friend_email_input = st.text_input(
            "Friend's email",
            placeholder="friend@example.com",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Send request", type="primary", use_container_width=True)

    if submitted:
        if not friend_email_input.strip():
            st.error("Please enter an email address.")
        else:
            ok, msg = send_friend_request(_my_email, friend_email_input.strip().lower())
            if ok:
                if msg == "auto_accepted":
                    st.success(
                        f"They already sent you a request — you're now friends with **{friend_email_input.strip()}**!"
                    )
                else:
                    st.success(
                        f"Request sent to **{friend_email_input.strip()}**. "
                        "They'll see it next time they open Pie360."
                    )
                get_pending_outgoing.clear()
            else:
                st.error(msg)

    st.divider()

    st.markdown(
        '<div class="f-card-header">Share an invite link</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="toggle-desc">'
        'Generate a one-time link to send to anyone — no Pie360 account needed yet. '
        'Valid for 7 days. Once they sign in via the link, you\'re automatically connected.'
        '</p>',
        unsafe_allow_html=True,
    )

    _APP_BASE_URL = "https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app"

    if "generated_invite_token" not in st.session_state:
        if st.button("Generate invite link", use_container_width=True):
            token = create_invite_token(_my_email)
            if token:
                st.session_state["generated_invite_token"] = token
                st.rerun()
            else:
                st.error("Could not create invite link. Please try again.")
    else:
        token = st.session_state["generated_invite_token"]
        invite_url = f"{_APP_BASE_URL}?invite={token}"
        st.code(invite_url, language=None)
        st.caption("Copy the link above and send it. It can only be used once.")
        if st.button("Generate a new link", use_container_width=True):
            del st.session_state["generated_invite_token"]
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Compare
# ══════════════════════════════════════════════════════════════════════════════
with tab_compare:
    friends_list = get_friends(_my_email)

    if not friends_list:
        st.markdown(
            '<div class="empty-state">'
            'Add friends first to compare portfolios.'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        friend_emails = [f["email"] for f in friends_list]
        default_idx = 0
        if st.session_state.get("_compare_friend") in friend_emails:
            default_idx = friend_emails.index(st.session_state["_compare_friend"])

        selected_friend = st.selectbox(
            "Compare with",
            options=friend_emails,
            index=default_idx,
            key="compare_select",
        )

        my_snap     = get_my_snapshot(_my_email)
        friend_snap = get_friend_snapshot(selected_friend, _my_email)

        def _published_label(snap: dict | None) -> str:
            if snap is None:
                return "Not published"
            pub = snap.get("published_at")
            if not pub:
                return "Not published"
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                return f"Updated {dt.strftime('%b %d, %Y')}"
            except Exception:
                return "Published"

        col_me, col_friend = st.columns(2)

        with col_me:
            my_pub       = _published_label(my_snap)
            n_my         = len(my_snap.get("holdings_json") or []) if my_snap else 0
            _my_pub_at   = my_snap and my_snap.get("published_at")
            _my_pill     = "pill-green" if _my_pub_at else "pill-muted"
            _my_lbl      = "Published" if _my_pub_at else "Not shared"
            _my_pos      = f"&nbsp;&nbsp;<span class='pill pill-blue'>{n_my} positions</span>" if n_my else ""
            st.markdown(
                f'<div class="f-card">'
                f'<div class="f-card-header">You</div>'
                f'<div style="font-size:0.82rem;color:{FG_SEC};">{_my_email}</div>'
                f'<div class="friend-since">{my_pub}</div>'
                f'<div style="margin-top:8px;">'
                f'<span class="pill {_my_pill}">{_my_lbl}</span>{_my_pos}'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        with col_friend:
            fr_pub       = _published_label(friend_snap)
            n_fr         = len(friend_snap.get("holdings_json") or []) if friend_snap and friend_snap.get("holdings_json") else 0
            has_fr       = friend_snap is not None and friend_snap.get("published_at")
            _fr_pill     = "pill-green" if has_fr else "pill-muted"
            _fr_lbl      = "Published" if has_fr else "Not shared yet"
            _fr_pos      = f"&nbsp;&nbsp;<span class='pill pill-blue'>{n_fr} positions</span>" if n_fr else ""
            st.markdown(
                f'<div class="f-card">'
                f'<div class="f-card-header">{selected_friend}</div>'
                f'<div style="font-size:0.82rem;color:{FG_SEC};">{selected_friend}</div>'
                f'<div class="friend-since">{fr_pub}</div>'
                f'<div style="margin-top:8px;">'
                f'<span class="pill {_fr_pill}">{_fr_lbl}</span>{_fr_pos}'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        # ── Cycle positioning ──────────────────────────────────────────────────
        my_phase = (my_snap.get("cycle_phase") if my_snap else None) or st.session_state.get("cycle_phase")
        fr_phase = friend_snap.get("cycle_phase") if friend_snap else None
        my_rec   = (my_snap.get("recession_prob") if my_snap else None) or st.session_state.get("recession_probability")
        fr_rec   = friend_snap.get("recession_prob") if friend_snap else None

        if my_phase or fr_phase:
            st.markdown(
                '<div class="f-card-header" style="margin-top:16px;">Cycle positioning</div>',
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Your cycle phase", my_phase or "—")
                if my_rec is not None:
                    st.metric("Your recession risk", f"{my_rec:.0f}%")
            with c2:
                st.metric(f"{selected_friend.split('@')[0]}'s cycle phase", fr_phase or "—")
                if fr_rec is not None:
                    st.metric(f"{selected_friend.split('@')[0]}'s recession risk", f"{fr_rec:.0f}%")

        # ── Holdings comparison ────────────────────────────────────────────────
        my_holdings = my_snap.get("holdings_json") or []
        fr_holdings = friend_snap.get("holdings_json") if friend_snap else None

        if not my_snap or not my_snap.get("published_at"):
            st.info(
                "You haven't published your portfolio yet. "
                "Go to **Share Settings** to publish your watchlist."
            )
        elif not friend_snap:
            st.info(f"**{selected_friend}** hasn't published their portfolio yet.")
        elif not friend_snap.get("share_holdings"):
            st.info(f"**{selected_friend}** hasn't enabled holdings sharing.")
        else:
            st.markdown(
                '<div class="f-card-header" style="margin-top:16px;">Holdings comparison</div>',
                unsafe_allow_html=True,
            )

            my_dict = {h["ticker"]: h.get("weight", 0.0) for h in my_holdings if "ticker" in h}
            fr_dict = {h["ticker"]: h.get("weight", 0.0) for h in (fr_holdings or []) if "ticker" in h}
            all_tickers = sorted(set(list(my_dict.keys()) + list(fr_dict.keys())))

            if not all_tickers:
                st.info("No holdings data to compare — make sure both portfolios have weights set.")
            else:
                import plotly.graph_objects as go

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    name="You",
                    y=all_tickers,
                    x=[my_dict.get(t, 0) for t in all_tickers],
                    orientation="h",
                    marker_color=CHART_BLUE,
                    opacity=0.85,
                ))
                fig.add_trace(go.Bar(
                    name=selected_friend.split("@")[0],
                    y=all_tickers,
                    x=[fr_dict.get(t, 0) for t in all_tickers],
                    orientation="h",
                    marker_color="#7c4dff",
                    opacity=0.85,
                ))
                fig.update_layout(
                    barmode="group",
                    height=max(300, len(all_tickers) * 36),
                    margin=dict(l=0, r=0, t=8, b=0),
                    plot_bgcolor=CARD_BG,
                    paper_bgcolor=CARD_BG,
                    font=dict(family="Geist, sans-serif", size=12, color=FG_PRIMARY),
                    xaxis=dict(
                        title="Weight (%)",
                        gridcolor=BORDER,
                        tickfont=dict(family="Geist Mono, monospace", size=10),
                    ),
                    yaxis=dict(
                        gridcolor=BORDER,
                        tickfont=dict(family="Geist Mono, monospace", size=10),
                    ),
                    legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
                )
                st.plotly_chart(fig, use_container_width=True)

                shared  = set(my_dict.keys()) & set(fr_dict.keys())
                only_me = set(my_dict.keys()) - set(fr_dict.keys())
                only_fr = set(fr_dict.keys()) - set(my_dict.keys())

                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("Shared positions", len(shared))
                with c2:
                    st.metric("Only you hold", len(only_me))
                with c3:
                    st.metric(f"Only {selected_friend.split('@')[0]} holds", len(only_fr))

                if shared:
                    st.markdown(
                        '<div class="f-card-header" style="margin-top:12px;">Shared positions</div>',
                        unsafe_allow_html=True,
                    )
                    cols = st.columns(min(4, len(shared)))
                    for i, ticker in enumerate(sorted(shared)):
                        with cols[i % len(cols)]:
                            my_w = my_dict.get(ticker, 0)
                            fr_w = fr_dict.get(ticker, 0)
                            diff = my_w - fr_w
                            diff_str = f"+{diff:.1f}%" if diff > 0 else f"{diff:.1f}%"
                            diff_color = SUCCESS if diff >= 0 else DANGER
                            st.markdown(
                                f'<div style="text-align:center;padding:8px 4px;">'
                                f'<div style="font-size:1rem;font-weight:700;color:{FG_PRIMARY};">{ticker}</div>'
                                f'<div style="font-family:\'Geist Mono\',monospace;font-size:0.72rem;color:{FG_SEC};">'
                                f'You: {my_w:.1f}% | Friend: {fr_w:.1f}%'
                                f'</div>'
                                f'<div style="font-family:\'Geist Mono\',monospace;font-size:0.72rem;'
                                f'color:{diff_color};">{diff_str} vs friend</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Share Settings
# ══════════════════════════════════════════════════════════════════════════════
with tab_privacy:
    my_snap = get_my_snapshot(_my_email)

    st.markdown(
        '<div class="f-card-header">What friends can see</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="toggle-desc" style="margin-bottom:16px;">'
        'Choose what to share. Changes only apply when you click <strong>Publish snapshot</strong>. '
        'Friends see nothing until you publish.'
        '</p>',
        unsafe_allow_html=True,
    )

    col_tgl, col_desc = st.columns([1, 3])
    with col_tgl:
        share_holdings = st.toggle(
            "Holdings",
            value=bool(my_snap.get("share_holdings", False)),
            key="tgl_holdings",
        )
    with col_desc:
        st.markdown(
            '<div style="padding-top:8px;">'
            '<strong>Tickers &amp; allocation weights</strong><br>'
            '<span class="toggle-desc">Your watchlist positions and percentage weights.</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    col_tgl2, col_desc2 = st.columns([1, 3])
    with col_tgl2:
        share_performance = st.toggle(
            "Performance",
            value=bool(my_snap.get("share_performance", False)),
            key="tgl_performance",
        )
    with col_desc2:
        st.markdown(
            '<div style="padding-top:8px;">'
            '<strong>Performance metrics</strong><br>'
            '<span class="toggle-desc">'
            'Coming soon — will include YTD return and drawdown once live tracking is added.'
            '</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    col_tgl3, col_desc3 = st.columns([1, 3])
    with col_tgl3:
        share_risk = st.toggle(
            "Risk metrics",
            value=bool(my_snap.get("share_risk_metrics", False)),
            key="tgl_risk",
        )
    with col_desc3:
        st.markdown(
            '<div style="padding-top:8px;">'
            '<strong>Risk &amp; quality metrics</strong><br>'
            '<span class="toggle-desc">Buffett scores, cycle sensitivity, and macro tilt for your positions.</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    st.markdown(
        '<div class="f-card-header">Publish your snapshot</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="toggle-desc">'
        'Reads your current watchlist and weights from this browser and saves a snapshot '
        'to the server. Friends can pull it the next time they open the Compare tab. '
        'You can republish any time to update it.'
        '</p>',
        unsafe_allow_html=True,
    )

    pub_at = my_snap.get("published_at")
    if pub_at:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
            pub_label = dt.strftime("Last published %b %d, %Y at %H:%M UTC")
        except Exception:
            pub_label = "Previously published"
        st.markdown(
            f'<span class="pill pill-green">{pub_label}</span>',
            unsafe_allow_html=True,
        )
        st.markdown("")

    if st.button("Publish snapshot", type="primary", use_container_width=True):
        raw_tickers = st.session_state.get("_watchlist_cache") or []
        raw_weights = st.session_state.get("_weights_cache") or {}

        if not raw_tickers:
            st.warning(
                "Your watchlist is empty. "
                "Add tickers on the **Watchlist** page first, then come back here to publish."
            )
        else:
            holdings = [
                {"ticker": t, "weight": float(raw_weights.get(t, 0.0))}
                for t in raw_tickers
            ]
            settings = {
                "share_holdings":    share_holdings,
                "share_performance": share_performance,
                "share_risk_metrics": share_risk,
            }
            ok = save_snapshot(
                my_email=_my_email,
                holdings=holdings,
                settings=settings,
                cycle_phase=st.session_state.get("cycle_phase"),
                recession_prob=st.session_state.get("recession_probability"),
            )
            if ok:
                n = len(holdings)
                st.success(
                    f"Snapshot published — {n} position{'s' if n != 1 else ''} saved. "
                    "Friends with access can now see your portfolio."
                )
                get_my_snapshot.clear()
                st.rerun()
            else:
                st.error("Could not save snapshot. Please try again.")

    st.divider()

    if pub_at:
        st.markdown(
            '<div class="f-card-header" style="color:#d92626;">Danger zone</div>',
            unsafe_allow_html=True,
        )
        if st.button("Remove my shared snapshot", use_container_width=True):
            try:
                from components.supabase_client import get_client
                get_client().table("portfolio_snapshots").update(
                    {"published_at": None, "holdings_json": [], "share_holdings": False,
                     "share_performance": False, "share_risk_metrics": False}
                ).eq("user_email", _my_email).execute()
                get_my_snapshot.clear()
                st.success("Your snapshot has been removed. Friends can no longer see your portfolio.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not remove snapshot: {exc}")
