from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def strip_model_none(value: Any, *, preserve_payload: bool = False) -> Any:
    """Approximate Harbor's Pydantic model_dump(exclude_none=True, mode="json").

    None-valued ATIF model fields disappear, but arbitrary payload dictionaries
    under fields such as arguments and extra keep their own null values.
    """
    if isinstance(value, dict):
        if preserve_payload:
            return {
                key: strip_model_none(item, preserve_payload=True)
                for key, item in value.items()
            }
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if item is None:
                continue
            cleaned[key] = strip_model_none(
                item, preserve_payload=key in {"arguments", "extra"}
            )
        return cleaned
    if isinstance(value, list):
        return [strip_model_none(item, preserve_payload=preserve_payload) for item in value]
    return value


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_atif_trajectory(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    return (
        isinstance(data.get("schema_version"), str)
        and isinstance(data.get("agent"), dict)
        and isinstance(data.get("steps"), list)
    )


def copy_existing_atif(source: Path, output: Path) -> bool:
    if not source.exists():
        return False
    try:
        data = read_json(source)
    except (OSError, json.JSONDecodeError):
        return False
    if not is_atif_trajectory(data):
        return False

    output.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != output.resolve():
        shutil.copyfile(source, output)
    return True


def summarize(path: Path) -> dict[str, Any]:
    data = read_json(path)
    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    reasoning_steps = [
        step for step in steps if isinstance(step, dict) and step.get("reasoning_content")
    ]
    tool_calls = 0
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("tool_calls"), list):
            tool_calls += len(step["tool_calls"])
    return {
        "path": str(path),
        "agent": (data.get("agent") or {}).get("name"),
        "model": (data.get("agent") or {}).get("model_name"),
        "schema_version": data.get("schema_version"),
        "session_id": data.get("session_id"),
        "steps": len(steps),
        "reasoning_steps": len(reasoning_steps),
        "tool_calls": tool_calls,
        "final_metrics": data.get("final_metrics"),
    }

