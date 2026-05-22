#!/bin/bash
# setup-hooks.sh — jednorazowy setup git hooks dla tego repo
#
# Bez tego skrypt hooks z .githooks/ NIE są aktywne (default git hooks dir to .git/hooks/).
# Ten skrypt zmienia core.hooksPath żeby git używał .githooks/ — który JEST commitowany,
# więc po klonowaniu wszyscy mają te same checks.
#
# Uruchom raz po klonowaniu repo:
#   ./tools/setup-hooks.sh

set -e
cd "$(dirname "$0")/.."

# Sanity: musimy być w git repo
if [ ! -d .git ]; then
    echo "❌ Nie jestem w git repo (brak .git/). Uruchom z roota projektu."
    exit 1
fi

# Sanity: hooks dir istnieje
if [ ! -d .githooks ]; then
    echo "❌ Brak .githooks/ — repo może być uszkodzone albo to nie HospesAI."
    exit 1
fi

# Ustaw core.hooksPath
git config core.hooksPath .githooks
chmod +x .githooks/* tools/*.py tools/*.sh 2>/dev/null || true

echo "✓ Git hooks aktywne (.githooks/):"
for h in .githooks/*; do
    [ -f "$h" ] && echo "  • $(basename "$h")"
done
echo ""
echo "Bypass (na własną odpowiedzialność): git commit --no-verify"
echo ""
echo "Sanity check: spróbuj utworzyć commit z imieniem prawdziwego najemcy w opisie —"
echo "powinien zostać zablokowany przez commit-msg hook."
