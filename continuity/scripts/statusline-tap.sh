#!/bin/bash
# Wraps the existing status line: records context % locally, then runs the original command unchanged.
D="$(cd "$(dirname "$0")" && pwd)"; IN="$(cat)"
printf '%s' "$IN" | python3 "$D/continuity.py" tap >/dev/null 2>&1
ORIG="$(cat "${CONTINUITY_CONF:-$HOME/.config/continuity}/statusline-original.txt" 2>/dev/null)"
[ -n "$ORIG" ] && printf '%s' "$IN" | bash -c "$ORIG"
