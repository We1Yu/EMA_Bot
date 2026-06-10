"""
EMA Scanner 網頁儀表板
啟動：python web_app.py
預設網址：http://localhost:5000
"""

import json
import time
import threading
import concurrent.futures
from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from paper_trader import PaperTrader, PAPER_FILE
from bingx        import get_contracts, get_klines, get_ticker_price
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


def _duration(open_ms: int) -> str:
    secs = int(time.time() - open_ms / 1000)
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        h, m = divmod(secs // 60, 60)
        return f"{h}h {m}m"
    d, rem = divmod(secs, 86400)
    return f"{d}d {rem // 3600}h"


def _fetch_current_prices(symbols: list[str]) -> dict[str, float]:
    """平行取得多個幣種的現價"""
    result = {}
    def _one(sym):
        p = get_ticker_price(sym)
        return sym, p
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for sym, price in ex.map(_one, symbols):
            if price is not None:
                result[sym] = price
    return result


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

    # 持倉列表（含現價 & 未實現損益）
    now_ms = int(time.time() * 1000)
    pos_symbols = list(trader.positions.keys())
    cur_prices  = _fetch_current_prices(pos_symbols) if pos_symbols else {}

    positions = []
    for sym, pos in trader.positions.items():
        cur = cur_prices.get(sym)
        remaining = 0.5 if pos.tp1_hit else 1.0
        if cur is not None:
            if pos.direction == "LONG":
                upnl = (cur - pos.entry_price) * pos.contracts * remaining
                upnl_pct = (cur - pos.entry_price) / pos.entry_price * 100
            else:
                upnl = (pos.entry_price - cur) * pos.contracts * remaining
                upnl_pct = (pos.entry_price - cur) / pos.entry_price * 100
        else:
            upnl = upnl_pct = None

        risk_dist = abs(pos.entry_price - pos.stop_loss)
        risk_amt  = round(pos.contracts * risk_dist * remaining, 2)

        # 進度（0=entry, -100=SL, +150=TP1, +250=TP2）
        if cur is not None and risk_dist > 0:
            if pos.direction == "LONG":
                progress_r = (cur - pos.entry_price) / risk_dist
            else:
                progress_r = (pos.entry_price - cur) / risk_dist
        else:
            progress_r = None

        cur_notional = round(pos.contracts * cur, 2) if cur is not None else round(pos.notional, 2)
        positions.append({
            "symbol":       sym,
            "strategy":     pos.strategy or "EMA_CONVERGENCE",
            "direction":    pos.direction,
            "entry":        pos.entry_price,
            "cur_price":    cur,
            "upnl":         round(upnl, 2) if upnl is not None else None,
            "upnl_pct":     round(upnl_pct, 2) if upnl_pct is not None else None,
            "stop_loss":    pos.stop_loss,
            "target1":      pos.target1,
            "target2":      pos.target2,
            "contracts":    round(pos.contracts, 4),
            "notional":     cur_notional,
            "risk_amt":     risk_amt,
            "score":        pos.score,
            "open_time":    _tw(pos.open_time_ms),
            "duration":     _duration(pos.open_time_ms),
            "tp1_hit":      pos.tp1_hit,
            "progress_r":   round(progress_r, 2) if progress_r is not None else None,
            "oi_info":      None,  # OI 資訊僅在開倉時記錄，持倉期間不再更新
        })

    # 加總未實現損益給 stats
    total_upnl = sum(p["upnl"] for p in positions if p["upnl"] is not None)
    total_notional = sum(p["notional"] for p in positions)
    stats["total_upnl"]     = round(total_upnl, 2)
    stats["total_notional"] = round(total_notional, 2)

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
            KLINES_1H = 100
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
