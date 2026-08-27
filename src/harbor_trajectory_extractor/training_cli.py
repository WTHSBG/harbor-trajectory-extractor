from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harbor_trajectory_extractor.agents import normalize_agent_name
from harbor_trajectory_extractor.training import (
    SUPPORTED_LAYOUTS,
    detect_layout,
    export_training_jsonl,
    read_system_prompt,
)
from harbor_trajectory_extractor.training_agents import (
    SUPPORTED_TRAINING_AGENTS,
    export_agent_training_jsonl,
)
from harbor_trajectory_extractor.training_claude import (
    export_claude_native_training_jsonl,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build tool-aware training JSONL from Claude Code, Hermes, Kimi Code, "
            "or OpenCode sessions. Claude Code CyberGym run directories also support "
            "native main/subagent discovery and compact-boundary splitting."
        )
    )
    parser.add_argument(
        "--agent",
        help=(
            "Native session agent: claude-code, hermes, kimi-code, or opencode. "
            "Omit for the legacy Claude Code CyberGym directory workflow."
        ),
    )
    parser.add_argument("--source", type=Path, required=True, help="Native session, task, or run path")
    parser.add_argument("--output", type=Path, required=True, help="Destination .jsonl file")
    parser.add_argument(
        "--layout",
        choices=sorted(SUPPORTED_LAYOUTS),
        default="auto",
        help=(
            "Input layout: auto, baiyansong (tasks/), hanxueming (node/worker), "
            "or rujia (worker_*/user and worker_*/v8)"
        ),
    )
    parser.add_argument(
        "--system-prompt",
        help="Explicitly use one plaintext prompt for every agent role",
    )
    parser.add_argument("--system-prompt-file", type=Path)
    parser.add_argument(
        "--main-system-prompt-file",
        type=Path,
        help="Optional override: plaintext or JSON sample containing the main-agent system message",
    )
    parser.add_argument(
        "--subagent-system-prompt-file",
        type=Path,
        help="Optional override for the Explore system message",
    )
    parser.add_argument(
        "--success-only",
        action="store_true",
        help="Only export tasks passing the selected layout's success check",
    )
    parser.add_argument("--include-incomplete", action="store_true")
    parser.add_argument(
        "--include-nonterminal-missing-tool-results",
        action="store_true",
        help=(
            "Keep structurally inconsistent samples where a missing tool result is "
            "followed by later assistant turns. Disabled by default."
        ),
    )
    parser.add_argument("--drop-observer", action="store_true")
    parser.add_argument(
        "--include-runtime-state",
        action="store_true",
        help=(
            "Append reconstructed Hook runtime state to system messages. Disabled "
            "by default because it is absent from the captured prompt samples."
        ),
    )
    parser.add_argument(
        "--max-estimated-tokens",
        type=int,
        help=(
            "Skip segments above this conservative character-based estimate. "
            "No message or tool round is truncated."
        ),
    )
    parser.add_argument("--model", help="Model override when the native artifact omits it")
    parser.add_argument(
        "--session",
        help="Hermes session id or unique prefix when the source contains multiple sessions",
    )
    parser.add_argument(
        "--instruction-path",
        type=Path,
        help="Instruction file for native adapters whose capture omits the user prompt",
    )
    return parser


def _is_cybergym_source(source: Path) -> bool:
    try:
        detect_layout(source)
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    system_prompt = args.system_prompt
    if args.system_prompt_file:
        system_prompt = read_system_prompt(args.system_prompt_file)
    try:
        agent = normalize_agent_name(args.agent) if args.agent else None
        use_cybergym = (
            agent in {None, "claude-code"}
            and (args.layout != "auto" or _is_cybergym_source(args.source))
        )
        if use_cybergym:
            report = export_training_jsonl(
                source=args.source,
                output=args.output,
                system_prompt=system_prompt,
                main_system_prompt_file=args.main_system_prompt_file,
                subagent_system_prompt_file=args.subagent_system_prompt_file,
                layout=args.layout,
                success_only=args.success_only,
                include_incomplete=args.include_incomplete,
                include_nonterminal_missing_tool_results=(
                    args.include_nonterminal_missing_tool_results
                ),
                include_runtime_state=args.include_runtime_state,
                drop_observer=args.drop_observer,
                max_estimated_tokens=args.max_estimated_tokens,
            )
        elif agent == "claude-code":
            if args.success_only:
                raise ValueError(
                    "--success-only requires a Claude Code CyberGym run layout"
                )
            report = export_claude_native_training_jsonl(
                source=args.source,
                output=args.output,
                system_prompt=system_prompt,
                main_system_prompt_file=args.main_system_prompt_file,
                subagent_system_prompt_file=args.subagent_system_prompt_file,
                include_incomplete=args.include_incomplete,
                include_nonterminal_missing_tool_results=(
                    args.include_nonterminal_missing_tool_results
                ),
                include_runtime_state=args.include_runtime_state,
                drop_observer=args.drop_observer,
                max_estimated_tokens=args.max_estimated_tokens,
            )
        else:
            if agent is None:
                supported = ", ".join(SUPPORTED_TRAINING_AGENTS)
                raise ValueError(
                    "--agent is required for a native session source; supported: "
                    + supported
                )
            if args.success_only:
                raise ValueError(
                    "--success-only applies to Claude Code CyberGym run layouts only"
                )
            if args.include_runtime_state or args.drop_observer:
                raise ValueError(
                    "--include-runtime-state and --drop-observer apply to Claude Code "
                    "CyberGym run layouts only"
                )
            report = export_agent_training_jsonl(
                agent=agent,
                source=args.source,
                output=args.output,
                system_prompt=system_prompt,
                main_system_prompt_file=args.main_system_prompt_file,
                subagent_system_prompt_file=args.subagent_system_prompt_file,
                model_name=args.model,
                session_id=args.session,
                instruction_path=args.instruction_path,
                include_incomplete=args.include_incomplete,
                include_nonterminal_missing_tool_results=(
                    args.include_nonterminal_missing_tool_results
                ),
                max_estimated_tokens=args.max_estimated_tokens,
            )
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
