from __future__ import annotations

from typing import Any


class BaseEnvironment:
    """Stub used only so vendored converter classes can import type names."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(
            f"BaseEnvironment stub cannot execute runtime method {name!r}; "
            "harbor-trajectory-extractor only supports post-run conversion."
        )

