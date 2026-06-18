from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PositionItem(BaseModel):
    symbol: str
    strategy: str
    direction: str
    entry: float
    cur_price: float | None = None
    upnl: float | None = None
    upnl_pct: float | None = None
    stop_loss: float
    target1: float
    target2: float
    contracts: float
    notional: float
    risk_amt: float
    score: float
    open_time: str
    duration: str
    tp1_hit: bool
    progress_r: float | None = None


class TradeItem(BaseModel):
    symbol: str
    direction: str
    strategy: str | None = None
    entry_price: float
    exit_price: float
    contracts: float
    pnl: float
    pnl_pct: float | None = None
    open_ms: int
    close_ms: int
    open_time: str
    close_time: str
    exit_reason: str | None = None


class AccountStats(BaseModel):
    balance: float
    total_pnl: float
    win_rate: float | None = None
    total_trades: int
    total_upnl: float
    total_notional: float


class EquityCurve(BaseModel):
    labels: list[str]
    data: list[float]


class AccountResponse(BaseModel):
    stats: dict[str, Any]
    positions: list[PositionItem]
    trades: list[dict[str, Any]]
    equity_curve: EquityCurve


class ResetResponse(BaseModel):
    status: str
    initial_balance: float
    reset_at: str


class EquityRecord(BaseModel):
    ts: str | None = None
    balance: float | None = None
    equity: float | None = None
    model_config = {"extra": "allow"}
