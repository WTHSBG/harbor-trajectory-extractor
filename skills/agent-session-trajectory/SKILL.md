---
name: agent-session-trajectory
description: Generate a Harbor ATIF trajectory file from a supported agent session/source artifact. Use when the user asks to export, create, extract, or generate trajectory.json/ATIF trajectory data for Codex, Claude Code/claudecode/cc, or OpenCode sessions.
---

# Agent Session Trajectory

Use this skill to produce a Harbor-standard ATIF trajectory from a supported
agent's native session/source artifact. Current supported agents are:

- `codex`
- `claude-code` / `cc` / `claudecode`
- `opencode`

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
session, pass `--source`.

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
```

Use `--output-dir <dir>` to choose the directory. Use `--output <file>` to
choose the exact file path.

## Discoverability

List supported agents. This should print only `claude-code`, `codex`, and
`opencode`:

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
- `opencode`: cannot be fully exported after a normal run unless the run's JSON
  stdout was captured at run time. Require `--source` pointing at saved
  `opencode run --format=json` output such as `opencode.jsonl` or
  `opencode.txt`. If `--source` is omitted, the script only checks the current
  directory for those obvious capture files; it does not recover default
  OpenCode history.
- Other agents are not currently supported by this tool, even if Harbor has
  adapters for them.

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
- OpenCode must be run with `run --format=json` and tee stdout to a file before
  extraction is possible. If the user already ran OpenCode without saving that
  JSON stream, say the trajectory cannot be fully reconstructed and tell them
  how to capture the next run.

OpenCode capture example:

```bash
opencode run --format=json --thinking -- "$INSTRUCTION" 2>&1 | tee opencode.jsonl
agent-session-trajectory --agent opencode --source ./opencode.jsonl --summary
```

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
