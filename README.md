# harbor-trajectory-extractor

Extract a completed agent session into Harbor's ATIF `trajectory.json` format.

The input is the agent's own artifact from the run you just finished: a session
JSONL file, a sessions directory, a JSON stdout capture, or an agent-native
trajectory file. Harbor is only the output schema here; you do not need to run
the agent through Harbor.

The converter code is vendored from Harbor's installed-agent adapters and runs
inside this project. It does not shell out to `harbor` and does not require
Harbor to be installed.

## Install

```bash
python3 -m venv src/harbor_trajectory_extractor/.venv
source src/harbor_trajectory_extractor/.venv/bin/activate
python -m pip install -r requirements.txt
```

On machines where `python -m venv` / `ensurepip` is broken, create the venv with
uv instead:

```bash
uv venv --python 3.13 src/harbor_trajectory_extractor/.venv
uv pip install --python src/harbor_trajectory_extractor/.venv/bin/python -r requirements.txt
source src/harbor_trajectory_extractor/.venv/bin/activate
```

Run without activating:

```bash
src/harbor_trajectory_extractor/.venv/bin/htextract --help
```

## Mental Model

There are only two questions.

1. The agent already ran: where is this run's native session artifact?

```bash
htextract --agent claude-code --source ~/.claude/projects/<project>/<session>.jsonl --summary
htextract --agent codex --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl --summary
htextract --agent opencode --source ./opencode.jsonl --summary
```

2. The agent has not run yet: what must I enable before running it?

```bash
htextract --describe-agent opencode
```

Then run the agent with the printed flags, keep the produced artifact, and pass
that artifact back with `--source`.

By default the output is `trajectory.json` next to the source file, or inside the
source directory. Use `--output` to write somewhere else.

## Common Commands

List supported agent names:

```bash
htextract --list-agents
```

Show the source artifact and capture recipe for one agent:

```bash
htextract --describe-agent claude-code
```

Extract and print a compact summary:

```bash
htextract --agent claude-code --source <session.jsonl> --summary
```

Write to a specific file:

```bash
htextract --agent codex --source <session.jsonl> --output /tmp/trajectory.json
```

## Codex Skill

This repo includes a local Codex skill at
`skills/current-session-trajectory/`. It is not installed automatically; keep it
in this repo or copy it into a Codex skills directory when you want another
Codex session to generate a Harbor ATIF trajectory from an agent session/source
artifact.

The skill's helper script can auto-select the newest local session for Codex,
Claude Code, and limited OpenCode captures. For any exact session, or for any
other supported agent, pass `--source`.

The default output filename is written in the current working directory:

```text
<agent>-<session>-trajectory.json
```

Examples:

```bash
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --agent codex --summary
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --agent codex --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl --summary
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --agent claude-code --summary
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --agent opencode --source ./opencode.jsonl --summary
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --agent gemini-cli --source ./gemini-trajectory.jsonl --summary
```

Use `--output-dir <dir>` to keep the generated default filename in another
directory, or `--output <file>` to choose the exact path.

To discover what a non-default agent needs:

```bash
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --list-agents
python skills/current-session-trajectory/scripts/generate_current_trajectory.py --describe-agent gemini-cli
```

When export is impossible, the script prints a `cannot export` message with the
agent, source, and next command to run.

## Claude Code

Already ran:

```bash
htextract \
  --agent claude-code \
  --source ~/.claude/projects/<project>/<session>.jsonl \
  --summary
```

You can also pass `CLAUDE_CONFIG_DIR` if it contains exactly one session:

```bash
htextract --agent claude-code --source <CLAUDE_CONFIG_DIR> --summary
```

Claude Code records session JSONL by default. If you want an easy-to-find source
directory for future runs, set `CLAUDE_CONFIG_DIR` before starting Claude Code:

```bash
export CLAUDE_CONFIG_DIR="$PWD/.claude-session"

claude --print -- "$INSTRUCTION"

htextract --agent claude-code --source "$CLAUDE_CONFIG_DIR" --summary
```

Reasoning only appears when Claude Code emits thinking blocks. For runs where
you need `reasoning_content`, request thinking explicitly:

```bash
claude \
  --output-format=stream-json \
  --thinking enabled \
  --thinking-display summarized \
  --max-thinking-tokens 4096 \
  --print -- "$INSTRUCTION"
```

`claude-code.txt` is optional. It is not created by Claude Code as a session log;
it is just stdout captured from `--output-format=stream-json --print`, and this
tool only uses it to fill `total_cost_usd` when present.

## OpenCode

OpenCode needs a capture flag. If you did not save `opencode run --format=json`
stdout, this tool cannot reconstruct a full trajectory after the fact.

Run future sessions like this:

```bash
opencode --model="$MODEL" run \
  --format=json \
  --thinking \
  --dangerously-skip-permissions \
  -- "$INSTRUCTION" \
  2>&1 | tee opencode.jsonl
```

Then extract:

```bash
htextract --agent opencode --source ./opencode.jsonl --summary
```

If your OpenCode stream omits the user prompt, pass the instruction file:

```bash
htextract \
  --agent opencode \
  --source ./opencode.jsonl \
  --instruction-path ./instruction.txt \
  --summary
```

## Codex

Already ran:

```bash
htextract \
  --agent codex \
  --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl \
  --summary
```

You can also pass a session directory or `CODEX_HOME/sessions` if it contains one
unambiguous session:

```bash
htextract --agent codex --source <CODEX_HOME>/sessions --summary
```

For future runs, use a dedicated `CODEX_HOME` so the session is easy to locate:

```bash
export CODEX_HOME="$PWD/.codex-session"

codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --skip-git-repo-check \
  --model "$MODEL" \
  --json \
  -c model_reasoning_effort=high \
  -c model_reasoning_summary=auto \
  -- "$INSTRUCTION"

htextract --agent codex --source "$CODEX_HOME/sessions" --summary
```

The converter reads Codex session JSONL files. Captured stdout such as
`codex.txt` can be useful for humans, but it is not the trajectory source.

## Other Agents

Run `htextract --describe-agent <name>` for the exact native source to keep.
Common examples:

- `gemini-cli` / `antigravity-cli`: Gemini trajectory JSONL or JSON export.
- `swe-agent` / `mini-swe-agent`: native trajectory JSON files.
- `openhands`: OpenHands session event files or completion JSON files.
- Agents that already emit ATIF: pass their `trajectory.json` as `--source`.

Generated trajectories may include explicit `reasoning_content` when the source
agent emitted it. Treat these files as sensitive artifacts.

## Vendored Source

The Harbor compatibility namespace under
`src/harbor_trajectory_extractor/vendor/harbor/` is derived from Harbor 0.13.2's
installed-agent trajectory conversion code plus a small local compatibility
layer. See `NOTICE` for attribution.
