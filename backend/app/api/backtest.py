"""回測 API（在背景執行緒中跑）"""

import threading

from fastapi import APIRouter

router = APIRouter()

_task: dict = {"running": False, "result": None, "error": None}
_lock       = threading.Lock()


@router.get("/")
async def get_backtest_result():
    """取得上次回測結果（若尚未執行則回傳 null）"""
    with _lock:
        return {
            "running": _task["running"],
            "result":  _task["result"],
            "error":   _task["error"],
        }


@router.get("/status")
async def backtest_status():
    """查詢回測任務執行狀態"""
    with _lock:
        return {
            "running": _task["running"],
            "has_result": _task["result"] is not None,
            "error":   _task["error"],
        }


@router.post("/")
async def trigger_backtest(use_all: bool = False, max_symbols: int = 30):
    """觸發回測（非同步背景執行）

    - `use_all=false`（預設）：只跑前 max_symbols 個幣種（BTC/ETH 優先）
    - `use_all=true`：全市場（耗時較長）
    """
    with _lock:
        if _task["running"]:
            return {"error": "回測任務進行中，請稍候"}
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
