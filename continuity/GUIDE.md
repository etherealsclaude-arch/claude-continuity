# Continuity guide

Keeps long projects going across sessions. Everything runs locally and uses no model calls except the writing Claude does itself.

## What runs by itself
- The status line records how full the chat is (`context_window.used_percentage`). Your old status line still shows.
- Hooks save your prompts and Claude's replies to the project's Obsidian folder (secrets are blanked out).
- At the threshold (default 70%) Claude is told once to finish its current step, write a short handoff, and start a fresh session with the same title.
- A new session in that project loads the handoff automatically and marks it as taken. A repeat trigger cannot start a second successor.

## First use in a project
Claude runs `status`. If the project has no Obsidian destination, it suggests a vault and folder, asks you once, and remembers the answer. Different projects can use different vaults or different folders in one vault.

## Files (inside the project's Obsidian folder)
`current-state.md` (short current state), `handoffs/`, `transcripts/` (exact wording).
Settings and bindings: `~/.config/continuity/`. Runtime state: `~/.local/state/continuity/`.

## Commands (`C` = `python3 ~/.claude/skills/continuity/scripts/continuity.py`)
| Do | Command |
|---|---|
| Change threshold, this project | `C threshold 60` |
| Change threshold, everywhere | `C threshold 70 --scope global` |
| One-off override | `CONTINUITY_THRESHOLD=50 claude` |
| Save a checkpoint now | type `checkpoint` in the chat (no session id needed) |
| Search this project's notes | `C find "terms"` (`--transcripts` for exact wording) |
| Pause for a project / everywhere | `C disable` / `C disable --scope global` |
| Remove all hooks and restore the status line | `bash ~/.claude/skills/continuity/scripts/uninstall.sh` |
| Reinstall | `bash ~/.claude/skills/continuity/scripts/install.sh` |

Backup of the settings before install: `~/.claude/settings.json.continuity.bak`.

## Manual steps
- Terminal: Claude prints one line, `cd <project> && claude -n "<title>" "<prompt>"`. You run it.
- Desktop app: Claude starts the session itself (`start_session`). You open it from the sidebar.

## Desktop app limit
The Desktop app did not run the status line command in this session, so the automatic percentage signal is only confirmed for the terminal. Fallbacks: type `checkpoint` in the chat, or opt in to an estimate from the transcript's token counts: set `"window": <tokens>` in `~/.config/continuity/config.json` (use your real window size, for example 1000000). Without `window`, nothing fires automatically there.

Desktop verdict: hook payloads carry no context field and the status line does not run, so rollover is manual (one word, `checkpoint`). The terminal CLI is automatic.
