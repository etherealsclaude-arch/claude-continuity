# claude-continuity

A Claude Code skill that keeps long projects going across sessions: per-project Obsidian state notes, local transcript archive, a context-threshold checkpoint, and a one-time handoff to a fresh session with the same title. Local only, stdlib Python, no model calls.

Install: copy `continuity/` to `~/.claude/skills/`, then run `bash ~/.claude/skills/continuity/scripts/install.sh` (backs up `settings.json`; `uninstall.sh` reverses it). See `continuity/GUIDE.md`.

Limits: the automatic threshold needs the status line signal (terminal). In the Desktop app rollover is manual: type `checkpoint`.
