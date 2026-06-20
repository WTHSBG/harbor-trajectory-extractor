from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harbor_trajectory_extractor.agents import normalize_agent_name


@dataclass
class DummyAgentContext:
    cost_usd: float | None = None
    n_input_tokens: int = 0
    n_output_tokens: int = 0
    n_cache_tokens: int = 0


def _load_instruction(agent_dir: Path, instruction_path: Path | None) -> str | None:
    candidates = []
    if instruction_path is not None:
        candidates.append(instruction_path)
    candidates.extend(
        [
            agent_dir / "instruction.txt",
            agent_dir / "instruction.md",
            agent_dir.parent / "instruction.txt",
            agent_dir.parent / "instruction.md",
        ]
    )
    for path in candidates:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return None


def _patch_instruction_fields(agent: Any, instruction: str | None) -> None:
    if not instruction:
        return
    for attr in ("_instruction", "_rendered_instruction"):
        if hasattr(agent, attr) and not getattr(agent, attr, None):
            try:
                setattr(agent, attr, instruction)
            except Exception:
                pass


def convert_with_harbor(
    *,
    agent_name: str,
    agent_dir: Path,
    model_name: str | None,
    kwargs: dict[str, Any],
    instruction_path: Path | None,
) -> Path | None:
    from harbor.agents.factory import AgentFactory
    from harbor.models.agent.name import AgentName

    normalized = normalize_agent_name(agent_name)
    if normalized not in AgentName.values():
        raise ValueError(f"Unsupported Harbor agent name: {agent_name}")

    agent = AgentFactory.create_agent_from_name(
        AgentName(normalized),
        logs_dir=agent_dir,
        model_name=model_name,
        **kwargs,
    )
    _patch_instruction_fields(agent, _load_instruction(agent_dir, instruction_path))
    agent.populate_context_post_run(DummyAgentContext())

    output = agent_dir / "trajectory.json"
    return output if output.exists() else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Internal Harbor backend worker")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--agent-dir", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--kwargs-json", default="{}")
    parser.add_argument("--instruction-path", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        kwargs = json.loads(args.kwargs_json)
        if not isinstance(kwargs, dict):
            raise ValueError("--kwargs-json must decode to an object")
        output = convert_with_harbor(
            agent_name=args.agent,
            agent_dir=args.agent_dir,
            model_name=args.model,
            kwargs=kwargs,
            instruction_path=args.instruction_path,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", flush=True)
        return 1

    if output:
        print(str(output), flush=True)
        return 0
    print("ERROR: Harbor backend completed but did not produce trajectory.json", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

