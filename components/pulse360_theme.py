# ── Backward-compatibility shim ───────────────────────────────────────────────
# This file was renamed to pie360_theme.py as part of the Stage 2 Pulse360→Pie360
# rename. All imports should now use `from components.pie360_theme import ...`.
# This shim re-exports everything so any missed references continue to work.
# Safe to delete once all imports have been confirmed updated.
from components.pie360_theme import *  # noqa: F401, F403
from components.pie360_theme import (
    inject_theme, page_header, card_wrap, eyebrow, info_banner, signal_pill,
    PAGE_BG, CARD_BG, SUBTLE_BG, BORDER, BORDER_MUT,
    FG_PRIMARY, FG_SEC, FG_MUTED, SUCCESS, WARNING, DANGER,
    CHART_BLUE, CHART_PURPLE,
    BLUE, TEXT_PRI, TEXT_SEC, TEXT_MUT, BLUE_LIGHT,
)
