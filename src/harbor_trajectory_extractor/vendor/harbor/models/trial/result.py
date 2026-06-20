from __future__ import annotations

from pydantic import BaseModel


class ModelInfo(BaseModel):
    name: str
    provider: str | None = None


class AgentInfo(BaseModel):
    name: str
    version: str
    model_info: ModelInfo | None = None

