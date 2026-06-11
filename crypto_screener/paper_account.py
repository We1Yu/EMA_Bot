"""
Virtual (paper) trading account for the Binance Futures screener.
Tracks positions opened by scanner signals, checks stop/target on each update.
"""

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import PAPER_INITIAL_BALANCE, PAPER_RISK_PCT

TW_TZ      = timezone(timedelta(hours=8))
PAPER_FILE = Path(__file__).parent / "paper_account.json"


@dataclass
class Position:
    symbol:      str
    direction:   str      # "LONG" (breakout above MAs) or "SHORT" (breakdown below MAs)
    entry_price: float
    stop_loss:   float
    target_1:    float
    target_2:    float
    target_3:    float
    contracts:   float
    notional:    float
    open_time:   float    # unix timestamp
    score:       int
    tier:        str
    tp1_hit:     bool = False
    tp2_hit:     bool = False


class PaperAccount:
    def __init__(
        self,
        initial_balance: float = PAPER_INITIAL_BALANCE,
        risk_pct: float = PAPER_RISK_PCT,
    ):
        self.initial_balance = initial_balance
        self.balance         = initial_balance
        self.risk_pct        = risk_pct
        self.positions: dict[str, Position] = {}
        self.history:   list[dict]          = []

    # ── Open ──────────────────────────────────────────────────
    def open_position(self, signal: dict) -> bool:
        """Open a new position from a scanner signal dict. Returns True if opened."""
        sym = signal["symbol"]
        if sym in self.positions:
            return False

        entry = signal["entry"]
        sl    = signal["stop_loss"]
        risk  = abs(entry - sl)
        if risk == 0:
            return False

        contracts = (self.balance * self.risk_pct) / risk
        pos = Position(
            symbol      = sym,
            direction   = signal.get("direction", "LONG"),
            entry_price = entry,
            stop_loss   = sl,
            target_1    = signal["target_1"],
            target_2    = signal["target_2"],
            target_3    = signal["target_3"],
            contracts   = contracts,
            notional    = contracts * entry,
            open_time   = time.time(),
            score       = signal["score"],
            tier        = signal["tier"],
        )
        self.positions[sym] = pos
        return True

    # ── Price update ─────────────────────────────────────────
    def update_price(self, symbol: str, high: float, low: float) -> list[dict]:
        """Check stop/target against bar high/low. Returns list of exit events."""
        pos = self.positions.get(symbol)
        if not pos:
            return []

        events: list[dict] = []

        if pos.direction == "LONG":
            # Stop loss
            if low <= pos.stop_loss:
                events.append(self._close(symbol, pos.stop_loss, "SL"))
            # TP1 — exit 30%, move stop to entry
            elif not pos.tp1_hit and high >= pos.target_1:
                pnl = (pos.target_1 - pos.entry_price) * pos.contracts * 0.3
                self.balance += pnl
                self.history.append(self._record(pos, pos.target_1, "TP1", pnl, 0.3))
                if symbol in self.positions:
                    self.positions[symbol].tp1_hit  = True
                    self.positions[symbol].stop_loss = pos.entry_price   # trail to entry
                events.append({"symbol": symbol, "reason": "TP1", "pnl": round(pnl, 4)})
            # TP2 — exit 40%, move stop to target_1
            elif pos.tp1_hit and not pos.tp2_hit and high >= pos.target_2:
                pnl = (pos.target_2 - pos.entry_price) * pos.contracts * 0.4
                self.balance += pnl
                self.history.append(self._record(pos, pos.target_2, "TP2", pnl, 0.4))
                if symbol in self.positions:
                    self.positions[symbol].tp2_hit  = True
                    self.positions[symbol].stop_loss = pos.target_1      # trail to TP1
                events.append({"symbol": symbol, "reason": "TP2", "pnl": round(pnl, 4)})
            # TP3 — trail remaining 30%
            elif pos.tp2_hit and high >= pos.target_3:
                events.append(self._close(symbol, pos.target_3, "TP3"))

        else:  # SHORT — mirrored
            # Stop loss
            if high >= pos.stop_loss:
                events.append(self._close(symbol, pos.stop_loss, "SL"))
            # TP1 — exit 30%, move stop to entry
            elif not pos.tp1_hit and low <= pos.target_1:
                pnl = (pos.entry_price - pos.target_1) * pos.contracts * 0.3
                self.balance += pnl
                self.history.append(self._record(pos, pos.target_1, "TP1", pnl, 0.3))
                if symbol in self.positions:
                    self.positions[symbol].tp1_hit  = True
                    self.positions[symbol].stop_loss = pos.entry_price   # trail to entry
                events.append({"symbol": symbol, "reason": "TP1", "pnl": round(pnl, 4)})
            # TP2 — exit 40%, move stop to target_1
            elif pos.tp1_hit and not pos.tp2_hit and low <= pos.target_2:
                pnl = (pos.entry_price - pos.target_2) * pos.contracts * 0.4
                self.balance += pnl
                self.history.append(self._record(pos, pos.target_2, "TP2", pnl, 0.4))
                if symbol in self.positions:
                    self.positions[symbol].tp2_hit  = True
                    self.positions[symbol].stop_loss = pos.target_1      # trail to TP1
                events.append({"symbol": symbol, "reason": "TP2", "pnl": round(pnl, 4)})
            # TP3 — trail remaining 30%
            elif pos.tp2_hit and low <= pos.target_3:
                events.append(self._close(symbol, pos.target_3, "TP3"))

        return events

    def _close(self, symbol: str, price: float, reason: str) -> dict:
        pos  = self.positions.pop(symbol)
        frac = 0.3 if (pos.tp1_hit and pos.tp2_hit) else (0.7 if pos.tp1_hit else 1.0)
        if pos.direction == "LONG":
            pnl = (price - pos.entry_price) * pos.contracts * frac
        else:
            pnl = (pos.entry_price - price) * pos.contracts * frac
        self.balance += pnl
        rec = self._record(pos, price, reason, pnl, frac, full_close=True)
        self.history.append(rec)
        return {"symbol": symbol, "reason": reason, "pnl": round(pnl, 4)}

    def _record(
        self, pos: Position, exit_price: float, reason: str,
        pnl: float, fraction: float, full_close: bool = False,
    ) -> dict:
        return {
            "symbol":      pos.symbol,
            "tier":        pos.tier,
            "score":       pos.score,
            "direction":   pos.direction,
            "entry":       round(pos.entry_price, 8),
            "exit":        round(exit_price, 8),
            "stop_loss":   round(pos.stop_loss, 8),
            "target_1":    round(pos.target_1, 8),
            "target_2":    round(pos.target_2, 8),
            "contracts":   round(pos.contracts * fraction, 8),
            "pnl":         round(pnl, 4),
            "reason":      reason,
            "full_close":  full_close,
            "open_time":   pos.open_time,
            "close_time":  time.time(),
        }

    # ── Stats ─────────────────────────────────────────────────
    def get_stats(self) -> dict:
        full   = [t for t in self.history if t.get("full_close")]
        wins   = [t for t in full if t["pnl"] > 0]
        losses = [t for t in full if t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in self.history)

        bal  = self.initial_balance
        peak = bal
        max_dd = 0.0
        for t in self.history:
            bal += t["pnl"]
            if bal > peak:
                peak = bal
            dd = (peak - bal) / peak * 100
            if dd > max_dd:
                max_dd = dd

        win_sum  = sum(t["pnl"] for t in wins)
        loss_sum = sum(t["pnl"] for t in losses)

        return {
            "initial_balance":  self.initial_balance,
            "current_balance":  round(self.balance, 2),
            "total_pnl":        round(total_pnl, 2),
            "return_pct":       round((self.balance - self.initial_balance) / self.initial_balance * 100, 2),
            "events":           len(self.history),
            "full_closes":      len(full),
            "wins":             len(wins),
            "losses":           len(losses),
            "win_rate":         round(len(wins) / len(full) * 100, 1) if full else 0,
            "avg_win":          round(win_sum  / len(wins),   2) if wins   else 0,
            "avg_loss":         round(loss_sum / len(losses), 2) if losses else 0,
            "profit_factor":    round(abs(win_sum / loss_sum), 2) if loss_sum else None,
            "max_drawdown_pct": round(max_dd, 2),
            "open_positions":   len(self.positions),
        }

    def print_report(self) -> None:
        s  = self.get_stats()
        tw = datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M TWN")
        print(f"\n{'='*55}")
        print(f"  Virtual Account Report  {tw}")
        print(f"{'='*55}")
        print(f"  Initial:       ${s['initial_balance']:>12,.2f}")
        print(f"  Balance:       ${s['current_balance']:>12,.2f}")
        print(f"  Total PnL:     ${s['total_pnl']:>+12,.2f}  ({s['return_pct']:+.2f}%)")
        print(f"  Max Drawdown:  {s['max_drawdown_pct']:.2f}%")
        print(f"  Full closes:   {s['full_closes']}")
        print(f"  Win Rate:      {s['win_rate']:.1f}%")
        print(f"  Avg Win:       ${s['avg_win']:>+12,.2f}")
        print(f"  Avg Loss:      ${s['avg_loss']:>+12,.2f}")
        pf = s["profit_factor"]
        print(f"  Profit Factor: {f'{pf:.2f}' if pf is not None else 'N/A'}")
        print(f"  Open Positions:{s['open_positions']}")
        if self.positions:
            for sym, pos in self.positions.items():
                ts = datetime.fromtimestamp(pos.open_time, tz=TW_TZ).strftime("%m/%d %H:%M")
                tp = "TP1✓" if pos.tp1_hit else ""
                print(f"    {sym:20s} {pos.tier}  @{pos.entry_price:.6g}"
                      f"  SL={pos.stop_loss:.6g}  {tp}  opened:{ts}")
        print(f"{'='*55}")

    # ── Persistence ───────────────────────────────────────────
    def save(self, path: Path = PAPER_FILE) -> None:
        data = {
            "initial_balance": self.initial_balance,
            "balance":         self.balance,
            "risk_pct":        self.risk_pct,
            "positions":       {k: asdict(v) for k, v in self.positions.items()},
            "history":         self.history,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Path = PAPER_FILE) -> "PaperAccount":
        if not path.exists():
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        acct = cls(data["initial_balance"], data.get("risk_pct", PAPER_RISK_PCT))
        acct.balance   = data["balance"]
        acct.positions = {
            k: Position(**{
                "tp1_hit": False, "tp2_hit": False,
                **v,
            })
            for k, v in data.get("positions", {}).items()
        }
        acct.history = data.get("history", [])
        return acct
