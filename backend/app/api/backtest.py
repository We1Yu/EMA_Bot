"""回測 API（在背景執行緒中跑）"""

import threading

from fastapi import APIRouter

router = APIRouter()

_task: dict = {"running": False, "result": None, "error": None}
_lock       = threading.Lock()


@router.get("/status")
async def backtest_status():
    with _lock:
        return {
            "running": _task["running"],
            "result":  _task["result"],
            "error":   _task["error"],
        }


@router.post("/")
async def trigger_backtest(use_all: bool = False, max_symbols: int = 30):
    """觸發回測（非同步背景執行）"""
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
