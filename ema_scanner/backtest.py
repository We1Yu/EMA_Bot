"""
回測引擎
使用歷史 K 線資料模擬交易訊號與紙上帳戶表現

用法（在 ema_scanner 目錄下執行）：
  python backtest.py BTC-USDT              # 單一交易對，詳細輸出
  python backtest.py BTC-USDT ETH-USDT    # 多個交易對
  python backtest.py --top20              # 前 20 大市值自動測試
"""

import sys
from datetime import datetime, timezone, timedelta

from bingx        import get_contracts, get_klines
from scanner      import scan_symbol
from scorer       import score_setup, passes_threshold
from paper_trader import PaperTrader

TW_TZ           = timezone(timedelta(hours=8))
KLINES_4H_LIMIT = 500   # ~83 天
KLINES_1H_LIMIT = 1440  # ~60 天（BingX API 硬上限）
MIN_4H_BARS     = 250   # EMA200 至少需要 200 根


# ── 輔助函式 ─────────────────────────────────────────────────

def _align_1h(candles_1h: list[dict], open_ms: int) -> list[dict]:
    """取得第 4H K線收盤前的所有 1H K線（含當根）"""
    end_ms = open_ms + 4 * 3600 * 1000
    return [c for c in candles_1h if c["time"] < end_ms]


def _fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=TW_TZ).strftime("%m/%d %H:%M")


# ── 單一幣種回測 ─────────────────────────────────────────────

def run_backtest(
    symbol:          str,
    initial_balance: float = 10_000.0,
    risk_pct:        float = 0.02,
    verbose:         bool  = True,
) -> dict:
    if verbose:
        print(f"\n[回測] {symbol}  取得歷史資料...")

    candles_4h = get_klines(symbol, "4H", KLINES_4H_LIMIT)
    candles_1h = get_klines(symbol, "1H", KLINES_1H_LIMIT)

    if not candles_4h or not candles_1h:
        if verbose:
            print(f"  [錯誤] 無法取得 {symbol} 資料")
        return {"symbol": symbol, "error": "無法取得資料"}

    if verbose:
        start_ts = _fmt_ts(candles_4h[0]["time"])
        end_ts   = _fmt_ts(candles_4h[-1]["time"])
        print(f"  4H: {len(candles_4h)} 根  1H: {len(candles_1h)} 根  ({start_ts} → {end_ts})")

    trader       = PaperTrader(initial_balance, risk_pct)
    total_signals = 0

    for i in range(MIN_4H_BARS, len(candles_4h) - 1):
        bar = candles_4h[i]

        # 1. 先用本棒更新已開部位（本棒期間是否觸發出場）
        if symbol in trader.positions:
            for ev in trader.check_bar(symbol, bar["high"], bar["low"], bar["time"]):
                if verbose:
                    print(f"  [{_fmt_ts(ev['close_ms'])}] {ev['reason']:3s}  "
                          f"{ev['direction']:5s}  PnL: ${ev['pnl']:>+9.2f}")

        # 2. 本棒收盤時掃描入場訊號（若無持倉）
        if symbol not in trader.positions:
            sub_1h = _align_1h(candles_1h, bar["time"])
            if len(sub_1h) < 60:
                continue

            result = scan_symbol(symbol, candles_4h[: i + 1], sub_1h)
            if result:
                score = score_setup(result)
                if passes_threshold(score):
                    total_signals += 1
                    if trader.open_position(result, score):
                        lvl = result["levels"]
                        if verbose:
                            print(f"  [{_fmt_ts(bar['time'])}] 開倉  {result['direction']:5s}  "
                                  f"@{lvl['entry']:.6g}  SL={lvl['stop_loss']:.6g}  "
                                  f"T1={lvl['target1']:.6g}  score={score}")

    # 回測結束：強制以最後一棒收盤平倉（若仍有持倉）
    if symbol in trader.positions:
        last = candles_4h[-1]
        ev = trader._close(symbol, last["close"], "END", last["time"])
        if verbose:
            print(f"  [{_fmt_ts(ev['close_ms'])}] END  "
                  f"{ev['direction']:5s}  PnL: ${ev['pnl']:>+9.2f}  (強制平倉)")

    stats = trader.get_stats()
    stats["symbol"]        = symbol
    stats["total_signals"] = total_signals
    return {"symbol": symbol, "stats": stats, "trades": trader.trade_history}


# ── 多幣種回測 ───────────────────────────────────────────────

def run_multi_backtest(
    symbols:         list[str],
    initial_balance: float = 10_000.0,
    risk_pct:        float = 0.02,
    verbose:         bool  = False,
) -> dict:
    results = []
    for i, sym in enumerate(symbols, 1):
        print(f"  [{i:>3}/{len(symbols)}] {sym}")
        r = run_backtest(sym, initial_balance, risk_pct, verbose)
        results.append(r)

    valid      = [r for r in results if "error" not in r]
    all_trades = [t for r in valid for t in r.get("trades", [])]

    if not all_trades:
        return {"results": results, "summary": {"total_trades": 0}}

    full   = [t for t in all_trades if t["full_close"]]
    wins   = [t for t in full if t["pnl"] > 0]
    losses = [t for t in full if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in all_trades)
    win_sum   = sum(t["pnl"] for t in wins)
    loss_sum  = sum(t["pnl"] for t in losses)

    summary = {
        "symbols_tested":     len(valid),
        "total_signals":      sum(r["stats"].get("total_signals", 0) for r in valid),
        "total_events":       len(all_trades),
        "full_closes":        len(full),
        "wins":               len(wins),
        "losses":             len(losses),
        "win_rate_pct":       round(len(wins) / len(full) * 100, 1) if full else 0,
        "total_pnl":          round(total_pnl, 2),
        "avg_pnl_per_close":  round(total_pnl / len(full), 2) if full else 0,
        "profit_factor":      round(abs(win_sum / loss_sum), 2) if loss_sum != 0 else None,
    }
    return {"results": results, "summary": summary}


# ── 報告輸出 ─────────────────────────────────────────────────

def print_backtest_report(result: dict) -> None:
    if "error" in result:
        print(f"\n[{result['symbol']}] 錯誤：{result['error']}")
        return

    s      = result["stats"]
    trades = result.get("trades", [])

    print(f"\n{'='*62}")
    print(f"  回測結果：{result['symbol']}")
    print(f"{'='*62}")
    print(f"  初始資金：  ${s['initial_balance']:>12,.2f}")
    print(f"  最終餘額：  ${s['current_balance']:>12,.2f}")
    print(f"  總損益：    ${s.get('total_pnl', 0.0):>+12,.2f}  ({s.get('total_return_pct', 0.0):+.2f}%)")
    print(f"  最大回撤：  {s.get('max_drawdown_pct', 0.0):.2f}%")
    print(f"  觸發訊號：  {s.get('total_signals', 0)} 次")
    print(f"  完整平倉：  {s.get('full_closes', 0)} 筆")
    print(f"  勝率：      {s.get('win_rate_pct', 0):.1f}%  (勝 {s.get('wins', 0)} / 敗 {s.get('losses', 0)})")
    print(f"  平均獲利：  ${s.get('avg_win', 0):>+12,.2f}")
    print(f"  平均虧損：  ${s.get('avg_loss', 0):>+12,.2f}")
    pf = s.get('profit_factor')
    print(f"  獲利因子：  {f'{pf:.2f}' if pf is not None else 'N/A'}")
    print(f"{'='*62}")

    if trades:
        print(f"\n  {'平倉時間':16s} {'方向':5s} {'原因':4s} {'損益':>11s}")
        print(f"  {'-'*16} {'-'*5} {'-'*4} {'-'*11}")
        for t in trades:
            ts = datetime.fromtimestamp(t["close_ms"] / 1000, tz=TW_TZ)
            print(f"  {ts:%Y/%m/%d %H:%M}  {t['direction']:5s}  {t['reason']:4s}  ${t['pnl']:>+10.2f}")


def print_multi_summary(results: dict) -> None:
    sm = results["summary"]
    rs = results["results"]

    print(f"\n{'幣種':<20s} {'訊號':>6s} {'平倉':>6s} {'勝率':>8s} {'損益':>13s} {'回撤':>8s}")
    print("-" * 65)
    for r in rs:
        if "error" in r:
            continue
        s   = r["stats"]
        sym = r["symbol"].replace("-USDT", "")
        print(f"{sym:<20s} {s.get('total_signals', 0):>6d} "
              f"{s['full_closes']:>6d} {s['win_rate_pct']:>7.1f}% "
              f"${s['total_pnl']:>+12,.2f} {s['max_drawdown_pct']:>7.2f}%")

    print(f"\n{'='*55}")
    print(f"  回測匯總")
    print(f"{'='*55}")
    print(f"  測試幣種：{sm['symbols_tested']}")
    print(f"  總訊號：  {sm['total_signals']}")
    print(f"  完整平倉：{sm['full_closes']}")
    print(f"  總勝率：  {sm['win_rate_pct']:.1f}%  (勝 {sm['wins']} / 敗 {sm['losses']})")
    print(f"  總損益：  ${sm['total_pnl']:+,.2f}")
    print(f"  每筆均損益：${sm['avg_pnl_per_close']:+,.2f}")
    pf = sm.get('profit_factor')
    print(f"  獲利因子：{f'{pf:.2f}' if pf is not None else 'N/A'}")
    print(f"{'='*55}")


# ── CLI 入口 ─────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "--top20":
        print("[回測] 取得合約清單...")
        symbols = get_contracts()[:20]
        print(f"[回測] 對前 {len(symbols)} 個交易對逐一回測...\n")
        results = run_multi_backtest(symbols, verbose=False)
        print_multi_summary(results)

    elif len(args) == 1:
        result = run_backtest(args[0], verbose=True)
        print_backtest_report(result)

    else:
        print(f"[回測] 對 {len(args)} 個交易對逐一回測...\n")
        results = run_multi_backtest(args, verbose=False)
        for r in results["results"]:
            print_backtest_report(r)
        print_multi_summary(results)
