"""訊號歷史 API"""

import json
from typing import Literal

from fastapi import APIRouter, Query

from app.core.config import SIGNALS_LOG, SIGNALS_JSONL

router = APIRouter()


def _load_signals_log() -> list[dict]:
    if SIGNALS_LOG.exists():
        try:
            return json.loads(SIGNALS_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _load_signals_history() -> list[dict]:
    records: list[dict] = []
    if SIGNALS_JSONL.exists():
        try:
            with open(SIGNALS_JSONL, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except Exception:
            pass
    return records


def _apply_filters(
    signals: list[dict],
    strategy: str | None,
    direction: str | None,
) -> list[dict]:
    if strategy:
        signals = [s for s in signals if s.get("strategy") == strategy]
    if direction:
        signals = [s for s in signals if s.get("direction") == direction]
    return signals


@router.get("/")
async def get_signals(
    limit:     int                                               = Query(50, ge=1, le=300),
    strategy:  Literal["EMA_CONVERGENCE", "EMA_PULLBACK", "STRUCTURE_BREAKOUT"] | None = None,
    direction: Literal["LONG", "SHORT"] | None                  = None,
):
    """最近 N 筆達標訊號（最新優先），可依策略與方向篩選"""
    signals = _load_signals_log()
    signals = _apply_filters(signals, strategy, direction)
    return list(reversed(signals[-limit:]))


@router.get("/history")
async def get_signals_history(
    limit:     int                                               = Query(200, ge=1, le=2000),
    strategy:  Literal["EMA_CONVERGENCE", "EMA_PULLBACK", "STRUCTURE_BREAKOUT"] | None = None,
    direction: Literal["LONG", "SHORT"] | None                  = None,
):
    """全部歷史訊號（從 JSONL，最新優先），可依策略與方向篩選"""
    signals = _load_signals_history()
    signals = _apply_filters(signals, strategy, direction)
    return list(reversed(signals[-limit:]))


@router.get("/stats")
async def get_signals_stats():
    """訊號統計：各策略 / 方向的觸發次數"""
    signals = _load_signals_history()

    by_strategy: dict[str, int] = {}
    by_direction: dict[str, int] = {"LONG": 0, "SHORT": 0}
    score_sum = 0.0
    score_cnt = 0

    for s in signals:
        strat = s.get("strategy", "UNKNOWN")
        by_strategy[strat] = by_strategy.get(strat, 0) + 1

        d = s.get("direction")
        if d in by_direction:
            by_direction[d] += 1

        sc = s.get("score")
        if sc is not None:
            score_sum += sc
            score_cnt += 1

    return {
        "total":        len(signals),
        "by_strategy":  by_strategy,
        "by_direction": by_direction,
        "avg_score":    round(score_sum / score_cnt, 2) if score_cnt else None,
    }
