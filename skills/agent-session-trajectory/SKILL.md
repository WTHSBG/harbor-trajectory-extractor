---
name: agent-session-trajectory
description: Generate a Harbor ATIF trajectory file from an agent session/source artifact. Use when the user asks to export, create, extract, or generate trajectory.json/ATIF trajectory data for any htextract-supported agent session, including Codex, Claude Code/claudecode/cc, OpenCode, or an explicitly provided source path.
---

# Agent Session Trajectory

Use this skill to produce a Harbor-standard ATIF trajectory from an agent's
native session/source artifact.

## Quick Start

Prefer the bundled script:

```bash
agent-session-trajectory --agent codex --summary
```

If the wrapper is not on `PATH`, use the installed skill path:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/agent-session-trajectory/scripts/export_trajectory.py" --agent codex --summary
```

If `--source` is omitted, the script can auto-detect the newest local session
for `codex`, `claude-code`, and limited `opencode` captures. For any specific
session, or for other supported agents, pass `--source`.

The script writes this default filename to the current working directory:

```text
<agent>-<session>-trajectory.json
```

Examples:

```bash
agent-session-trajectory --agent codex --summary
agent-session-trajectory --agent codex --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl --summary
agent-session-trajectory --agent claude-code --summary
agent-session-trajectory --agent claude-code --source ~/.claude/projects/<project>/<session>.jsonl --summary
agent-session-trajectory --agent opencode --source ./opencode.jsonl --summary
agent-session-trajectory --agent gemini-cli --source ./gemini-trajectory.jsonl --summary
```

Use `--output-dir <dir>` to choose the directory. Use `--output <file>` to
choose the exact file path.

## Discoverability

List supported agents:

```bash
agent-session-trajectory --list-agents
```

Show what source artifact a specific agent needs:

```bash
agent-session-trajectory --describe-agent codex
```

## Source Notes

- `codex`: can usually auto-detect the newest session under
  `$CODEX_HOME/sessions` or `~/.codex/sessions`. Use `--source <session.jsonl>`
  when the intended session is not the newest.
- `claude-code`: can usually auto-detect the newest session under
  `$CLAUDE_CONFIG_DIR` or `~/.claude/projects`. Use `--source <session.jsonl>`
  for an exact session.
- `opencode`: normally requires `--source` pointing at captured
  `opencode run --format=json` stdout. If omitted, the script only checks the
  current directory for obvious `opencode.jsonl` or `opencode.txt` files.
- Other supported agents: pass the exact native source path shown by
  `--describe-agent <agent>`.

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

## Failure Handling

If generation fails, clearly tell the user:

- which agent was requested
- which source path was used or whether auto-detection failed
- whether they should pass `--source`, run `--describe-agent <agent>`, or
  capture a new session with the required agent flags

## Verification

After generation, report the output path and the summary counts:

- `agent`
- `session_id`
- `steps`
- `reasoning_steps`
- `tool_calls`

Treat generated trajectory files as sensitive because they may contain prompts,
tool outputs, commands, file paths, and reasoning summaries.
