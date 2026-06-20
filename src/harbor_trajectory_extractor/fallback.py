from __future__ import annotations

from pathlib import Path

from harbor_trajectory_extractor.atif import copy_existing_atif


def extract_with_fallback(agent_dir: Path, output: Path) -> bool:
    """Fallback extractor for already-ATIF trajectories.

    Most full native-log conversions intentionally live in Harbor's official
    adapter backend. This fallback keeps the standalone CLI useful for agents
    that already wrote ATIF, or for directories where Harbor previously wrote
    trajectory.json.
    """
    candidates = [
        agent_dir / "trajectory.json",
        *sorted(agent_dir.glob("trajectory.cont-*.json")),
    ]
    for candidate in candidates:
        if copy_existing_atif(candidate, output):
            return True
    return False

