from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harbor_trajectory_extractor.agents import (
    format_agent_workflow,
    normalize_agent_name,
    supported_agent_names,
)
from harbor_trajectory_extractor.atif import summarize
from harbor_trajectory_extractor.fallback import extract_with_fallback
from harbor_trajectory_extractor.sources import (
    SourcePreparationError,
    default_output_for_source,
    prepare_source,
)
from harbor_trajectory_extractor.vendored import (
    VendoredBackendError,
    extract_with_vendored_backend,
)

HELP_EPILOG = """Workflows:
  Supported agents:
    claude-code, codex, opencode

  Agent already ran:
    htextract --agent claude-code --source ~/.claude/projects/<project>/<session>.jsonl --summary
    htextract --agent codex --source ~/.codex/sessions/<yyyy>/<mm>/<dd>/<session>.jsonl --summary
    opencode export <sessionID> > opencode-export.json
    htextract --agent opencode --source ./opencode-export.json --summary

  Agent has not run yet:
    htextract --describe-agent opencode
    # Use OpenCode interactively and export later, or capture run-mode JSONL.
    htextract --agent opencode --source ./opencode-export.json --summary

Use --describe-agent <agent> before running cc/opencode/codex to see exactly
which files are available by default and which flags you must add before a run.
"""


class UsageError(ValueError):
    """Raised when CLI arguments are syntactically valid but incomplete."""


class ExtractionError(RuntimeError):
    """Raised when every converter path fails."""


@dataclass(frozen=True)
class ExtractRequest:
    """Fully-normalized request used by the extraction path.

    By the time we construct this object, discovery-only commands such as
    --list-agents and --describe-agent have already returned, paths are absolute,
    the agent alias has been normalized, and the source has been staged for the
    converter.
    """

    agent: str
    work_dir: Path
    output: Path
    model_name: str | None
    adapter_kwargs: dict[str, Any]
    instruction_path: Path | None
    print_summary: bool
    cleanup: Any | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract Harbor ATIF trajectory.json from native agent artifacts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )

    # Discovery commands: these do not read agent logs or write trajectory files.
    parser.add_argument(
        "--list-agents",
        action="store_true",
        help="Print supported Harbor agent names and exit.",
    )
    parser.add_argument(
        "--describe-agent",
        help=(
            "Print the already-ran source path and not-yet-run capture recipe "
            "for an agent."
        ),
    )

    # Extraction inputs: these are required only when actually extracting.
    parser.add_argument(
        "--agent",
        help="Agent name. Currently supported: claude-code, codex, opencode.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        help=(
            "Native artifact from the agent run. Examples: Claude Code session "
            ".jsonl or CLAUDE_CONFIG_DIR, Codex session .jsonl or sessions/ "
            "directory, OpenCode JSON stdout file."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Output path. Defaults to trajectory.json next to the source file, "
            "or inside the source directory."
        ),
    )
    parser.add_argument(
        "--instruction-path",
        type=Path,
        help="Optional instruction file used by adapters that need the prompt.",
    )

    parser.add_argument(
        "--model",
        help="Optional model name used when the source artifact does not include one.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact trajectory summary after extraction.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def run_discovery_command(args: argparse.Namespace) -> int | None:
    """Handle commands that only explain the tool and then exit.

    There are two user situations this CLI must serve:
    - If the user already ran an agent, --describe-agent tells them which files
      can be passed directly through --source.
    - If the user has not run an agent yet, the same output tells them which
      runtime flags and tee/copy steps are needed before coming back.
    """
    if args.list_agents:
        for name in supported_agent_names():
            print(name)
        return 0

    if args.describe_agent:
        workflow = format_agent_workflow(args.describe_agent)
        if workflow is None:
            supported = ", ".join(supported_agent_names())
            print(
                f"unsupported agent: {args.describe_agent}\n"
                f"currently supported agents: {supported}",
                file=sys.stderr,
            )
            return 2
        print(workflow)
        return 0

    return None


def build_extract_request(args: argparse.Namespace) -> ExtractRequest:
    """Validate extraction arguments and convert them into a typed request."""
    if not args.agent and not args.source:
        raise UsageError(
            "No extraction command selected.\n\n"
            "If the agent already ran:\n"
            "  htextract --agent <agent> --source <session-log-or-dir> --summary\n\n"
            "If the agent has not run yet:\n"
            "  htextract --describe-agent <agent>\n\n"
            "Use --help for full examples."
        )
    if not args.agent:
        raise UsageError(
            "Missing --agent. Use --list-agents to see supported agents, "
            "or --describe-agent <agent> to see capture requirements."
        )
    if not args.source:
        raise UsageError(
            "Missing --source. Pass the native artifact from this agent run, "
            f"for example `htextract --agent {args.agent} --source <path>`. "
            f"Run "
            f"`htextract --describe-agent {args.agent}` for examples."
        )

    agent = normalize_agent_name(args.agent)
    source = args.source.resolve()
    try:
        prepared_source = prepare_source(agent, source)
    except SourcePreparationError as exc:
        raise UsageError(str(exc)) from exc
    work_dir = prepared_source.work_dir.resolve()
    default_output = default_output_for_source(source)

    output = (args.output or default_output).resolve()

    return ExtractRequest(
        agent=agent,
        work_dir=work_dir,
        output=output,
        model_name=args.model,
        adapter_kwargs={},
        instruction_path=args.instruction_path.resolve()
        if args.instruction_path
        else None,
        print_summary=args.summary,
        cleanup=prepared_source.cleanup,
    )


def run_vendored_backend(request: ExtractRequest) -> Path:
    """Run Harbor's vendored native-log-to-ATIF converter."""
    return extract_with_vendored_backend(
        agent_name=request.agent,
        agent_dir=request.work_dir,
        output=request.output,
        model_name=request.model_name,
        kwargs=request.adapter_kwargs,
        instruction_path=request.instruction_path,
    )


def run_fallback_backend(request: ExtractRequest) -> Path:
    """Reuse an already-existing ATIF trajectory.json when no converter is needed."""
    if extract_with_fallback(request.work_dir, request.output):
        return request.output
    raise ExtractionError("fallback: no existing ATIF trajectory.json found")


def extract_trajectory(request: ExtractRequest) -> Path:
    """Convert native logs or reuse existing ATIF when the source already has it."""
    errors: list[str] = []

    try:
        return run_vendored_backend(request)
    except VendoredBackendError as exc:
        errors.append(f"native converter: {exc}")

    try:
        return run_fallback_backend(request)
    except ExtractionError as exc:
        errors.append(str(exc))

    raise ExtractionError("\n".join(errors))


def print_result(output: Path, *, summary: bool) -> None:
    """Print either the output path or a compact JSON summary."""
    if summary:
        print(json.dumps(summarize(output), indent=2, ensure_ascii=False))
    else:
        print(output)


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else argv
    if not raw_argv:
        build_parser().print_help()
        return 0

    args = parse_args(raw_argv)

    discovery_exit_code = run_discovery_command(args)
    if discovery_exit_code is not None:
        return discovery_exit_code

    try:
        request = build_extract_request(args)
        output = extract_trajectory(request)
    except UsageError as exc:
        print(exc, file=sys.stderr)
        return 2
    except ExtractionError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        if "request" in locals() and request.cleanup is not None:
            request.cleanup.cleanup()

    print_result(output, summary=request.print_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
