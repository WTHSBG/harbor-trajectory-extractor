"""Convert Kimi Code CLI sessions (``~/.kimi-code/sessions``) into ATIF.

Kimi Code records each session as::

    ~/.kimi-code/sessions/wd_<name>_<hash>/session_<uuid>/
        agents/main/wire.jsonl   # session message stream (authoritative)
        state.json               # session metadata (id, cwd, title, ...)

The wire file is a JSONL event log. This module groups ``step.begin`` /
``step.end`` loop events into ATIF agent steps and turns
``context.append_message`` / ``turn.prompt`` events into user/system steps.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harbor_trajectory_extractor.vendored import activate_vendor_namespace

activate_vendor_namespace()

from harbor.agents.installed.base import BaseInstalledAgent  # noqa: E402
from harbor.models.trajectories import (  # noqa: E402
    Agent,
    FinalMetrics,
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)
from harbor.utils.trajectory_utils import format_trajectory_json  # noqa: E402

AGENT_NAME = "kimi-code"
WIRE_FILENAME = "wire.jsonl"
STATE_FILENAME = "state.json"
TRAJECTORY_FILENAME = "trajectory.json"

# Message origins that Kimi Code records with role "user" but that are not
# typed by a human (injections, reminders, background task reports, ...).
_SYSTEM_ORIGINS = {
    "injection",
    "system_trigger",
    "skill_activation",
    "background_task",
    "cron_job",
    "task",
}


@dataclass
class _WireStep:
    """Accumulates loop events between a step.begin and its step.end."""

    time_ms: int | None = None
    text_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    usage: dict[str, Any] | None = None

    def has_content(self) -> bool:
        return bool(self.text_parts or self.reasoning_parts or self.tool_calls)


def _ms_to_iso(time_ms: Any) -> str | None:
    if not isinstance(time_ms, (int, float)):
        return None
    return (
        datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _content_parts_text(content: Any) -> str:
    """Flatten a message content payload into plain text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    return "".join(texts)


def _find_state_path(wire_path: Path) -> Path | None:
    session_dir = wire_path.parent.parent.parent
    if wire_path.parent.name == "main" and wire_path.parent.parent.name == "agents":
        candidate = session_dir / STATE_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _read_state(state_path: Path | None) -> dict[str, Any]:
    if state_path is None:
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def locate_wire_file(logs_dir: Path) -> Path | None:
    """Find the main-agent wire file inside a prepared work directory."""
    direct = logs_dir / "agents" / "main" / WIRE_FILENAME
    if direct.is_file():
        return direct
    candidates = sorted(logs_dir.rglob(WIRE_FILENAME))
    for candidate in candidates:
        if candidate.parent.name == "main" and candidate.parent.parent.name == "agents":
            return candidate
    return candidates[0] if candidates else None


def _session_id_from(wire_path: Path, state: dict[str, Any]) -> str | None:
    raw_id = state.get("id")
    if isinstance(raw_id, str) and raw_id:
        return raw_id.removeprefix("session_")
    for part in wire_path.parts:
        if part.startswith("session_"):
            return part.removeprefix("session_")
    return None


def _usage_to_metrics(usage: dict[str, Any]) -> tuple[Metrics, int, int, int]:
    input_other = usage.get("inputOther") or 0
    output = usage.get("output") or 0
    cache_read = usage.get("inputCacheRead") or 0
    cache_creation = usage.get("inputCacheCreation") or 0
    prompt = input_other + cache_read + cache_creation
    extra = {"input_cache_creation": cache_creation} if cache_creation else None
    metrics = Metrics(
        prompt_tokens=prompt,
        completion_tokens=output,
        cached_tokens=cache_read or None,
        extra=extra,
    )
    return metrics, prompt, output, cache_read


class _WireParser:
    """Single-pass parser turning wire events into ATIF steps."""

    def __init__(self) -> None:
        self.steps: list[Step] = []
        self.current: _WireStep | None = None
        self.step_by_call_id: dict[str, _WireStep] = {}
        self.seen_user_texts: set[str] = set()
        self.pending_prompt: dict[str, Any] | None = None
        self.model_name: str | None = None
        self.protocol_version: str | None = None
        self._total_prompt = 0
        self._total_completion = 0
        self._total_cached = 0

    # -- event dispatch -------------------------------------------------

    def feed(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "turn.prompt":
            self._flush_pending_prompt()
            self.pending_prompt = event
            return
        if etype == "context.append_message":
            # A typed prompt is logged twice in the wire: first as turn.prompt,
            # then as a context.append_message with the same text. Keep only
            # the append_message copy (it carries the message id and origin).
            message = event.get("message") or {}
            prompt_text = self._pending_prompt_text()
            if prompt_text is not None and _content_parts_text(
                message.get("content")
            ) == prompt_text:
                self.pending_prompt = None
            else:
                self._flush_pending_prompt()
            self._feed_message(message, event.get("time"))
            return
        self._flush_pending_prompt()
        if etype == "metadata":
            version = event.get("protocol_version")
            if isinstance(version, str):
                self.protocol_version = version
        elif etype == "context.append_loop_event":
            self._feed_loop_event(event.get("event") or {}, event.get("time"))
        elif etype in {"llm.request", "profile.bind", "usage.record"}:
            self._feed_model_hint(event)
        if etype == "usage.record":
            self._feed_usage_record(event)

    # -- individual event kinds -----------------------------------------

    def _feed_model_hint(self, event: dict[str, Any]) -> None:
        alias = event.get("modelAlias") or event.get("model")
        if isinstance(alias, str) and alias:
            self.model_name = alias

    def _feed_usage_record(self, event: dict[str, Any]) -> None:
        usage = event.get("usage")
        if (
            self.current is not None
            and self.current.usage is None
            and isinstance(usage, dict)
        ):
            self.current.usage = usage

    def _feed_message(self, message: dict[str, Any], time_ms: Any) -> None:
        if message.get("role") != "user":
            return
        text = _content_parts_text(message.get("content"))
        if not text:
            return
        self.seen_user_texts.add(text)
        origin = (message.get("origin") or {}).get("kind")
        source = "system" if origin in _SYSTEM_ORIGINS else "user"
        self.steps.append(
            Step(
                step_id=len(self.steps) + 1,
                timestamp=_ms_to_iso(time_ms),
                source=source,
                message=text,
                extra={
                    key: value
                    for key, value in {
                        "origin": origin,
                        "message_id": message.get("id"),
                    }.items()
                    if value
                }
                or None,
            )
        )

    def _pending_prompt_text(self) -> str | None:
        if self.pending_prompt is None:
            return None
        return _content_parts_text(self.pending_prompt.get("input")) or None

    def _flush_pending_prompt(self) -> None:
        # Emit a turn.prompt that never reached the context as its own step.
        prompt, self.pending_prompt = self.pending_prompt, None
        if prompt is None:
            return
        text = _content_parts_text(prompt.get("input"))
        if not text or text in self.seen_user_texts:
            return
        self.seen_user_texts.add(text)
        origin = (prompt.get("origin") or {}).get("kind")
        self.steps.append(
            Step(
                step_id=len(self.steps) + 1,
                timestamp=_ms_to_iso(prompt.get("time")),
                source="user" if origin in {None, "user"} else "system",
                message=text,
                extra={"origin": origin} if origin else None,
            )
        )

    def _feed_loop_event(self, event: dict[str, Any], time_ms: Any) -> None:
        etype = event.get("type")
        if etype == "step.begin":
            self._flush_current()
            self.current = _WireStep(time_ms=time_ms)
            return
        if self.current is None:
            return
        current = self.current
        if etype == "content.part":
            part = event.get("part") or {}
            if part.get("type") == "text" and part.get("text"):
                current.text_parts.append(part["text"])
            elif part.get("type") == "think" and part.get("think"):
                current.reasoning_parts.append(part["think"])
        elif etype == "tool.call":
            call_id = event.get("toolCallId")
            name = event.get("name")
            args = event.get("args")
            if not call_id or not name:
                return
            if not isinstance(args, dict):
                args = {"value": args} if args is not None else {}
            current.tool_calls.append(
                {"id": str(call_id), "name": str(name), "arguments": args}
            )
            self.step_by_call_id[str(call_id)] = current
        elif etype == "tool.result":
            call_id = event.get("toolCallId")
            result = event.get("result")
            if call_id is None or not isinstance(result, dict):
                return
            owner = self.step_by_call_id.get(str(call_id), current)
            owner.tool_results[str(call_id)] = result
        elif etype == "step.end":
            usage = event.get("usage")
            if isinstance(usage, dict):
                current.usage = usage
            self._flush_current()

    # -- step emission ----------------------------------------------------

    def _flush_current(self) -> None:
        current, self.current = self.current, None
        if current is None:
            return
        if not current.has_content():
            return

        message = "".join(current.text_parts) or "(tool use)"
        reasoning = "".join(current.reasoning_parts) or None

        tool_calls: list[ToolCall] | None = None
        observation: Observation | None = None
        if current.tool_calls:
            tool_calls = [
                ToolCall(
                    tool_call_id=call["id"],
                    function_name=call["name"],
                    arguments=call["arguments"],
                )
                for call in current.tool_calls
            ]
            results: list[ObservationResult] = []
            for call in current.tool_calls:
                result = current.tool_results.get(call["id"])
                if result is None:
                    continue
                output = result.get("output")
                if not isinstance(output, str):
                    output = json.dumps(output, ensure_ascii=False)
                extra = {
                    key: value
                    for key, value in {
                        "is_error": result.get("isError"),
                        "truncated": result.get("truncated"),
                        "note": result.get("note"),
                    }.items()
                    if value
                }
                results.append(
                    ObservationResult(
                        source_call_id=call["id"],
                        content=output,
                        extra=extra or None,
                    )
                )
            if results:
                observation = Observation(results=results)

        metrics: Metrics | None = None
        if current.usage:
            metrics, prompt, completion, cached = _usage_to_metrics(current.usage)
            self._total_prompt += prompt
            self._total_completion += completion
            self._total_cached += cached

        self.steps.append(
            Step(
                step_id=len(self.steps) + 1,
                timestamp=_ms_to_iso(current.time_ms),
                source="agent",
                message=message,
                reasoning_content=reasoning,
                tool_calls=tool_calls,
                observation=observation,
                metrics=metrics,
                llm_call_count=1,
            )
        )

    # -- finalization -----------------------------------------------------

    def finish(self) -> None:
        self._flush_pending_prompt()
        self._flush_current()

    def final_metrics(self) -> FinalMetrics:
        return FinalMetrics(
            total_prompt_tokens=self._total_prompt or None,
            total_completion_tokens=self._total_completion or None,
            total_cached_tokens=self._total_cached or None,
            total_steps=len(self.steps),
        )


def convert_session(
    wire_path: Path,
    *,
    state_path: Path | None = None,
    model_name: str | None = None,
    version: str | None = None,
) -> Trajectory | None:
    """Convert one Kimi Code wire.jsonl into an ATIF Trajectory."""
    wire_path = Path(wire_path)
    parser = _WireParser()
    with wire_path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                parser.feed(event)
    parser.finish()

    if not parser.steps:
        return None

    state = _read_state(state_path if state_path is not None else _find_state_path(wire_path))
    resolved_model = model_name or parser.model_name

    agent_extra = {
        key: value
        for key, value in {
            "cwd": state.get("cwd") or state.get("workDir"),
            "title": state.get("title"),
            "wire_protocol_version": parser.protocol_version,
        }.items()
        if value
    }

    return Trajectory(
        schema_version="ATIF-v1.7",
        session_id=_session_id_from(wire_path, state),
        agent=Agent(
            name=AGENT_NAME,
            version=version or "unknown",
            model_name=resolved_model,
            extra=agent_extra or None,
        ),
        steps=parser.steps,
        final_metrics=parser.final_metrics(),
    )


class KimiCode(BaseInstalledAgent):
    """Vendored-backend adapter exposing the Kimi Code converter."""

    SUPPORTS_ATIF: bool = True

    @staticmethod
    def name() -> str:
        return AGENT_NAME

    def populate_context_post_run(self, context: Any) -> None:
        wire_path = locate_wire_file(self.logs_dir)
        if wire_path is None:
            return
        trajectory = convert_session(
            wire_path,
            model_name=self.model_name,
            version=self.version(),
        )
        if trajectory is None:
            return

        trajectory_path = self.logs_dir / TRAJECTORY_FILENAME
        try:
            trajectory_path.write_text(format_trajectory_json(trajectory.to_json_dict()))
        except OSError as exc:
            self.logger.debug("Failed to write trajectory file %s: %s", trajectory_path, exc)
            return

        final_metrics = trajectory.final_metrics
        if final_metrics:
            context.cost_usd = final_metrics.total_cost_usd
            context.n_input_tokens = final_metrics.total_prompt_tokens or 0
            context.n_output_tokens = final_metrics.total_completion_tokens or 0
            context.n_cache_tokens = final_metrics.total_cached_tokens or 0
