from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StrategyLiteral = Literal["EMA_CONVERGENCE", "EMA_SQUEEZE_BREAKOUT", "EMA_PULLBACK", "STRUCTURE_BREAKOUT"]
DirectionLiteral = Literal["LONG", "SHORT"]


class SignalItem(BaseModel):
    symbol: str
    direction: str
    strategy: str
    score: float
    entry: float
    stop_loss: float
    target1: float
    target2: float
    bandwidth: float
    conditions: list[str] = Field(default_factory=list)
    time: str


class SignalsStatsResponse(BaseModel):
    total: int
    by_strategy: dict[str, int]
    by_direction: dict[str, int]
    avg_score: float | None = None
