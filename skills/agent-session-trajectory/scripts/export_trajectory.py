#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


AGENT_ALIASES = {
    "cc": "claude-code",
    "claude": "claude-code",
    "claudecode": "claude-code",
    "claude_code": "claude-code",
    "claude-code": "claude-code",
    "codex": "codex",
    "hermes": "hermes",
    "hermes-agent": "hermes",
    "hermes_agent": "hermes",
    "hermers": "hermes",
    "kimi": "kimi-code",
    "kimi-code": "kimi-code",
    "kimi_code": "kimi-code",
    "kimicode": "kimi-code",
    "opencode": "opencode",
    "open-code": "opencode",
}

AUTO_DISCOVER_AGENTS = {"codex", "claude-code", "hermes", "kimi-code", "opencode"}
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

HELP_EPILOG = """OpenCode:
  For normal interactive OpenCode usage, pass the session id and this script
  will run `opencode export <sessionID>` automatically:

    opencode session list
    agent-session-trajectory --agent opencode --session <sessionID> --summary

  You can also export manually and pass the JSON file:

    opencode export <sessionID> > opencode-export.json
    agent-session-trajectory --agent opencode --source ./opencode-export.json --summary

  For one-shot run-mode usage, capture JSONL directly:

    opencode run --format=json --thinking -- "$INSTRUCTION" 2>&1 | tee opencode.jsonl
    agent-session-trajectory --agent opencode --source ./opencode.jsonl --summary

Kimi Code:
  Kimi Code saves every session under ~/.kimi-code/sessions. Convert the
  newest one automatically, or pass an exact session directory or wire file:

    agent-session-trajectory --agent kimi-code --summary
    agent-session-trajectory --agent kimi-code --session <sessionID> --summary
    agent-session-trajectory --agent kimi-code --source ~/.kimi-code/sessions/<wd_dir>/session_<uuid>/agents/main/wire.jsonl --summary

Hermes:
  Hermes stores sessions in $HERMES_HOME/state.db (normally
  ~/.hermes/state.db). Convert the newest session or select one by id:

    agent-session-trajectory --agent hermes --summary
    agent-session-trajectory --agent hermes --session <sessionID> --summary
    agent-session-trajectory --agent hermes --source ~/.hermes/state.db --session <sessionID> --summary
"""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def htextract_base_command() -> list[str]:
    configured = os.environ.get("HTEXTRACT")
    if configured:
        return shlex.split(configured)

    root = repo_root()
    for candidate in [
        root / ".venv" / "bin" / "htextract",
        root / "src" / "harbor_trajectory_extractor" / ".venv" / "bin" / "htextract",
    ]:
        if candidate.exists():
            return [str(candidate)]

    found = shutil.which("htextract")
    if found:
        return [found]

    return [sys.executable, "-m", "harbor_trajectory_extractor.cli"]


def htextract_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root() / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env


def run_info_command(args: list[str]) -> int:
    return subprocess.run(
        htextract_base_command() + args,
        cwd=Path.cwd(),
        env=htextract_env(),
        text=True,
    ).returncode


def supported_agents() -> set[str]:
    result = subprocess.run(
        htextract_base_command() + ["--list-agents"],
        cwd=Path.cwd(),
        env=htextract_env(),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return set(AUTO_DISCOVER_AGENTS)
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def normalize_agent(raw: str) -> str:
    requested = raw.strip().lower()
    agent = AGENT_ALIASES.get(requested, requested)
    known = supported_agents()
    if agent not in known:
        valid = ", ".join(sorted(known))
        raise SystemExit(
            f"cannot export: unsupported agent {raw!r}.\n"
            f"Supported agents are:\n{valid}\n"
            "Run this script with --list-agents to print the list again."
        )
    return agent


def iter_json_lines(path: Path, *, limit: int = 500) -> Iterable[dict]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield value
    except OSError:
        return


def read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def sanitize(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    cleaned = cleaned.strip(".-")
    return cleaned or "unknown-session"


def newest(paths: Iterable[Path]) -> Path | None:
    candidates = [path for path in paths if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def find_codex_source(session_hint: str | None) -> Path:
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
    candidates = sorted(root.rglob("*.jsonl")) if root.exists() else []
    return select_candidate("codex", candidates, session_hint)


def find_claude_source(session_hint: str | None) -> Path:
    roots: list[Path] = []
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        roots.append(Path(config_dir))
    roots.append(Path.home() / ".claude" / "projects")

    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            candidates.extend(root.rglob("*.jsonl"))
    return select_candidate("claude-code", candidates, session_hint)


def find_kimi_code_source(session_hint: str | None) -> Path:
    root = (
        Path(os.environ.get("KIMI_CODE_HOME", Path.home() / ".kimi-code")) / "sessions"
    )
    candidates = (
        sorted(root.glob("*/session_*/agents/main/wire.jsonl")) if root.exists() else []
    )
    return select_candidate("kimi-code", candidates, session_hint)


def find_hermes_source(session_hint: str | None) -> Path:
    root = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    state_db = root / "state.db"
    if state_db.is_file():
        # htextract resolves the exact/prefix session id inside the database.
        return state_db

    cwd = Path.cwd()
    candidates = [cwd / "hermes-session.jsonl"]
    candidates.extend(cwd.glob("hermes-session*.jsonl"))
    candidates.extend(cwd.glob("*hermes*session*.jsonl"))
    # The selector may refer to any row inside a multi-session export, so do
    # not pre-filter candidate filenames by the first JSONL record. htextract
    # performs the exact/prefix selection after loading the export.
    return select_candidate("hermes", candidates, None)


def find_opencode_source(session_hint: str | None) -> Path:
    if session_hint:
        return export_opencode_session(session_hint)

    cwd = Path.cwd()
    names = ["opencode-export.json", "opencode.jsonl", "opencode.txt"]
    candidates = [cwd / name for name in names]
    candidates.extend(cwd.glob("opencode-export*.json"))
    candidates.extend(cwd.glob("*opencode-export*.json"))
    candidates.extend(cwd.glob("opencode-*.json"))
    candidates.extend(cwd.glob("*.opencode.jsonl"))
    candidates.extend(cwd.glob("opencode-*.jsonl"))
    return select_candidate("opencode", candidates, session_hint)


def export_opencode_session(session_id: str) -> Path:
    opencode = shutil.which("opencode")
    if not opencode:
        raise SystemExit(
            "cannot export: `opencode` was not found on PATH.\n"
            "Install OpenCode or pass --source <opencode-export.json>."
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="agent-session-trajectory-opencode-"))
    output = tmp_dir / f"opencode-export-{sanitize(session_id)}.json"
    result = subprocess.run(
        [opencode, "export", session_id],
        cwd=Path.cwd(),
        env=os.environ.copy(),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise SystemExit(
            f"cannot export: `opencode export {session_id}` failed.\n"
            f"{stderr or result.stdout.strip() or 'No error output.'}\n"
            "Run `opencode session list` to verify the session id, or pass "
            "--source <opencode-export.json>."
        )

    output.write_text(result.stdout, encoding="utf-8")
    return output


def select_candidate(agent: str, candidates: list[Path], session_hint: str | None) -> Path:
    existing = [path for path in candidates if path.is_file()]
    if session_hint:
        matches = [
            path
            for path in existing
            if session_hint in path.name
            or session_hint in str(path)
            or session_hint == extract_session_id(agent, path)
        ]
        selected = newest(matches)
        if selected:
            return selected
        raise SystemExit(
            f"cannot export: could not find {agent} session matching {session_hint!r}.\n"
            f"Pass --source <path> for the exact session, or run:\n"
            f"  {Path(__file__).name} --describe-agent {agent}"
        )

    selected = newest(existing)
    if selected:
        return selected
    if agent == "opencode":
        raise SystemExit(
            "cannot export: could not find an OpenCode export/capture in the current directory.\n"
            "For an interactive session, run:\n"
            "  opencode session list\n"
            "  opencode export <sessionID> > opencode-export.json\n"
            "  agent-session-trajectory --agent opencode --source ./opencode-export.json --summary\n"
            "For a one-shot run, capture JSONL with:\n"
            '  opencode run --format=json --thinking -- "$INSTRUCTION" 2>&1 | tee opencode.jsonl'
        )
    raise SystemExit(
        f"cannot export: could not auto-detect a {agent} source.\n"
        f"Pass --source <path> for the exact session, or run:\n"
        f"  {Path(__file__).name} --describe-agent {agent}"
    )


def extract_session_id(agent: str, source: Path) -> str:
    if agent == "codex":
        for event in iter_json_lines(source):
            if event.get("type") == "session_meta":
                payload = event.get("payload")
                if isinstance(payload, dict) and isinstance(payload.get("id"), str):
                    return payload["id"]
        match = UUID_RE.search(source.name)
        return match.group(0) if match else source.stem

    if agent == "claude-code":
        for event in iter_json_lines(source):
            session_id = event.get("sessionId")
            if isinstance(session_id, str) and session_id:
                return session_id
        return source.stem

    if agent == "opencode":
        exported = read_json(source)
        if isinstance(exported, dict):
            info = exported.get("info")
            if isinstance(info, dict) and isinstance(info.get("id"), str):
                return info["id"]
        for event in iter_json_lines(source):
            session_id = event.get("sessionID")
            if isinstance(session_id, str) and session_id:
                return session_id
        return source.stem

    if agent == "kimi-code":
        if source.parent.name == "main" and source.parent.parent.name == "agents":
            state = read_json(source.parents[2] / "state.json")
            if isinstance(state, dict) and isinstance(state.get("id"), str):
                return state["id"].removeprefix("session_")
        for part in source.parts:
            if part.startswith("session_"):
                return part.removeprefix("session_")
        match = UUID_RE.search(str(source))
        return match.group(0) if match else source.stem

    if agent == "hermes":
        if source.name == "state.db":
            return source.stem
        for row in iter_json_lines(source):
            session_id = row.get("id") or row.get("session_id")
            if isinstance(session_id, str) and session_id:
                return session_id
        return source.stem

    return source.stem


def extract_hermes_db_session_id(
    source: Path, session_hint: str | None
) -> str | None:
    """Resolve the selected Hermes id for a descriptive default filename."""
    if source.name != "state.db":
        return None
    try:
        conn = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        try:
            if session_hint:
                rows = conn.execute(
                    "SELECT id FROM sessions "
                    "WHERE id = ? OR substr(id, 1, length(?)) = ? "
                    "ORDER BY started_at DESC LIMIT 2",
                    (session_hint, session_hint, session_hint),
                ).fetchall()
                exact = [str(row[0]) for row in rows if row[0] == session_hint]
                if exact:
                    return exact[0]
                if len(rows) == 1:
                    return str(rows[0][0])
                return None
            row = conn.execute(
                "SELECT id FROM sessions WHERE COALESCE(source, '') != 'tool' "
                "ORDER BY COALESCE(ended_at, started_at) DESC, started_at DESC LIMIT 1"
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            conn.close()
    except (OSError, sqlite3.DatabaseError):
        return None


def default_output(
    agent: str,
    source: Path,
    output_dir: Path,
    session_hint: str | None = None,
) -> Path:
    resolved_hermes_id = (
        extract_hermes_db_session_id(source, session_hint)
        if agent == "hermes"
        else None
    )
    session_id = sanitize(
        resolved_hermes_id or session_hint or extract_session_id(agent, source)
    )
    return output_dir / f"{agent}-{session_id}-trajectory.json"


def run_htextract(
    *,
    agent: str,
    source: Path,
    output: Path,
    instruction_path: Path | None,
    model: str | None,
    session: str | None,
    summary: bool,
) -> int:
    cmd = htextract_base_command() + [
        "--agent",
        agent,
        "--source",
        str(source),
        "--output",
        str(output),
    ]
    if instruction_path:
        cmd += ["--instruction-path", str(instruction_path)]
    if model:
        cmd += ["--model", model]
    if session and agent == "hermes":
        cmd += ["--session", session]
    if summary:
        cmd.append("--summary")

    result = subprocess.run(cmd, cwd=Path.cwd(), env=htextract_env(), text=True)
    if result.returncode != 0:
        print(
            "\nCannot export trajectory with the selected inputs.\n"
            f"agent: {agent}\n"
            f"source: {source}\n"
            "Next steps:\n"
            f"  1. Verify the source exists and is the native artifact for {agent}.\n"
            f"  2. Run: {Path(__file__).name} --describe-agent {agent}\n"
            "  3. For OpenCode interactive sessions, export with `opencode export <sessionID>`; for run-mode, capture JSONL.",
            file=sys.stderr,
        )
    return result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Harbor ATIF trajectory for an agent session/source artifact. "
            "Currently supported agents: codex, claude-code, hermes, kimi-code, opencode. "
            "Without --source, auto-detection is only available for codex, "
            "claude-code, hermes, kimi-code, and OpenCode session ids or local captures."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )
    parser.add_argument("--agent", help="Agent name. Currently supported: codex, claude-code/cc, hermes, kimi-code/kimi, opencode")
    parser.add_argument("--source", type=Path, help="Exact session/source file or directory")
    parser.add_argument(
        "--session",
        help=(
            "Session id or filename substring to select. For Hermes this "
            "selects a row in state.db/JSONL. For OpenCode it may be a saved "
            "session id; the script runs `opencode export <sessionID>`."
        ),
    )
    parser.add_argument("--output", type=Path, help="Exact output path")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory for the default <agent>-<session>-trajectory.json output",
    )
    parser.add_argument("--instruction-path", type=Path, help="Instruction file for opencode streams that omit the prompt")
    parser.add_argument("--model", help="Model name when the source artifact omits it")
    parser.add_argument("--summary", action="store_true", help="Print htextract summary")
    parser.add_argument("--list-agents", action="store_true", help="List currently supported agents")
    parser.add_argument("--describe-agent", help="Describe the source/capture requirements for one agent")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.list_agents:
        return run_info_command(["--list-agents"])

    if args.describe_agent:
        return run_info_command(["--describe-agent", normalize_agent(args.describe_agent)])

    if not args.agent:
        raise SystemExit("cannot export: --agent is required unless using --list-agents or --describe-agent")

    agent = normalize_agent(args.agent)

    if args.source:
        source = args.source.expanduser().resolve()
    elif agent == "codex":
        source = find_codex_source(args.session)
    elif agent == "claude-code":
        source = find_claude_source(args.session)
    elif agent == "kimi-code":
        source = find_kimi_code_source(args.session)
    elif agent == "hermes":
        source = find_hermes_source(args.session)
    elif agent == "opencode":
        source = find_opencode_source(args.session)
    else:
        raise SystemExit(
            f"cannot export: --source is required for {agent}.\n"
            "Only codex, claude-code, hermes, kimi-code, and limited opencode captures support auto-detection.\n"
            f"Run: {Path(__file__).name} --describe-agent {agent}"
        )

    if not source.exists():
        raise SystemExit(
            f"cannot export: source does not exist: {source}\n"
            f"Run: {Path(__file__).name} --describe-agent {agent}\n"
            "Then pass --source <path> for the exact session/source artifact."
        )

    output = args.output.expanduser().resolve() if args.output else default_output(
        agent,
        source,
        args.output_dir.expanduser().resolve(),
        args.session,
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"agent: {agent}")
    print(f"source: {source}")
    print(f"output: {output}")

    return run_htextract(
        agent=agent,
        source=source,
        output=output,
        instruction_path=args.instruction_path.expanduser().resolve()
        if args.instruction_path
        else None,
        model=args.model,
        session=args.session,
        summary=args.summary,
    )


if __name__ == "__main__":
    raise SystemExit(main())
