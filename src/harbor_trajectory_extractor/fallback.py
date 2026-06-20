from __future__ import annotations

from pathlib import Path

from harbor_trajectory_extractor.atif import copy_existing_atif


def extract_with_fallback(work_dir: Path, output: Path) -> bool:
    """Fallback extractor for already-ATIF trajectories.

    Most native-log conversions live in the vendored Harbor adapter code. This
    fallback keeps the CLI useful for agents that already wrote ATIF.
    """
    candidates = [
        work_dir / "trajectory.json",
        *sorted(work_dir.glob("trajectory.cont-*.json")),
    ]
    for candidate in candidates:
        if copy_existing_atif(candidate, output):
            return True
    return False
