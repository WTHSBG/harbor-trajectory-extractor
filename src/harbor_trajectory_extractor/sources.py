from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from harbor_trajectory_extractor.agents import (
    describe_agent,
    normalize_agent_name,
    supported_agent_names,
)


class SourcePreparationError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedSource:
    work_dir: Path
    cleanup: tempfile.TemporaryDirectory[str] | None = None


def default_output_for_source(source: Path) -> Path:
    """Return the default trajectory path for a direct native source."""
    return (source.parent if source.is_file() else source) / "trajectory.json"


def prepare_source(agent: str, source: Path) -> PreparedSource:
    """Stage a native agent artifact into the converter work layout.

    Harbor's installed-agent converters expect a small directory of files rather
    than a single CLI argument. Users should not have to care about that shape,
    so this function creates a temporary work directory around the native input.
    """
    source = source.resolve()
    if not source.exists():
        raise SourcePreparationError(f"--source does not exist: {source}")

    normalized = normalize_agent_name(agent)
    if normalized not in supported_agent_names():
        supported = ", ".join(supported_agent_names())
        raise SourcePreparationError(
            f"unsupported agent: {agent}. Currently supported agents: {supported}."
        )
    if normalized == "claude-code":
        return _prepare_claude_code_source(source)
    if normalized == "opencode":
        return _prepare_opencode_source(source)
    if normalized == "codex":
        return _prepare_codex_source(source)
    if normalized == "hermes":
        return _prepare_hermes_source(source)
    if normalized == "kimi-code":
        return _prepare_kimi_code_source(source)
    return _prepare_generic_source(normalized, source)


def _new_work_dir() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    cleanup = tempfile.TemporaryDirectory(prefix="htextract-")
    work_dir = Path(cleanup.name) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    return cleanup, work_dir


def _link_or_copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source)
    except OSError:
        shutil.copy2(source, target)


def _link_or_copy_dir(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        shutil.copytree(source, target, dirs_exist_ok=True)


def _jsonl_files_under(source: Path) -> list[Path]:
    if source.is_file():
        return [source] if source.suffix == ".jsonl" else []
    return sorted(path for path in source.rglob("*.jsonl") if path.is_file())


def _stage_files(files: list[Path], target_dir: Path) -> None:
    for file_path in files:
        _link_or_copy_file(file_path, target_dir / file_path.name)


def _prepare_claude_code_source(source: Path) -> PreparedSource:
    """Accept a Claude Code session JSONL file, session dir, or CLAUDE_CONFIG_DIR."""
    if source.is_dir() and (source / "sessions" / "projects").is_dir():
        return PreparedSource(work_dir=source)

    cleanup, work_dir = _new_work_dir()

    if source.is_dir() and (source / "projects").is_dir():
        _link_or_copy_dir(source, work_dir / "sessions")
        _stage_optional_sibling(source, work_dir, "claude-code.txt")
        return PreparedSource(work_dir=work_dir, cleanup=cleanup)

    files = _jsonl_files_under(source)
    if not files:
        cleanup.cleanup()
        raise SourcePreparationError(
            "Claude Code --source must be a session .jsonl file, a directory "
            "containing one session's .jsonl files, or CLAUDE_CONFIG_DIR."
        )

    parent_dirs = {file_path.parent for file_path in files}
    if len(parent_dirs) != 1:
        cleanup.cleanup()
        raise SourcePreparationError(
            "Claude Code --source found JSONL files in multiple directories. "
            "Pass the exact session .jsonl file or one session directory."
        )

    _stage_files(files, work_dir / "sessions" / "projects" / "imported")
    optional_root = source.parent if source.is_file() else source
    _stage_optional_sibling(optional_root, work_dir, "claude-code.txt")
    return PreparedSource(work_dir=work_dir, cleanup=cleanup)


def _prepare_opencode_source(source: Path) -> PreparedSource:
    """Accept opencode export JSON, run JSONL, or a directory containing opencode.txt."""
    if source.is_dir():
        if (source / "opencode.txt").is_file():
            return PreparedSource(work_dir=source)
        raise SourcePreparationError(
            "OpenCode --source must be `opencode export <sessionID>` JSON, "
            "`opencode run --format=json` JSONL, or a directory containing "
            "opencode.txt."
        )

    cleanup, work_dir = _new_work_dir()
    _link_or_copy_file(source, work_dir / "opencode.txt")
    return PreparedSource(work_dir=work_dir, cleanup=cleanup)


def _prepare_codex_source(source: Path) -> PreparedSource:
    """Accept a Codex session JSONL file, session dir, or sessions root."""
    if source.is_dir() and (source / "sessions").is_dir():
        return PreparedSource(work_dir=source)

    cleanup, work_dir = _new_work_dir()

    if source.is_file():
        if source.suffix != ".jsonl":
            cleanup.cleanup()
            raise SourcePreparationError("Codex --source file must be a .jsonl session file.")
        _link_or_copy_file(source, work_dir / "sessions" / "imported" / source.name)
        return PreparedSource(work_dir=work_dir, cleanup=cleanup)

    direct_jsonl = sorted(path for path in source.glob("*.jsonl") if path.is_file())
    if direct_jsonl:
        _stage_files(direct_jsonl, work_dir / "sessions" / "imported")
        return PreparedSource(work_dir=work_dir, cleanup=cleanup)

    if any(path.is_file() for path in source.rglob("*.jsonl")):
        _link_or_copy_dir(source, work_dir / "sessions")
        return PreparedSource(work_dir=work_dir, cleanup=cleanup)

    cleanup.cleanup()
    raise SourcePreparationError(
        "Codex --source must be a session .jsonl file, a session directory, "
        "or a CODEX_HOME/sessions directory."
    )


def _prepare_kimi_code_source(source: Path) -> PreparedSource:
    """Accept a Kimi Code wire.jsonl, session dir, agents/ or main/ dir, or a
    directory containing exactly one session (e.g. a wd_* directory)."""
    if source.is_file():
        return _prepare_kimi_code_wire_file(source)

    if (source / "agents" / "main" / "wire.jsonl").is_file():
        # Full session directory: usable as-is.
        return PreparedSource(work_dir=source)

    cleanup, work_dir = _new_work_dir()

    if (source / "main" / "wire.jsonl").is_file():
        # The session's agents/ directory.
        _link_or_copy_dir(source, work_dir / "agents")
        _stage_optional_sibling(source.parent, work_dir, "state.json")
        return PreparedSource(work_dir=work_dir, cleanup=cleanup)

    if (source / "wire.jsonl").is_file() and not any(source.glob("session_*")):
        # An agent main/ directory holding the wire file.
        _link_or_copy_dir(source, work_dir / "agents" / "main")
        _stage_optional_sibling(source.parent.parent, work_dir, "state.json")
        return PreparedSource(work_dir=work_dir, cleanup=cleanup)

    session_dirs = sorted(
        {
            path.parents[2]
            for path in source.rglob("wire.jsonl")
            if path.parent.name == "main" and path.parent.parent.name == "agents"
        }
    )
    if len(session_dirs) == 1:
        _link_or_copy_dir(session_dirs[0], work_dir / "session")
        return PreparedSource(work_dir=work_dir / "session", cleanup=cleanup)

    cleanup.cleanup()
    if session_dirs:
        raise SourcePreparationError(
            "Kimi Code --source directory contains multiple sessions. Pass the "
            "exact session_<uuid> directory or its agents/main/wire.jsonl file."
        )
    raise SourcePreparationError(
        "Kimi Code --source must be a session_<uuid> directory, an "
        "agents/main/wire.jsonl file, or a wd_* directory containing one session."
    )


def _prepare_hermes_source(source: Path) -> PreparedSource:
    """Accept a Hermes export, state.db, HERMES_HOME, or prepared directory."""
    if source.is_dir():
        if (source / "hermes-session.jsonl").is_file() or (source / "state.db").is_file():
            return PreparedSource(work_dir=source)
        exports = sorted(path for path in source.glob("*.jsonl") if path.is_file())
        if len(exports) == 1:
            cleanup, work_dir = _new_work_dir()
            _link_or_copy_file(exports[0], work_dir / "hermes-session.jsonl")
            return PreparedSource(work_dir=work_dir, cleanup=cleanup)
        if len(exports) > 1:
            raise SourcePreparationError(
                "Hermes --source directory contains multiple JSONL files. Pass the "
                "exact session export or a directory containing hermes-session.jsonl."
            )
        raise SourcePreparationError(
            "Hermes --source directory must be HERMES_HOME containing state.db, "
            "or contain one session export JSONL."
        )

    cleanup, work_dir = _new_work_dir()
    if source.name == "state.db" or source.suffix == ".db":
        _link_or_copy_file(source, work_dir / "state.db")
        # A live Hermes database normally uses WAL mode. Stage its sidecars as
        # well so committed messages that have not checkpointed into state.db
        # are visible through the temporary converter layout.
        for suffix in ("-wal", "-shm"):
            sidecar = source.with_name(source.name + suffix)
            if sidecar.is_file():
                _link_or_copy_file(sidecar, work_dir / f"state.db{suffix}")
    elif source.suffix.lower() in {".json", ".jsonl"}:
        _link_or_copy_file(source, work_dir / "hermes-session.jsonl")
    else:
        cleanup.cleanup()
        raise SourcePreparationError(
            "Hermes --source file must be state.db or a JSON/JSONL session export."
        )
    return PreparedSource(work_dir=work_dir, cleanup=cleanup)


def _prepare_kimi_code_wire_file(source: Path) -> PreparedSource:
    cleanup, work_dir = _new_work_dir()
    if source.parent.name == "main" and source.parent.parent.name == "agents":
        # Preserve the session_<uuid> directory name so the session id can be
        # recovered from the staged path even without a state.json.
        session_dir = source.parents[2]
        session_name = session_dir.name or "imported"
        staged = work_dir / session_name
        _link_or_copy_file(source, staged / "agents" / "main" / source.name)
        state = session_dir / "state.json"
        if state.is_file():
            _link_or_copy_file(state, staged / "state.json")
        return PreparedSource(work_dir=staged, cleanup=cleanup)
    _link_or_copy_file(source, work_dir / "agents" / "main" / "wire.jsonl")
    candidate = source.with_name("state.json")
    if candidate.is_file():
        _link_or_copy_file(candidate, work_dir / "state.json")
    return PreparedSource(work_dir=work_dir, cleanup=cleanup)


def _prepare_generic_source(agent: str, source: Path) -> PreparedSource:
    if source.is_dir():
        return PreparedSource(work_dir=source)

    info = describe_agent(agent)
    simple_patterns = []
    if info is not None:
        simple_patterns = [
            pattern
            for pattern in info.required_files
            if "/" not in pattern and "*" not in pattern and "?" not in pattern
        ]

    if len(simple_patterns) == 1:
        cleanup, work_dir = _new_work_dir()
        _link_or_copy_file(source, work_dir / simple_patterns[0])
        return PreparedSource(work_dir=work_dir, cleanup=cleanup)

    raise SourcePreparationError(
        f"{agent} --source supports directories by default, but this agent "
        "does not have a single native file name this tool can infer. Pass a "
        "directory containing the required native files."
    )


def _stage_optional_sibling(source_dir: Path, work_dir: Path, filename: str) -> None:
    candidate = source_dir / filename
    if candidate.is_file():
        _link_or_copy_file(candidate, work_dir / filename)
