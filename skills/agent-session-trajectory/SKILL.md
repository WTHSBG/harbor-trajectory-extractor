---
name: agent-session-trajectory
description: Generate a Harbor ATIF trajectory file from a supported agent session/source artifact. Use when the user asks to export, create, extract, or generate trajectory.json/ATIF trajectory data for Codex, Claude Code/claudecode/cc, Kimi Code/kimi, or OpenCode sessions.
---

# Agent Session Trajectory

Use this skill to produce a Harbor-standard ATIF trajectory from a supported
agent's native session/source artifact. Current supported agents are:

- `codex`
- `claude-code` / `cc` / `claudecode`
- `kimi-code` / `kimi`
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
for `codex`, `claude-code`, `kimi-code`, and limited `opencode` captures. For
any specific session, pass `--source`.

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
agent-session-trajectory --agent kimi-code --summary
agent-session-trajectory --agent kimi-code --source ~/.kimi-code/sessions/<wd_dir>/session_<uuid> --summary
agent-session-trajectory --agent opencode --session <sessionID> --summary
agent-session-trajectory --agent opencode --source ./opencode-export.json --summary
```

Use `--output-dir <dir>` to choose the directory. Use `--output <file>` to
choose the exact file path.

## Discoverability

List supported agents. This should print only `claude-code`, `codex`,
`kimi-code`, and `opencode`:

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
- `kimi-code`: can usually auto-detect the newest session under
  `~/.kimi-code/sessions` (override the root with `KIMI_CODE_HOME`). Only the
  main agent wire (`agents/main/wire.jsonl`) is converted; subagent wires are
  not exported yet. Use `--session <sessionID>` to pick a specific session id,
  or `--source` with a `session_<uuid>` directory or its
  `agents/main/wire.jsonl`.
- `opencode`: normal interactive sessions are saved locally by OpenCode. Export
  one automatically with `agent-session-trajectory --agent opencode --session
  <sessionID>`. The script runs `opencode export <sessionID>` internally and
  converts the exported JSON. You can also export manually with `opencode export
  <sessionID> > opencode-export.json` and pass that JSON file with `--source`.
  The script can also read `opencode run --format=json` JSONL captures such as
  `opencode.jsonl` or `opencode.txt`. If `--source` and `--session` are omitted,
  it only checks the current directory for obvious export/capture files.
- Other agents are not currently supported by this tool, even if Harbor has
  adapters for them.

## Capture Before Running

If the agent has not run yet, check capture requirements first:

```bash
htextract --describe-agent codex
htextract --describe-agent claude-code
htextract --describe-agent kimi-code
htextract --describe-agent opencode
```

Important defaults:

- Codex writes session JSONL under `CODEX_HOME/sessions`; set `CODEX_HOME` for
  predictable collection.
- Claude Code writes session JSONL by default; set `CLAUDE_CONFIG_DIR` for a
  predictable collection directory.
- Kimi Code writes `agents/main/wire.jsonl` and `state.json` under
  `~/.kimi-code/sessions/<wd_dir>/session_<uuid>/` by default; no extra flags
  are needed before a run.
- OpenCode interactive sessions can be exported after the fact with
  `opencode export <sessionID> > opencode-export.json`; use that route for
  normal interactive usage. `opencode run --format=json --thinking` remains a
  useful direct-capture option for one-shot runs.

OpenCode interactive export example:

```bash
opencode session list
agent-session-trajectory --agent opencode --session <sessionID> --summary
```

Manual OpenCode export example:

```bash
opencode export <sessionID> > opencode-export.json
agent-session-trajectory --agent opencode --source ./opencode-export.json --summary
```

OpenCode direct-capture example:

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
