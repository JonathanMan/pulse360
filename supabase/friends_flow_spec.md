# Pie360 — Friends & Portfolio Sharing: End-to-End Flow Spec

## Architecture overview

```
Browser (Streamlit session)
  ↕  st.session_state / st_javascript localStorage
pages/14_Friends.py
  ↕  Python function calls
components/friends_store.py
  ↕  supabase-py (service_role key)
Supabase (Postgres + RLS)
  ├── friendships
  ├── invite_tokens
  └── portfolio_snapshots
```

Identity key throughout: `user_email` — returned by `get_user_email()` which may be an E.164 phone string for phone-only accounts.

---

## Flow 1: Add friend by email

```
User (A) types friend's email → clicks "Send request"
  │
  ├─ send_friend_request(A.email, B.email)
  │     │
  │     ├─ Guard: A == B → error "You can't add yourself"
  │     ├─ _existing_row(A, B)  [checks both directions]
  │     │     │
  │     │     ├─ row.status == "accepted" → error "Already friends"
  │     │     ├─ row.status == "pending" AND row.requester == A
  │     │     │     → error "Request already sent"
  │     │     ├─ row.status == "pending" AND row.requester == B
  │     │     │     → UPDATE status="accepted"  [auto-accept crossover]
  │     │     │       return (True, "auto_accepted")
  │     │     ├─ row.status == "rejected"
  │     │     │     → UPDATE status="pending"   [re-activate]
  │     │     │       return (True, "")
  │     │     └─ no row → INSERT (requester=A, recipient=B, status="pending")
  │     │                  return (True, "")
  │     │
  │     └─ Exception → return (False, error_message)
  │
  ├─ on (True, "auto_accepted"): clear cache → success "You're now friends!"
  ├─ on (True, ""):              clear cache → success "Request sent"
  └─ on (False, msg):            st.error(msg)
```

**DB state after success:**
```
friendships row: { requester_email: A, recipient_email: B, status: "pending"|"accepted" }
```

---

## Flow 2: Accept or reject incoming request

```
User (B) opens "My Network" tab
  │
  ├─ get_pending_incoming(B.email)
  │     SELECT requester_email FROM friendships
  │     WHERE recipient_email = B AND status = "pending"
  │
  ├─ [Accept button] → accept_request(B.email, A.email)
  │     UPDATE friendships SET status="accepted"
  │     WHERE requester_email=A AND recipient_email=B AND status="pending"
  │     → clear st.cache_data → st.rerun()
  │
  └─ [Decline button] → reject_request(B.email, A.email)
        UPDATE friendships SET status="rejected"
        WHERE requester_email=A AND recipient_email=B AND status="pending"
        → clear cache → st.rerun()
```

---

## Flow 3: Remove friend

```
User (A) clicks "Remove" next to B
  │
  └─ remove_friend(A.email, B.email)
        DELETE FROM friendships
        WHERE (requester=A AND recipient=B)
           OR (requester=B AND recipient=A)
        → clear cache → st.rerun()
```

Note: both directions are deleted to maintain symmetry even though the unique constraint only covers ordered pairs.

---

## Flow 4: Generate invite link

```
User (A) clicks "Generate invite link"
  │
  ├─ create_invite_token(A.email)
  │     token = uuid4()
  │     expires = now() + 7 days
  │     INSERT invite_tokens (token, created_by=A, expires_at)
  │     return token
  │
  ├─ store token in st.session_state["generated_invite_token"]
  └─ display URL: https://pie360.app?invite={token}
```

**DB state:**
```
invite_tokens row: { token, created_by: A, used_by: NULL, expires_at: +7d }
```

---

## Flow 5: Consume invite link (recipient visits URL)

```
app.py: ?invite=TOKEN detected → st.session_state["_pending_invite_token"] = TOKEN

pages/14_Friends.py startup:
  │
  ├─ _pending_invite = st.session_state.pop("_pending_invite_token")
  └─ consume_invite_token(token, B.email)
        │
        ├─ SELECT * FROM invite_tokens WHERE token = TOKEN
        │     not found → (False, "Invite link not found or already used")
        │
        ├─ row.used_by not NULL → (False, "Already used")
        ├─ now() > expires_at   → (False, "Expired")
        ├─ creator == B.email   → (False, "Can't use own link")
        │
        ├─ UPDATE invite_tokens SET used_by=B WHERE token=TOKEN
        │
        ├─ send_friend_request(A.email, B.email)  [creates pending row if none exists]
        │
        ├─ _existing_row(A, B):
        │     if status != "accepted" → UPDATE status="accepted"
        │     if no row              → INSERT (requester=A, recipient=B, status="accepted")
        │
        └─ return (True, A.email)

on success: st.success("You're now friends with A!")
            clear get_friends / get_pending caches
```

**DB state after:**
```
invite_tokens: { used_by: B.email }
friendships:   { requester: A, recipient: B, status: "accepted" }
```

---

## Flow 6: Publish portfolio snapshot

```
User (A) is on "Share Settings" tab
  │
  ├─ get_my_snapshot(A.email)
  │     SELECT * FROM portfolio_snapshots WHERE user_email = A
  │     Returns defaults dict if no row yet
  │
  ├─ Toggles: share_holdings | share_performance | share_risk_metrics
  │
  └─ clicks "Publish snapshot"
        │
        ├─ Read raw_tickers / raw_weights from st.session_state
        │     (loaded from localStorage by watchlist_store.py)
        │
        ├─ if raw_tickers empty → st.warning("Add tickers first")
        │
        └─ save_snapshot(A.email, holdings, settings, cycle_phase, recession_prob)
              UPSERT portfolio_snapshots ON CONFLICT(user_email)
              SET holdings_json, share_*, cycle_phase, recession_prob,
                  published_at = now()
              → clear get_my_snapshot cache
              → st.success("Snapshot published — N positions saved")
```

**DB state:**
```
portfolio_snapshots row: {
  user_email:         A,
  holdings_json:      [{ticker, weight}, ...],
  share_holdings:     true|false,
  share_performance:  true|false,
  share_risk_metrics: true|false,
  cycle_phase:        "Mid / Expansion",
  recession_prob:     28.4,
  published_at:       2026-05-27T14:32:00Z
}
```

---

## Flow 7: View friend's snapshot (Compare tab)

```
User (A) opens "Compare" tab, selects B
  │
  ├─ get_my_snapshot(A.email)       [TTL 60s]
  └─ get_friend_snapshot(B.email, A.email)   [TTL 120s]
        │
        ├─ _are_friends(A, B)
        │     SELECT id FROM friendships
        │     WHERE (requester=A AND recipient=B AND status="accepted")
        │        OR (requester=B AND recipient=A AND status="accepted")
        │     not friends → return None (access denied)
        │
        ├─ SELECT * FROM portfolio_snapshots WHERE user_email = B
        │     no row         → return None
        │     published_at NULL → return None
        │
        └─ Apply share flags:
              always include: user_email, display_name, published_at,
                              cycle_phase, recession_prob, share_* flags
              if share_holdings:    include holdings_json
              else:                 holdings_json = None
              return filtered dict

Display logic:
  ├─ both published + share_holdings=true → show holdings comparison chart
  ├─ A not published → st.info("You haven't published yet")
  ├─ B not published → st.info("Friend hasn't published yet")
  └─ B.share_holdings=false → st.info("Friend hasn't enabled holdings sharing")
```

---

## Cache TTLs (friends_store.py)

| Function | TTL | Rationale |
|---|---|---|
| `get_friends` | 30s | Frequent UI display; short enough to pick up new accepts |
| `get_pending_incoming` | 15s | Users check often for new requests |
| `get_pending_outgoing` | 15s | Same pattern |
| `get_my_snapshot` | 60s | Publish button manually clears anyway |
| `get_friend_snapshot` | 120s | Snapshots change rarely (manual publish only) |

Cache invalidation: mutation functions call `.clear()` on the relevant cached functions immediately after a write — no TTL wait needed on the mutation path.

---

## Privacy model

```
User A's data visible to B only when ALL of:
  1. friendships row exists with status="accepted" (either direction)
  2. A.published_at IS NOT NULL
  3. A.share_holdings = true  (for holdings data specifically)

Cycle phase + recession_prob are always shared with accepted friends
once published_at is set — they are not gated by share_* toggles.
```

---

## Edge cases and guards

| Scenario | Handling |
|---|---|
| A sends request to B; B sends request to A before accepting | `_existing_row` detects reverse-pending → auto-accepts |
| Same invite link used twice | `used_by NOT NULL` check → rejected |
| Invite link expired | `now() > expires_at` check → rejected |
| Creator visits own invite link | `creator == my_email` check → rejected |
| Snapshot row doesn't exist yet | `get_my_snapshot` returns defaults dict (no `None` return) |
| Friend removes connection mid-session | `_are_friends()` returns False → `get_friend_snapshot` returns `None` |
| Supabase unreachable | All functions have try/except → return empty list / False / None |
| `save_snapshot` called with empty ticker list | `14_Friends.py` guards: warns and does not call `save_snapshot` |

---

## How to set up the tables

1. Open **Supabase Dashboard → SQL Editor → New query**
2. Paste the contents of `supabase/friends_schema.sql`
3. Click **Run**
4. Confirm output: three rows from the verification SELECT, all with `rowsecurity = true`

No migrations needed for existing rows — all three tables are greenfield.

---

## Future enhancements (not yet built)

- **Push notifications**: when a friend request is received, trigger a Supabase Edge Function → Resend email to recipient
- **Mutual-friend suggestions**: `friendships` is symmetric — a graph query can surface 2nd-degree connections
- **Snapshot history**: add a `portfolio_snapshot_history` table (current row moves to history on each publish)
- **JWT-scoped RLS**: replace service_role catch-all policies with `auth.jwt() ->> 'email'` checks once Streamlit supports same-tab OAuth redirects
- **Share link expiry UI**: show user their active / expired invite tokens with revoke button
