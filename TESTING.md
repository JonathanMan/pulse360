# Pulse360 — Testing Guide

## 1. Automated Tests (run before every deploy)

```bash
cd ~/Downloads/pulse360
pip install pytest --break-system-packages
pytest tests/ -v
```

Expected output: all tests pass. Fix any failures before pushing.

**Test files and what they cover:**

| File | What it tests |
|---|---|
| `tests/test_auth.py` | Phone number formatting, session helpers, guest detection |
| `tests/test_alert_engine.py` | All alert rule operators including edge cases |
| `tests/test_macro_scoring.py` | Macro regime scoring, score colours, score labels |
| `tests/test_portfolio_parser.py` | CSV/broker import parsing for all column formats |
| `tests/test_user_profile.py` | Profile levels, feature gating, nav section contents |

---

## 2. Manual Pre-Deploy Checklist

Run through this before every deploy. ~15 min total.

### 2a. Session & Auth Flow

| # | Steps | Expected |
|---|---|---|
| A1 | Open app in fresh incognito window | Onboarding screen shows |
| A2 | Pick "Active Investor" → Get Started | Dashboard loads, nav shows 5 sections |
| A3 | Close tab → reopen same URL | Dashboard loads directly, **onboarding skipped** |
| A4 | Switch profile in sidebar to Analyst | Screener + Heatmap + Backtest appear |
| A5 | Close tab → reopen | Analyst profile restored |
| A6 | Click Watchlist as guest | Gate card shows with phone + Google + features |
| A7 | Click Alerts as guest | Gate card shows |
| A8 | Click Settings as guest | Account section shows gate, profile/defaults still visible |
| A9 | Click Dashboard as guest | Full access, no gate |
| A10 | Click Macro Pulse as guest | Full access, no gate |
| A11 | Sign in via Google | Redirects back, nav intact, no onboarding |
| A12 | Check sidebar after login | Profile badge visible, sign-out available |
| A13 | Sign out | Session cleared, Watchlist shows gate again |
| A14 | Sign in via phone OTP | Send code → Enter code → Lands on previous page |

### 2b. Navigation

| # | Steps | Expected |
|---|---|---|
| N1 | Fresh session | Nav shows: Macro Context / My Portfolio / Research / Analysis / Account |
| N2 | Check sidebar | No "NAVIGATION" label, no "expand_more" text |
| N3 | All section headers visible | MACRO CONTEXT, MY PORTFOLIO, etc. in uppercase |
| N4 | Active page highlighted | Left border on current page item |
| N5 | Beginner profile | Stock Screener + Portfolio Heatmap show locked (🔒) in onboarding preview |
| N6 | Switch to Analyst | All 13 pages unlocked in nav |

### 2c. Macro Pulse Page

| # | Steps | Expected |
|---|---|---|
| M1 | Click Macro Pulse | 9 forecaster cards load with name, specialty, bias tag |
| M2 | Check bias tags | Each card shows Perma-bull / Perma-bear / Neutral / Contrarian / Flexible pill |
| M3 | Consensus bar | Shows Bull / Neutral / Bear breakdown |
| M4 | AI Refresh button | Loads (may be slow), updates signals, shows timestamp |
| M5 | signals persist to Portfolio | Open Investment Analyser, check banner shows expert consensus |

### 2d. Investment Analyser

| # | Steps | Expected |
|---|---|---|
| P1 | Upload a CSV with AAPL/MSFT/GOOGL | Positions parsed, table shows |
| P2 | AI analysis runs | Streams text, mentions cycle phase |
| P3 | Macro banner present | Shows recession risk + expert consensus (if Macro Pulse visited) |
| P4 | Upload IBKR export | Parses correctly (uses symbol/pos/mark_price columns) |
| P5 | Upload malformed CSV | Graceful error, not a crash |

### 2e. Watchlist (logged in)

| # | Steps | Expected |
|---|---|---|
| W1 | Add AAPL | Ticker appears in list |
| W2 | Add invalid ticker (e.g. XXXXX) | Score shows as 0 or N/A, no crash |
| W3 | Switch macro regime | MacroAdj scores update |
| W4 | Remove ticker | Disappears from list |
| W5 | Earnings Radar section | Shows upcoming earnings or empty state |
| W6 | CSV export | Downloads file with scored data |

### 2f. Dashboard

| # | Steps | Expected |
|---|---|---|
| D1 | Load Dashboard | Recession probability gauge renders |
| D2 | Cycle phase badge | Shows current phase with confidence |
| D3 | Charts have NBER shading | Grey recession bands visible on time-series |
| D4 | Percentile badges | Show YoY/MoM context on indicators |

### 2g. Alerts (logged in)

| # | Steps | Expected |
|---|---|---|
| AL1 | Create rule: Recession Prob > 50 | Rule appears in list |
| AL2 | Toggle rule off | Rule greyed out |
| AL3 | Delete rule | Removed from list |
| AL4 | Check Dashboard | Alert banners appear when rules fire |

### 2h. Settings (logged in)

| # | Steps | Expected |
|---|---|---|
| S1 | Account section shows | Email/phone displayed, login methods listed |
| S2 | Investor Profile section | Profile cards render, changing saves |
| S3 | Dashboard Defaults | Controls render without error |
| S4 | Data & API Status | FRED + Anthropic status shown |

### 2i. Error & Edge Cases

| # | Scenario | Expected |
|---|---|---|
| E1 | FRED API key missing | Dashboard shows fallback sample data, no crash |
| E2 | Anthropic key missing | AI features show error message, no crash |
| E3 | Upload empty CSV | Graceful error message |
| E4 | Supabase unreachable | Auth degrades to guest mode, no white screen |
| E5 | Very long ticker list (50 tickers) | Watchlist handles without crash |

---

## 3. Mobile / Responsive Check

Open the app on mobile (or DevTools → responsive mode at 390px width):

- [ ] Sidebar collapses correctly
- [ ] Onboarding card is readable
- [ ] Gate cards are readable
- [ ] Macro Pulse cards scroll horizontally or stack
- [ ] Charts resize without overflow

---

## 4. Adding New Tests

When you add a new pure-logic function, add a test file in `tests/`.

**Rules:**
- No Streamlit rendering in unit tests — use `conftest.py` stubs
- No live API calls — mock anything that hits FRED, Supabase, or Anthropic
- Name test files `test_<module>.py`, test classes `Test<Feature>`, methods `test_<behaviour>`

**Quick test for a new function:**
```bash
pytest tests/test_your_file.py -v
```

**Run a single test:**
```bash
pytest tests/test_alert_engine.py::TestEvaluateRuleCrossing::test_crosses_above_fires -v
```
