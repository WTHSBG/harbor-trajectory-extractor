from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from harbor_trajectory_extractor.official_worker import convert_with_harbor


class OfficialBackendError(RuntimeError):
    pass


def _can_import_harbor() -> bool:
    return importlib.util.find_spec("harbor") is not None


def _python_from_harbor_script(script: Path) -> Path | None:
    try:
        first_line = script.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError, UnicodeDecodeError):
        return None
    if not first_line.startswith("#!"):
        return None
    candidate = Path(first_line[2:].strip().split()[0])
    return candidate if candidate.exists() else None


def find_harbor_python() -> Path | None:
    harbor_bin = shutil.which("harbor")
    if not harbor_bin:
        return None
    return _python_from_harbor_script(Path(harbor_bin))


def _src_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_subprocess_backend(
    *,
    python: Path,
    agent_name: str,
    agent_dir: Path,
    model_name: str | None,
    kwargs_json: str,
    instruction_path: Path | None,
) -> Path:
    cmd = [
        str(python),
        "-m",
        "harbor_trajectory_extractor.official_worker",
        "--agent",
        agent_name,
        "--agent-dir",
        str(agent_dir),
        "--kwargs-json",
        kwargs_json,
    ]
    if model_name:
        cmd += ["--model", model_name]
    if instruction_path:
        cmd += ["--instruction-path", str(instruction_path)]

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(_src_root())
        if not env.get("PYTHONPATH")
        else str(_src_root()) + os.pathsep + env["PYTHONPATH"]
    )
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if proc.returncode != 0:
        message = (proc.stdout + proc.stderr).strip()
        raise OfficialBackendError(message or f"Harbor backend exited {proc.returncode}")
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise OfficialBackendError("Harbor backend produced no output")
    path = Path(lines[-1])
    if not path.exists():
        raise OfficialBackendError(f"Harbor backend reported missing output: {path}")
    return path


def extract_with_official_backend(
    *,
    agent_name: str,
    agent_dir: Path,
    output: Path,
    model_name: str | None,
    kwargs: dict[str, Any],
    kwargs_json: str,
    instruction_path: Path | None,
) -> Path:
    agent_dir = agent_dir.resolve()

    if _can_import_harbor():
        produced = convert_with_harbor(
            agent_name=agent_name,
            agent_dir=agent_dir,
            model_name=model_name,
            kwargs=kwargs,
            instruction_path=instruction_path,
        )
        if produced is None:
            raise OfficialBackendError("Harbor backend completed but did not produce trajectory.json")
    else:
        harbor_python = find_harbor_python()
        if harbor_python is None:
            raise OfficialBackendError("Cannot import harbor and no harbor executable was found on PATH")
        produced = _run_subprocess_backend(
            python=harbor_python,
            agent_name=agent_name,
            agent_dir=agent_dir,
            model_name=model_name,
            kwargs_json=kwargs_json,
            instruction_path=instruction_path,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    if produced.resolve() != output.resolve():
        shutil.copyfile(produced, output)
    return output

