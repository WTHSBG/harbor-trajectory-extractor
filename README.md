# harbor-trajectory-extractor

Standalone CLI for extracting Harbor ATIF `trajectory.json` files from a Harbor
trial `agent/` log directory.

The converter code is vendored from Harbor's installed-agent adapters and runs
inside this project. It does not import the external `harbor` package, does not
shell out to the `harbor` CLI, and does not require Harbor to be installed.

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

## Notes

Generated trajectories may include explicit `reasoning_content` when the source
agent emitted it. Treat these files as sensitive artifacts.

## Vendored Source

The Harbor compatibility namespace under
`src/harbor_trajectory_extractor/vendor/harbor/` is derived from Harbor 0.13.2's
installed-agent trajectory conversion code plus a small local compatibility
layer. See `NOTICE` for attribution.
