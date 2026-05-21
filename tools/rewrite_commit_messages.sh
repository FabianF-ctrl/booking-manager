#!/bin/bash
# rewrite_commit_messages.sh — bezpieczny rewrite commit messages
#
# Background: `git filter-repo --message-callback` ma znaną pułapkę z multi-line
# bytes literals (b"""...""") — wrapping prependuje 2 spacje do każdej linii kodu
# źródłowego, włącznie z liniami WEWNĄTRZ triple-quoted string literals. Bytes
# value staje się "Line 1\n  Line 2" zamiast "Line 1\nLine 2".
#
# Ten skrypt omija problem używając `git commit-tree` bezpośrednio. Buduje nowe
# commity z czystych message files, identyczne tree/author/date — tylko message
# się zmienia. Brak żadnego callback wrapping.
#
# Użycie:
#   1. Stwórz /tmp/msg_<short-sha>.txt dla każdego commitu do edycji
#      (np. /tmp/msg_abc1234.txt z pełną nową treścią — pierwsza linia = subject)
#   2. Uruchom:
#        ./tools/rewrite_commit_messages.sh <base-sha> <commit1> [<commit2>...]
#      base-sha = parent pierwszego commitu do edycji (NIE edytowany)
#      commitN  = commity do edycji w kolejności chronologicznej (od najstarszego)
#   3. Sprawdź `git log --oneline` i `git cat-file -p <new-sha>`
#   4. `git push --force origin <branch>` (jeśli było już pushowane)
#
# Przykład: przepisz dwa ostatnie commity zachowując pierwszy.
#   ./tools/rewrite_commit_messages.sh <HEAD~2> <HEAD~1-sha> <HEAD-sha>

set -e

if [ $# -lt 2 ]; then
    echo "Usage: $0 <base-sha-NOT-rewritten> <commit-sha-to-rewrite> [<commit-sha>...]"
    echo ""
    echo "Each commit needs /tmp/msg_<short-sha>.txt with new full message."
    exit 1
fi

BASE_SHA="$1"
shift
PARENT="$BASE_SHA"

# Sanity: base must exist
/usr/bin/git rev-parse --verify "$BASE_SHA" >/dev/null 2>&1 || {
    echo "ERROR: base-sha $BASE_SHA not found"; exit 1
}

for orig in "$@"; do
    /usr/bin/git rev-parse --verify "$orig" >/dev/null 2>&1 || {
        echo "ERROR: commit $orig not found"; exit 1
    }

    short=$(/usr/bin/git rev-parse --short "$orig")
    msg_file="/tmp/msg_${short}.txt"
    if [ ! -f "$msg_file" ]; then
        echo "ERROR: missing $msg_file (need new message for $orig)"
        exit 1
    fi

    TREE=$(/usr/bin/git log -1 --format='%T' "$orig")
    AUTHOR_NAME=$(/usr/bin/git log -1 --format='%an' "$orig")
    AUTHOR_EMAIL=$(/usr/bin/git log -1 --format='%ae' "$orig")
    AUTHOR_DATE=$(/usr/bin/git log -1 --format='%ad' --date=raw "$orig")
    COMMITTER_NAME=$(/usr/bin/git log -1 --format='%cn' "$orig")
    COMMITTER_EMAIL=$(/usr/bin/git log -1 --format='%ce' "$orig")
    COMMITTER_DATE=$(/usr/bin/git log -1 --format='%cd' --date=raw "$orig")

    NEW=$(GIT_AUTHOR_NAME="$AUTHOR_NAME" \
          GIT_AUTHOR_EMAIL="$AUTHOR_EMAIL" \
          GIT_AUTHOR_DATE="$AUTHOR_DATE" \
          GIT_COMMITTER_NAME="$COMMITTER_NAME" \
          GIT_COMMITTER_EMAIL="$COMMITTER_EMAIL" \
          GIT_COMMITTER_DATE="$COMMITTER_DATE" \
          /usr/bin/git commit-tree "$TREE" -p "$PARENT" -F "$msg_file")

    first_line=$(/usr/bin/head -1 "$msg_file")
    new_short=$(/usr/bin/git rev-parse --short "$NEW")
    echo "  $short → $new_short   $first_line"
    PARENT="$NEW"
done

CURRENT_BRANCH=$(/usr/bin/git symbolic-ref --short HEAD)
OLD_HEAD=$(/usr/bin/git rev-parse --short HEAD)
/usr/bin/git update-ref "refs/heads/$CURRENT_BRANCH" "$PARENT"
NEW_HEAD=$(/usr/bin/git rev-parse --short HEAD)

echo ""
echo "Branch '$CURRENT_BRANCH' updated: $OLD_HEAD → $NEW_HEAD"
echo "Next: git push --force origin $CURRENT_BRANCH"
