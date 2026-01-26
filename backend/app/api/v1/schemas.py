from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SimulationRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class OptimizationRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: str
    type: Literal["simulate", "optimize"]
    status: Literal["queued", "running", "completed", "failed"]
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
