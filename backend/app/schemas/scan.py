from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class BtcRegimeResponse(BaseModel):
    is_bull: bool
    label: str
    btc_ema15: float | None = None
    btc_ema60: float | None = None
    checked_at: str


class ScanSignalItem(BaseModel):
    symbol: str
    direction: str
    strategy: str
    score: float
    entry: float
    stop_loss: float
    target1: float
    target2: float
    bandwidth: float
    conditions: list[str]
    time: str


class ScanResult(BaseModel):
    found: int
    opened: int
    signals: list[ScanSignalItem]
    btc_regime_bull: bool
    btc_ema15: float | None = None
    btc_ema60: float | None = None
    scanned_at: str


class ScanStatusResponse(BaseModel):
    running: bool
    result: ScanResult | None = None
    error: str | None = None


class ScanTriggerResponse(BaseModel):
    status: str
