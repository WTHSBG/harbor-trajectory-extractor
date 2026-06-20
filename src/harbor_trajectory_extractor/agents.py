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
    "qwen-code": "qwen-coder",
    "qwen": "qwen-coder",
    "terminus": "terminus-2",
    "terminus-1": "terminus-2",
}


@dataclass(frozen=True)
class AgentInput:
    agent: str
    primary_files: tuple[str, ...]
    notes: str


AGENT_INPUTS: dict[str, AgentInput] = {
    "acp": AgentInput("acp", ("acp-summary.json", "acp-events.jsonl"), "ACP session updates captured by Harbor's ACP runner."),
    "aider": AgentInput("aider", ("aider.txt",), "Aider currently does not emit ATIF in Harbor; existing trajectory.json is reused if present."),
    "antigravity-cli": AgentInput("antigravity-cli", ("antigravity-cli.trajectory.jsonl", "antigravity-cli.trajectory.json"), "Gemini-compatible session export copied from the Antigravity CLI state directory."),
    "claude-code": AgentInput("claude-code", ("sessions/projects/*/*.jsonl", "claude-code.txt"), "Claude Code session JSONL is authoritative; claude-code.txt supplies final cost when present."),
    "cline-cli": AgentInput("cline-cli", ("trajectory.json",), "Cline CLI writes an ATIF trajectory during the run; this tool reuses it if present."),
    "codex": AgentInput("codex", ("sessions/**/*.jsonl", "codex.txt"), "Codex CLI session JSONL copied from CODEX_HOME/sessions."),
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
    "opencode": AgentInput("opencode", ("opencode.txt",), "opencode run --format=json stdout."),
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

