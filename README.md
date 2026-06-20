# harbor-trajectory-extractor

Standalone CLI for extracting Harbor ATIF `trajectory.json` files from a Harbor
trial `agent/` log directory.

The converter code is vendored from Harbor's installed-agent adapters and runs
inside this project. It does not import the external `harbor` package, does not
shell out to the `harbor` CLI, and does not require Harbor to be installed.

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

Or run from source without installing:

```bash
PYTHONPATH=src python -m harbor_trajectory_extractor --help
```

## Two Workflows

This tool supports two different moments in the agent lifecycle.

### 1. Agent Already Ran

First ask the tool what files it needs for that agent:

```bash
htextract --describe-agent claude-code
```

Then point it at the directory containing those captured files:

```bash
htextract \
  --agent claude-code \
  --agent-dir jobs/some-job/some-trial/agent \
  --summary
```

Write the trajectory somewhere else:

```bash
htextract \
  --agent codex \
  --agent-dir /path/to/agent \
  --output /tmp/trajectory.json \
  --model gpt-5.1
```

### 2. Agent Has Not Run Yet

Ask the tool for the capture recipe before running the agent:

```bash
htextract --describe-agent opencode
```

Run the agent with the printed runtime flags and log/session preservation steps.
After the run finishes, extract from the captured agent directory:

```bash
htextract \
  --agent opencode \
  --agent-dir /path/to/agent \
  --summary
```

For `claude-code`/`cc`, `opencode`, and `codex`, the run-time flags matter:
without the native session/log output, this extractor cannot reconstruct a full
trajectory after the fact.

## Other Commands

List supported Harbor agent names:

```bash
htextract --list-agents
```

Show both workflows for a specific agent:

```bash
htextract --describe-agent opencode
```

Pass adapter-specific kwargs through to the vendored Harbor adapter:

```bash
htextract \
  --agent openhands \
  --agent-dir /path/to/agent \
  --kwargs-json '{"trajectory_config":{"raw_content":true}}'
```

## Backends

- `--backend auto` first calls the vendored Harbor converter, then falls back to
  copying an existing ATIF `trajectory.json`.
- `--backend vendored` requires the vendored converter to produce a trajectory.
- `--backend fallback` only reuses an existing ATIF trajectory file.

The vendored backend contains Harbor's conversion implementations for agents that
have native-log-to-ATIF post-processing in Harbor. The fallback path exists for
agents that already emit ATIF directly, or for agents where Harbor itself only
collects metrics and does not create a trajectory.

## Input Files By Agent

Run `htextract --describe-agent <name>` for exact patterns. Common examples:

- `claude-code`: `sessions/projects/*/*.jsonl`, with `claude-code.txt` for final cost.
- `codex`: `sessions/**/*.jsonl`.
- `opencode`: `opencode.txt` from `opencode run --format=json`.
- `gemini-cli` / `antigravity-cli`: `*.trajectory.jsonl` or `*.trajectory.json`.
- `swe-agent` / `mini-swe-agent`: native trajectory JSON files.
- `openhands`: OpenHands `sessions/*/events/*.json` or completion JSON files.

## Capture Requirements

This tool extracts trajectories from files that the agent already wrote during
its run. It cannot recover a complete trajectory if the agent was run without
the native log/session output enabled or preserved.

### Claude Code

Required:

- Set `CLAUDE_CONFIG_DIR` to the agent log session directory before running
  Claude Code, usually `<agent-dir>/sessions`.
- Preserve session JSONL files under
  `<agent-dir>/sessions/projects/<project>/*.jsonl`. Harbor uses
  `projects/-app/*.jsonl` inside benchmark containers.
- Run with `--output-format=stream-json --print` and tee stdout/stderr to
  `<agent-dir>/claude-code.txt` if you want the final `total_cost_usd`.

Harbor's run shape is:

```bash
export CLAUDE_CONFIG_DIR=/logs/agent/sessions
mkdir -p "$CLAUDE_CONFIG_DIR/projects/-app"

claude \
  --verbose \
  --output-format=stream-json \
  --permission-mode=bypassPermissions \
  --print -- "$INSTRUCTION" \
  2>&1 </dev/null | tee /logs/agent/claude-code.txt
```

Reasoning is only present when Claude Code emits thinking blocks. To capture it,
request thinking explicitly, for example:

```bash
claude \
  --output-format=stream-json \
  --thinking enabled \
  --thinking-display summarized \
  --max-thinking-tokens 4096 \
  --print -- "$INSTRUCTION"
```

### OpenCode

Required:

- Run `opencode run` with `--format=json`.
- Tee stdout/stderr to `<agent-dir>/opencode.txt`.
- Include `--thinking` if you want reasoning blocks preserved in the stream.

Harbor's run shape is:

```bash
opencode --model="$MODEL" run \
  --format=json \
  --thinking \
  --dangerously-skip-permissions \
  -- "$INSTRUCTION" \
  2>&1 </dev/null | tee /logs/agent/opencode.txt
```

If your OpenCode stream omits the user prompt, pass `--instruction-path` to
`htextract` or place `instruction.txt` beside the agent directory.

### Codex

Required:

- Run `codex exec` with `--json`.
- Use a dedicated `CODEX_HOME` during the run.
- After Codex exits, copy `$CODEX_HOME/sessions` to `<agent-dir>/sessions`.
- Tee stdout/stderr to `<agent-dir>/codex.txt`.

Harbor's run shape is:

```bash
export CODEX_HOME=/tmp/codex-home

codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --skip-git-repo-check \
  --model "$MODEL" \
  --json \
  --enable unified_exec \
  -c model_reasoning_effort=high \
  -- "$INSTRUCTION" \
  2>&1 </dev/null | tee /logs/agent/codex.txt

mkdir -p /logs/agent
cp -R "$CODEX_HOME/sessions" /logs/agent/sessions
```

To affect reasoning summaries, add for example
`-c model_reasoning_summary=auto` or `-c model_reasoning_summary=detailed`.

## Notes

Generated trajectories may include explicit `reasoning_content` when the source
agent emitted it. Treat these files as sensitive artifacts.

## Vendored Source

The Harbor compatibility namespace under
`src/harbor_trajectory_extractor/vendor/harbor/` is derived from Harbor 0.13.2's
installed-agent trajectory conversion code plus a small local compatibility
layer. See `NOTICE` for attribution.
