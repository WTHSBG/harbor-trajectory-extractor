from __future__ import annotations

from dataclasses import dataclass


SUPPORTED_AGENTS: tuple[str, ...] = (
    "claude-code",
    "codex",
    "opencode",
)

ALIASES: dict[str, str] = {
    "cc": "claude-code",
    "claude": "claude-code",
    "claude_code": "claude-code",
    "claudecode": "claude-code",
    "open-code": "opencode",
}


@dataclass(frozen=True)
class AgentInput:
    agent: str
    required_files: tuple[str, ...]
    notes: str
    run_requirements: tuple[str, ...] = ()
    optional_files: tuple[str, ...] = ()
    source_examples: tuple[str, ...] = ()


AGENT_INPUTS: dict[str, AgentInput] = {
    "claude-code": AgentInput(
        "claude-code",
        ("Claude Code session .jsonl",),
        "Claude Code session JSONL is authoritative; claude-code.txt is optional and only supplies final cost when present.",
        (
            "Claude Code records sessions by default under ~/.claude/projects/.../*.jsonl.",
            "For a predictable source path, set CLAUDE_CONFIG_DIR before running; pass that directory or its session .jsonl to --source.",
            "For reasoning_content, request thinking explicitly, e.g. --thinking enabled --thinking-display summarized --max-thinking-tokens <n>; otherwise the trajectory may have no reasoning blocks.",
            "For total_cost_usd, run with --output-format=stream-json --print and tee stdout/stderr to claude-code.txt next to the session source; the session JSONL is still the required artifact.",
        ),
        optional_files=("claude-code.txt",),
        source_examples=(
            "htextract --agent claude-code --source ~/.claude/projects/<project>/<session>.jsonl --summary",
            "htextract --agent claude-code --source <CLAUDE_CONFIG_DIR> --summary",
        ),
    ),
    "codex": AgentInput(
        "codex",
        ("Codex session .jsonl or CODEX_HOME/sessions",),
        "Codex CLI session JSONL is authoritative; codex.txt is not used by the converter.",
        (
            "Run codex exec with --json so Codex writes machine-readable session events under CODEX_HOME/sessions.",
            "Use a dedicated CODEX_HOME during the run and preserve $CODEX_HOME/sessions after codex exits.",
            "For reasoning summaries, configure Codex with -c model_reasoning_summary=<auto|concise|detailed|none>; Harbor defaults model_reasoning_effort=high.",
            "codex.txt is only a human-readable run log; this converter reads the session JSONL, not stdout.",
        ),
        source_examples=(
            "htextract --agent codex --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl --summary",
            "htextract --agent codex --source <CODEX_HOME>/sessions --summary",
        ),
    ),
    "opencode": AgentInput(
        "opencode",
        (
            "OpenCode export JSON from `opencode export <sessionID>`",
            "OpenCode JSON stdout from `opencode run --format=json`",
        ),
        (
            "OpenCode interactive sessions are saved locally. Export them with "
            "`opencode export <sessionID> > opencode-export.json`, then pass "
            "that JSON file as --source."
        ),
        (
            "If you are using the agent-session-trajectory skill wrapper, run `agent-session-trajectory --agent opencode --session <sessionID>` to export and convert in one step.",
            "Already ran interactively: list sessions with `opencode session list`, then run `opencode export <sessionID> > opencode-export.json`.",
            "Not run yet: you can either use OpenCode normally and export afterwards, or capture `opencode run --format=json --thinking` stdout directly.",
            "Reasoning is preserved when the OpenCode session/export contains `reasoning` parts; for run-mode JSONL, include --thinking.",
            "If a run-mode JSONL stream omits the user prompt, pass --instruction-path.",
        ),
        source_examples=(
            "opencode export <sessionID> > opencode-export.json && htextract --agent opencode --source ./opencode-export.json --summary",
            "htextract --agent opencode --source ./opencode.jsonl --instruction-path ./instruction.txt --summary",
        ),
    ),
}


def normalize_agent_name(agent: str) -> str:
    name = agent.strip().lower()
    return ALIASES.get(name, name)


def supported_agent_names() -> tuple[str, ...]:
    return tuple(sorted(SUPPORTED_AGENTS))


def describe_agent(agent: str) -> AgentInput | None:
    return AGENT_INPUTS.get(normalize_agent_name(agent))


def format_agent_workflow(agent: str) -> str | None:
    info = describe_agent(agent)
    if info is None:
        return None

    lines = [
        f"agent: {info.agent}",
        "",
        "If the agent already ran",
        "  Pass this run's native artifact directly with --source:",
    ]
    if info.source_examples:
        for example in info.source_examples:
            lines.append(f"    {example}")
    else:
        lines.append(f"    htextract --agent {info.agent} --source <native-log-or-dir> --summary")
    lines.append("  Native artifacts this converter needs:")
    for pattern in info.required_files:
        lines.append(f"    - {pattern}")
    if info.optional_files:
        lines.append("  Optional artifacts:")
        for pattern in info.optional_files:
            lines.append(f"    - {pattern}")
    lines.extend(
        [
            "  Optional output path:",
            f"    htextract --agent {info.agent} --source <native-log-or-dir> --output <trajectory.json>",
            "",
            "If the agent has not run yet",
        ]
    )

    if info.run_requirements:
        lines.append("  Run/capture requirements:")
        for requirement in info.run_requirements:
            lines.append(f"    - {requirement}")
    else:
        lines.append(
            "  This agent has no extra native-log capture recipe in this tool; "
            "it must already emit ATIF trajectory.json or use fallback."
        )
    lines.extend(
        [
            "  After the run, point htextract at the artifact from that run:",
            f"    htextract --agent {info.agent} --source <native-log-or-dir> --summary",
            "",
            f"notes: {info.notes}",
        ]
    )
    return "\n".join(lines)
