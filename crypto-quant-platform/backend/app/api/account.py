"""帳戶 & 紙倉 API"""

import concurrent.futures
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter

from app.services.paper_trader import PaperTrader
from app.services.data_ingestion.binance import get_ticker_price
from app.core.config import CLOSED_TRADES_JSONL

import json

router = APIRouter()
TW_TZ  = timezone(timedelta(hours=8))


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


def _fetch_prices(symbols: list[str]) -> dict[str, float]:
    result = {}
    def _one(sym):
        return sym, get_ticker_price(sym)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for sym, price in ex.map(_one, symbols):
            if price is not None:
                result[sym] = price
    return result


@router.get("/")
async def get_account():
    """帳戶統計 + 持倉 + 最近 100 筆交易 + 資金曲線"""
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

    # 持倉（含現價與未實現損益）
    pos_symbols = list(trader.positions.keys())
    cur_prices  = _fetch_prices(pos_symbols) if pos_symbols else {}

    positions = []
    for sym, pos in trader.positions.items():
        cur       = cur_prices.get(sym)
        remaining = 0.5 if pos.tp1_hit else 1.0

        if cur is not None:
            if pos.direction == "LONG":
                upnl     = (cur - pos.entry_price) * pos.contracts * remaining
                upnl_pct = (cur - pos.entry_price) / pos.entry_price * 100
            else:
                upnl     = (pos.entry_price - cur) * pos.contracts * remaining
                upnl_pct = (pos.entry_price - cur) / pos.entry_price * 100
        else:
            upnl = upnl_pct = None

        risk_dist = abs(pos.entry_price - pos.stop_loss)
        risk_amt  = round(pos.contracts * risk_dist * remaining, 2)

        if cur is not None and risk_dist > 0:
            progress_r = ((cur - pos.entry_price) / risk_dist
                          if pos.direction == "LONG"
                          else (pos.entry_price - cur) / risk_dist)
        else:
            progress_r = None

        cur_notional = round(pos.contracts * cur, 2) if cur is not None else round(pos.notional, 2)
        positions.append({
            "symbol":      sym,
            "strategy":    pos.strategy or "EMA_CONVERGENCE",
            "direction":   pos.direction,
            "entry":       pos.entry_price,
            "cur_price":   cur,
            "upnl":        round(upnl, 2)        if upnl        is not None else None,
            "upnl_pct":    round(upnl_pct, 2)    if upnl_pct    is not None else None,
            "stop_loss":   pos.stop_loss,
            "target1":     pos.target1,
            "target2":     pos.target2,
            "contracts":   round(pos.contracts, 4),
            "notional":    cur_notional,
            "risk_amt":    risk_amt,
            "score":       pos.score,
            "open_time":   _tw(pos.open_time_ms),
            "duration":    _duration(pos.open_time_ms),
            "tp1_hit":     pos.tp1_hit,
            "progress_r":  round(progress_r, 2) if progress_r is not None else None,
        })

    total_upnl     = sum(p["upnl"] for p in positions if p["upnl"] is not None)
    total_notional = sum(p["notional"] for p in positions)
    stats["total_upnl"]     = round(total_upnl, 2)
    stats["total_notional"] = round(total_notional, 2)

    trades = []
    for t in reversed(trader.trade_history):
        trades.append({**t, "open_time": _tw(t["open_ms"]), "close_time": _tw(t["close_ms"])})
        if len(trades) >= 100:
            break

    return {
        "stats":        stats,
        "positions":    positions,
        "trades":       trades,
        "equity_curve": {"labels": labels, "data": equity},
    }


@router.get("/records")
async def get_records():
    """全部逐筆平倉紀錄（最新優先）"""
    records: list[dict] = []
    if CLOSED_TRADES_JSONL.exists():
        try:
            with open(CLOSED_TRADES_JSONL, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except Exception:
            pass
    return list(reversed(records))
