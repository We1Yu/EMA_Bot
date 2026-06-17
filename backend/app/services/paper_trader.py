"""
紙上帳戶 (Paper Trading) 模組
模擬交易執行、追蹤部位、記錄損益
"""

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.core.config import PAPER_FILE, DATA_DIR

TW_TZ         = timezone(timedelta(hours=8))
RISK_PCT      = 0.02
MAX_POSITIONS = 4
MAX_SAME_DIR  = 2
TP1_FRACTION  = 0.25   # TP1 時平倉比例（取 25%，留 75% 衝 TP2）


@dataclass
class Position:
    symbol:       str
    direction:    str
    entry_price:  float
    stop_loss:    float
    target1:      float
    target2:      float
    contracts:    float
    notional:     float
    open_time_ms: int
    score:        float
    tp1_hit:      bool = False
    last_bar_ms:  int  = 0
    strategy:     str  = ""


class PaperTrader:
    def __init__(
        self,
        initial_balance: float = 10_000.0,
        risk_pct:        float = RISK_PCT,
        max_positions:   int   = MAX_POSITIONS,
        max_same_dir:    int   = MAX_SAME_DIR,
    ):
        self.initial_balance = initial_balance
        self.balance         = initial_balance
        self.risk_pct        = risk_pct
        self.max_positions   = max_positions
        self.max_same_dir    = max_same_dir
        self.positions:     dict[str, Position] = {}
        self.trade_history: list[dict]          = []

    # ── 開倉 ──────────────────────────────────────────────────
    def open_position(self, result: dict, score: float) -> bool:
        symbol = result["symbol"]
        if symbol in self.positions:
            return False
        if len(self.positions) >= self.max_positions:
            return False
        direction = result["direction"]
        same_dir  = sum(1 for p in self.positions.values() if p.direction == direction)
        if same_dir >= self.max_same_dir:
            return False

        lvl       = result["levels"]
        entry     = lvl["entry"]
        sl        = lvl["stop_loss"]
        risk_dist = abs(entry - sl)
        if risk_dist == 0:
            return False

        contracts = (self.balance * self.risk_pct) / risk_dist
        pos = Position(
            symbol       = symbol,
            direction    = result["direction"],
            entry_price  = entry,
            stop_loss    = sl,
            target1      = lvl["target1"],
            target2      = lvl["target2"],
            contracts    = contracts,
            notional     = contracts * entry,
            open_time_ms = result.get("candle_time_ms", int(time.time() * 1000)),
            score        = score,
            strategy     = result.get("strategy", ""),
        )
        self.positions[symbol] = pos
        return True

    # ── K 棒更新（高低點觸發止損/止盈）──────────────────────
    def check_bar(self, symbol: str, high: float, low: float, bar_time_ms: int) -> list[dict]:
        pos = self.positions.get(symbol)
        if not pos:
            return []
        if bar_time_ms <= pos.last_bar_ms:
            return []

        events = []
        if pos.direction == "LONG":
            if low <= pos.stop_loss:
                events.append(self._close(symbol, pos.stop_loss, "SL", bar_time_ms))
            elif not pos.tp1_hit and high >= pos.target1:
                events.append(self._partial(symbol, pos.target1, "TP1", bar_time_ms))
                if symbol in self.positions:
                    self.positions[symbol].stop_loss = pos.entry_price
            elif pos.tp1_hit and high >= pos.target2:
                events.append(self._close(symbol, pos.target2, "TP2", bar_time_ms))
        else:
            if high >= pos.stop_loss:
                events.append(self._close(symbol, pos.stop_loss, "SL", bar_time_ms))
            elif not pos.tp1_hit and low <= pos.target1:
                events.append(self._partial(symbol, pos.target1, "TP1", bar_time_ms))
                if symbol in self.positions:
                    self.positions[symbol].stop_loss = pos.entry_price
            elif pos.tp1_hit and low <= pos.target2:
                events.append(self._close(symbol, pos.target2, "TP2", bar_time_ms))

        if symbol in self.positions:
            self.positions[symbol].last_bar_ms = bar_time_ms

        return events

    def update_positions(self, latest_bar_by_symbol: dict[str, dict]) -> list[dict]:
        events = []
        for sym in list(self.positions.keys()):
            bar = latest_bar_by_symbol.get(sym)
            if bar:
                events.extend(self.check_bar(sym, bar["high"], bar["low"], bar["time"]))
        return events

    # ── 平倉輔助 ─────────────────────────────────────────────
    def _close(self, symbol: str, exit_price: float, reason: str, time_ms: int) -> dict:
        pos = self.positions.pop(symbol)
        if reason == "SL" and pos.tp1_hit:
            reason = "套保"
        remaining = (1.0 - TP1_FRACTION) if pos.tp1_hit else 1.0
        if pos.direction == "LONG":
            pnl = (exit_price - pos.entry_price) * pos.contracts * remaining
        else:
            pnl = (pos.entry_price - exit_price) * pos.contracts * remaining
        self.balance += pnl
        record = self._record(pos, exit_price, reason, pnl, time_ms, remaining, full_close=True)
        self.trade_history.append(record)
        return record

    def _partial(self, symbol: str, exit_price: float, reason: str, time_ms: int) -> dict:
        pos         = self.positions[symbol]
        pos.tp1_hit = True
        fraction    = TP1_FRACTION
        if pos.direction == "LONG":
            pnl = (exit_price - pos.entry_price) * pos.contracts * fraction
        else:
            pnl = (pos.entry_price - exit_price) * pos.contracts * fraction
        self.balance += pnl
        record = self._record(pos, exit_price, reason, pnl, time_ms, fraction, full_close=False)
        self.trade_history.append(record)
        return record

    def _record(self, pos: Position, exit_price: float, reason: str, pnl: float,
                time_ms: int, fraction: float, full_close: bool) -> dict:
        return {
            "symbol":     pos.symbol,
            "direction":  pos.direction,
            "strategy":   pos.strategy,
            "entry":      round(pos.entry_price, 8),
            "exit":       round(exit_price,      8),
            "stop_loss":  round(pos.stop_loss,   8),
            "target1":    round(pos.target1,     8),
            "target2":    round(pos.target2,     8),
            "contracts":  round(pos.contracts * fraction, 8),
            "pnl":        round(pnl, 4),
            "reason":     reason,
            "score":      pos.score,
            "open_ms":    pos.open_time_ms,
            "close_ms":   time_ms,
            "full_close": full_close,
        }

    # ── 統計 ─────────────────────────────────────────────────
    def get_stats(self) -> dict:
        h = self.trade_history
        if not h:
            return {
                "initial_balance": self.initial_balance,
                "current_balance": round(self.balance, 2),
                "trades": 0,
            }

        full   = [t for t in h if t["full_close"]]
        wins   = [t for t in full if t["pnl"] > 0]
        losses = [t for t in full if t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in h)

        bal = self.initial_balance
        peak = bal
        max_dd = 0.0
        for t in h:
            bal += t["pnl"]
            if bal > peak:
                peak = bal
            dd = (peak - bal) / peak * 100
            if dd > max_dd:
                max_dd = dd

        win_sum  = sum(t["pnl"] for t in wins)
        loss_sum = sum(t["pnl"] for t in losses)

        return {
            "initial_balance":   self.initial_balance,
            "current_balance":   round(self.balance, 2),
            "total_pnl":         round(total_pnl, 2),
            "total_return_pct":  round((self.balance - self.initial_balance) / self.initial_balance * 100, 2),
            "total_events":      len(h),
            "full_closes":       len(full),
            "wins":              len(wins),
            "losses":            len(losses),
            "win_rate_pct":      round(len(wins) / len(full) * 100, 1) if full else 0,
            "avg_win":           round(win_sum  / len(wins),   2) if wins   else 0,
            "avg_loss":          round(loss_sum / len(losses), 2) if losses else 0,
            "profit_factor":     round(abs(win_sum / loss_sum), 2) if loss_sum != 0 else None,
            "max_drawdown_pct":  round(max_dd, 2),
            "open_positions":    len(self.positions),
        }

    def print_report(self) -> None:
        s  = self.get_stats()
        tw = datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M TWN")
        print(f"\n{'='*55}")
        print(f"  紙上帳戶報告  {tw}")
        print(f"{'='*55}")
        print(f"  初始資金：  ${s['initial_balance']:>12,.2f}")
        print(f"  當前餘額：  ${s['current_balance']:>12,.2f}")
        print(f"  總損益：    ${s.get('total_pnl', 0.0):>+12,.2f}  ({s.get('total_return_pct', 0.0):+.2f}%)")
        print(f"  最大回撤：  {s.get('max_drawdown_pct', 0.0):.2f}%")
        print(f"  完整平倉：  {s.get('full_closes', 0)} 筆")
        print(f"  勝率：      {s.get('win_rate_pct', 0):.1f}%")
        print(f"  平均獲利：  ${s.get('avg_win', 0):>+12,.2f}")
        print(f"  平均虧損：  ${s.get('avg_loss', 0):>+12,.2f}")
        pf = s.get("profit_factor")
        print(f"  獲利因子：  {f'{pf:.2f}' if pf is not None else 'N/A'}")
        print(f"  持倉中：    {s.get('open_positions', len(self.positions))} 筆")
        if self.positions:
            for sym, pos in self.positions.items():
                ts = datetime.fromtimestamp(pos.open_time_ms / 1000, tz=TW_TZ)
                print(f"    {sym:20s} {pos.direction}  @{pos.entry_price:.6g}"
                      f"  SL={pos.stop_loss:.6g}  開倉:{ts:%m/%d %H:%M}")
        print(f"{'='*55}")

    # ── 持久化 ───────────────────────────────────────────────
    def save(self, path: Path | None = None) -> None:
        path = path or PAPER_FILE
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "initial_balance": self.initial_balance,
            "balance":         self.balance,
            "risk_pct":        self.risk_pct,
            "max_positions":   self.max_positions,
            "positions":       {k: asdict(v) for k, v in self.positions.items()},
            "trade_history":   self.trade_history,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Path | None = None) -> "PaperTrader":
        path = path or PAPER_FILE
        if not path.exists():
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        trader = cls(data["initial_balance"], data.get("risk_pct", RISK_PCT),
                     data.get("max_positions", MAX_POSITIONS))
        trader.balance       = data["balance"]
        trader.positions     = {
            k: Position(**{**{"tp1_hit": False, "last_bar_ms": 0, "strategy": ""}, **v})
            for k, v in data.get("positions", {}).items()
        }
        trader.trade_history = data.get("trade_history", [])
        return trader
