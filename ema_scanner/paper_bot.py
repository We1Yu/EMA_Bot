"""
EMA Convergence Paper Trading Bot
自動執行虛擬帳戶交易、監控持倉、記錄損益

執行：python paper_bot.py
排程：
  - 每 5  分鐘：用 15m K 棒更新所有持倉（止損 / 止盈）
  - 每 60 分鐘：全市場掃描新訊號，觸發時開虛擬倉
  - 額外觸發：4H K線收盤時立即掃描
"""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from bingx        import get_contracts, get_klines
from scanner      import scan_symbol
from scorer       import score_setup, passes_threshold
from paper_trader import PaperTrader

# ── 常數 ──────────────────────────────────────────────────────
TW_TZ            = timezone(timedelta(hours=8))
BOT_STATE_FILE   = Path(__file__).parent / "bot_state.json"
SIGNALS_LOG      = Path(__file__).parent / "signals_log.json"

CHECK_INTERVAL   = 5  * 60     # 5 分鐘：持倉監控
SCAN_INTERVAL    = 60 * 60     # 60 分鐘：市場掃描
DEDUP_WINDOW     = 4  * 60 * 60
KLINES_4H_LIMIT  = 250
KLINES_1H_LIMIT  = 50


# ── 工具 ─────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M:%S TWN")

def _log(msg: str) -> None:
    print(f"[{_now()}] {msg}")

def _load_state() -> dict:
    if BOT_STATE_FILE.exists():
        try:
            return json.loads(BOT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_state(state: dict) -> None:
    now_ts = time.time()
    pruned = {k: v for k, v in state.items() if now_ts - v < DEDUP_WINDOW}
    BOT_STATE_FILE.write_text(
        json.dumps(pruned, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def _log_signal(result: dict, score: float) -> None:
    try:
        existing = json.loads(SIGNALS_LOG.read_text(encoding="utf-8")) if SIGNALS_LOG.exists() else []
        existing.append({
            "symbol":    result["symbol"],
            "direction": result["direction"],
            "score":     score,
            "entry":     result["levels"]["entry"],
            "stop_loss": result["levels"]["stop_loss"],
            "target1":   result["levels"]["target1"],
            "target2":   result["levels"]["target2"],
            "bandwidth": result["convergence"]["bandwidth"],
            "time":      datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M"),
        })
        SIGNALS_LOG.write_text(
            json.dumps(existing[-300:], ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


# ── 持倉監控（5 分鐘一次）────────────────────────────────────

def check_positions() -> None:
    trader = PaperTrader.load()
    if not trader.positions:
        return

    updated = False
    for symbol in list(trader.positions.keys()):
        # 取最近 4 根 15m K 棒（最後一根可能還在形成中，取前三根）
        candles = get_klines(symbol, "15m", 5)
        if not candles:
            continue

        closed_bars = candles[:-1]   # 排除正在形成的最新棒
        pos = trader.positions.get(symbol)
        if not pos:
            continue

        for bar in closed_bars:
            if bar["time"] <= pos.last_bar_ms:
                continue   # 已處理過

            events = trader.check_bar(symbol, bar["high"], bar["low"], bar["time"])
            updated = True

            for ev in events:
                icon = "✅" if ev["pnl"] > 0 else "❌" if ev["pnl"] < 0 else "➖"
                _log(f"  {icon} {ev['symbol']:20s} "
                     f"{ev['direction']} {ev['reason']:3s}  "
                     f"PnL: ${ev['pnl']:>+9.2f}")

            pos = trader.positions.get(symbol)   # 可能已被平倉
            if not pos:
                break

    if updated:
        trader.save()


# ── 市場掃描（60 分鐘一次）───────────────────────────────────

def run_scan() -> None:
    _log("=" * 52)
    _log("市場掃描開始")

    symbols = get_contracts()
    if not symbols:
        _log("[錯誤] 無法取得合約清單")
        return

    _log(f"掃描 {len(symbols)} 個交易對...")

    state   = _load_state()
    trader  = PaperTrader.load()
    now_ts  = time.time()

    new_signals  = 0
    new_positions = 0
    converging   = 0

    for symbol in symbols:
        c4 = get_klines(symbol, "4H", KLINES_4H_LIMIT)
        c1 = get_klines(symbol, "1H", KLINES_1H_LIMIT)
        if not c4 or not c1:
            continue

        result = scan_symbol(symbol, c4, c1)
        if not result:
            continue

        converging += 1
        score = score_setup(result)
        if not passes_threshold(score):
            continue

        new_signals += 1

        # 去重：4 小時內同幣種不重複開倉
        last_ts = state.get(symbol, 0)
        if now_ts - last_ts < DEDUP_WINDOW:
            _log(f"  [跳過] {symbol:20s} 距上次訊號 < 4 小時")
            continue

        state[symbol] = now_ts
        _log_signal(result, score)

        icon = "🟢" if result["direction"] == "LONG" else "🔴"
        lvl  = result["levels"]
        opened = trader.open_position(result, score)

        if opened:
            new_positions += 1
            _log(f"  {icon} 開倉  {symbol:20s} {result['direction']}  "
                 f"@{lvl['entry']:.6g}  SL={lvl['stop_loss']:.6g}  "
                 f"T1={lvl['target1']:.6g}  score={score}")
        else:
            _log(f"  {icon} 訊號  {symbol:20s} {result['direction']}  "
                 f"score={score}  [已有持倉，略過]")

    trader.save()
    _save_state(state)

    _log(f"掃描完成 — 收斂:{converging}  達標:{new_signals}  新開倉:{new_positions}")
    _print_stats(trader)


def _print_stats(trader: PaperTrader) -> None:
    s = trader.get_stats()
    _log("-" * 52)
    _log(f"  帳戶餘額：${s['current_balance']:>10,.2f}  "
         f"({s['total_return_pct']:>+.2f}%)")
    if s.get("full_closes", 0) > 0:
        pf = s['profit_factor']
        pf_str = "∞" if pf is None else f"{pf:.2f}"
        _log(f"  勝率：{s['win_rate_pct']:.1f}%  "
             f"({s['wins']}勝/{s['losses']}敗)  "
             f"獲利因子：{pf_str}  "
             f"最大回撤：{s['max_drawdown_pct']:.2f}%")
    _log(f"  持倉中：{s['open_positions']} 筆")
    if trader.positions:
        for sym, pos in trader.positions.items():
            ts = datetime.fromtimestamp(pos.open_time_ms / 1000, tz=TW_TZ)
            _log(f"    {sym:20s} {pos.direction}  "
                 f"@{pos.entry_price:.6g}  SL={pos.stop_loss:.6g}  "
                 f"{'TP1已達 ' if pos.tp1_hit else ''}開:{ts:%m/%d %H:%M}")
    _log("-" * 52)


# ── 主排程迴圈 ────────────────────────────────────────────────

def main() -> None:
    print()
    print("=" * 55)
    print("  EMA Convergence Paper Trading Bot")
    print("  持倉監控：每 5 分鐘（15m K 棒）")
    print("  市場掃描：每 60 分鐘 + 4H 收盤")
    print("=" * 55)
    print()

    # 啟動立即執行一次完整掃描
    run_scan()

    last_scan_ts  = time.time()
    last_check_ts = time.time()
    last_4h_win   = datetime.now(timezone.utc).hour // 4

    while True:
        time.sleep(20)

        now_utc  = datetime.now(timezone.utc)
        now_ts   = time.time()
        cur_4h_w = now_utc.hour // 4

        # 每 5 分鐘：持倉監控
        if now_ts - last_check_ts >= CHECK_INTERVAL:
            last_check_ts = now_ts
            check_positions()

        # 每 60 分鐘 或 4H 收盤：全市場掃描
        triggered_interval = (now_ts - last_scan_ts) >= SCAN_INTERVAL
        triggered_4h_close = (cur_4h_w != last_4h_win)

        if triggered_interval or triggered_4h_close:
            if triggered_4h_close:
                _log(f"觸發：新 4H K線收盤（UTC {cur_4h_w * 4:02d}:00）")
            last_4h_win  = cur_4h_w
            last_scan_ts = now_ts
            run_scan()


if __name__ == "__main__":
    main()
