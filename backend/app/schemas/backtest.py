from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    use_all: bool = False
    max_symbols: int = Field(30, ge=1, le=500)


class BacktestTriggerResponse(BaseModel):
    status: str
    params: dict[str, Any]


class BacktestStatusResponse(BaseModel):
    running: bool
    has_result: bool
    error: str | None = None


class BacktestResultResponse(BaseModel):
    running: bool
    result: dict[str, Any] | None = None
    error: str | None = None
