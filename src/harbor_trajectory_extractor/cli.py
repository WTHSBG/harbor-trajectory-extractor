from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harbor_trajectory_extractor.agents import (
    describe_agent,
    format_agent_workflow,
    normalize_agent_name,
    supported_agent_names,
)
from harbor_trajectory_extractor.atif import summarize
from harbor_trajectory_extractor.fallback import extract_with_fallback
from harbor_trajectory_extractor.vendored import (
    VendoredBackendError,
    extract_with_vendored_backend,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    epilog = """Workflows:
  1. Agent already ran:
     htextract --describe-agent claude-code
     htextract --agent claude-code --agent-dir jobs/<job>/<trial>/agent --summary

  2. Agent has not run yet:
     htextract --describe-agent opencode
     # Run the agent with the printed capture requirements, preserving logs in <agent-dir>.
     htextract --agent opencode --agent-dir <agent-dir> --summary

Use --describe-agent <agent> before running cc/opencode/codex to see required
runtime flags and post-run copy steps.
"""
    parser = argparse.ArgumentParser(
        description="Extract Harbor ATIF trajectory.json from captured agent logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    parser.add_argument("--list-agents", action="store_true", help="Print supported Harbor agent names and exit.")
    parser.add_argument(
        "--describe-agent",
        help=(
            "Print both workflows for an agent: files needed if it already ran, "
            "and capture flags/copy steps if it has not run yet."
        ),
    )
    parser.add_argument("--agent", help="Harbor agent name, e.g. claude-code, codex, opencode.")
    parser.add_argument(
        "--agent-dir",
        type=Path,
        help="Path to the captured agent log directory, e.g. a Harbor trial agent/ directory.",
    )
    parser.add_argument("--output", type=Path, help="Output path. Defaults to <agent-dir>/trajectory.json.")
    parser.add_argument("--model", help="Optional model name passed to the vendored Harbor adapter.")
    parser.add_argument(
        "--backend",
        choices=("auto", "vendored", "fallback"),
        default="auto",
        help="auto tries vendored Harbor converter first, then existing-ATIF fallback.",
    )
    parser.add_argument(
        "--kwargs-json",
        default="{}",
        help="JSON object of extra kwargs passed to the vendored Harbor adapter, for example OpenHands trajectory_config.",
    )
    parser.add_argument("--instruction-path", type=Path, help="Optional instruction file used by adapters that need the prompt.")
    parser.add_argument("--summary", action="store_true", help="Print a compact trajectory summary after extraction.")
    return parser.parse_args(argv)


def _print_agent_description(agent: str) -> int:
    info = describe_agent(agent)
    if info is None:
        print(f"unknown agent: {agent}", file=sys.stderr)
        return 2
    workflow = format_agent_workflow(info.agent)
    if workflow is None:
        print(f"unknown agent: {agent}", file=sys.stderr)
        return 2
    print(workflow)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_agents:
        for name in supported_agent_names():
            print(name)
        return 0

    if args.describe_agent:
        return _print_agent_description(args.describe_agent)

    if not args.agent or not args.agent_dir:
        print("--agent and --agent-dir are required unless using --list-agents or --describe-agent", file=sys.stderr)
        return 2

    agent = normalize_agent_name(args.agent)
    agent_dir = args.agent_dir.resolve()
    output = (args.output or (agent_dir / "trajectory.json")).resolve()
    try:
        kwargs = json.loads(args.kwargs_json)
    except json.JSONDecodeError as exc:
        print(f"invalid --kwargs-json: {exc}", file=sys.stderr)
        return 2
    if not isinstance(kwargs, dict):
        print("--kwargs-json must be a JSON object", file=sys.stderr)
        return 2

    errors: list[str] = []

    if args.backend in {"auto", "vendored"}:
        try:
            extract_with_vendored_backend(
                agent_name=agent,
                agent_dir=agent_dir,
                output=output,
                model_name=args.model,
                kwargs=kwargs,
                instruction_path=args.instruction_path,
            )
        except VendoredBackendError as exc:
            errors.append(f"vendored backend: {exc}")
            if args.backend == "vendored":
                print(errors[-1], file=sys.stderr)
                return 1
        else:
            if args.summary:
                print(json.dumps(summarize(output), indent=2, ensure_ascii=False))
            else:
                print(output)
            return 0

    if args.backend in {"auto", "fallback"}:
        if extract_with_fallback(agent_dir, output):
            if args.summary:
                print(json.dumps(summarize(output), indent=2, ensure_ascii=False))
            else:
                print(output)
            return 0
        errors.append("fallback: no existing ATIF trajectory.json found")

    for error in errors:
        print(error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
