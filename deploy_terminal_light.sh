#!/usr/bin/env bash
# =============================================================================
# deploy_terminal_light.sh
# =============================================================================
# Applies Pulse360 Terminal Light v2 design to the pulse360 repo and pushes.
#
# Usage:
#   chmod +x deploy_terminal_light.sh
#   ./deploy_terminal_light.sh /path/to/your/pulse360/repo
#
# What this does:
#   1. Copies pulse360_theme.py  → components/pulse360_theme.py
#   2. Copies config.toml        → .streamlit/config.toml
#   3. Runs patch_chart_utils.py → patches components/chart_utils.py
#   4. Updates all import statements (taplox_theme → pulse360_theme)
#   5. Updates old Taplox signal colours in all pages
#   6. Commits with a descriptive message and pushes to origin/master
# =============================================================================

set -euo pipefail

# ── Args ──────────────────────────────────────────────────────────────────────
REPO="${1:-}"
if [[ -z "$REPO" ]]; then
    echo "Usage: ./deploy_terminal_light.sh /path/to/pulse360"
    exit 1
fi
if [[ ! -d "$REPO/.git" ]]; then
    echo "ERROR: $REPO is not a git repository."
    exit 1
fi

# ── Locate the folder containing these scripts ────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Pulse360 — Terminal Light v2 deployment"
echo "  Repo: $REPO"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── 1. Copy theme file ────────────────────────────────────────────────────────
echo "▶ Copying pulse360_theme.py → components/"
cp "$SCRIPT_DIR/pulse360_theme.py" "$REPO/components/pulse360_theme.py"
echo "  ✓ done"

# ── 2. Copy config.toml ───────────────────────────────────────────────────────
echo "▶ Updating .streamlit/config.toml"
cp "$SCRIPT_DIR/config.toml" "$REPO/.streamlit/config.toml"
echo "  ✓ done"

# ── 3. Patch chart_utils.py ───────────────────────────────────────────────────
echo "▶ Patching components/chart_utils.py"
cp "$SCRIPT_DIR/patch_chart_utils.py" "$REPO/patch_chart_utils.py"
cd "$REPO"
python3 patch_chart_utils.py
rm patch_chart_utils.py
echo "  ✓ done"

# ── 4. Update import statements ───────────────────────────────────────────────
echo "▶ Updating import statements (taplox_theme → pulse360_theme)"

# All .py files in the repo
find "$REPO" -name "*.py" \
    ! -path "*/__pycache__/*" \
    ! -name "taplox_theme.py" \
    ! -name "pulse360_theme.py" | while read -r f; do

    if grep -q "taplox_theme" "$f"; then
        sed -i '' \
            's/from components\.taplox_theme import/from components.pulse360_theme import/g' \
            "$f"
        echo "  ✓ $f"
    fi
done

# ── 5. Update Taplox signal colours in all pages ──────────────────────────────
echo "▶ Replacing Taplox signal colours across pages/"

# Map: old → new
declare -A COLOURS=(
    ["#2ecc71"]="#00a35a"
    ["#f39c12"]="#c98800"
    ["#e74c3c"]="#d92626"
    ["#3b7ddd"]="#0a0a0a"
    ["#e8f1fb"]="#f4f4f4"
    ["#293241"]="#0a0a0a"
    ["#6c757d"]="#6a6a6a"
    ["#adb5bd"]="#a0a0a0"
    ["#e9ecef"]="#ececec"
    ["#f5f7fb"]="#f4f4f4"
)

find "$REPO/pages" "$REPO/components" -name "*.py" \
    ! -path "*/__pycache__/*" \
    ! -name "taplox_theme.py" \
    ! -name "pulse360_theme.py" | while read -r f; do

    changed=0
    for old in "${!COLOURS[@]}"; do
        new="${COLOURS[$old]}"
        if grep -q "$old" "$f"; then
            sed -i '' "s/$old/$new/g" "$f"
            changed=1
        fi
    done
    [[ $changed -eq 1 ]] && echo "  ✓ $f"
done

# ── 6. Remove the old taplox_theme.py ────────────────────────────────────────
echo "▶ Archiving taplox_theme.py (renamed, not deleted)"
if [[ -f "$REPO/components/taplox_theme.py" ]]; then
    mv "$REPO/components/taplox_theme.py" "$REPO/components/taplox_theme.py.bak"
    echo "  ✓ renamed to taplox_theme.py.bak"
fi

# ── 7. Git commit and push ────────────────────────────────────────────────────
echo ""
echo "▶ Committing changes"
cd "$REPO"
git add -A
git status --short

git commit -m "style: apply Terminal Light v2 design system

- Replace Taplox theme with Pulse360 Terminal Light v2 (pulse360_theme.py)
- Update .streamlit/config.toml: primaryColor #0a0a0a, bg #fafafa
- Patch chart_utils: p360 grid/axis colours, Geist Mono tick labels
- Update _RANGESELECTOR: black active state, mono font
- Update render_action_item: sharp corners, mono label
- Replace all Taplox signal colours (#2ecc71→#00a35a, #f39c12→#c98800,
  #e74c3c→#d92626) across pages/ and components/
- Update all taplox_theme imports → pulse360_theme"

echo ""
echo "▶ Pushing to origin/master"
git push origin master

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✓ Terminal Light v2 deployed successfully."
echo "  Streamlit Cloud will redeploy automatically."
echo "═══════════════════════════════════════════════════════"
echo ""
