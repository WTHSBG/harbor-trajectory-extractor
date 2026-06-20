# harbor-trajectory-extractor

Extract a completed agent session into Harbor's ATIF `trajectory.json` format.

Current supported agents are `claude-code`, `codex`, and `opencode`. The input
is that agent's own artifact from the run you just finished: a session JSONL
file, a sessions directory, or a JSON stdout capture. Harbor is only the output
schema here; you do not need to run the agent through Harbor.

The converter code is vendored from Harbor's installed-agent adapters and runs
inside this project. It does not shell out to `harbor` and does not require
Harbor to be installed.

## Clone And Install

```bash
git clone git@github.com:WTHSBG/harbor-trajectory-extractor.git
cd harbor-trajectory-extractor
scripts/install-skill.sh
```

This does three things:

- installs the `htextract` CLI into `./.venv`
- symlinks `skills/agent-session-trajectory` into
  `${CODEX_HOME:-~/.codex}/skills/agent-session-trajectory`
- writes wrappers to `~/.local/bin/htextract` and
  `~/.local/bin/agent-session-trajectory`

Use `--copy` if you want to copy the skill instead of symlinking it, `--force`
to replace an existing installed skill, or `--no-tool` if `htextract` is already
installed.

After installation, restart Codex or reload skills if your Codex surface needs
that. The skill name is `$agent-session-trajectory`, and the installed helper
command is:

```bash
agent-session-trajectory --help
```

## Manual CLI Install

If you only want the trajectory extraction tool:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/htextract --help
```

You can also activate the venv:

```bash
source .venv/bin/activate
htextract --help
```

If `python3 -m venv` fails because `ensurepip` is unavailable, use uv:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e .
```

## Project Layout

```text
.
├── scripts/install-skill.sh              # clone-to-Codex installer
├── skills/agent-session-trajectory/      # installable Codex skill
├── src/harbor_trajectory_extractor/      # standalone htextract CLI package
├── tests/                                # CLI and converter tests
├── pyproject.toml
└── requirements.txt
```

## Mental Model

There are only two questions.

1. The agent already ran: where is this run's native session artifact?

```bash
htextract --agent claude-code --source ~/.claude/projects/<project>/<session>.jsonl --summary
htextract --agent codex --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl --summary
htextract --agent opencode --source ./opencode-export.json --summary
```

For OpenCode interactive sessions, first export the saved session:

```bash
opencode session list
agent-session-trajectory --agent opencode --session <sessionID> --summary
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

This currently prints only:

```text
claude-code
codex
opencode
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
`skills/agent-session-trajectory/`. Install it with:

```bash
scripts/install-skill.sh
```

The installer symlinks the skill by default, so future git pulls update the
installed skill automatically. The skill helps another Codex session generate a
Harbor ATIF trajectory from an agent session/source artifact.

The skill's helper script supports only Codex, Claude Code, and OpenCode. It can
auto-select the newest local session for Codex, Claude Code, and limited
OpenCode captures. For any exact session, pass `--source`.

The default output filename is written in the current working directory:

```text
<agent>-<session>-trajectory.json
```

Examples:

```bash
agent-session-trajectory --agent codex --summary
agent-session-trajectory --agent codex --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl --summary
agent-session-trajectory --agent claude-code --summary
agent-session-trajectory --agent opencode --source ./opencode.jsonl --summary
```

Use `--output-dir <dir>` to keep the generated default filename in another
directory, or `--output <file>` to choose the exact path.

To discover what one of the supported agents needs:

```bash
agent-session-trajectory --list-agents
agent-session-trajectory --describe-agent opencode
```

When export is impossible, the script prints a `cannot export` message with the
agent, source, and next command to run.

For local development without installing the wrapper, run the bundled script
from the repo root:

```bash
python3 skills/agent-session-trajectory/scripts/export_trajectory.py --agent codex --summary
```

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

OpenCode interactive sessions are saved locally. For normal interactive use,
the `agent-session-trajectory` skill wrapper can export a saved OpenCode
session by id and convert it in one command:

```bash
opencode session list
agent-session-trajectory --agent opencode --session <sessionID> --summary
```

Under the hood, the wrapper runs `opencode export <sessionID>` and feeds the
export JSON into `htextract`. You can do the same manually:

```bash
opencode export <sessionID> > opencode-export.json
htextract --agent opencode --source ./opencode-export.json --summary
```

`opencode export` JSON contains `messages[].parts[]`, including plaintext
`reasoning` parts when the model/provider emitted them.

For non-interactive one-shot runs, you can still capture stdout directly:

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

If your run-mode JSONL stream omits the user prompt, pass the instruction file:

```bash
htextract \
  --agent opencode \
  --source ./opencode.jsonl \
  --instruction-path ./instruction.txt \
  --summary
```

You can inspect a saved interactive session without the helper by exporting it:

```bash
opencode export <sessionID> | jq '.messages[].parts[] | select(.type=="reasoning")'
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

Codex reasoning has an important limitation: this tool can only export plaintext
reasoning summaries that Codex writes into the session JSONL. In current testing
with `codex exec` and `model_reasoning_summary=auto`/`detailed`, Codex recorded
`reasoning_output_tokens` and a `reasoning` event, but the actual reasoning body
was stored as `encrypted_content` with an empty `summary`. Harbor's converter
does not decrypt that field, and this standalone extractor follows the same
behavior, so the generated trajectory will not contain `reasoning_content` for
those Codex runs.

## Other Agents

This tool currently supports only:

- `claude-code`
- `codex`
- `opencode`

Other Harbor installed-agent adapters may exist in the vendored source tree,
but they are not exposed or validated by this standalone extractor yet.

Generated trajectories may include explicit `reasoning_content` when the source
agent emitted plaintext reasoning. Verified behavior:

- Claude Code can export plaintext `reasoning_content` when run with thinking
  enabled, for example `--thinking enabled --thinking-display summarized`.
- OpenCode can export plaintext `reasoning_content` when stdout is captured with
  `opencode run --format=json --thinking`.
- Codex may record reasoning token counts while storing the reasoning body only
  as encrypted content; in that case `reasoning_content` is not available.

Treat trajectory files as sensitive artifacts.

## Vendored Source

The Harbor compatibility namespace under
`src/harbor_trajectory_extractor/vendor/harbor/` is derived from Harbor 0.13.2's
installed-agent trajectory conversion code plus a small local compatibility
layer. See `NOTICE` for attribution.
