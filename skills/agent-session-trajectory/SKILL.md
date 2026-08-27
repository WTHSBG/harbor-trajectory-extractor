---
name: agent-session-trajectory
description: Generate Harbor ATIF trajectories or training messages JSONL from supported agent session artifacts. Use for trajectory.json/ATIF export from Codex, Claude Code, Hermes, Kimi Code, or OpenCode, and for training-data export from Claude Code, Hermes, Kimi Code, or OpenCode.
---

# Agent Session Trajectory

Use this skill to produce a Harbor-standard ATIF trajectory from a supported
agent's native session/source artifact, or tool-aware training `messages` JSONL.
Current ATIF agents are:

- `codex`
- `claude-code` / `cc` / `claudecode`
- `hermes` / `hermers` / `hermes-agent`
- `kimi-code` / `kimi`
- `opencode`

Training export supports every agent above except `codex`.

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
for `codex`, `claude-code`, `hermes`, `kimi-code`, and limited `opencode` captures. For
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
agent-session-trajectory --agent hermes --session <sessionID> --summary
agent-session-trajectory --agent hermes --source ~/.hermes/state.db --session <sessionID> --summary
agent-session-trajectory --agent kimi-code --summary
agent-session-trajectory --agent kimi-code --source ~/.kimi-code/sessions/<wd_dir>/session_<uuid> --summary
agent-session-trajectory --agent opencode --session <sessionID> --summary
agent-session-trajectory --agent opencode --source ./opencode-export.json --summary
```

Use `--output-dir <dir>` to choose the directory. Use `--output <file>` to
choose the exact file path.

## Training JSONL

Use `htextract-training` for training samples:

```bash
htextract-training --agent claude-code --source ~/.claude/projects/<project>/<session>.jsonl --output claude-training.jsonl
htextract-training --agent hermes --source ~/.hermes/state.db --session <sessionID> --output hermes-training.jsonl
htextract-training --agent kimi-code --source ~/.kimi-code/sessions/<wd_dir>/session_<uuid> --output kimi-training.jsonl
htextract-training --agent opencode --source ./opencode-export.json --output opencode-training.jsonl
```

Verify both the JSONL and its sibling `.report.json`. Claude Code and Kimi Code
compact boundaries must remain separate samples. Claude `agent-acompact-*` and
Kimi `context.apply_compaction` outputs use `sample_type=context_compaction`;
never concatenate their pre-compact and post-compact contexts.

## Discoverability

List supported agents. This should print only `claude-code`, `codex`, `hermes`,
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
- `hermes`: can auto-detect `$HERMES_HOME/state.db` (normally
  `~/.hermes/state.db`). Use `--session <sessionID>` to select an exact or
  uniquely-prefixed session. You can also pass `state.db`, its `HERMES_HOME`
  directory, or a JSONL created by
  `hermes sessions export <file> --session-id <sessionID>`. Plaintext
  `reasoning`, `reasoning_content`,
  `reasoning_details`, and reasoning summaries are normalized to ATIF
  `reasoning_content`; encrypted-only provider state has no plaintext body.
- `kimi-code`: can usually auto-detect the newest session under
  `~/.kimi-code/sessions` (override the root with `KIMI_CODE_HOME`). ATIF export
  currently converts the main agent wire; training export also converts
  `agents/agent-*` subagents and compaction boundaries. Use `--session <sessionID>` to pick a specific session id,
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
htextract --describe-agent hermes
htextract --describe-agent kimi-code
htextract --describe-agent opencode
```

Important defaults:

- Codex writes session JSONL under `CODEX_HOME/sessions`; set `CODEX_HOME` for
  predictable collection.
- Claude Code writes session JSONL by default; set `CLAUDE_CONFIG_DIR` for a
  predictable collection directory.
- Hermes writes every session to `$HERMES_HOME/state.db` by default. Use
  `/reasoning high` or `agent.reasoning_effort: high` with a reasoning-capable
  model when you want plaintext thinking, then select the session with
  `--session` or export it with `hermes sessions export`.
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
