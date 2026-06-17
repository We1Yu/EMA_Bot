"""即時掃描 API（在背景執行緒中跑全市場掃描）"""

import json
import threading
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter

from app.services.data_ingestion.binance import get_contracts, get_klines
from app.services.strategies.scanner import scan_symbol
from app.services.scoring.scorer import score_setup, passes_threshold
from app.services.paper_trader import PaperTrader
from app.core.config import SIGNALS_LOG, DATA_DIR

router = APIRouter()
TW_TZ  = timezone(timedelta(hours=8))

_task: dict     = {"running": False, "result": None, "error": None}
_lock           = threading.Lock()

KLINES_4H = 250
KLINES_1H = 100


def _load_signals() -> list[dict]:
    if SIGNALS_LOG.exists():
        try:
            return json.loads(SIGNALS_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


@router.get("/status")
async def scan_status():
    """查詢掃描任務狀態"""
    with _lock:
        return {
            "running": _task["running"],
            "result":  _task["result"],
            "error":   _task["error"],
        }


@router.post("/")
async def trigger_scan():
    """觸發全市場掃描（非同步背景執行）"""
    with _lock:
        if _task["running"]:
            return {"error": "掃描任務進行中，請稍候"}, 409
        _task.update(running=True, result=None, error=None)

    def _do():
        try:
            symbols = get_contracts()
            results = []

            for sym in symbols:
                c4 = get_klines(sym, "4h", KLINES_4H)
                c1 = get_klines(sym, "1h", KLINES_1H)
                if not c4 or not c1:
                    continue
                r = scan_symbol(sym, c4, c1)
                if not r:
                    continue
                score = score_setup(r)
                if passes_threshold(score):
                    results.append({
                        "symbol":    sym,
                        "direction": r["direction"],
                        "strategy":  r.get("strategy", "EMA_CONVERGENCE"),
                        "score":     score,
                        "entry":     r["levels"]["entry"],
                        "stop_loss": r["levels"]["stop_loss"],
                        "target1":   r["levels"]["target1"],
                        "target2":   r["levels"]["target2"],
                        "bandwidth": r["convergence"]["bandwidth"],
                        "time":      datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M"),
                    })

            # 寫入訊號紀錄
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            existing = _load_signals()
            existing.extend(results)
            SIGNALS_LOG.write_text(
                json.dumps(existing[-300:], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 同步開虛擬倉
            trader = PaperTrader.load()
            opened = 0
            for sig in sorted(results, key=lambda x: x["score"], reverse=True):
                r = {
                    "symbol":    sig["symbol"],
                    "direction": sig["direction"],
                    "strategy":  sig["strategy"],
                    "levels": {
                        "entry":     sig["entry"],
                        "stop_loss": sig["stop_loss"],
                        "target1":   sig["target1"],
                        "target2":   sig["target2"],
                        "atr":       0,
                    },
                    "convergence":    {"bandwidth": sig["bandwidth"], "compression_bars": 3},
                    "candle_time_ms": int(time.time() * 1000),
                }
                if trader.open_position(r, sig["score"]):
                    opened += 1
            if opened:
                trader.save()

            with _lock:
                _task.update(running=False, result={
                    "found":   len(results),
                    "opened":  opened,
                    "signals": results,
                })
        except Exception as exc:
            with _lock:
                _task.update(running=False, error=str(exc))

    threading.Thread(target=_do, daemon=True).start()
    return {"status": "started"}
