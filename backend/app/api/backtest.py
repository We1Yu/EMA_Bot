"""回測 API（在背景執行緒中跑）"""

import threading

from fastapi import APIRouter

from app.schemas.backtest import (
    BacktestRequest,
    BacktestTriggerResponse,
    BacktestStatusResponse,
    BacktestResultResponse,
)

router = APIRouter()

_task: dict = {"running": False, "result": None, "error": None}
_lock       = threading.Lock()


@router.get("/", response_model=BacktestResultResponse)
async def get_backtest_result():
    """取得上次回測結果（若尚未執行則回傳 null）"""
    with _lock:
        return {
            "running": _task["running"],
            "result":  _task["result"],
            "error":   _task["error"],
        }


@router.get("/status", response_model=BacktestStatusResponse)
async def backtest_status():
    """查詢回測任務執行狀態"""
    with _lock:
        return {
            "running": _task["running"],
            "has_result": _task["result"] is not None,
            "error":   _task["error"],
        }


@router.post("/", response_model=BacktestTriggerResponse)
async def trigger_backtest(body: BacktestRequest = BacktestRequest()):
    """觸發回測（非同步背景執行）

    - `use_all=false`（預設）：只跑前 max_symbols 個幣種（BTC/ETH 優先）
    - `use_all=true`：全市場（耗時較長）
    """
    use_all     = body.use_all
    max_symbols = body.max_symbols

    with _lock:
        if _task["running"]:
            return {"status": "error", "params": {"use_all": use_all, "max_symbols": max_symbols}}
        _task.update(running=True, result=None, error=None)

    def _do():
        try:
            from app.services.backtest.engine import run_backtest
            result = run_backtest(use_all=use_all, max_symbols=max_symbols)
            with _lock:
                _task.update(running=False, result=result)
        except Exception as exc:
            with _lock:
                _task.update(running=False, error=str(exc))

    threading.Thread(target=_do, daemon=True).start()
    return {"status": "started", "params": {"use_all": use_all, "max_symbols": max_symbols}}
