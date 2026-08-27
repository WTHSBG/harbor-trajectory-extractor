from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from harbor_trajectory_extractor.agents import normalize_agent_name
from harbor_trajectory_extractor.atif import read_json
from harbor_trajectory_extractor.claude_code_prompts import MAIN_SYSTEM_PROMPT
from harbor_trajectory_extractor.hermes import (
    convert_session as convert_hermes_session,
    load_export as load_hermes_export,
    load_state_db as load_hermes_state_db,
    locate_source as locate_hermes_source,
)
from harbor_trajectory_extractor.kimi_code import convert_session as convert_kimi_session
from harbor_trajectory_extractor.sources import PreparedSource, prepare_source
from harbor_trajectory_extractor.training import (
    estimate_tokens,
    has_missing_tool_result_followed_by_assistant,
    has_only_terminal_missing_tool_results,
    missing_tool_result_turns,
    read_system_prompt,
    segment_is_complete,
)
from harbor_trajectory_extractor.vendored import extract_with_vendored_backend


SUPPORTED_TRAINING_AGENTS: tuple[str, ...] = (
    "claude-code",
    "hermes",
    "kimi-code",
    "opencode",
)

DEFAULT_SYSTEM_PROMPTS = {
    "claude-code": MAIN_SYSTEM_PROMPT,
    "hermes": "You are Hermes Agent, an AI coding agent.",
    "kimi-code": "You are Kimi Code CLI, an interactive general AI agent.",
    "opencode": "You are OpenCode, an AI coding agent.",
}


@dataclass(frozen=True)
class TrajectoryArtifact:
    trajectory: dict[str, Any]
    artifact_id: str
    sample_type: str = "main"
    system_prompt: str | None = None
    system_prompt_source: str = "fallback"
    parent_agent_id: str | None = None
    extra: dict[str, Any] | None = None


@dataclass
class AgentTrainingReport:
    source: str
    output: str
    agent: str
    artifacts_seen: int = 0
    samples_written: int = 0
    main_samples_written: int = 0
    subagent_samples_written: int = 0
    context_compaction_samples_written: int = 0
    samples_with_reasoning: int = 0
    samples_with_tool_calls: int = 0
    duplicate_samples_skipped: int = 0
    incomplete_samples_skipped: int = 0
    oversized_samples_skipped: int = 0
    terminal_tool_result_missing_samples_included: int = 0
    nonterminal_missing_tool_results_samples_included: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "output": self.output,
            "agent": self.agent,
            "artifacts_seen": self.artifacts_seen,
            "samples_written": self.samples_written,
            "sample_type_counts": {
                "main": self.main_samples_written,
                "subagent": self.subagent_samples_written,
                "context_compaction": self.context_compaction_samples_written,
            },
            "samples_with_reasoning": self.samples_with_reasoning,
            "samples_with_tool_calls": self.samples_with_tool_calls,
            "duplicate_samples_skipped": self.duplicate_samples_skipped,
            "incomplete_samples_skipped": self.incomplete_samples_skipped,
            "oversized_samples_skipped": self.oversized_samples_skipped,
            "terminal_tool_result_missing_samples_included": (
                self.terminal_tool_result_missing_samples_included
            ),
            "nonterminal_missing_tool_results_samples_included": (
                self.nonterminal_missing_tool_results_samples_included
            ),
            "warnings": self.warnings,
        }


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _read_kimi_profile_prompt(wire_path: Path) -> str | None:
    """Return the exact Kimi profile prompt recorded for one agent wire."""
    try:
        with wire_path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or event.get("type") != "profile.bind":
                    continue
                prompt = event.get("systemPrompt")
                if isinstance(prompt, str) and prompt.strip():
                    return prompt.strip()
    except OSError:
        return None
    return None


def _kimi_session_dir(source: Path) -> Path:
    source = source.resolve()
    if source.is_file():
        if source.name != "wire.jsonl":
            raise ValueError("Kimi Code training source file must be wire.jsonl")
        if source.parent.parent.name == "agents":
            return source.parents[2]
        return source.parent
    if (source / "agents" / "main" / "wire.jsonl").is_file():
        return source
    if (source / "main" / "wire.jsonl").is_file() and source.name == "agents":
        return source.parent
    if (source / "wire.jsonl").is_file() and source.parent.name == "agents":
        return source.parent.parent
    main_wires = sorted(source.glob("**/agents/main/wire.jsonl"))
    session_dirs = {path.parents[2] for path in main_wires}
    if len(session_dirs) == 1:
        return next(iter(session_dirs))
    if not session_dirs:
        raise ValueError("Kimi Code source contains no agents/main/wire.jsonl")
    raise ValueError(
        "Kimi Code source contains multiple sessions; pass one session_<uuid> directory"
    )


def _read_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
    return events


def _convert_kimi_events(
    events: list[dict[str, Any]],
    *,
    state_path: Path | None,
    model_name: str | None,
) -> dict[str, Any] | None:
    if not events:
        return None
    with tempfile.TemporaryDirectory(prefix="htextract-kimi-segment-") as tmp:
        wire_path = Path(tmp) / "wire.jsonl"
        wire_path.write_text(
            "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
            encoding="utf-8",
        )
        trajectory = convert_kimi_session(
            wire_path,
            state_path=state_path,
            model_name=model_name,
        )
        return trajectory.to_json_dict() if trajectory is not None else None


def _renumber_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    renumbered: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        copied = dict(step)
        copied["step_id"] = index
        renumbered.append(copied)
    return renumbered


def _kimi_compaction_metadata(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: event.get(key)
        for key in (
            "compactedCount",
            "tokensBefore",
            "tokensAfter",
            "summaryOutputTokens",
            "keptUserMessageCount",
            "time",
        )
        if event.get(key) is not None
    }


def _load_kimi_artifacts(source: Path, model_name: str | None) -> list[TrajectoryArtifact]:
    session_dir = _kimi_session_dir(source)
    state_path = session_dir / "state.json"
    state: dict[str, Any] = {}
    try:
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            state = loaded
    except (OSError, json.JSONDecodeError):
        pass
    agent_state = state.get("agents")
    agent_state = agent_state if isinstance(agent_state, dict) else {}

    wires = sorted(
        session_dir.glob("agents/*/wire.jsonl"),
        key=lambda path: (path.parent.name != "main", path.parent.name),
    )
    artifacts: list[TrajectoryArtifact] = []
    for wire_path in wires:
        agent_id = wire_path.parent.name
        metadata = agent_state.get(agent_id)
        metadata = metadata if isinstance(metadata, dict) else {}
        sample_type = "main" if agent_id == "main" else "subagent"
        prompt = _read_kimi_profile_prompt(wire_path)
        parent_agent_id = (
            str(metadata.get("parentAgentId"))
            if metadata.get("parentAgentId") is not None
            else None
        )
        events = _read_jsonl_dicts(wire_path)
        boundaries = [
            index
            for index, event in enumerate(events)
            if event.get("type") == "context.apply_compaction"
            and isinstance(event.get("summary"), str)
            and event.get("summary", "").strip()
        ]
        ranges: list[tuple[int, int, dict[str, Any] | None]] = []
        start = 0
        previous_boundary: dict[str, Any] | None = None
        for boundary_index in boundaries:
            ranges.append((start, boundary_index, previous_boundary))
            previous_boundary = events[boundary_index]
            start = boundary_index + 1
        ranges.append((start, len(events), previous_boundary))

        current_context_steps: list[dict[str, Any]] = []
        all_user_steps: list[dict[str, Any]] = []
        for segment_index, (segment_start, segment_end, prior_boundary) in enumerate(ranges):
            segment_trajectory = _convert_kimi_events(
                events[segment_start:segment_end],
                state_path=state_path if state_path.is_file() else None,
                model_name=model_name,
            )
            if segment_trajectory is None:
                segment_steps: list[dict[str, Any]] = []
                segment_trajectory = {
                    "schema_version": "ATIF-v1.7",
                    "session_id": str(state.get("id") or session_dir.name).removeprefix(
                        "session_"
                    ),
                    "agent": {"name": "kimi-code", "version": "unknown"},
                    "steps": segment_steps,
                }
            else:
                segment_steps = [
                    dict(step)
                    for step in segment_trajectory.get("steps") or []
                    if isinstance(step, dict)
                ]

            prefix_steps: list[dict[str, Any]] = []
            if prior_boundary is not None:
                kept_count = prior_boundary.get("keptUserMessageCount")
                kept_count = kept_count if isinstance(kept_count, int) and kept_count > 0 else 0
                if kept_count:
                    prefix_steps.extend(dict(step) for step in all_user_steps[-kept_count:])
                context_summary = prior_boundary.get("contextSummary")
                if isinstance(context_summary, str) and context_summary.strip():
                    prefix_steps.append(
                        {
                            "source": "user",
                            "message": f"[CONTEXT_SUMMARY]\n{context_summary.strip()}",
                        }
                    )
                current_context_steps = list(prefix_steps)

            segment_steps = _renumber_steps(prefix_steps + segment_steps)
            segment_trajectory["steps"] = segment_steps
            current_context_steps.extend(
                step for step in segment_steps[len(prefix_steps) :] if isinstance(step, dict)
            )
            all_user_steps.extend(
                dict(step)
                for step in segment_steps[len(prefix_steps) :]
                if step.get("source") == "user"
                and not str(step.get("message") or "").startswith("[CONTEXT_SUMMARY]")
            )
            if any(step.get("source") == "agent" for step in segment_steps):
                artifacts.append(
                    TrajectoryArtifact(
                        trajectory=segment_trajectory,
                        artifact_id=f"{agent_id}-segment-{segment_index + 1:03d}",
                        sample_type=sample_type,
                        system_prompt=prompt,
                        system_prompt_source="captured" if prompt else "fallback",
                        parent_agent_id=parent_agent_id,
                        extra={
                            "segment_index": segment_index + 1,
                            "post_compaction": prior_boundary is not None,
                        },
                    )
                )

            if segment_index >= len(boundaries):
                continue
            boundary = events[boundaries[segment_index]]
            summary = str(boundary.get("summary") or "").strip()
            if not summary:
                continue
            compaction_trajectory = dict(segment_trajectory)
            compaction_steps = [dict(step) for step in current_context_steps]
            compaction_steps.extend(
                [
                    {
                        "source": "user",
                        "message": (
                            "[CONTEXT_COMPACTION_REQUEST]\n"
                            "Summarize the conversation state needed to continue the task."
                        ),
                    },
                    {"source": "agent", "message": summary},
                ]
            )
            compaction_trajectory["steps"] = _renumber_steps(compaction_steps)
            artifacts.append(
                TrajectoryArtifact(
                    trajectory=compaction_trajectory,
                    artifact_id=f"{agent_id}-compaction-{segment_index + 1:03d}",
                    sample_type="context_compaction",
                    system_prompt=prompt,
                    system_prompt_source="captured" if prompt else "fallback",
                    parent_agent_id=agent_id,
                    extra={
                        "compaction_request_source": "canonical-fallback",
                        **_kimi_compaction_metadata(boundary),
                    },
                )
            )
    return artifacts


def _load_hermes_artifacts(
    source: Path, model_name: str | None, session_id: str | None
) -> list[TrajectoryArtifact]:
    source = source.resolve()
    if source.is_dir():
        located = locate_hermes_source(source)
        if located is None:
            raise ValueError("Hermes source contains no state.db or session export")
        kind, path = located
    elif source.suffix == ".db" or source.name == "state.db":
        kind, path = "state-db", source
    else:
        kind, path = "export", source
    session = (
        load_hermes_state_db(path, session_id=session_id)
        if kind == "state-db"
        else load_hermes_export(path, session_id=session_id)
    )
    sessions = [session]
    root_id = str(session.get("id") or session.get("session_id") or "")
    if kind == "state-db" and root_id:
        child_ids = _hermes_descendant_ids(path, root_id)
        sessions.extend(load_hermes_state_db(path, session_id=child_id) for child_id in child_ids)

    artifacts: list[TrajectoryArtifact] = []
    for index, item in enumerate(sessions):
        trajectory = convert_hermes_session(item, model_name=model_name)
        if trajectory is None:
            continue
        prompt = item.get("system_prompt")
        captured = prompt.strip() if isinstance(prompt, str) and prompt.strip() else None
        item_id = str(item.get("id") or item.get("session_id") or path.stem)
        parent_id = (
            str(item.get("parent_session_id"))
            if item.get("parent_session_id") is not None
            else None
        )
        artifacts.append(
            TrajectoryArtifact(
                trajectory=trajectory.to_json_dict(),
                artifact_id=item_id,
                sample_type="main" if index == 0 else "subagent",
                system_prompt=captured,
                system_prompt_source="captured" if captured else "fallback",
                parent_agent_id=parent_id,
            )
        )
    return artifacts


def _hermes_descendant_ids(path: Path, root_id: str) -> list[str]:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(sessions)")
        }
        if "parent_session_id" not in columns:
            return []
        order_by = "started_at, id" if "started_at" in columns else "id"
        rows = conn.execute(
            "SELECT id, parent_session_id FROM sessions "
            f"WHERE parent_session_id IS NOT NULL ORDER BY {order_by}"
        ).fetchall()
    finally:
        conn.close()
    children: dict[str, list[str]] = {}
    for child_id, parent_id in rows:
        children.setdefault(str(parent_id), []).append(str(child_id))
    descendants: list[str] = []
    queue = list(children.get(root_id, []))
    while queue:
        child_id = queue.pop(0)
        descendants.append(child_id)
        queue.extend(children.get(child_id, []))
    return descendants


def _isolated_prepared_source(agent: str, source: Path) -> PreparedSource:
    """Keep training export from writing trajectory.json into a source directory."""
    source = source.resolve()
    if source.is_file():
        return prepare_source(agent, source)

    cleanup = tempfile.TemporaryDirectory(prefix="htextract-training-")
    work_dir = Path(cleanup.name) / "work"
    work_dir.mkdir(parents=True)
    if agent == "claude-code" and (source / "sessions" / "projects").is_dir():
        (work_dir / "sessions").symlink_to(source / "sessions", target_is_directory=True)
        optional = source / "claude-code.txt"
        if optional.is_file():
            (work_dir / optional.name).symlink_to(optional)
        return PreparedSource(work_dir=work_dir, cleanup=cleanup)
    if agent == "opencode" and (source / "opencode.txt").is_file():
        (work_dir / "opencode.txt").symlink_to(source / "opencode.txt")
        return PreparedSource(work_dir=work_dir, cleanup=cleanup)
    cleanup.cleanup()
    return prepare_source(agent, source)


def _load_vendored_artifact(
    agent: str,
    source: Path,
    *,
    model_name: str | None,
    instruction_path: Path | None,
) -> list[TrajectoryArtifact]:
    prepared = _isolated_prepared_source(agent, source)
    output_dir = tempfile.TemporaryDirectory(prefix="htextract-training-atif-")
    try:
        output = Path(output_dir.name) / "trajectory.json"
        extract_with_vendored_backend(
            agent_name=agent,
            agent_dir=prepared.work_dir,
            output=output,
            model_name=model_name,
            kwargs={},
            instruction_path=instruction_path,
        )
        trajectory = read_json(output)
    finally:
        output_dir.cleanup()
        if prepared.cleanup is not None:
            prepared.cleanup.cleanup()
    session_id = trajectory.get("session_id")
    return [
        TrajectoryArtifact(
            trajectory=trajectory,
            artifact_id=str(session_id or source.stem),
        )
    ]


def load_agent_artifacts(
    *,
    agent: str,
    source: Path,
    model_name: str | None = None,
    session_id: str | None = None,
    instruction_path: Path | None = None,
) -> list[TrajectoryArtifact]:
    normalized = normalize_agent_name(agent)
    if normalized not in SUPPORTED_TRAINING_AGENTS:
        supported = ", ".join(SUPPORTED_TRAINING_AGENTS)
        raise ValueError(
            f"unsupported training agent: {agent}. Supported training agents: {supported}"
        )
    if normalized == "kimi-code":
        return _load_kimi_artifacts(source, model_name)
    if normalized == "hermes":
        return _load_hermes_artifacts(source, model_name, session_id)
    return _load_vendored_artifact(
        normalized,
        source,
        model_name=model_name,
        instruction_path=instruction_path,
    )


def _prompt_from_trajectory(trajectory: dict[str, Any]) -> str | None:
    for step in trajectory.get("steps") or []:
        if not isinstance(step, dict) or step.get("source") != "system":
            continue
        message = step.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


def _observation_by_call_id(step: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    observation = step.get("observation")
    observation = observation if isinstance(observation, dict) else {}
    results = observation.get("results")
    results = results if isinstance(results, list) else []
    bound: dict[str, dict[str, Any]] = {}
    unbound: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        call_id = result.get("source_call_id")
        if isinstance(call_id, str) and call_id:
            bound.setdefault(call_id, result)
        else:
            unbound.append(result)
    return bound, unbound


def trajectory_to_messages(
    trajectory: dict[str, Any],
    *,
    system_prompt: str,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt.strip()}
    ]
    prompt_consumed = False
    for step in trajectory.get("steps") or []:
        if not isinstance(step, dict):
            continue
        source = step.get("source")
        content = _stringify(step.get("message")).strip()
        if source == "system":
            if not prompt_consumed and content == system_prompt.strip():
                prompt_consumed = True
                continue
            if content:
                messages.append({"role": "user", "content": f"[SYSTEM_EVENT]\n{content}"})
            continue
        if source == "user":
            if content:
                messages.append({"role": "user", "content": content})
            continue
        if source != "agent":
            continue

        raw_calls = step.get("tool_calls")
        raw_calls = raw_calls if isinstance(raw_calls, list) else []
        calls: list[dict[str, Any]] = []
        for index, raw_call in enumerate(raw_calls):
            if not isinstance(raw_call, dict):
                continue
            call_id = raw_call.get("tool_call_id") or raw_call.get("id")
            call_id = str(call_id or f"tool-{step.get('step_id', 'unknown')}-{index}")
            calls.append(
                {
                    "id": call_id,
                    "name": str(
                        raw_call.get("function_name")
                        or raw_call.get("name")
                        or "unknown"
                    ),
                    "arguments": raw_call.get("arguments")
                    if isinstance(raw_call.get("arguments"), dict)
                    else {"value": raw_call.get("arguments")},
                }
            )

        if calls and content in {"(tool use)", "(reasoning)"}:
            content = ""
        assistant: dict[str, Any] = {"role": "assistant", "content": content}
        reasoning = step.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            assistant["reasoning_content"] = reasoning.strip()
        if calls:
            assistant["tool_calls"] = calls
        if content or assistant.get("reasoning_content") or calls:
            messages.append(assistant)

        bound_results, unbound_results = _observation_by_call_id(step)
        for call in calls:
            result = bound_results.get(call["id"])
            if result is None:
                continue
            extra = result.get("extra")
            extra = extra if isinstance(extra, dict) else {}
            prefix = "ERROR" if extra.get("is_error") else "OBSERVATION"
            tool_message: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": call["name"],
                "content": f"{prefix}:\n{_stringify(result.get('content'))}",
            }
            messages.append(tool_message)
        for result in unbound_results:
            text = _stringify(result.get("content")).strip()
            if text:
                messages.append(
                    {"role": "user", "content": f"[UNBOUND_TOOL_RESULT]\n{text}"}
                )

    while len(messages) > 1 and messages[-1].get("role") == "user":
        messages.pop()
    return messages


def _sample_id(agent: str, artifact: TrajectoryArtifact) -> str:
    session_id = artifact.trajectory.get("session_id") or "unknown-session"
    clean_session = str(session_id).replace("/", "_").replace(":", "_")
    clean_artifact = artifact.artifact_id.replace("/", "_").replace(":", "_")
    return f"{agent}-{clean_session}-{clean_artifact}-{artifact.sample_type}"


def _sample_digest(sample: dict[str, Any]) -> str:
    serialized = json.dumps(
        {"sample_type": sample["sample_type"], "messages": sample["messages"]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _write_jsonl(output: Path, samples: Iterable[dict[str, Any]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(
                json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + "\n"
            )


def export_agent_training_jsonl(
    *,
    agent: str,
    source: Path,
    output: Path,
    system_prompt: str | None = None,
    system_prompt_file: Path | None = None,
    main_system_prompt_file: Path | None = None,
    subagent_system_prompt_file: Path | None = None,
    model_name: str | None = None,
    session_id: str | None = None,
    instruction_path: Path | None = None,
    include_incomplete: bool = False,
    include_nonterminal_missing_tool_results: bool = False,
    max_estimated_tokens: int | None = None,
) -> AgentTrainingReport:
    normalized = normalize_agent_name(agent)
    source = source.resolve()
    output = output.resolve()
    common_override = system_prompt
    if system_prompt_file is not None:
        common_override = read_system_prompt(system_prompt_file)
    main_override = (
        read_system_prompt(main_system_prompt_file)
        if main_system_prompt_file is not None
        else None
    )
    subagent_override = (
        read_system_prompt(subagent_system_prompt_file)
        if subagent_system_prompt_file is not None
        else None
    )

    artifacts = load_agent_artifacts(
        agent=normalized,
        source=source,
        model_name=model_name,
        session_id=session_id,
        instruction_path=instruction_path,
    )
    report = AgentTrainingReport(
        source=str(source), output=str(output), agent=normalized, artifacts_seen=len(artifacts)
    )
    samples: list[dict[str, Any]] = []
    seen_digests: set[str] = set()

    for artifact in artifacts:
        override = subagent_override if artifact.sample_type == "subagent" else main_override
        captured_prompt = artifact.system_prompt or _prompt_from_trajectory(
            artifact.trajectory
        )
        prompt = (
            common_override
            or override
            or captured_prompt
            or DEFAULT_SYSTEM_PROMPTS[normalized]
        ).strip()
        prompt_source = (
            "override"
            if common_override or override
            else artifact.system_prompt_source
            if artifact.system_prompt
            else "captured"
            if captured_prompt
            else "fallback"
        )
        messages = trajectory_to_messages(artifact.trajectory, system_prompt=prompt)
        if not any(message.get("role") == "assistant" for message in messages):
            report.incomplete_samples_skipped += 1
            continue

        missing_results = missing_tool_result_turns(messages)
        terminal_missing = has_only_terminal_missing_tool_results(messages, missing_results)
        nonterminal_missing = has_missing_tool_result_followed_by_assistant(
            messages, missing_results
        )
        termination: dict[str, Any] | None = None
        if terminal_missing:
            report.terminal_tool_result_missing_samples_included += 1
            termination = {
                "reason": "missing_terminal_tool_result",
                "tool_names": [
                    str(call.get("name") or "")
                    for call in messages[-1].get("tool_calls", [])
                ],
            }
        elif nonterminal_missing:
            if not include_nonterminal_missing_tool_results:
                report.incomplete_samples_skipped += 1
                report.warnings.append(
                    f"skipped {artifact.artifact_id}: nonterminal tool result is missing"
                )
                continue
            report.nonterminal_missing_tool_results_samples_included += 1
            termination = {
                "reason": "nonterminal_missing_tool_results_included",
                "missing_turns": missing_results,
            }
        elif not segment_is_complete(messages) and not include_incomplete:
            report.incomplete_samples_skipped += 1
            continue

        estimated_tokens = estimate_tokens(messages)
        if max_estimated_tokens is not None and estimated_tokens > max_estimated_tokens:
            report.oversized_samples_skipped += 1
            continue

        agent_info = artifact.trajectory.get("agent")
        agent_info = agent_info if isinstance(agent_info, dict) else {}
        sample: dict[str, Any] = {
            "id": _sample_id(normalized, artifact),
            "sample_type": artifact.sample_type,
            "messages": messages,
            "metadata": {
                "source_agent": normalized,
                "source_session_id": artifact.trajectory.get("session_id"),
                "source_artifact_id": artifact.artifact_id,
                "parent_agent_id": artifact.parent_agent_id,
                "model_name": agent_info.get("model_name"),
                "system_prompt_source": prompt_source,
                "system_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "reasoning_available": any(
                    bool(message.get("reasoning_content")) for message in messages
                ),
                "estimated_tokens": estimated_tokens,
                "artifact": artifact.extra or {},
            },
        }
        if termination is not None:
            sample["termination"] = termination
        digest = _sample_digest(sample)
        if digest in seen_digests:
            report.duplicate_samples_skipped += 1
            continue
        seen_digests.add(digest)
        samples.append(sample)

    _write_jsonl(output, samples)
    report.samples_written = len(samples)
    report.main_samples_written = sum(s["sample_type"] == "main" for s in samples)
    report.subagent_samples_written = sum(
        s["sample_type"] == "subagent" for s in samples
    )
    report.context_compaction_samples_written = sum(
        s["sample_type"] == "context_compaction" for s in samples
    )
    report.samples_with_reasoning = sum(
        bool(s["metadata"]["reasoning_available"]) for s in samples
    )
    report.samples_with_tool_calls = sum(
        any(message.get("tool_calls") for message in s["messages"]) for s in samples
    )
    report_path = output.with_suffix(output.suffix + ".report.json")
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report
