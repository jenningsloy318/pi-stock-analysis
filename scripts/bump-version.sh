#!/usr/bin/env bash
# scripts/bump-version.sh — sync the version across every manifest that ships
# with this package, and prepend a CHANGELOG stub.
#
# Usage:  scripts/bump-version.sh <new-version>
# Example: scripts/bump-version.sh 0.2.0
#
# Idempotent: safe to re-run with the same version (won't duplicate the
# CHANGELOG stub). No network, no git operations — you commit + tag by hand
# after reviewing the stub.
#
# Files touched:
#   - package.json                            (npm version, canonical)
#   - skills/stock-analysis/SKILL.md          (front-matter version:)
#   - CHANGELOG.md                            (prepend a stub if new version)

set -euo pipefail

# ─── arg check ──────────────────────────────────────────────────────────────
NEW="${1:-}"
if [[ -z "$NEW" ]]; then
    echo "usage: scripts/bump-version.sh <new-version>" >&2
    echo "example: scripts/bump-version.sh 0.2.0" >&2
    exit 2
fi
if [[ ! "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
    echo "not semver: $NEW" >&2
    exit 2
fi

# ─── locate repo root (script may be invoked from anywhere) ────────────────
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# ─── sanity: we're in the right repo ────────────────────────────────────────
if ! grep -q '"name": "pi-stock-analysis"' package.json 2>/dev/null; then
    echo "package.json is not pi-stock-analysis (ran from wrong dir?)" >&2
    exit 1
fi

CURRENT=$(node -p "require('./package.json').version")
TODAY=$(date +%Y-%m-%d)

echo "Bumping $CURRENT → $NEW"

# ─── 1. package.json ────────────────────────────────────────────────────────
if [[ "$CURRENT" != "$NEW" ]]; then
    npm --no-git-tag-version version "$NEW" >/dev/null
    echo "  ✓ package.json → $NEW"
else
    echo "  · package.json already $NEW"
fi

# ─── 2. skills/stock-analysis/SKILL.md front-matter ─────────────────────────
SKILL="skills/stock-analysis/SKILL.md"
if [[ -f "$SKILL" ]]; then
    SKILL_CUR=$(sed -nE 's/^version: "(.*)"$/\1/p' "$SKILL" | head -n1)
    if [[ "$SKILL_CUR" != "$NEW" ]]; then
        # BSD/GNU sed portable: write to a tmp file then move.
        tmp=$(mktemp)
        sed -E "s/^version: \".*\"$/version: \"$NEW\"/" "$SKILL" > "$tmp"
        mv "$tmp" "$SKILL"
        echo "  ✓ $SKILL → $NEW (was $SKILL_CUR)"
    else
        echo "  · $SKILL already $NEW"
    fi
else
    echo "  ! $SKILL not found — skipped" >&2
fi

# ─── 3. CHANGELOG.md — prepend a stub if this version isn't listed ─────────
CHANGELOG="CHANGELOG.md"
if [[ -f "$CHANGELOG" ]]; then
    if grep -qE "^## \[$NEW\]" "$CHANGELOG"; then
        echo "  · CHANGELOG.md already has an entry for [$NEW]"
    else
        tmp=$(mktemp)
        awk -v ver="$NEW" -v today="$TODAY" '
            BEGIN { inserted = 0 }
            # Insert the new stub immediately before the first existing "## [x.y.z]" entry.
            !inserted && /^## \[[0-9]/ {
                print "## [" ver "] - " today
                print ""
                print "### Added"
                print "- TODO"
                print ""
                inserted = 1
            }
            { print }
            END {
                # If the file had no prior version sections (e.g. first release),
                # append the stub at the end.
                if (!inserted) {
                    print ""
                    print "## [" ver "] - " today
                    print ""
                    print "### Added"
                    print "- TODO"
                }
            }
        ' "$CHANGELOG" > "$tmp"
        mv "$tmp" "$CHANGELOG"
        echo "  ✓ CHANGELOG.md → prepended [$NEW] stub"
    fi
else
    echo "  ! $CHANGELOG not found — skipped" >&2
fi

echo
echo "Done. Next steps:"
echo "  1. Edit the CHANGELOG.md '### Added' stub with real entries."
echo "  2. git add -p && git commit -m \"chore: bump version to $NEW\""
echo "  3. git tag v$NEW && git push --tags"
