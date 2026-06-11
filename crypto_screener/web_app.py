"""
高頻虛擬交易機器人 — 網頁儀表板
啟動：python web_app.py
預設網址：http://localhost:5000
"""

import asyncio
import importlib.util
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp
from flask import Flask, jsonify, render_template

import bingx_source as source
from paper_account import PaperAccount
from config import SCALP_DASHBOARD_PORT

TW_TZ      = timezone(timedelta(hours=8))
PAPER_FILE = Path(__file__).parent / "paper_account_scalp.json"
STATE_FILE = Path(__file__).parent / "scalp_state.json"

# ── EMA Scanner account (separate module/process) ──────────────────
EMA_DIR          = Path(__file__).parent.parent / "ema_scanner"
EMA_PAPER_FILE   = EMA_DIR / "paper_account.json"
EMA_SIGNALS_FILE = EMA_DIR / "signals_log.json"


def _load_module(name: str, path: Path):
    spec   = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PaperTrader = _load_module("ema_paper_trader", EMA_DIR / "paper_trader.py").PaperTrader

app = Flask(__name__)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _tw(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=TW_TZ).strftime("%Y/%m/%d %H:%M:%S")


def _duration(open_ts: float) -> str:
    secs = int(time.time() - open_ts)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        h, m = divmod(secs // 60, 60)
        return f"{h}h {m}m"
    d, rem = divmod(secs, 86400)
    return f"{d}d {rem // 3600}h"


async def _fetch_prices(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    result = {}
    async with aiohttp.ClientSession() as session:
        tasks = {sym: source.fetch_price(session, sym) for sym in symbols}
        prices = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for sym, price in zip(tasks.keys(), prices):
            if isinstance(price, (int, float)):
                result[sym] = price
    return result


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    account = PaperAccount.load(PAPER_FILE)
    state   = _load_state()

    pos_symbols = list(account.positions.keys())
    cur_prices  = asyncio.run(_fetch_prices(pos_symbols))

    positions = []
    for sym, pos in account.positions.items():
        cur = cur_prices.get(sym)
        remaining = 1.0
        if pos.tp2_hit:
            remaining = 0.3
        elif pos.tp1_hit:
            remaining = 0.7

        upnl = upnl_pct = None
        if cur is not None:
            if pos.direction == "LONG":
                upnl = (cur - pos.entry_price) * pos.contracts * remaining
                upnl_pct = (cur - pos.entry_price) / pos.entry_price * 100
            else:
                upnl = (pos.entry_price - cur) * pos.contracts * remaining
                upnl_pct = (pos.entry_price - cur) / pos.entry_price * 100

        positions.append({
            "symbol":      sym,
            "direction":   pos.direction,
            "strategy":    getattr(pos, "strategy", "MA_BREAKOUT"),
            "entry_logic": getattr(pos, "entry_logic", ""),
            "tier":        pos.tier,
            "score":       pos.score,
            "entry":       pos.entry_price,
            "cur_price":   cur,
            "stop_loss":   pos.stop_loss,
            "target_1":    pos.target_1,
            "target_2":    pos.target_2,
            "target_3":    pos.target_3,
            "contracts":   round(pos.contracts, 6),
            "notional":    round(pos.notional, 2),
            "upnl":        round(upnl, 2) if upnl is not None else None,
            "upnl_pct":    round(upnl_pct, 2) if upnl_pct is not None else None,
            "tp1_hit":     pos.tp1_hit,
            "tp2_hit":     pos.tp2_hit,
            "open_time":   _tw(pos.open_time),
            "duration":    _duration(pos.open_time),
        })

    # 最近成交紀錄（最新優先）
    history = []
    for t in reversed(account.history[-100:]):
        history.append({
            **t,
            "open_time_str":  _tw(t["open_time"]),
            "close_time_str": _tw(t["close_time"]),
        })

    return jsonify({
        "stats":          account.get_stats(),
        "positions":      positions,
        "history":        history,
        "signals":        state.get("signals", []),
        "interval":       state.get("interval", "-"),
        "total_scanned":  state.get("total_scanned", 0),
        "last_scan":      _tw(state["updated"]) if state.get("updated") else "-",
    })


@app.route("/api/ema_state")
def api_ema_state():
    trader = PaperTrader.load(EMA_PAPER_FILE)

    pos_symbols = list(trader.positions.keys())
    cur_prices  = asyncio.run(_fetch_prices(pos_symbols))

    positions = []
    for sym, pos in trader.positions.items():
        cur = cur_prices.get(sym)
        remaining = 0.5 if pos.tp1_hit else 1.0

        upnl = upnl_pct = None
        if cur is not None:
            if pos.direction == "LONG":
                upnl = (cur - pos.entry_price) * pos.contracts * remaining
                upnl_pct = (cur - pos.entry_price) / pos.entry_price * 100
            else:
                upnl = (pos.entry_price - cur) * pos.contracts * remaining
                upnl_pct = (pos.entry_price - cur) / pos.entry_price * 100

        positions.append({
            "symbol":     sym,
            "direction":  pos.direction,
            "strategy":   pos.strategy,
            "score":      pos.score,
            "entry":      pos.entry_price,
            "cur_price":  cur,
            "stop_loss":  pos.stop_loss,
            "target_1":   pos.target1,
            "target_2":   pos.target2,
            "contracts":  round(pos.contracts, 6),
            "notional":   round(pos.notional, 2),
            "upnl":       round(upnl, 2) if upnl is not None else None,
            "upnl_pct":   round(upnl_pct, 2) if upnl_pct is not None else None,
            "tp1_hit":    pos.tp1_hit,
            "open_time":  _tw(pos.open_time_ms / 1000),
            "duration":   _duration(pos.open_time_ms / 1000),
        })

    history = []
    for t in reversed(trader.trade_history[-100:]):
        history.append({
            **t,
            "open_time_str":  _tw(t["open_ms"] / 1000),
            "close_time_str": _tw(t["close_ms"] / 1000),
        })

    signals = []
    if EMA_SIGNALS_FILE.exists():
        try:
            raw = json.loads(EMA_SIGNALS_FILE.read_text(encoding="utf-8"))
            signals = list(reversed(raw[-20:]))
        except Exception:
            pass

    return jsonify({
        "stats":     trader.get_stats(),
        "positions": positions,
        "history":   history,
        "signals":   signals,
    })


if __name__ == "__main__":
    print("=" * 50)
    print("  高頻虛擬交易機器人 儀表板")
    print(f"  http://localhost:{SCALP_DASHBOARD_PORT}")
    print("=" * 50)
    app.run(debug=False, host="0.0.0.0", port=SCALP_DASHBOARD_PORT)
