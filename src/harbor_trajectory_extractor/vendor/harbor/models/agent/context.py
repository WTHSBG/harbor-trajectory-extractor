from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentContext(BaseModel):
    n_input_tokens: int | None = Field(default=None)
    n_cache_tokens: int | None = Field(default=None)
    n_output_tokens: int | None = Field(default=None)
    cost_usd: float | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)

    def is_empty(self) -> bool:
        return all(value is None for value in self.model_dump().values())

