"""Convert Hermes Agent session exports or ``state.db`` into ATIF.

Hermes persists sessions in ``$HERMES_HOME/state.db`` (normally
``~/.hermes/state.db``).  ``hermes sessions export`` writes one complete
session object per JSONL line.  Both forms contain the same OpenAI-shaped
message stream, including plaintext reasoning fields when the selected model
and provider expose them.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

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


AGENT_NAME = "hermes"
SESSION_EXPORT_FILENAME = "hermes-session.jsonl"
STATE_DB_FILENAME = "state.db"
TRAJECTORY_FILENAME = "trajectory.json"
_CONTENT_JSON_PREFIX = "\x00json:"


def _json_value(value: Any) -> Any:
    """Decode JSON stored in Hermes TEXT columns, leaving plain text alone."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _decode_db_content(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_CONTENT_JSON_PREFIX):
        try:
            return json.loads(value[len(_CONTENT_JSON_PREFIX) :])
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def _epoch_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            value = float(stripped)
        except ValueError:
            # ATIF accepts an already-formatted ISO timestamp.
            return stripped
    if not isinstance(value, (int, float)):
        return None
    return (
        datetime.fromtimestamp(float(value), tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _content_text(content: Any) -> str:
    """Flatten visible message content while excluding thinking blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        part_type = str(content.get("type") or "").lower()
        if part_type in {"thinking", "reasoning", "redacted_thinking"}:
            return ""
        for key in ("text", "content", "output_text"):
            value = content.get(key)
            if isinstance(value, str):
                return value
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    if isinstance(content, list):
        return "".join(_content_text(part) for part in content)
    return str(content)


def _append_reasoning_text(parts: list[str], value: Any) -> None:
    if not isinstance(value, str):
        return
    text = value.strip()
    # Hermes may store a single-space compatibility pad for strict thinking
    # providers.  It is protocol state, not model reasoning.
    if text and text not in parts:
        parts.append(text)


def _reasoning_from_structure(value: Any, parts: list[str]) -> None:
    value = _json_value(value)
    if isinstance(value, list):
        for item in value:
            _reasoning_from_structure(item, parts)
        return
    if not isinstance(value, dict):
        return

    block_type = str(value.get("type") or "").lower()
    if block_type == "redacted_thinking":
        return

    # OpenRouter details use text/summary, Anthropic blocks use thinking, and
    # Codex reasoning items use summary arrays containing summary_text blocks.
    for key in ("thinking", "text", "summary_text"):
        _append_reasoning_text(parts, value.get(key))

    summary = value.get("summary")
    if isinstance(summary, (list, dict)):
        _reasoning_from_structure(summary, parts)
    elif isinstance(summary, str):
        _append_reasoning_text(parts, summary)

    nested = value.get("content")
    if block_type in {"thinking", "reasoning", "reasoning.text", "summary_text"}:
        if isinstance(nested, str):
            _append_reasoning_text(parts, nested)
        elif isinstance(nested, (list, dict)):
            _reasoning_from_structure(nested, parts)


def _extract_reasoning(message: dict[str, Any]) -> str | None:
    """Return only plaintext reasoning that Hermes actually persisted."""
    parts: list[str] = []
    _append_reasoning_text(parts, message.get("reasoning"))
    _append_reasoning_text(parts, message.get("reasoning_content"))
    _reasoning_from_structure(message.get("reasoning_details"), parts)
    _reasoning_from_structure(message.get("codex_reasoning_items"), parts)

    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").lower()
            if block_type in {"thinking", "reasoning"}:
                _reasoning_from_structure(block, parts)
    return "\n\n".join(parts) or None


def _tool_arguments(value: Any) -> dict[str, Any]:
    value = _json_value(value)
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    return {"value": value}


def _tool_calls(message: dict[str, Any]) -> list[ToolCall] | None:
    raw_calls = _json_value(message.get("tool_calls"))
    if not isinstance(raw_calls, list):
        return None
    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls):
        if not isinstance(raw, dict):
            continue
        function = raw.get("function")
        function = function if isinstance(function, dict) else {}
        call_id = raw.get("id") or raw.get("tool_call_id") or f"hermes-tool-{index}"
        name = function.get("name") or raw.get("name") or raw.get("tool_name") or "unknown"
        arguments = function.get("arguments", raw.get("arguments"))
        calls.append(
            ToolCall(
                tool_call_id=str(call_id),
                function_name=str(name),
                arguments=_tool_arguments(arguments),
            )
        )
    return calls or None


def _message_metrics(message: dict[str, Any]) -> Metrics | None:
    usage = message.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens")
    completion = usage.get("completion_tokens") or usage.get("output_tokens")
    cached = usage.get("cache_read_tokens") or usage.get("cached_tokens")
    if completion is None and message.get("role") == "assistant":
        completion = message.get("token_count")
    if not any(value is not None for value in (prompt, completion, cached)):
        return None
    return Metrics(
        prompt_tokens=int(prompt) if prompt is not None else None,
        completion_tokens=int(completion) if completion is not None else None,
        cached_tokens=int(cached) if cached is not None else None,
    )


def _model_config(session: dict[str, Any]) -> dict[str, Any]:
    value = _json_value(session.get("model_config"))
    return value if isinstance(value, dict) else {}


def _reasoning_effort(session: dict[str, Any]) -> str | float | None:
    config = _model_config(session)
    reasoning = config.get("reasoning_config")
    if isinstance(reasoning, dict):
        effort = reasoning.get("effort")
        if isinstance(effort, (str, int, float)):
            return effort
    effort = config.get("reasoning_effort")
    return effort if isinstance(effort, (str, int, float)) else None


def _session_final_metrics(session: dict[str, Any], steps: list[Step]) -> FinalMetrics:
    def number(name: str) -> int | None:
        value = session.get(name)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    cost = session.get("actual_cost_usd")
    if cost is None:
        cost = session.get("estimated_cost_usd")
    try:
        cost_value = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost_value = None

    extra = {
        key: value
        for key, value in {
            "reasoning_tokens": number("reasoning_tokens"),
            "cache_write_tokens": number("cache_write_tokens"),
            "api_call_count": number("api_call_count"),
            "cost_status": session.get("cost_status"),
        }.items()
        if value is not None
    }
    return FinalMetrics(
        total_prompt_tokens=number("input_tokens"),
        total_completion_tokens=number("output_tokens"),
        total_cached_tokens=number("cache_read_tokens"),
        total_cost_usd=cost_value,
        total_steps=len(steps),
        extra=extra or None,
    )


def convert_session(
    session: dict[str, Any],
    *,
    model_name: str | None = None,
    version: str | None = None,
) -> Trajectory | None:
    """Convert one exported Hermes session dictionary into ATIF."""
    raw_messages = session.get("messages")
    if not isinstance(raw_messages, list):
        return None
    messages = [message for message in raw_messages if isinstance(message, dict)]

    steps: list[Step] = []
    effort = _reasoning_effort(session)

    # state.db stores the system prompt on the session row rather than as a
    # normal message.  Keep it in the trajectory when it is available.
    system_prompt = session.get("system_prompt")
    if isinstance(system_prompt, str) and system_prompt.strip() and not any(
        message.get("role") == "system" and _content_text(message.get("content")) == system_prompt
        for message in messages
    ):
        steps.append(
            Step(
                step_id=1,
                timestamp=_epoch_to_iso(session.get("started_at")),
                source="system",
                message=system_prompt,
            )
        )

    index = 0
    while index < len(messages):
        message = messages[index]
        role = str(message.get("role") or "")
        content = _content_text(message.get("content"))
        timestamp = _epoch_to_iso(message.get("timestamp"))

        if role in {"system", "user"}:
            if content:
                steps.append(
                    Step(
                        step_id=len(steps) + 1,
                        timestamp=timestamp,
                        source=role,
                        message=content,
                        extra={"message_id": message.get("id")}
                        if message.get("id") is not None
                        else None,
                    )
                )
        elif role == "assistant":
            calls = _tool_calls(message)
            reasoning = _extract_reasoning(message)
            display_message = content or ("(tool use)" if calls else "(reasoning)")
            results: list[ObservationResult] = []
            if calls:
                call_ids = {call.tool_call_id for call in calls}
                while index + 1 < len(messages) and messages[index + 1].get("role") == "tool":
                    index += 1
                    tool_message = messages[index]
                    source_call_id = tool_message.get("tool_call_id")
                    if source_call_id is not None:
                        source_call_id = str(source_call_id)
                    # ATIF validates references.  Preserve unmatched results as
                    # unbound observations instead of producing invalid output.
                    if source_call_id not in call_ids:
                        source_call_id = None
                    extra = {
                        key: value
                        for key, value in {
                            "tool_name": tool_message.get("tool_name") or tool_message.get("name"),
                            "message_id": tool_message.get("id"),
                        }.items()
                        if value is not None
                    }
                    results.append(
                        ObservationResult(
                            source_call_id=source_call_id,
                            content=_content_text(tool_message.get("content")) or None,
                            extra=extra or None,
                        )
                    )

            if content or reasoning or calls:
                extra = {
                    key: value
                    for key, value in {
                        "message_id": message.get("id"),
                        "finish_reason": message.get("finish_reason"),
                    }.items()
                    if value is not None
                }
                steps.append(
                    Step(
                        step_id=len(steps) + 1,
                        timestamp=timestamp,
                        source="agent",
                        model_name=message.get("model") or None,
                        reasoning_effort=effort,
                        message=display_message,
                        reasoning_content=reasoning,
                        tool_calls=calls,
                        observation=Observation(results=results) if results else None,
                        metrics=_message_metrics(message),
                        llm_call_count=1,
                        extra=extra or None,
                    )
                )
        elif role == "tool" and content:
            # A malformed/legacy export may contain an unpaired tool result.
            # Keep it visible without inventing a tool-call reference.
            steps.append(
                Step(
                    step_id=len(steps) + 1,
                    timestamp=timestamp,
                    source="system",
                    message=f"[tool result: {message.get('tool_name') or 'unknown'}]\n{content}",
                )
            )
        index += 1

    if not steps:
        return None

    agent_extra = {
        key: value
        for key, value in {
            "source": session.get("source"),
            "title": session.get("title"),
            "cwd": session.get("cwd"),
            "git_branch": session.get("git_branch"),
            "git_repo_root": session.get("git_repo_root"),
            "parent_session_id": session.get("parent_session_id"),
        }.items()
        if value is not None
    }
    session_id = session.get("id") or session.get("session_id")
    return Trajectory(
        schema_version="ATIF-v1.7",
        session_id=str(session_id) if session_id is not None else None,
        agent=Agent(
            name=AGENT_NAME,
            version=version or "unknown",
            model_name=model_name or session.get("model"),
            extra=agent_extra or None,
        ),
        steps=steps,
        final_metrics=_session_final_metrics(session, steps),
    )


def _select_session(
    sessions: Iterable[dict[str, Any]], session_id: str | None
) -> dict[str, Any]:
    candidates = list(sessions)
    if session_id:
        exact = [item for item in candidates if str(item.get("id") or item.get("session_id")) == session_id]
        if len(exact) == 1:
            return exact[0]
        prefix = [
            item
            for item in candidates
            if str(item.get("id") or item.get("session_id") or "").startswith(session_id)
        ]
        if len(prefix) == 1:
            return prefix[0]
        if len(prefix) > 1:
            raise ValueError(f"Hermes session prefix {session_id!r} is ambiguous")
        raise ValueError(f"Hermes session {session_id!r} was not found in the source")
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("Hermes source contains no sessions")
    raise ValueError(
        "Hermes export contains multiple sessions; pass --session <session-id> "
        "or export one session with `hermes sessions export <file> --session-id <id>`."
    )


def load_export(path: Path, *, session_id: str | None = None) -> dict[str, Any]:
    """Load a Hermes JSON/JSONL export, including the legacy message-per-line form."""
    text = path.read_text(encoding="utf-8", errors="replace")
    stripped = text.strip()
    if not stripped:
        raise ValueError("Hermes export is empty")

    parsed_rows: list[Any] = []
    try:
        whole = json.loads(stripped)
    except json.JSONDecodeError:
        whole = None
    if whole is not None:
        parsed_rows = whole if isinstance(whole, list) else [whole]
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed_rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    objects = [row for row in parsed_rows if isinstance(row, dict)]
    sessions = [row for row in objects if isinstance(row.get("messages"), list)]
    if sessions:
        return _select_session(sessions, session_id)

    # Legacy Hermes transcripts stored one OpenAI message object per line.
    messages = [row for row in objects if row.get("role")]
    if messages:
        return {
            "id": session_id or path.stem,
            "messages": messages,
        }
    raise ValueError("Hermes export contains no recognizable session messages")


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def load_state_db(path: Path, *, session_id: str | None = None) -> dict[str, Any]:
    """Read one session from Hermes' canonical SQLite store without mutating it."""
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        session_columns = _sqlite_columns(conn, "sessions")
        if not session_columns:
            raise ValueError("Hermes state.db has no sessions table")

        if session_id:
            rows = conn.execute(
                "SELECT * FROM sessions "
                "WHERE id = ? OR substr(id, 1, length(?)) = ? "
                "ORDER BY started_at DESC LIMIT 2",
                (session_id, session_id, session_id),
            ).fetchall()
            exact = [row for row in rows if row["id"] == session_id]
            if exact:
                row = exact[0]
            elif len(rows) == 1:
                row = rows[0]
            elif len(rows) > 1:
                raise ValueError(f"Hermes session prefix {session_id!r} is ambiguous")
            else:
                raise ValueError(f"Hermes session {session_id!r} was not found in state.db")
        else:
            order_columns = []
            if "ended_at" in session_columns and "started_at" in session_columns:
                order_columns.append("COALESCE(ended_at, started_at) DESC")
            elif "started_at" in session_columns:
                order_columns.append("started_at DESC")
            order_columns.append("id DESC")
            main_session_clause = (
                "WHERE COALESCE(source, '') != 'tool'"
                if "source" in session_columns
                else ""
            )
            row = conn.execute(
                f"SELECT * FROM sessions {main_session_clause} "
                f"ORDER BY {', '.join(order_columns)} LIMIT 1"
            ).fetchone()
            if row is None and main_session_clause:
                row = conn.execute(
                    f"SELECT * FROM sessions "
                    f"ORDER BY {', '.join(order_columns)} LIMIT 1"
                ).fetchone()
            if row is None:
                raise ValueError("Hermes state.db contains no sessions")

        session = dict(row)
        # New Hermes versions de-duplicate the system prompt into a separate
        # table. Resolve it when the inline column is empty.
        if (
            not session.get("system_prompt")
            and session.get("system_prompt_hash")
            and "system_prompt_hash" in session_columns
            and _sqlite_columns(conn, "system_prompts")
        ):
            prompt_row = conn.execute(
                "SELECT prompt FROM system_prompts WHERE hash = ?",
                (session["system_prompt_hash"],),
            ).fetchone()
            if prompt_row:
                session["system_prompt"] = prompt_row[0]

        message_columns = _sqlite_columns(conn, "messages")
        if not message_columns:
            raise ValueError("Hermes state.db has no messages table")
        active_clause = " AND COALESCE(active, 1) = 1" if "active" in message_columns else ""
        rows = conn.execute(
            f"SELECT * FROM messages WHERE session_id = ?{active_clause} ORDER BY id",
            (session["id"],),
        ).fetchall()
        messages: list[dict[str, Any]] = []
        for message_row in rows:
            message = dict(message_row)
            message["content"] = _decode_db_content(message.get("content"))
            for key in (
                "tool_calls",
                "reasoning_details",
                "codex_reasoning_items",
                "codex_message_items",
            ):
                if message.get(key):
                    message[key] = _json_value(message[key])
            messages.append(message)
        session["messages"] = messages
        return session
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"could not read Hermes state.db: {exc}") from exc
    finally:
        conn.close()


def locate_source(logs_dir: Path) -> tuple[str, Path] | None:
    state_db = logs_dir / STATE_DB_FILENAME
    if state_db.is_file():
        return "state-db", state_db
    export = logs_dir / SESSION_EXPORT_FILENAME
    if export.is_file():
        return "export", export

    exports = sorted(
        path
        for path in logs_dir.rglob("*.jsonl")
        if path.is_file() and path.name != TRAJECTORY_FILENAME
    )
    if len(exports) == 1:
        return "export", exports[0]
    dbs = sorted(path for path in logs_dir.rglob(STATE_DB_FILENAME) if path.is_file())
    if len(dbs) == 1:
        return "state-db", dbs[0]
    return None


class Hermes(BaseInstalledAgent):
    """Vendored-backend adapter exposing the standalone Hermes converter."""

    SUPPORTS_ATIF: bool = True

    def __init__(self, *args: Any, session_id: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.session_id = session_id

    @staticmethod
    def name() -> str:
        return AGENT_NAME

    def populate_context_post_run(self, context: Any) -> None:
        located = locate_source(self.logs_dir)
        if located is None:
            return
        kind, source = located
        session = (
            load_state_db(source, session_id=self.session_id)
            if kind == "state-db"
            else load_export(source, session_id=self.session_id)
        )
        trajectory = convert_session(
            session,
            model_name=self.model_name,
            version=self.version(),
        )
        if trajectory is None:
            return

        trajectory_path = self.logs_dir / TRAJECTORY_FILENAME
        trajectory_path.write_text(
            format_trajectory_json(trajectory.to_json_dict()), encoding="utf-8"
        )
        final = trajectory.final_metrics
        if final:
            context.n_input_tokens = final.total_prompt_tokens or 0
            context.n_output_tokens = final.total_completion_tokens or 0
            context.n_cache_tokens = final.total_cached_tokens or 0
            context.cost_usd = final.total_cost_usd
