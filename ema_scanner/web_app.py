"""
EMA Scanner 網頁儀表板
啟動：python web_app.py
預設網址：http://localhost:5000
"""

import json
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from paper_trader import PaperTrader, PAPER_FILE
from bingx        import get_contracts, get_klines
from scanner      import scan_symbol
from scorer       import score_setup, passes_threshold

TW_TZ       = timezone(timedelta(hours=8))
SIGNALS_LOG = Path(__file__).parent / "signals_log.json"

app = Flask(__name__)

# ── 後台任務狀態（掃描 / 回測共用同一槽）────────────────────
_task: dict = {"running": False, "type": None, "result": None, "error": None}
_lock = threading.Lock()


# ── 工具函式 ─────────────────────────────────────────────────

def _load_signals() -> list[dict]:
    if SIGNALS_LOG.exists():
        try:
            return json.loads(SIGNALS_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _tw(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=TW_TZ).strftime("%Y/%m/%d %H:%M")


# ── API ──────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/account")
def api_account():
    trader = PaperTrader.load()
    stats  = trader.get_stats()

    # 資金曲線
    bal    = trader.initial_balance
    labels = ["開始"]
    equity = [bal]
    for t in trader.trade_history:
        bal += t["pnl"]
        equity.append(round(bal, 2))
        labels.append(_tw(t["close_ms"]))

    # 持倉列表
    positions = []
    for sym, pos in trader.positions.items():
        positions.append({
            "symbol":    sym,
            "direction": pos.direction,
            "entry":     pos.entry_price,
            "stop_loss": pos.stop_loss,
            "target1":   pos.target1,
            "target2":   pos.target2,
            "contracts": round(pos.contracts, 6),
            "notional":  round(pos.notional, 2),
            "score":     pos.score,
            "open_time": _tw(pos.open_time_ms),
            "tp1_hit":   pos.tp1_hit,
        })

    # 最近 100 筆交易（最新優先）
    trades = []
    for t in reversed(trader.trade_history):
        trades.append({**t, "open_time": _tw(t["open_ms"]), "close_time": _tw(t["close_ms"])})
        if len(trades) >= 100:
            break

    return jsonify({
        "stats":        stats,
        "positions":    positions,
        "trades":       trades,
        "equity_curve": {"labels": labels, "data": equity},
    })


@app.route("/api/signals")
def api_signals():
    signals = _load_signals()
    return jsonify(list(reversed(signals[-50:])))


@app.route("/api/task/status")
def api_task_status():
    with _lock:
        return jsonify({
            "running": _task["running"],
            "type":    _task["type"],
            "result":  _task["result"],
            "error":   _task["error"],
        })


@app.route("/api/scan", methods=["POST"])
def api_scan():
    with _lock:
        if _task["running"]:
            return jsonify({"error": "任務進行中"}), 409
        _task.update(running=True, type="scan", result=None, error=None)

    def _do():
        try:
            KLINES_4H = 250
            KLINES_1H = 50
            symbols   = get_contracts()
            results   = []

            for sym in symbols:
                c4 = get_klines(sym, "4H", KLINES_4H)
                c1 = get_klines(sym, "1H", KLINES_1H)
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
                        "score":     score,
                        "entry":     r["levels"]["entry"],
                        "stop_loss": r["levels"]["stop_loss"],
                        "target1":   r["levels"]["target1"],
                        "target2":   r["levels"]["target2"],
                        "bandwidth": r["convergence"]["bandwidth"],
                        "time":      datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M"),
                    })

            # 寫入訊號紀錄
            existing = _load_signals()
            existing.extend(results)
            SIGNALS_LOG.write_text(
                json.dumps(existing[-300:], ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # 同步開虛擬倉
            trader = PaperTrader.load()
            opened = 0
            for sig in results:
                # 重新建構 result dict 格式讓 open_position 可用
                r = {
                    "symbol":    sig["symbol"],
                    "direction": sig["direction"],
                    "levels": {
                        "entry":     sig["entry"],
                        "stop_loss": sig["stop_loss"],
                        "target1":   sig["target1"],
                        "target2":   sig["target2"],
                        "atr":       0,
                    },
                    "convergence": {"bandwidth": sig["bandwidth"], "compression_bars": 3},
                    "candle_time_ms": int(time.time() * 1000),
                }
                if trader.open_position(r, sig["score"]):
                    opened += 1
            if opened:
                trader.save()

            with _lock:
                _task.update(running=False, result={"found": len(results), "opened": opened, "signals": results})
        except Exception as exc:
            with _lock:
                _task.update(running=False, error=str(exc))

    threading.Thread(target=_do, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    data   = request.get_json() or {}
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "請輸入交易對"}), 400

    with _lock:
        if _task["running"]:
            return jsonify({"error": "任務進行中"}), 409
        _task.update(running=True, type="backtest", result=None, error=None)

    def _do():
        try:
            from backtest import run_backtest
            result = run_backtest(symbol, verbose=False)
            with _lock:
                _task.update(running=False, result=result)
        except Exception as exc:
            with _lock:
                _task.update(running=False, error=str(exc))

    threading.Thread(target=_do, daemon=True).start()
    return jsonify({"status": "started"})


# ── 啟動 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  EMA Scanner 儀表板")
    print("  http://localhost:5000")
    print("=" * 50)
    app.run(debug=False, host="0.0.0.0", port=5000)
