from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harbor_trajectory_extractor.agents import normalize_agent_name
from harbor_trajectory_extractor.atif import read_json, write_json


class VendoredBackendError(RuntimeError):
    pass


@dataclass
class DummyAgentContext:
    cost_usd: float | None = None
    n_input_tokens: int | None = None
    n_output_tokens: int | None = None
    n_cache_tokens: int | None = None
    metadata: dict[str, Any] | None = None


CLASS_MAP: dict[str, tuple[str, str]] = {
    "acp": ("harbor.agents.installed.acp", "AcpAgent"),
    "antigravity-cli": ("harbor.agents.installed.antigravity_cli", "AntigravityCli"),
    "claude-code": ("harbor.agents.installed.claude_code", "ClaudeCode"),
    "cline-cli": ("harbor.agents.installed.cline", "ClineCli"),
    "codex": ("harbor.agents.installed.codex", "Codex"),
    "copilot-cli": ("harbor.agents.installed.copilot_cli", "CopilotCli"),
    "cursor-cli": ("harbor.agents.installed.cursor_cli", "CursorCli"),
    "devin": ("harbor.agents.installed.devin", "Devin"),
    "gemini-cli": ("harbor.agents.installed.gemini_cli", "GeminiCli"),
    "goose": ("harbor.agents.installed.goose", "Goose"),
    "hermes": ("harbor_trajectory_extractor.hermes", "Hermes"),
    "kimi-cli": ("harbor.agents.installed.kimi_cli", "KimiCli"),
    "kimi-code": ("harbor_trajectory_extractor.kimi_code", "KimiCode"),
    "mini-swe-agent": ("harbor.agents.installed.mini_swe_agent", "MiniSweAgent"),
    "openclaw": ("harbor.agents.installed.openclaw", "OpenClaw"),
    "opencode": ("harbor.agents.installed.opencode", "OpenCode"),
    "openhands": ("harbor.agents.installed.openhands", "OpenHands"),
    "qwen-coder": ("harbor.agents.installed.qwen_code", "QwenCode"),
    "rovodev-cli": ("harbor.agents.installed.rovodev_cli", "RovodevCli"),
    "swe-agent": ("harbor.agents.installed.swe_agent", "SweAgent"),
    "trae-agent": ("harbor.agents.installed.trae_agent", "TraeAgent"),
}


def vendor_root() -> Path:
    return Path(__file__).resolve().parent / "vendor"


def activate_vendor_namespace() -> None:
    root = str(vendor_root())
    if sys.path[0:1] != [root]:
        try:
            sys.path.remove(root)
        except ValueError:
            pass
        sys.path.insert(0, root)

    harbor_mod = sys.modules.get("harbor")
    if harbor_mod is not None:
        mod_file = getattr(harbor_mod, "__file__", "")
        if mod_file and not str(mod_file).startswith(root):
            for name in list(sys.modules):
                if name == "harbor" or name.startswith("harbor."):
                    sys.modules.pop(name, None)


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
    for attr in ("_instruction", "_rendered_instruction", "_last_instruction"):
        if hasattr(agent, attr) and not getattr(agent, attr, None):
            try:
                setattr(agent, attr, instruction)
            except Exception:
                pass


def _build_agent(
    *,
    agent_name: str,
    agent_dir: Path,
    model_name: str | None,
    kwargs: dict[str, Any],
) -> Any:
    activate_vendor_namespace()
    normalized = normalize_agent_name(agent_name)
    target = CLASS_MAP.get(normalized)
    if target is None:
        raise VendoredBackendError(
            f"No vendored Harbor converter for {agent_name!r}; "
            "this agent either emits ATIF directly or Harbor has no converter."
        )
    module_name, class_name = target
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return cls(logs_dir=agent_dir, model_name=model_name, **kwargs)


def extract_with_vendored_backend(
    *,
    agent_name: str,
    agent_dir: Path,
    output: Path,
    model_name: str | None,
    kwargs: dict[str, Any],
    instruction_path: Path | None,
) -> Path:
    agent_dir = agent_dir.resolve()

    try:
        agent = _build_agent(
            agent_name=agent_name,
            agent_dir=agent_dir,
            model_name=model_name,
            kwargs=kwargs,
        )
        _patch_instruction_fields(agent, _load_instruction(agent_dir, instruction_path))
        agent.populate_context_post_run(DummyAgentContext())
    except Exception as exc:
        raise VendoredBackendError(str(exc)) from exc

    produced = agent_dir / "trajectory.json"
    if not produced.exists():
        raise VendoredBackendError("vendored Harbor converter did not produce trajectory.json")

    write_json(output, read_json(produced))
    return output
