from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from harbor_trajectory_extractor.training import ExportReport, export_training_jsonl


def _link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source, target_is_directory=source.is_dir())
    except OSError:
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)


def _main_session_candidates(source: Path) -> list[Path]:
    source = source.resolve()
    if source.is_file():
        if source.suffix != ".jsonl":
            raise ValueError("Claude Code training source file must be a session .jsonl")
        if source.parent.name == "subagents":
            session_id = source.parent.parent.name
            main_path = source.parent.parent.parent / f"{session_id}.jsonl"
            return [main_path] if main_path.is_file() else []
        return [source]

    roots: list[Path] = []
    if (source / "sessions" / "projects").is_dir():
        roots.append(source / "sessions" / "projects")
    elif (source / "projects").is_dir():
        roots.append(source / "projects")
    else:
        roots.append(source)
    candidates = {
        path.resolve()
        for root in roots
        for path in root.rglob("*.jsonl")
        if path.is_file() and "subagents" not in path.parts
    }
    if len(candidates) != 1:
        if not candidates:
            raise ValueError("Claude Code source contains no main session .jsonl")
        raise ValueError(
            "Claude Code source contains multiple main sessions; pass one session .jsonl"
        )
    return sorted(candidates)


def _claude_config_root(main_path: Path) -> Path | None:
    for parent in main_path.parents:
        if parent.name == "projects":
            return parent.parent
    return None


def _stage_native_session(source: Path) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    candidates = _main_session_candidates(source)
    if len(candidates) != 1:
        raise ValueError("Claude Code source must resolve to exactly one main session")
    main_path = candidates[0]
    session_id = main_path.stem
    cleanup = tempfile.TemporaryDirectory(prefix="htextract-claude-training-")
    run_root = Path(cleanup.name) / "run"
    project_root = (
        run_root
        / "tasks"
        / "native"
        / "logs"
        / "imported"
        / "cc_session"
        / ".claude"
        / "projects"
        / "-workspace"
    )
    _link_or_copy(main_path, project_root / main_path.name)

    subagent_dir = main_path.parent / session_id / "subagents"
    if subagent_dir.is_dir():
        _link_or_copy(subagent_dir, project_root / session_id / "subagents")

    config_root = _claude_config_root(main_path)
    if config_root is not None:
        debug_path = config_root / "debug" / f"{session_id}.txt"
        if debug_path.is_file():
            _link_or_copy(
                debug_path,
                project_root.parents[1] / "debug" / debug_path.name,
            )
    return cleanup, run_root


def export_claude_native_training_jsonl(
    *,
    source: Path,
    output: Path,
    system_prompt: str | None = None,
    main_system_prompt_file: Path | None = None,
    subagent_system_prompt_file: Path | None = None,
    include_incomplete: bool = False,
    include_nonterminal_missing_tool_results: bool = False,
    include_runtime_state: bool = False,
    drop_observer: bool = False,
    max_estimated_tokens: int | None = None,
) -> ExportReport:
    source = source.resolve()
    cleanup, staged_source = _stage_native_session(source)
    try:
        report = export_training_jsonl(
            source=staged_source,
            output=output,
            system_prompt=system_prompt,
            main_system_prompt_file=main_system_prompt_file,
            subagent_system_prompt_file=subagent_system_prompt_file,
            layout="baiyansong",
            include_incomplete=include_incomplete,
            include_nonterminal_missing_tool_results=(
                include_nonterminal_missing_tool_results
            ),
            include_runtime_state=include_runtime_state,
            drop_observer=drop_observer,
            max_estimated_tokens=max_estimated_tokens,
        )
    finally:
        cleanup.cleanup()
    report.source = str(source)
    report_path = output.resolve().with_suffix(output.suffix + ".report.json")
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report
