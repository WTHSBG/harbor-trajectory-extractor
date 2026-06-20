---
name: current-session-trajectory
description: Generate a Harbor ATIF trajectory file for the current or most recent agent session. Use when the user asks to export, create, extract, or generate trajectory.json/ATIF trajectory data for Codex, Claude Code/claudecode/cc, or OpenCode sessions, especially the current session.
---

# Current Session Trajectory

Use this skill to produce a Harbor-standard ATIF trajectory from the current or
most recent session of `codex`, `claude-code`, or `opencode`.

## Quick Start

Prefer the bundled script:

```bash
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --agent codex --summary
```

The script writes the trajectory to the current working directory by default:

```text
<agent>-<session>-trajectory.json
```

Examples:

```bash
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --agent codex --summary
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --agent claude-code --summary
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --agent opencode --source ./opencode.jsonl --summary
```

Use `--output-dir <dir>` to choose the directory. Use `--output <file>` to
choose the exact file path.

## Agent Notes

- `codex`: can usually auto-detect the newest session under
  `$CODEX_HOME/sessions` or `~/.codex/sessions`. Use `--source <session.jsonl>`
  when the intended session is not the newest.
- `claude-code`: can usually auto-detect the newest session under
  `$CLAUDE_CONFIG_DIR` or `~/.claude/projects`. Use `--source <session.jsonl>`
  for an exact session.
- `opencode`: normally requires `--source` pointing at captured
  `opencode run --format=json` stdout. If omitted, the script only checks the
  current directory for obvious `opencode.jsonl` or `opencode.txt` files.

## Capture Before Running

If the agent has not run yet, check capture requirements first:

```bash
htextract --describe-agent codex
htextract --describe-agent claude-code
htextract --describe-agent opencode
```

Important defaults:

- Codex writes session JSONL under `CODEX_HOME/sessions`; set `CODEX_HOME` for
  predictable collection.
- Claude Code writes session JSONL by default; set `CLAUDE_CONFIG_DIR` for a
  predictable collection directory.
- OpenCode must be run with `run --format=json` and tee stdout to a file.

## Verification

After generation, report the output path and the summary counts:

- `agent`
- `session_id`
- `steps`
- `reasoning_steps`
- `tool_calls`

Treat generated trajectory files as sensitive because they may contain prompts,
tool outputs, commands, file paths, and reasoning summaries.
