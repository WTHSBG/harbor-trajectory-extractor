# harbor-trajectory-extractor

Standalone CLI for extracting Harbor ATIF `trajectory.json` files from a Harbor
trial `agent/` log directory.

The default backend uses Harbor's own installed agent adapters, so it covers the
same agent names exposed by Harbor's `AgentFactory`. If the current Python cannot
import `harbor`, the CLI automatically finds the `harbor` executable on `PATH`,
reads its shebang, and reruns the official converter inside Harbor's Python
environment.

## Install

```bash
pip install -e .
```

Or run without installing:

```bash
PYTHONPATH=src python -m harbor_trajectory_extractor --help
```

## Usage

Extract in place:

```bash
htextract \
  --agent claude-code \
  --agent-dir jobs/some-job/some-trial/agent \
  --summary
```

Write somewhere else:

```bash
htextract \
  --agent codex \
  --agent-dir /path/to/agent \
  --output /tmp/trajectory.json \
  --model gpt-5.1
```

List supported Harbor agent names:

```bash
htextract --list-agents
```

Show what files a converter expects:

```bash
htextract --describe-agent opencode
```

Pass adapter-specific kwargs through to Harbor:

```bash
htextract \
  --agent openhands \
  --agent-dir /path/to/agent \
  --kwargs-json '{"trajectory_config":{"raw_content":true}}'
```

## Backends

- `--backend auto` first calls Harbor's official adapter, then falls back to
  copying an existing ATIF `trajectory.json`.
- `--backend harbor` requires the official Harbor adapter to produce a trajectory.
- `--backend fallback` only reuses an existing ATIF trajectory file.

The official backend is the complete path for all Harbor-supported agents. The
fallback path exists for directories where an agent already emitted ATIF or
Harbor previously wrote `trajectory.json`.

## Input Files By Agent

Run `htextract --describe-agent <name>` for exact patterns. Common examples:

- `claude-code`: `sessions/projects/*/*.jsonl`, with `claude-code.txt` for final cost.
- `codex`: `sessions/**/*.jsonl`.
- `opencode`: `opencode.txt` from `opencode run --format=json`.
- `gemini-cli` / `antigravity-cli`: `*.trajectory.jsonl` or `*.trajectory.json`.
- `swe-agent` / `mini-swe-agent`: native trajectory JSON files.
- `openhands`: OpenHands `sessions/*/events/*.json` or completion JSON files.

## Notes

Generated trajectories may include explicit `reasoning_content` when the source
agent emitted it. Treat these files as sensitive artifacts.

