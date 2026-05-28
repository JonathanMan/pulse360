# Pie360 — Claude Project Context

## Working style
- SHORT replies. Terse, direct. No restating context. Expand only when asked or task requires it.
- Skip TaskCreate for tasks under ~4 steps.
- Use Read offset+limit for large files when only one section is needed.

## What this project is
Pie360 is a Streamlit + Python macro-economic investment dashboard for individual investors.
Shows cycle phase, recession probability, leading indicators, AI daily briefings, stock research, and a Friends social layer.
Live at: https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app (GitHub repo stays `pulse360` intentionally)

## Active config
- Repo: `https://github.com/JonathanMan/pulse360` — push to `master`
- Local clone: `~/Downloads/pulse360`
- Run: `python3 -m streamlit run app.py` → `http://localhost:8501`
- Secrets: `~/Downloads/pulse360/.streamlit/secrets.toml` (never commit)

## Key files
> Full table → memory/key_files.md

Core: `app.py` (router) · `components/pie360_theme.py` (master CSS) · `models/recession_model.py` · `data/fred_client.py` · `data/market_client.py` · `ai/prompts.py`

## Design system
Terminal Light v2 — complete. Active work is features/quality only.
> Colour tokens + rules → memory/design_system.md

## Open items
- Backtest + Simulator (`pages/1_Backtest.py`, `pages/3_Simulator.py`) — no visual QA yet
- `forecaster_weights.py` — Supabase store exists, no page UI yet
- Resend domain `pie360.app` — DNS verification pending
> Full detail → memory/remaining_items.md

## Dev workflow
Edit in `~/Downloads/pulse360/` → test locally → commit + push from Mac Terminal → cp to `pulse360-app/`.

> ⚠️ **`deploy_macro_pulse.sh` rsyncs with `--delete` from `pulse360-app/`.** New files: direct `git add/commit/push` first, then `cp` to `pulse360-app/` — or they'll be wiped on next deploy.

Commit convention: `style:` CSS/visual · `fix:` bugs · `feat:` features

## Streamlit critical gotchas
- **Widget state**: sync `session_state[key]` BEFORE the `st.*` call — `index=` is ignored if key already exists in state.
- **`st.rerun()`**: hard stop. Render ALL UI before any `sleep()`/`rerun()`. Never after.
- **`st_javascript`**: returns `0` on first render (don't cache); `rerun()` after write = race condition; no duplicate `key=` per cycle.
- **`st.cache_data` in tests**: conftest stubs as passthrough — call decorated functions directly, no `.__wrapped__` needed.

## Confluence docs (mono360.atlassian.net — PULSE360 space)
- Change log + validation: `/wiki/spaces/PULSE360/pages/23101690`
- Dev workflow: `/wiki/spaces/PULSE360/pages/23036064`
