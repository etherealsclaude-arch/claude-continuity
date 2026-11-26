#!/bin/bash
# Reversible. Backs up settings.json, adds tagged hooks, wraps (not replaces) the status line.
set -e
S="$HOME/.claude/settings.json"; D="$(cd "$(dirname "$0")" && pwd)"; C="${CONTINUITY_CONF:-$HOME/.config/continuity}"
mkdir -p "$C"; cp "$S" "$S.continuity.bak"
CUR="$(jq -r '.statusLine.command // empty' "$S")"
case "$CUR" in *statusline-tap.sh*) ;; *) printf '%s' "$CUR" > "$C/statusline-original.txt" ;; esac
H="python3 $D/continuity.py hook"
jq --arg h "$H" --arg tap "bash $D/statusline-tap.sh" '
  def add($ev; $arg): .hooks[$ev] = ((.hooks[$ev] // []) | map(select(.hooks[0].command | contains("continuity.py") | not))) + [{"hooks":[{"type":"command","command":($h+" "+$arg),"timeout":10}]}];
  add("SessionStart";"SessionStart") | add("UserPromptSubmit";"UserPromptSubmit") | add("PostToolUse";"PostToolUse") | add("Stop";"Stop")
  | .statusLine = {"type":"command","command":$tap}' "$S" > "$S.tmp" && mv "$S.tmp" "$S"
echo "installed. backup: $S.continuity.bak"
