from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .claude_code_prompts import (
    EXPLORE_SYSTEM_PROMPT,
    MAIN_SYSTEM_PROMPT,
    UNKNOWN_SUBAGENT_SYSTEM_PROMPT,
)


SUCCESS_STATUSES = {"success"}
HANXUEMING_VUL_NON_CRASH_CODES = {0, 71, 300}
HANXUEMING_CORRECT = "correct"
HANXUEMING_VUL_CRASHED_FIX_FAILED = "vul_crashed_fix_failed"
HANXUEMING_VUL_NOT_CRASHED_FIX_FAILED = "vul_not_crashed_fix_failed"
HANXUEMING_VUL_NOT_CRASHED = "vul_not_crashed"
HANXUEMING_MISSING_EXIT_CODE = "missing_exit_code"
HANXUEMING_PROBLEM_PRIORITY = (
    HANXUEMING_VUL_CRASHED_FIX_FAILED,
    HANXUEMING_VUL_NOT_CRASHED_FIX_FAILED,
    HANXUEMING_VUL_NOT_CRASHED,
    HANXUEMING_MISSING_EXIT_CODE,
)
HANXUEMING_VUL_EXIT_CODE_RE = re.compile(
    r'''["']vul_exit_code["']\s*:\s*(-?\d+)'''
)
HANXUEMING_FIX_EXIT_CODE_RE = re.compile(
    r'''["']fix_exit_code["']\s*:\s*(-?\d+)'''
)
LAYOUT_AUTO = "auto"
LAYOUT_BAIYANSONG = "baiyansong"
LAYOUT_HANXUEMING = "hanxueming"
LAYOUT_RUJIA = "rujia"
SUPPORTED_LAYOUTS = {LAYOUT_AUTO, LAYOUT_BAIYANSONG, LAYOUT_HANXUEMING, LAYOUT_RUJIA}
COMPACT_SUBTYPE = "compact_boundary"
COMPACT_AGENT_PREFIX = "agent-acompact-"
SESSION_START_RE = re.compile(
    r"Hook SessionStart:(startup|compact) \(SessionStart\) success:\n(.*)",
    re.DOTALL,
)


@dataclass(frozen=True)
class NativeEvent:
    ordinal: int
    raw: dict[str, Any]

    @property
    def uuid(self) -> str | None:
        value = self.raw.get("uuid")
        return value if isinstance(value, str) and value else None

    @property
    def parent_uuid(self) -> str | None:
        for key in ("parentUuid", "logicalParentUuid"):
            value = self.raw.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @property
    def timestamp(self) -> str:
        value = self.raw.get("timestamp")
        return value if isinstance(value, str) else ""


@dataclass
class ToolCallRecord:
    call_id: str
    name: str
    arguments: dict[str, Any]
    output: str | None = None
    is_error: bool = False


@dataclass
class AssistantTurn:
    message_id: str
    first_ordinal: int
    reasoning_parts: list[str] = field(default_factory=list)
    content_parts: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeState:
    kind: str
    timestamp: str
    content: str


@dataclass(frozen=True)
class SessionArtifact:
    task_id: str
    task_dir: Path
    session_path: Path
    session_id: str
    role: str
    debug_path: Path | None = None
    parent_session_id: str | None = None
    parent_agent_id: str | None = None
    agent_type: str | None = None


@dataclass
class ExportReport:
    source: str
    output: str
    layout: str
    success_only: bool = False
    main_system_prompt_sha256: str = ""
    subagent_system_prompt_sha256: str = ""
    runtime_state_included: bool = False
    tasks_seen: int = 0
    tasks_eligible: int = 0
    tasks_with_samples: int = 0
    tasks_skipped: int = 0
    tasks_without_sessions: int = 0
    sessions_seen: int = 0
    compact_agents_included: int = 0
    valid_compact_agents: int = 0
    invalid_compact_agents_skipped: int = 0
    terminal_tool_result_missing_samples_included: int = 0
    nonterminal_missing_tool_results_samples_included: int = 0
    samples_written: int = 0
    main_samples_written: int = 0
    subagent_samples_written: int = 0
    context_compaction_samples_written: int = 0
    duplicate_samples_skipped: int = 0
    incomplete_segments_skipped: int = 0
    oversized_segments_skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "output": self.output,
            "layout": self.layout,
            "success_only": self.success_only,
            "main_system_prompt_sha256": self.main_system_prompt_sha256,
            "subagent_system_prompt_sha256": self.subagent_system_prompt_sha256,
            "runtime_state_included": self.runtime_state_included,
            "tasks_seen": self.tasks_seen,
            "tasks_eligible": self.tasks_eligible,
            "successful_tasks_selected": (
                self.tasks_eligible if self.success_only else None
            ),
            "tasks_with_samples": self.tasks_with_samples,
            "tasks_skipped": self.tasks_skipped,
            "tasks_without_sessions": self.tasks_without_sessions,
            "sessions_seen": self.sessions_seen,
            "compact_agents_included": self.compact_agents_included,
            "valid_compact_agents": self.valid_compact_agents,
            "invalid_compact_agents_skipped": self.invalid_compact_agents_skipped,
            "terminal_tool_result_missing_samples_included": (
                self.terminal_tool_result_missing_samples_included
            ),
            "nonterminal_missing_tool_results_samples_included": (
                self.nonterminal_missing_tool_results_samples_included
            ),
            "samples_written": self.samples_written,
            "sample_type_counts": {
                "main": self.main_samples_written,
                "subagent": self.subagent_samples_written,
                "context_compaction": self.context_compaction_samples_written,
            },
            "duplicate_samples_skipped": self.duplicate_samples_skipped,
            "incomplete_segments_skipped": self.incomplete_segments_skipped,
            "oversized_segments_skipped": self.oversized_segments_skipped,
            "warnings": self.warnings,
        }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_system_prompt(path: Path) -> str:
    """Read a plaintext prompt or the first system message in a JSON sample."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read system prompt file {path}: {exc}") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        prompt = text.strip()
        if not prompt:
            raise ValueError(f"system prompt file is empty: {path}")
        return prompt
    if isinstance(value, dict):
        messages = value.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict) or message.get("role") != "system":
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
    raise ValueError(
        f"JSON system prompt file has no non-empty system message: {path}"
    )


def resolve_system_prompts(
    *,
    system_prompt: str | None,
    main_system_prompt: str | None,
    subagent_system_prompt: str | None,
    main_system_prompt_file: Path | None,
    subagent_system_prompt_file: Path | None,
) -> tuple[str, str]:
    """Resolve explicit overrides before the captured Claude Code prompts."""
    if system_prompt is not None:
        common = system_prompt.strip()
        if not common:
            raise ValueError("system_prompt must not be empty")
        return common, common
    main = (
        main_system_prompt.strip()
        if main_system_prompt is not None
        else read_system_prompt(main_system_prompt_file)
        if main_system_prompt_file is not None
        else MAIN_SYSTEM_PROMPT
    )
    subagent = (
        subagent_system_prompt.strip()
        if subagent_system_prompt is not None
        else read_system_prompt(subagent_system_prompt_file)
        if subagent_system_prompt_file is not None
        else EXPLORE_SYSTEM_PROMPT
    )
    if not main or not subagent:
        raise ValueError("main and subagent system prompts must not be empty")
    return main, subagent


def read_jsonl_events(path: Path) -> list[NativeEvent]:
    events: list[NativeEvent] = []
    with path.open(encoding="utf-8") as handle:
        for ordinal, line in enumerate(handle, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(NativeEvent(ordinal=ordinal, raw=value))
    return events


def _baiyansong_session_roots(task_dir: Path) -> list[Path]:
    return sorted(task_dir.glob("logs/*/cc_session/.claude/projects/-workspace"))


def _hanxueming_session_roots(task_dir: Path) -> list[Path]:
    candidate = task_dir / "logs" / "projects" / "-workspace"
    return [candidate] if candidate.is_dir() else []


def _rujia_session_roots(task_dir: Path) -> list[Path]:
    """Locate Claude Code project logs in the rujia task artifact layout."""
    candidate = task_dir / "logs" / "projects" / "-workspace"
    return [candidate] if candidate.is_dir() else []


def session_roots_for_task(task_dir: Path, layout: str) -> list[Path]:
    roots: list[Path] = []
    if layout in {LAYOUT_AUTO, LAYOUT_BAIYANSONG}:
        roots.extend(_baiyansong_session_roots(task_dir))
    if layout in {LAYOUT_AUTO, LAYOUT_HANXUEMING}:
        roots.extend(_hanxueming_session_roots(task_dir))
    if layout in {LAYOUT_AUTO, LAYOUT_RUJIA}:
        roots.extend(_rujia_session_roots(task_dir))
    return sorted(set(roots))


def detect_layout(source: Path) -> str:
    source = source.resolve()
    if (source / "tasks").is_dir() or _baiyansong_session_roots(source):
        return LAYOUT_BAIYANSONG
    if _hanxueming_session_roots(source) or any(
        source.glob("node*/worker*/logs/arvo_*/logs/projects/-workspace/*.jsonl")
    ):
        return LAYOUT_HANXUEMING
    if _rujia_session_roots(source) or any(
        source.glob("worker_*/user/*/logs/projects/-workspace/*.jsonl")
    ) or any(source.glob("worker_*/v8/*/logs/projects/-workspace/*.jsonl")):
        return LAYOUT_RUJIA
    raise ValueError(
        "could not detect layout: expected baiyansong tasks/.../cc_session/.claude/"
        "projects/-workspace, hanxueming node*/worker*/logs/arvo_*/logs/"
        "projects/-workspace, or rujia worker_*/{user,v8}/*/logs/projects/-workspace"
    )


def discover_task_dirs(source: Path, *, layout: str = LAYOUT_AUTO) -> list[Path]:
    source = source.resolve()
    if layout not in SUPPORTED_LAYOUTS:
        raise ValueError(f"unsupported layout: {layout}")
    resolved_layout = detect_layout(source) if layout == LAYOUT_AUTO else layout

    if session_roots_for_task(source, resolved_layout):
        return [source]

    if resolved_layout == LAYOUT_BAIYANSONG:
        tasks_dir = source / "tasks"
        if not tasks_dir.is_dir():
            raise ValueError("baiyansong source must contain tasks/ or be one task directory")
        return sorted(path for path in tasks_dir.iterdir() if path.is_dir())

    if resolved_layout == LAYOUT_RUJIA:
        task_dirs: set[Path] = set()
        for worker in source.glob("worker_*"):
            if not worker.is_dir():
                continue
            for category in ("user", "v8"):
                category_dir = worker / category
                if category_dir.is_dir():
                    task_dirs.update(path for path in category_dir.iterdir() if path.is_dir())
        if not task_dirs:
            raise ValueError(
                "rujia source must contain worker_*/user/* or worker_*/v8/* task directories"
            )
        return sorted(task_dirs)

    task_dirs = {
        path
        for path in source.glob("node*/worker*/logs/arvo_*")
        if path.is_dir()
    }
    if not task_dirs:
        raise ValueError(
            "hanxueming source must contain node*/worker*/logs/arvo_*/logs/"
            "projects/-workspace sessions or be one task directory"
        )
    return sorted(task_dirs)


def task_identifier(task_dir: Path) -> str:
    status = _read_json(task_dir / "final_status.json") or {}
    value = status.get("task_id")
    if isinstance(value, str) and value:
        return value
    match = re.match(r"^(arvo)[_:](\d+)", task_dir.name)
    if match:
        return f"{match.group(1)}:{match.group(2)}"
    return task_dir.name


def _classify_hanxueming_result(
    vul_exit_code: int | None, fix_exit_code: int | None
) -> str:
    """Mirror print_result.py's classification for one submitted result."""
    if vul_exit_code is None:
        return HANXUEMING_MISSING_EXIT_CODE
    vul_crashed = vul_exit_code not in HANXUEMING_VUL_NON_CRASH_CODES
    if not vul_crashed:
        if fix_exit_code is None or fix_exit_code == 0:
            return HANXUEMING_VUL_NOT_CRASHED
        return HANXUEMING_VUL_NOT_CRASHED_FIX_FAILED
    if fix_exit_code is None:
        return HANXUEMING_MISSING_EXIT_CODE
    if fix_exit_code == 0:
        return HANXUEMING_CORRECT
    return HANXUEMING_VUL_CRASHED_FIX_FAILED


def _analyze_hanxueming_result_log(log_path: Path) -> str:
    """Apply print_result.py's all-crash/last-submit selection exactly."""
    results: list[tuple[int | None, int | None]] = []
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                vul_matches = HANXUEMING_VUL_EXIT_CODE_RE.findall(line)
                fix_matches = HANXUEMING_FIX_EXIT_CODE_RE.findall(line)
                if not vul_matches and not fix_matches:
                    continue
                results.append(
                    (
                        int(vul_matches[-1]) if vul_matches else None,
                        int(fix_matches[-1]) if fix_matches else None,
                    )
                )
    except OSError:
        return HANXUEMING_MISSING_EXIT_CODE

    if not results:
        return HANXUEMING_MISSING_EXIT_CODE
    results = [result for result in results if result[0] != 0]
    if not results:
        results.append((0, 0))
    results = results[-1:]

    categories: set[str] = set()
    for vul_exit_code, fix_exit_code in results:
        category = _classify_hanxueming_result(vul_exit_code, fix_exit_code)
        if category == HANXUEMING_CORRECT:
            return HANXUEMING_CORRECT
        categories.add(category)
    for category in HANXUEMING_PROBLEM_PRIORITY:
        if category in categories:
            return category
    return HANXUEMING_MISSING_EXIT_CODE


def _hanxueming_result_log(task_dir: Path) -> Path | None:
    """Map worker/logs/<task>-<run> back to worker/result/<task>_<run>.log."""
    match = re.match(r"^(.+)-([^-]+)$", task_dir.name)
    if match is None or task_dir.parent.name != "logs":
        return None
    result_dir = task_dir.parent.parent / "result"
    filename = f"{match.group(1)}_{match.group(2)}.log"
    direct = result_dir / filename
    if direct.is_file():
        return direct
    matches = sorted(path for path in result_dir.rglob(filename) if path.is_file())
    return matches[0] if len(matches) == 1 else None


def task_is_eligible(
    task_dir: Path, *, success_only: bool, layout: str = LAYOUT_BAIYANSONG
) -> tuple[bool, str]:
    if layout == LAYOUT_RUJIA and success_only:
        raise ValueError("--success-only is not supported for layout rujia")
    if layout == LAYOUT_HANXUEMING and success_only:
        result_log = _hanxueming_result_log(task_dir)
        if result_log is None:
            return False, "missing_result_log"
        category = _analyze_hanxueming_result_log(result_log)
        return category == HANXUEMING_CORRECT, category

    status = _read_json(task_dir / "final_status.json")
    if status is None:
        return (not success_only), "missing_final_status"
    status_name = status.get("status")
    if not success_only or status_name in SUCCESS_STATUSES:
        return True, str(status_name or "unknown")
    return False, str(status_name or "unknown")


def discover_sessions(
    task_dir: Path, report: ExportReport, *, layout: str = LAYOUT_AUTO
) -> list[SessionArtifact]:
    task_id = task_identifier(task_dir)
    artifacts: list[SessionArtifact] = []
    roots = session_roots_for_task(task_dir, layout)
    for root in roots:
        for main_path in sorted(root.glob("*.jsonl")):
            session_id = main_path.stem
            if ".claude" in main_path.parts:
                debug_path = next(
                    (
                        parent / "debug" / f"{session_id}.txt"
                        for parent in main_path.parents
                        if parent.name == ".claude"
                    ),
                    None,
                )
            else:
                debug_path = task_dir / "logs" / "debug" / f"{session_id}.txt"
            artifacts.append(
                SessionArtifact(
                    task_id=task_id,
                    task_dir=task_dir,
                    session_path=main_path,
                    session_id=session_id,
                    role="main",
                    debug_path=debug_path if debug_path and debug_path.is_file() else None,
                )
            )
            subagent_dir = root / session_id / "subagents"
            if not subagent_dir.is_dir():
                continue
            for sub_path in sorted(subagent_dir.glob("agent-*.jsonl")):
                is_compact_agent = sub_path.name.startswith(COMPACT_AGENT_PREFIX)
                meta = _read_json(sub_path.with_suffix(".meta.json")) or {}
                agent_type = meta.get("agentType")
                if not isinstance(agent_type, str) or not agent_type.strip():
                    agent_type = None
                if is_compact_agent:
                    report.compact_agents_included += 1
                artifacts.append(
                    SessionArtifact(
                        task_id=task_id,
                        task_dir=task_dir,
                        session_path=sub_path,
                        session_id=session_id,
                        role="context_compaction" if is_compact_agent else "subagent",
                        debug_path=None,
                        parent_session_id=session_id,
                        parent_agent_id=sub_path.stem.removeprefix("agent-"),
                        agent_type=agent_type,
                    )
                )
    return artifacts


def _debug_path_for(artifact: SessionArtifact) -> Path | None:
    if artifact.debug_path is not None:
        return artifact.debug_path
    claude_root = artifact.session_path
    while claude_root.name != ".claude" and claude_root != claude_root.parent:
        claude_root = claude_root.parent
    if claude_root.name != ".claude":
        return None
    candidate = claude_root / "debug" / f"{artifact.session_id}.txt"
    return candidate if candidate.is_file() else None


def read_runtime_states(artifact: SessionArtifact) -> list[RuntimeState]:
    if artifact.role != "main":
        return []
    debug_path = _debug_path_for(artifact)
    if debug_path is None:
        return []

    states: list[RuntimeState] = []
    for line in debug_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "Hook SessionStart:" not in line or " success:" not in line:
            continue
        timestamp = line.split(" ", 1)[0]
        quoted = line.split("[DEBUG] ", 1)[-1]
        try:
            decoded = json.loads(quoted)
        except json.JSONDecodeError:
            continue
        match = SESSION_START_RE.search(decoded)
        if not match:
            continue
        states.append(
            RuntimeState(
                kind=match.group(1),
                timestamp=timestamp,
                content=match.group(2).strip(),
            )
        )
    return states


def _event_message_id(event: NativeEvent) -> str | None:
    message = event.raw.get("message")
    if not isinstance(message, dict):
        return None
    value = message.get("id")
    return value if isinstance(value, str) and value else None


def _tool_result_blocks(event: NativeEvent) -> list[dict[str, Any]]:
    if event.raw.get("type") != "user":
        return []
    message = event.raw.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        return []
    return [
        block
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]


def _assistant_tool_ids(event: NativeEvent) -> set[str]:
    message = event.raw.get("message")
    if event.raw.get("type") != "assistant" or not isinstance(message, dict):
        return set()
    content = message.get("content")
    if not isinstance(content, list):
        return set()
    return {
        str(block.get("id"))
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id")
    }


def _active_segment_events(
    all_events: list[NativeEvent],
    segment_events: list[NativeEvent],
    terminal_uuid: str | None,
) -> list[NativeEvent]:
    if not segment_events:
        return []
    by_uuid = {event.uuid: event for event in all_events if event.uuid}
    selected_uuids: set[str] = set()
    cursor = terminal_uuid
    while cursor and cursor not in selected_uuids:
        event = by_uuid.get(cursor)
        if event is None:
            break
        selected_uuids.add(cursor)
        cursor = event.parent_uuid

    segment_ordinals = {event.ordinal for event in segment_events}
    selected = [
        event
        for event in segment_events
        if event.uuid in selected_uuids or event.uuid is None
    ]

    message_ids = {
        message_id
        for event in selected
        if (message_id := _event_message_id(event)) is not None
    }
    tool_ids: set[str] = set()
    for event in segment_events:
        if _event_message_id(event) in message_ids:
            tool_ids.update(_assistant_tool_ids(event))

    for event in segment_events:
        message_id = _event_message_id(event)
        result_ids = {
            str(block.get("tool_use_id"))
            for block in _tool_result_blocks(event)
            if block.get("tool_use_id")
        }
        if message_id in message_ids or result_ids.intersection(tool_ids):
            selected.append(event)

    unique = {event.ordinal: event for event in selected if event.ordinal in segment_ordinals}
    return [unique[key] for key in sorted(unique)]


def split_session_segments(events: list[NativeEvent]) -> list[list[NativeEvent]]:
    boundaries = [
        event
        for event in events
        if event.raw.get("type") == "system"
        and event.raw.get("subtype") == COMPACT_SUBTYPE
    ]
    if not boundaries:
        terminal = next(
            (event.uuid for event in reversed(events) if event.raw.get("type") == "assistant"),
            None,
        )
        return [_active_segment_events(events, events, terminal)]

    segments: list[list[NativeEvent]] = []
    start = 0
    for boundary in boundaries:
        boundary_index = events.index(boundary)
        current = events[start:boundary_index]
        terminal = boundary.raw.get("logicalParentUuid")
        terminal_uuid = terminal if isinstance(terminal, str) else None
        current_uuids = {event.uuid for event in current if event.uuid}
        if terminal_uuid not in current_uuids:
            terminal_uuid = next(
                (
                    event.uuid
                    for event in reversed(current)
                    if event.raw.get("type") == "assistant"
                ),
                None,
            )
        segments.append(_active_segment_events(events, current, terminal_uuid))
        start = boundary_index + 1

    current = events[start:]
    terminal = next(
        (event.uuid for event in reversed(current) if event.raw.get("type") == "assistant"),
        None,
    )
    segments.append(_active_segment_events(events, current, terminal))
    return [segment for segment in segments if segment]


def _stringify_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
            else:
                parts.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
        return "\n\n".join(part for part in parts if part)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _assistant_turns(events: list[NativeEvent]) -> tuple[dict[str, AssistantTurn], dict[str, str]]:
    turns: dict[str, AssistantTurn] = {}
    call_to_message: dict[str, str] = {}
    anonymous_index = 0
    for event in events:
        if event.raw.get("type") != "assistant":
            continue
        message = event.raw.get("message")
        if not isinstance(message, dict):
            continue
        message_id = _event_message_id(event)
        if message_id is None:
            anonymous_index += 1
            message_id = f"anonymous-{anonymous_index}-{event.ordinal}"
        turn = turns.setdefault(
            message_id,
            AssistantTurn(message_id=message_id, first_ordinal=event.ordinal),
        )
        content = message.get("content")
        if isinstance(content, str):
            if content:
                turn.content_parts.append(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "thinking" and isinstance(block.get("thinking"), str):
                turn.reasoning_parts.append(block["thinking"])
            elif block_type == "text" and isinstance(block.get("text"), str):
                turn.content_parts.append(block["text"])
            elif block_type == "tool_use":
                call_id = block.get("id") or block.get("tool_use_id")
                if not isinstance(call_id, str) or not call_id:
                    continue
                raw_arguments = block.get("input")
                arguments = raw_arguments if isinstance(raw_arguments, dict) else {"input": raw_arguments}
                if call_id not in call_to_message:
                    turn.tool_calls.append(
                        ToolCallRecord(
                            call_id=call_id,
                            name=str(block.get("name") or ""),
                            arguments=arguments,
                        )
                    )
                    call_to_message[call_id] = message_id
    return turns, call_to_message


def _attach_tool_results(
    events: list[NativeEvent],
    turns: dict[str, AssistantTurn],
    call_to_message: dict[str, str],
) -> list[str]:
    orphan_results: list[str] = []
    calls = {
        call.call_id: call
        for turn in turns.values()
        for call in turn.tool_calls
    }
    for event in events:
        for block in _tool_result_blocks(event):
            call_id = block.get("tool_use_id")
            if not isinstance(call_id, str) or call_id not in call_to_message:
                orphan_results.append(str(call_id or "<missing>"))
                continue
            call = calls[call_id]
            if call.output is not None:
                continue
            call.output = _stringify_content(block.get("content", ""))
            call.is_error = bool(block.get("is_error", False))
    return orphan_results


def _format_tool_output(call: ToolCallRecord) -> str:
    prefix = "ERROR" if call.is_error else "OBSERVATION"
    return f"{prefix}:\n{call.output or ''}"


def _is_runtime_notification(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("<system-reminder>") or stripped.startswith(
        "<task-notification>"
    )


def _is_observer_content(text: str) -> bool:
    lowered = text.lower()
    return "observer advisory" in lowered or "observer 是旁路建议" in lowered


def _without_observer_state(text: str) -> str:
    """Remove the injected observer section while retaining working-set facts."""
    lines = text.splitlines()
    kept: list[str] = []
    in_observer = False
    for line in lines:
        heading = line.lstrip().startswith("## ")
        if line.strip().lower() == "## observer":
            in_observer = True
            continue
        if in_observer and heading:
            in_observer = False
        if not in_observer:
            kept.append(line)
    return "\n".join(kept).strip()


def events_to_messages(
    events: list[NativeEvent],
    *,
    system_prompt: str,
    runtime_state: str | None,
    drop_observer: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    turns, call_to_message = _assistant_turns(events)
    warnings = _attach_tool_results(events, turns, call_to_message)
    first_event_by_message = {turn.first_ordinal: turn for turn in turns.values()}

    system_parts = [system_prompt.strip()]
    if runtime_state:
        state = _without_observer_state(runtime_state) if drop_observer else runtime_state.strip()
        if state:
            system_parts.append(f"[RUNTIME_STATE]\n{state}")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "\n\n".join(part for part in system_parts if part)}
    ]

    for event in events:
        turn = first_event_by_message.get(event.ordinal)
        if turn is not None:
            assistant: dict[str, Any] = {
                "role": "assistant",
                "content": "\n\n".join(part for part in turn.content_parts if part),
            }
            if turn.reasoning_parts:
                assistant["reasoning_content"] = "\n\n".join(
                    part for part in turn.reasoning_parts if part
                )
            if turn.tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": call.call_id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in turn.tool_calls
                ]
            messages.append(assistant)
            for call in turn.tool_calls:
                if call.output is not None:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.call_id,
                            "name": call.name,
                            "content": _format_tool_output(call),
                        }
                    )
            continue

        if event.raw.get("type") != "user" or _tool_result_blocks(event):
            continue
        message = event.raw.get("message")
        if not isinstance(message, dict):
            continue
        content = _stringify_content(message.get("content", ""))
        if not content.strip():
            continue
        if drop_observer and (_is_observer_content(content) or _is_runtime_notification(content)):
            continue
        if event.raw.get("isCompactSummary"):
            content = f"[CONTEXT_SUMMARY]\n{content}"
        messages.append({"role": "user", "content": content})

    # Late hook/task notifications can arrive after the agent's final response.
    # Drop only those trailing user messages. A compact boundary may occur after
    # a completed tool result but before the next assistant inference; that tool
    # observation is part of the real context and must remain in the sample.
    while messages and messages[-1].get("role") == "user":
        messages.pop()
    return messages, warnings


def segment_is_complete(messages: list[dict[str, Any]]) -> bool:
    if not messages or messages[-1].get("role") not in {"assistant", "tool"}:
        return False
    for index, message in enumerate(messages):
        calls = message.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            continue
        following = messages[index + 1 : index + 1 + len(calls)]
        if len(following) != len(calls) or any(item.get("role") != "tool" for item in following):
            return False
    return True


def missing_tool_result_turns(messages: list[dict[str, Any]]) -> list[dict[str, int]]:
    """Return assistant turns whose tool calls lack immediately paired results."""
    missing: list[dict[str, int]] = []
    for index, message in enumerate(messages):
        calls = message.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            continue
        following = messages[index + 1 : index + 1 + len(calls)]
        found = sum(1 for item in following if item.get("role") == "tool")
        if len(following) != len(calls) or found != len(calls):
            missing.append(
                {
                    "message_index": index,
                    "expected_results": len(calls),
                    "found_results": found,
                }
            )
    return missing


def has_only_terminal_missing_tool_results(
    messages: list[dict[str, Any]], missing: list[dict[str, int]]
) -> bool:
    """True when the sole structural gap is an unanswered final tool call."""
    return (
        len(missing) == 1
        and missing[0]["message_index"] == len(messages) - 1
        and missing[0]["found_results"] == 0
        and messages[-1].get("role") == "assistant"
    )


def has_missing_tool_result_followed_by_assistant(
    messages: list[dict[str, Any]], missing: list[dict[str, int]]
) -> bool:
    """True when inference continued after an unanswered tool call."""
    return any(
        any(
            message.get("role") == "assistant"
            for message in messages[item["message_index"] + 1 :]
        )
        for item in missing
    )


def validate_context_compaction(messages: list[dict[str, Any]]) -> tuple[bool, str]:
    """Require a completed dedicated summary request/response pair."""
    if len(messages) < 3:
        return False, "too_few_messages"
    final = messages[-1]
    if final.get("role") != "assistant":
        return False, f"final_role:{final.get('role')}"
    if final.get("tool_calls"):
        return False, "final_assistant_has_tool_calls"
    final_content = final.get("content")
    if not isinstance(final_content, str) or not final_content.strip():
        return False, "empty_final_assistant"
    previous = messages[-2]
    if previous.get("role") != "user":
        return False, f"penultimate_role:{previous.get('role')}"
    request = previous.get("content")
    if not isinstance(request, str):
        return False, "compaction_request_not_string"
    request_lower = request.lower()
    if "conversation" not in request_lower or not any(
        signal in request_lower for signal in ("summary", "summarize")
    ):
        return False, "missing_compaction_request_signal"
    final_lower = final_content.lower()
    if "<summary>" not in final_lower or "</summary>" not in final_lower:
        return False, "missing_summary_block"
    return True, "valid"


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    ascii_count = sum(ord(character) < 128 for character in serialized)
    non_ascii_count = len(serialized) - ascii_count
    # Latin-heavy JSON is commonly close to four characters per token, while
    # CJK text is often near one Unicode character per token. Keep the estimate
    # dependency-free without systematically under-counting Chinese sessions.
    return max(1, (ascii_count + 3) // 4 + non_ascii_count)


def _runtime_state_for_segment(
    states: list[RuntimeState], segment_index: int
) -> str | None:
    desired = "startup" if segment_index == 0 else "compact"
    matches = [state.content for state in states if state.kind == desired]
    if segment_index == 0:
        return matches[0] if matches else None
    offset = segment_index - 1
    return matches[offset] if offset < len(matches) else None


def _sample_id(artifact: SessionArtifact, segment_index: int) -> str:
    if artifact.role == "main":
        role_suffix = "main"
    elif artifact.role == "context_compaction":
        role_suffix = f"context-compaction-{artifact.parent_agent_id}"
    else:
        role_suffix = f"subagent-{artifact.parent_agent_id}"
    normalized_task_id = artifact.task_id.replace(":", "_").replace("/", "_")
    return f"{normalized_task_id}-{artifact.session_id}-{role_suffix}-segment-{segment_index + 1:03d}"


def _sample_digest(sample: dict[str, Any]) -> str:
    body = json.dumps(
        {
            "sample_type": sample.get("sample_type"),
            "messages": sample["messages"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _prompt_for_artifact(
    artifact: SessionArtifact,
    *,
    main_prompt: str,
    explore_prompt: str,
    unknown_prompt: str,
) -> str:
    """Select the prompt visible to this artifact's agent role.

    Compact agents are storage-side helpers containing a copy of the main
    conversation; their prompt is therefore the main prompt. Ordinary
    subagents are selected by their captured agentType. Unknown types use the
    explicit minimal Claude SDK fallback requested by the exporter contract.
    """
    if artifact.role in {"main", "context_compaction"}:
        return main_prompt
    if artifact.agent_type == "Explore":
        return explore_prompt
    return unknown_prompt


def export_training_jsonl(
    *,
    source: Path,
    output: Path,
    system_prompt: str | None = None,
    main_system_prompt: str | None = None,
    subagent_system_prompt: str | None = None,
    main_system_prompt_file: Path | None = None,
    subagent_system_prompt_file: Path | None = None,
    layout: str = LAYOUT_AUTO,
    success_only: bool = False,
    include_incomplete: bool = False,
    include_nonterminal_missing_tool_results: bool = False,
    include_runtime_state: bool = False,
    drop_observer: bool = False,
    max_estimated_tokens: int | None = None,
) -> ExportReport:
    source = source.resolve()
    output = output.resolve()
    resolved_layout = detect_layout(source) if layout == LAYOUT_AUTO else layout
    if resolved_layout not in {LAYOUT_BAIYANSONG, LAYOUT_HANXUEMING, LAYOUT_RUJIA}:
        raise ValueError(f"unsupported layout: {layout}")
    if resolved_layout == LAYOUT_RUJIA and success_only:
        raise ValueError("--success-only is not supported for layout rujia")
    resolved_main_prompt, resolved_subagent_prompt = resolve_system_prompts(
        system_prompt=system_prompt,
        main_system_prompt=main_system_prompt,
        subagent_system_prompt=subagent_system_prompt,
        main_system_prompt_file=main_system_prompt_file,
        subagent_system_prompt_file=subagent_system_prompt_file,
    )
    unknown_prompt = (
        resolved_subagent_prompt
        if (
            system_prompt is not None
            or subagent_system_prompt is not None
            or subagent_system_prompt_file is not None
        )
        else UNKNOWN_SUBAGENT_SYSTEM_PROMPT
    )
    report = ExportReport(
        source=str(source),
        output=str(output),
        layout=resolved_layout,
        success_only=success_only,
        main_system_prompt_sha256=hashlib.sha256(
            resolved_main_prompt.encode("utf-8")
        ).hexdigest(),
        subagent_system_prompt_sha256=hashlib.sha256(
            resolved_subagent_prompt.encode("utf-8")
        ).hexdigest(),
        runtime_state_included=include_runtime_state,
    )
    samples: list[dict[str, Any]] = []
    seen_digests: set[str] = set()
    task_dirs_with_samples: set[Path] = set()

    for task_dir in discover_task_dirs(source, layout=resolved_layout):
        report.tasks_seen += 1
        eligible, reason = task_is_eligible(
            task_dir, success_only=success_only, layout=resolved_layout
        )
        if not eligible:
            report.tasks_skipped += 1
            report.warnings.append(f"skipped task {task_dir.name}: status={reason}")
            continue
        report.tasks_eligible += 1

        artifacts = discover_sessions(task_dir, report, layout=resolved_layout)
        if not artifacts:
            report.tasks_skipped += 1
            report.tasks_without_sessions += 1
            continue
        for artifact in artifacts:
            report.sessions_seen += 1
            events = read_jsonl_events(artifact.session_path)
            runtime_states = (
                read_runtime_states(artifact) if include_runtime_state else []
            )
            artifact_system_prompt = _prompt_for_artifact(
                artifact,
                main_prompt=resolved_main_prompt,
                explore_prompt=resolved_subagent_prompt,
                unknown_prompt=unknown_prompt,
            )
            for segment_index, segment in enumerate(split_session_segments(events)):
                messages, warnings = events_to_messages(
                    segment,
                    system_prompt=artifact_system_prompt,
                    runtime_state=_runtime_state_for_segment(runtime_states, segment_index),
                    drop_observer=drop_observer,
                )
                if warnings:
                    report.warnings.append(
                        f"{artifact.session_path}: segment {segment_index + 1} orphan tool results: "
                        + ", ".join(warnings)
                    )
                if artifact.role == "context_compaction":
                    valid_compaction, compact_reason = validate_context_compaction(messages)
                    if not valid_compaction:
                        report.invalid_compact_agents_skipped += 1
                        report.warnings.append(
                            f"skipped invalid compact agent {artifact.session_path}: "
                            f"segment {segment_index + 1}: {compact_reason}"
                        )
                        continue
                    report.valid_compact_agents += 1
                if not any(message.get("role") == "assistant" for message in messages):
                    report.incomplete_segments_skipped += 1
                    continue
                missing_results = missing_tool_result_turns(messages)
                terminal_missing_results = has_only_terminal_missing_tool_results(
                    messages, missing_results
                )
                nonterminal_missing_results = has_missing_tool_result_followed_by_assistant(
                    messages, missing_results
                )
                termination: dict[str, Any] | None = None
                if terminal_missing_results:
                    report.terminal_tool_result_missing_samples_included += 1
                    termination = {
                        "reason": "missing_terminal_tool_result",
                        "tool_names": [
                            str(call.get("name") or "")
                            for call in messages[-1].get("tool_calls", [])
                        ],
                    }
                elif nonterminal_missing_results:
                    if not include_nonterminal_missing_tool_results:
                        # Inference appears to continue without an observation.
                        # Only the dedicated opt-in may retain this; the broad
                        # --include-incomplete option must not bypass it.
                        report.incomplete_segments_skipped += 1
                        continue
                    report.nonterminal_missing_tool_results_samples_included += 1
                    termination = {
                        "reason": "nonterminal_missing_tool_results_included",
                        "missing_turns": missing_results,
                    }
                elif not segment_is_complete(messages) and not include_incomplete:
                    report.incomplete_segments_skipped += 1
                    continue
                if max_estimated_tokens is not None and estimate_tokens(messages) > max_estimated_tokens:
                    report.oversized_segments_skipped += 1
                    continue
                sample = {
                    "id": _sample_id(artifact, segment_index),
                    "sample_type": artifact.role,
                    "messages": messages,
                    "metadata": {
                        "source_agent": "claude-code",
                        "source_session_id": artifact.session_id,
                        "source_artifact_id": artifact.session_path.name,
                        "parent_session_id": artifact.parent_session_id,
                        "parent_agent_id": artifact.parent_agent_id,
                        "agent_type": artifact.agent_type,
                        "system_prompt_source": (
                            "override"
                            if (
                                system_prompt is not None
                                or main_system_prompt is not None
                                or subagent_system_prompt is not None
                                or main_system_prompt_file is not None
                                or subagent_system_prompt_file is not None
                            )
                            else "builtin"
                        ),
                        "system_prompt_sha256": hashlib.sha256(
                            artifact_system_prompt.encode("utf-8")
                        ).hexdigest(),
                        "reasoning_available": any(
                            bool(message.get("reasoning_content"))
                            for message in messages
                        ),
                        "estimated_tokens": estimate_tokens(messages),
                        "segment_index": segment_index + 1,
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
                task_dirs_with_samples.add(task_dir)

    if report.tasks_without_sessions:
        report.warnings.append(
            f"{report.tasks_without_sessions} task directories had no Claude Code sessions"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + "\n")
    report.samples_written = len(samples)
    report.tasks_with_samples = len(task_dirs_with_samples)
    report.main_samples_written = sum(
        sample.get("sample_type") == "main" for sample in samples
    )
    report.subagent_samples_written = sum(
        sample.get("sample_type") == "subagent" for sample in samples
    )
    report.context_compaction_samples_written = sum(
        sample.get("sample_type") == "context_compaction" for sample in samples
    )
    report_path = output.with_suffix(output.suffix + ".report.json")
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report
