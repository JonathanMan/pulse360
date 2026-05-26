# Pulse360 — Claude Project Context

## What this project is
Pulse360 is a Streamlit + Python macro-economic investment dashboard for individual investors.
It shows cycle phase, recession probability, leading indicators, and generates AI daily briefings.
We are doing a **CSS-only reskin** — Terminal Light v2 design system. No changes to data models, APIs, or business logic.

## Local setup
- Repo: `https://github.com/JonathanMan/pulse360` — push directly to `master`
- Local clone: `~/Downloads/pulse360`
- Run: `python3 -m streamlit run app.py` → opens at `http://localhost:8501`
- Secrets: `~/Downloads/pulse360/.streamlit/secrets.toml` (already configured — never commit this file)

## Key files
| File | Purpose |
|---|---|
| `components/pulse360_theme.py` | Master CSS + all design tokens — edit this for global style changes |
| `components/overview_row.py` | Dashboard overview row inline styles (phase card, gauge, risk scorecard) |
| `components/chart_utils.py` | Plotly chart layout — colours, fonts, hover labels, range selector |
| `pages/4_Portfolio.py` | Portfolio page inline styles |
| `pages/*.py` | Each page has its own `inject_theme()` call + optional inline styles |
| `.streamlit/config.toml` | Streamlit theme config (`primaryColor: #0a0a0a`, `backgroundColor: #fafafa`) |

## Design system: Terminal Light v2
All tokens are defined at the top of `components/pulse360_theme.py`.

### Colour tokens
```python
PAGE_BG     = "#fafafa"   # app canvas
CARD_BG     = "#ffffff"   # card surfaces
SUBTLE_BG   = "#f4f4f4"   # table headers, hover states, secondary panels
BORDER      = "#ececec"   # hairline borders (replaces all shadows)
BORDER_MUT  = "#b8b8b8"   # input borders
FG_PRIMARY  = "#0a0a0a"   # primary text + primary action colour
FG_SEC      = "#6a6a6a"   # secondary text / labels
FG_MUTED    = "#a0a0a0"   # muted / placeholder
SUCCESS     = "#00a35a"   # green signal
WARNING     = "#c98800"   # amber signal
DANGER      = "#d92626"   # red signal
CHART_BLUE  = "#1f6feb"
CHART_PURPLE = "#7c4dff"
```

### Typography
- **Sans:** Geist (400/500/600/700) — all UI text
- **Mono:** Geist Mono (400/500/600) — ALL numbers, eyebrow labels, meta text, chart axes

### Rules (never break these)
- `border-radius: 0` on all cards, tiles, inputs, containers
- `border-radius: 999px` on pills only (tabs, chips, status tags)
- **No box-shadow anywhere** — borders do all elevation work
- Transitions: `120ms ease` on interactive elements only

## Theme public API
```python
from components.pulse360_theme import inject_theme  # call once per page
from components.pulse360_theme import page_header, card_wrap, eyebrow, info_banner, signal_pill
# Colour tokens: PAGE_BG, CARD_BG, SUBTLE_BG, BORDER, BORDER_MUT,
#                FG_PRIMARY, FG_SEC, FG_MUTED, SUCCESS, WARNING, DANGER
# Legacy aliases (still work): BLUE, TEXT_PRI, TEXT_SEC, TEXT_MUT, BLUE_LIGHT
```

## What has been done (completed commits)
- `364ff5c` — initial Terminal Light v2 build: new `pulse360_theme.py`, all 36 files migrated from `taplox_theme`
- `5ea265d` — chart_utils tickfont + gridcolor patches
- `45934fa` — border-radius overrides strengthened in overview_row inline styles
- `efc2383` — phase card emoji removed, top-border accent applied; risk scorecard emoji dots removed; stronger container border overrides in theme
- `93e2f23` — sidebar `[aria-current="page"]` selector; `stVerticalBlockBorderWrapper :first-child` fix; Geist Mono on chart hover labels + yaxes tickfont; recession gauge fallback colour; Portfolio.py all rounded corners removed

## Known remaining items
- **Visual QA** — smoke-test against reference screenshots in `~/Downloads/design_handoff_pulse360/screenshots/` (key refs: `01-dashboard.png`, `07-briefing.png`)
- **Backtest + Simulator** (`pages/1_Backtest.py`, `pages/3_Simulator.py`) — colours migrated but no dedicated visual QA pass yet
- **Mobile QA** — TESTING.md section 3 has never been run; test at 390px width (sidebar collapse, gate cards, Macro Pulse card scroll, chart overflow)

## Pending ops tasks (not code — owner: Jonathan)
- **Resend domain verification** — `pie360.app` domain added in Resend dashboard (DNS records shown). Add these records at your DNS registrar:
  - `TXT resend._domainkey` → DKIM key (copy from resend.com/domains)
  - `MX send` → `feedback[...].ses.com` priority 10
  - `TXT send` → `v=spf1 i[...]om ~all`
  - `TXT _dmarc` → `v=DMARC1; p=none;` (optional)
  - Once Resend shows domain as verified, add to **Streamlit Cloud → Settings → Secrets**:
    ```
    RESEND_FROM = "briefing@pie360.app"
    ```
  - No code change needed — `ai/email_briefing.py` and `components/alert_engine.py` already read `st.secrets.get("RESEND_FROM", "onboarding@resend.dev")`

## Dev workflow
1. Edit files in `~/Downloads/pulse360/`
2. Run locally: `python3 -m streamlit run app.py` → `http://localhost:8501`
3. Confirm visually / test
4. Commit and push from Mac Terminal (sandbox cannot push):
```bash
git -C ~/Downloads/pulse360 add <files>
git -C ~/Downloads/pulse360 commit -m "<type>: <what you changed>"
git -C ~/Downloads/pulse360 push origin master
```
5. Streamlit Cloud autodeploys in ~1–2 min

> ⚠️ **Do NOT use `deploy_macro_pulse.sh` for new files.** It rsyncs with `--delete` from `pulse360-app/` (NOT `Pulse360/`) and will delete any repo file that isn't in `pulse360-app/`. After adding new files via direct git, copy them to `pulse360-app/` so future deploys don't wipe them:
> ```bash
> cp ~/Downloads/pulse360/components/<file>.py \
>    "/Users/jonathanman/Library/CloudStorage/GoogleDrive-jonathancyman@gmail.com/My Drive/Business/Claude/Pulse360/pulse360-app/components/<file>.py"
> cp ~/Downloads/pulse360/pages/<file>.py \
>    "/Users/jonathanman/Library/CloudStorage/GoogleDrive-jonathancyman@gmail.com/My Drive/Business/Claude/Pulse360/pulse360-app/pages/<file>.py"
> ```
> **For new files: always use direct git first, then copy to `pulse360-app/`.** The deploy script has a timing issue where newly-copied files result in "Nothing to commit" on the first run.

## Commit convention
`style: <description>` for CSS/visual changes  
`fix: <description>` for bug fixes  
`feat: <description>` for new features

## Streamlit gotchas (hard-won lessons)

### Widget state sync (profile switcher)
`app.py` sidebar has `st.selectbox(key="sidebar_profile_switch")`. If any page changes `pulse360_profile` in session state and reruns, Streamlit uses the **stored widget-key state** (old value) rather than `index=`. This caused the sidebar to silently revert every profile switch.

**Fix in `app.py` (before the selectbox call):**
```python
if st.session_state.get("sidebar_profile_switch") != profile_key:
    st.session_state["sidebar_profile_switch"] = profile_key
```
You cannot set widget key state *after* the widget renders — Streamlit throws `StreamlitAPIException`. Always sync in `app.py` before the `st.selectbox()` call.

### `st.rerun()` ordering
`st.rerun()` is a hard stop — it exits immediately. Render all UI elements **before** any `sleep()` / `rerun()` call, never after.

### `st_javascript` (localStorage)
- Returns `0` (int) on first render before JS mounts — never cache that value
- Never call `st.rerun()` immediately after a localStorage write (race condition)
- Same `key=` cannot be registered twice per render cycle

## Confluence docs (mono360.atlassian.net — PULSE360 space)
- Change log + validation: `/wiki/spaces/PULSE360/pages/23101690`
- Dev workflow: `/wiki/spaces/PULSE360/pages/23036064`

## Reference design
- Screenshots: `~/Downloads/design_handoff_pulse360/screenshots/`
- Design files (HTML prototypes): `~/Downloads/design_handoff_pulse360/design_files/`
- Design tokens reference: `~/Downloads/design_handoff_pulse360/design_files/colors_and_type.css`
