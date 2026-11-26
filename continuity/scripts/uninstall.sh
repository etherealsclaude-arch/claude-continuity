#!/bin/bash
# Removes only continuity hooks and restores the original status line command.
set -e
S="$HOME/.claude/settings.json"; C="${CONTINUITY_CONF:-$HOME/.config/continuity}"
ORIG="$(cat "$C/statusline-original.txt" 2>/dev/null || true)"
jq --arg o "$ORIG" '
  .hooks |= with_entries(.value |= map(select(.hooks[0].command | contains("continuity.py") | not)))
  | .hooks |= with_entries(select(.value | length > 0))
  | if $o == "" then del(.statusLine) else .statusLine = {"type":"command","command":$o} end' "$S" > "$S.tmp" && mv "$S.tmp" "$S"
echo "removed hooks, restored status line. State kept in $C and ~/.local/state/continuity"
