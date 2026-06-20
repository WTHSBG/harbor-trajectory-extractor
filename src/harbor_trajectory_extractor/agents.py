from __future__ import annotations

from dataclasses import dataclass


SUPPORTED_AGENTS: tuple[str, ...] = (
    "acp",
    "aider",
    "antigravity-cli",
    "claude-code",
    "cline-cli",
    "codex",
    "copilot-cli",
    "cursor-cli",
    "devin",
    "gemini-cli",
    "goose",
    "hermes",
    "kimi-cli",
    "langgraph",
    "mini-swe-agent",
    "nemo-agent",
    "nop",
    "openclaw",
    "opencode",
    "openhands",
    "openhands-sdk",
    "oracle",
    "pi",
    "qwen-coder",
    "rovodev-cli",
    "swe-agent",
    "terminus",
    "terminus-1",
    "terminus-2",
    "trae-agent",
)

ALIASES: dict[str, str] = {
    "cc": "claude-code",
    "claude": "claude-code",
    "claude_code": "claude-code",
    "open-code": "opencode",
    "qwen-code": "qwen-coder",
    "qwen": "qwen-coder",
    "terminus": "terminus-2",
    "terminus-1": "terminus-2",
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
    "acp": AgentInput("acp", ("acp-summary.json", "acp-events.jsonl"), "ACP session updates captured by Harbor's ACP runner."),
    "aider": AgentInput("aider", ("aider.txt",), "Aider currently does not emit ATIF in Harbor; existing trajectory.json is reused if present."),
    "antigravity-cli": AgentInput("antigravity-cli", ("antigravity-cli.trajectory.jsonl", "antigravity-cli.trajectory.json"), "Gemini-compatible session export copied from the Antigravity CLI state directory."),
    "claude-code": AgentInput(
        "claude-code",
        ("Claude Code session .jsonl",),
        "Claude Code session JSONL is authoritative; claude-code.txt is optional and only supplies final cost when present.",
        (
            "Set CLAUDE_CONFIG_DIR to the agent log sessions directory, e.g. <agent-dir>/sessions, before running claude.",
            "Run claude with --verbose --output-format=stream-json --print and tee stdout/stderr to <agent-dir>/claude-code.txt if you want total_cost_usd.",
            "Ensure the session JSONL lands under <agent-dir>/sessions/projects/<project>/*.jsonl; Harbor uses projects/-app inside the benchmark container.",
            "For reasoning_content, request thinking explicitly, e.g. --thinking enabled --thinking-display summarized --max-thinking-tokens <n>; otherwise the trajectory may have no reasoning blocks.",
        ),
        optional_files=("claude-code.txt",),
        source_examples=(
            "htextract --agent claude-code --source ~/.claude/projects/<project>/<session>.jsonl --summary",
            "htextract --agent claude-code --source <CLAUDE_CONFIG_DIR> --summary",
        ),
    ),
    "cline-cli": AgentInput("cline-cli", ("trajectory.json",), "Cline CLI writes an ATIF trajectory during the run; this tool reuses it if present."),
    "codex": AgentInput(
        "codex",
        ("Codex session .jsonl or CODEX_HOME/sessions",),
        "Codex CLI session JSONL is authoritative; codex.txt is not used by the converter.",
        (
            "Run codex exec with --json so Codex writes machine-readable session events under CODEX_HOME/sessions.",
            "Use a dedicated CODEX_HOME during the run and preserve $CODEX_HOME/sessions after codex exits.",
            "Tee stdout/stderr to codex.txt only if you want a human-readable run log; this converter does not read codex.txt.",
            "For reasoning summaries, configure Codex with -c model_reasoning_summary=<auto|concise|detailed|none>; Harbor defaults model_reasoning_effort=high.",
        ),
        source_examples=(
            "htextract --agent codex --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl --summary",
            "htextract --agent codex --source <CODEX_HOME>/sessions --summary",
        ),
    ),
    "copilot-cli": AgentInput("copilot-cli", ("copilot-cli.jsonl", "copilot-cli.txt"), "Copilot CLI JSONL stream captured by Harbor."),
    "cursor-cli": AgentInput("cursor-cli", ("cursor-cli.txt",), "Cursor CLI JSON events captured on stdout."),
    "devin": AgentInput("devin", ("sessions.db",), "Devin CLI SQLite session database."),
    "gemini-cli": AgentInput("gemini-cli", ("gemini-cli.trajectory.jsonl", "gemini-cli.trajectory.json"), "Gemini CLI session export copied from ~/.gemini/tmp."),
    "goose": AgentInput("goose", ("goose.txt",), "Goose CLI log or stream-json output."),
    "hermes": AgentInput("hermes", ("hermes-session.jsonl", "hermes.txt"), "Hermes session export JSONL."),
    "kimi-cli": AgentInput("kimi-cli", ("kimi-cli.txt",), "Kimi CLI wire-format stdout."),
    "langgraph": AgentInput("langgraph", ("trajectory.json",), "LangGraph runners are expected to emit ATIF directly when configured."),
    "mini-swe-agent": AgentInput("mini-swe-agent", ("mini-swe-agent.trajectory.json",), "mini-swe-agent native trajectory JSON."),
    "nemo-agent": AgentInput("nemo-agent", ("trajectory.json", "nemo-agent-output.txt"), "NVIDIA NeMo agent wrapper writes ATIF directly."),
    "nop": AgentInput("nop", ("trajectory.json",), "No-op agent has no native trajectory; existing ATIF is reused if present."),
    "openclaw": AgentInput("openclaw", ("openclaw.txt", "openclaw.session.jsonl", "instruction.txt"), "OpenClaw JSON envelope plus optional session JSONL."),
    "opencode": AgentInput(
        "opencode",
        ("OpenCode JSON stdout from `opencode run --format=json`",),
        "opencode run --format=json stdout.",
        (
            "Run opencode with run --format=json and tee stdout/stderr to <agent-dir>/opencode.txt.",
            "Include --thinking if you want reasoning blocks in the JSON stream; Harbor always adds it.",
            "The converter reconstructs the user turn from the stream when present; if your stream omits it, pass --instruction-path or keep instruction.txt beside the agent directory.",
        ),
        source_examples=(
            "htextract --agent opencode --source ./opencode.txt --summary",
            "htextract --agent opencode --source ./opencode.jsonl --instruction-path ./instruction.txt --summary",
        ),
    ),
    "openhands": AgentInput("openhands", ("sessions/*/events/*.json", "sessions/*/completions/*.json", "openhands.trajectory.json"), "OpenHands event files or raw completion files."),
    "openhands-sdk": AgentInput("openhands-sdk", ("trajectory.json", "openhands_sdk.txt"), "OpenHands SDK runner writes ATIF directly."),
    "oracle": AgentInput("oracle", ("trajectory.json",), "Oracle agent normally has no post-run converter; existing ATIF is reused if present."),
    "pi": AgentInput("pi", ("pi.txt",), "Pi currently only extracts metrics from stdout; existing ATIF is reused if present."),
    "qwen-coder": AgentInput("qwen-coder", ("qwen-sessions/**/*.jsonl", "qwen-code.txt"), "Qwen Code session JSONL copied from ~/.qwen/tmp."),
    "rovodev-cli": AgentInput("rovodev-cli", ("rovodev_session_context.json", "rovodev-cli.txt"), "RovoDev session_context.json copied from ~/.rovodev/sessions."),
    "swe-agent": AgentInput("swe-agent", ("swe-agent-output/**/*.traj", "swe-agent.trajectory.json"), "SWE-agent native trajectory JSON/traj file."),
    "terminus-2": AgentInput("terminus-2", ("trajectory.json", "trajectory.cont-*.json", "recording.cast"), "Terminus records trajectory during the run; this tool reuses or normalizes it if present."),
    "trae-agent": AgentInput("trae-agent", ("trae-trajectory.json", "trae-agent.txt"), "Trae agent native trajectory JSON."),
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
        "Scenario 1: agent already ran",
        "  Pass the native artifact directly with --source:",
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
            "  If you already have a Harbor trial agent/ directory, keep using:",
            f"    htextract --agent {info.agent} --agent-dir <agent-dir> --summary",
            "  Optional output path works with both --source and --agent-dir:",
            f"    htextract --agent {info.agent} --source <native-log-or-dir> --output <trajectory.json>",
            "",
            "Scenario 2: agent has not run yet",
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
            "  After the run, point htextract at the native artifact with --source,",
            "  or at a Harbor-shaped agent/ directory with --agent-dir:",
            f"    htextract --agent {info.agent} --source <native-log-or-dir> --summary",
            "",
            f"notes: {info.notes}",
        ]
    )
    return "\n".join(lines)
