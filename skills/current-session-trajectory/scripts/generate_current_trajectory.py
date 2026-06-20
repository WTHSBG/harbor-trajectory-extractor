#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


AGENT_ALIASES = {
    "cc": "claude-code",
    "claude": "claude-code",
    "claudecode": "claude-code",
    "claude_code": "claude-code",
    "claude-code": "claude-code",
    "codex": "codex",
    "opencode": "opencode",
    "open-code": "opencode",
}

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def normalize_agent(raw: str) -> str:
    agent = AGENT_ALIASES.get(raw.strip().lower())
    if not agent:
        valid = ", ".join(sorted(set(AGENT_ALIASES.values())))
        raise SystemExit(f"unsupported agent {raw!r}; choose one of: {valid}")
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


def find_opencode_source(session_hint: str | None) -> Path:
    cwd = Path.cwd()
    names = ["opencode.jsonl", "opencode.txt"]
    candidates = [cwd / name for name in names]
    candidates.extend(cwd.glob("*.opencode.jsonl"))
    candidates.extend(cwd.glob("opencode-*.jsonl"))
    return select_candidate("opencode", candidates, session_hint)


def select_candidate(agent: str, candidates: list[Path], session_hint: str | None) -> Path:
    existing = [path for path in candidates if path.is_file()]
    if session_hint:
        matches = [
            path
            for path in existing
            if session_hint in path.name or session_hint == extract_session_id(agent, path)
        ]
        selected = newest(matches)
        if selected:
            return selected
        raise SystemExit(f"could not find {agent} session matching {session_hint!r}")

    selected = newest(existing)
    if selected:
        return selected
    raise SystemExit(f"could not auto-detect a {agent} source; pass --source")


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
        for event in iter_json_lines(source):
            session_id = event.get("sessionID")
            if isinstance(session_id, str) and session_id:
                return session_id
        return source.stem

    return source.stem


def default_output(agent: str, source: Path, output_dir: Path) -> Path:
    session_id = sanitize(extract_session_id(agent, source))
    return output_dir / f"{agent}-{session_id}-trajectory.json"


def htextract_command() -> list[str]:
    root = repo_root()
    venv_htextract = root / "src" / "harbor_trajectory_extractor" / ".venv" / "bin" / "htextract"
    if venv_htextract.exists():
        return [str(venv_htextract)]

    found = shutil.which("htextract")
    if found:
        return [found]

    return [sys.executable, "-m", "harbor_trajectory_extractor.cli"]


def run_htextract(
    *,
    agent: str,
    source: Path,
    output: Path,
    instruction_path: Path | None,
    model: str | None,
    summary: bool,
) -> int:
    cmd = htextract_command() + [
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
    if summary:
        cmd.append("--summary")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root() / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    result = subprocess.run(cmd, cwd=Path.cwd(), env=env, text=True)
    return result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Harbor ATIF trajectory for the current or most recent "
            "codex, claude-code, or opencode session."
        )
    )
    parser.add_argument("--agent", required=True, help="codex, claude-code/cc, or opencode")
    parser.add_argument("--source", type=Path, help="Exact session/source file or directory")
    parser.add_argument("--session", help="Session id or filename substring to select")
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    agent = normalize_agent(args.agent)

    if args.source:
        source = args.source.expanduser().resolve()
    elif agent == "codex":
        source = find_codex_source(args.session)
    elif agent == "claude-code":
        source = find_claude_source(args.session)
    else:
        source = find_opencode_source(args.session)

    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")

    output = args.output.expanduser().resolve() if args.output else default_output(
        agent,
        source,
        args.output_dir.expanduser().resolve(),
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
        summary=args.summary,
    )


if __name__ == "__main__":
    raise SystemExit(main())
