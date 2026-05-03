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

## Dev workflow
1. Edit CSS in `components/pulse360_theme.py` (or page inline styles)
2. Save → browser auto-reloads at `localhost:8501`
3. Confirm visually
4. Commit and push:
```bash
git add <files>
git commit -m "style: <what you changed>"
git push origin master
```
5. Streamlit Cloud autodeploys in ~1–2 min

## Commit convention
`style: <description>` for all CSS/visual changes

## Confluence docs (mono360.atlassian.net — PULSE360 space)
- Change log + validation: `/wiki/spaces/PULSE360/pages/23101690`
- Dev workflow: `/wiki/spaces/PULSE360/pages/23036064`

## Reference design
- Screenshots: `~/Downloads/design_handoff_pulse360/screenshots/`
- Design files (HTML prototypes): `~/Downloads/design_handoff_pulse360/design_files/`
- Design tokens reference: `~/Downloads/design_handoff_pulse360/design_files/colors_and_type.css`
