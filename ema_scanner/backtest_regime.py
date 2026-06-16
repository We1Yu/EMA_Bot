"""
回測腳本：比較有/無 BTC Regime Filter 的勝率差異

使用方式：
  python backtest_regime.py              # 預設 30 個幣種
  python backtest_regime.py --all        # 全部幣種
  python backtest_regime.py --detail     # 附上每筆交易明細
"""

import bisect
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bingx        import get_contracts, get_klines
from fetch_data   import load as load_cached, DATA_DIR
from indicators   import ema_snapshot
from paper_trader import PaperTrader
from scanner      import scan_symbol
from scorer       import score_setup, passes_threshold

TW_TZ = timezone(timedelta(hours=8))

# ── 回測參數 ─────────────────────────────────────────────────
KLINES_4H    = 500
KLINES_1H    = 1500
WARMUP_BARS  = 210
INIT_BAL     = 10_000.0
MAX_SYMBOLS  = 30


def fmt_tw(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=TW_TZ).strftime("%Y/%m/%d %H:%M")


def print_stats(label: str, trader: PaperTrader, sigs: int) -> None:
    s  = trader.get_stats()
    fc = s.get("full_closes", 0)
    w  = s.get("wins", 0)
    l  = s.get("losses", 0)
    pf = s.get("profit_factor")
    print(f"\n  ┌─ {label}")
    print(f"  │  訊號觸發：{sigs:>4d} 個    已平倉：{fc} 筆  (勝 {w} / 敗 {l})")
    print(f"  │  勝率：     {s.get('win_rate_pct', 0):>5.1f}%")
    print(f"  │  總損益：   ${s.get('total_pnl', 0):>+12,.2f}")
    print(f"  │  最大回撤： {s.get('max_drawdown_pct', 0):.2f}%")
    print(f"  │  獲利因子： {f'{pf:.2f}' if pf else 'N/A'}")
    print(f"  │  平均獲利： ${s.get('avg_win', 0):>+10,.2f}")
    print(f"  └  平均虧損： ${s.get('avg_loss', 0):>+10,.2f}")


def main():
    show_detail = "--detail" in sys.argv
    use_all     = "--all"    in sys.argv

    print("=" * 64)
    print("  Regime Filter 回測比較")
    print("=" * 64)

    # 1. 幣種清單
    print("\n[1/4] 取得幣種清單...")
    all_syms = get_contracts()
    if not all_syms:
        print("      [錯誤] 無法取得合約清單"); return

    if use_all:
        symbols = all_syms
    else:
        priority = [s for s in ["BTC-USDT", "ETH-USDT"] if s in all_syms]
        others   = [s for s in all_syms if s not in priority]
        symbols  = (priority + others)[: MAX_SYMBOLS]
    print(f"      共 {len(symbols)} 個幣種")

    # 2. BTC 4H（Regime 判斷 + 主時間軸）
    print("\n[2/4] 抓取 BTC 4H K棒...")
    btc_4h = load_cached("BTC-USDT", "4H") or get_klines("BTC-USDT", "4H", KLINES_4H)
    if not btc_4h or len(btc_4h) < WARMUP_BARS:
        print("      [錯誤] BTC 資料不足"); return
    btc_emas = ema_snapshot(btc_4h)
    if not btc_emas:
        print("      [錯誤] BTC EMA 計算失敗"); return

    n_bars = len(btc_4h)
    span   = n_bars - WARMUP_BARS
    print(f"      {n_bars} 根 4H  |  {fmt_tw(btc_4h[WARMUP_BARS]['time'])} → {fmt_tw(btc_4h[-1]['time'])}")
    print(f"      有效模擬 bar：{span} 根（≈ {span*4//24} 天）")

    bear_bars = sum(
        1 for i in range(WARMUP_BARS, n_bars)
        if btc_emas["ema15"][i] is not None
        and btc_emas["ema60"][i] is not None
        and btc_emas["ema15"][i] < btc_emas["ema60"][i]
    )
    print(f"      BTC 空頭環境（EMA15<EMA60）：{bear_bars}/{span} 根（{bear_bars/span*100:.1f}%）")

    # 3. 各幣種資料
    has_cache = DATA_DIR.exists() and any(DATA_DIR.glob("*_4H.json"))
    src       = "本地快取" if has_cache else "BingX API"
    print(f"\n[3/4] 載入各幣種 K棒（{src}）...")

    sym_data: dict[str, dict] = {}
    for i, sym in enumerate(symbols, 1):
        c4h = (load_cached(sym, "4H") if has_cache else None) or get_klines(sym, "4H", KLINES_4H)
        c1h = (load_cached(sym, "1H") if has_cache else None) or get_klines(sym, "1H", KLINES_1H)
        if not has_cache:
            time.sleep(0.12)

        ok  = c4h and c1h and len(c4h) >= WARMUP_BARS and len(c1h) >= 60
        tag = f"4H:{len(c4h):>4d} 1H:{len(c1h):>4d}" if (c4h and c1h) else "資料不足"
        print(f"  [{i:3d}/{len(symbols)}] {sym:22s} {'OK  ' if ok else '跳過'}  {tag}")
        if ok:
            sym_data[sym] = {
                "c4h":       c4h,
                "c1h":       c1h,
                "c4h_times": [c["time"] for c in c4h],
                "c1h_times": [c["time"] for c in c1h],
            }

    print(f"\n      成功載入 {len(sym_data)} 個幣種")

    # 4. 逐 4H Bar 模擬（單一全局 PaperTrader，正確執行持倉上限）
    print(f"\n[4/4] 逐 4H Bar 模擬...")

    trader_w  = PaperTrader(INIT_BAL)   # 有 Regime Filter
    trader_wo = PaperTrader(INIT_BAL)   # 無 Regime Filter
    sig_w = sig_wo = 0
    blocked_signals: list[dict] = []    # 被 Regime Filter 擋掉的訊號

    for bar_idx in range(WARMUP_BARS, n_bars):
        bar_open_ms  = btc_4h[bar_idx]["time"]
        bar_close_ms = bar_open_ms + 4 * 3600 * 1000

        # BTC Regime
        e15 = btc_emas["ema15"][bar_idx]
        e60 = btc_emas["ema60"][bar_idx]
        regime = (e15 > e60) if (e15 is not None and e60 is not None) else True

        signals_w:  list[tuple] = []
        signals_wo: list[tuple] = []
        latest_bars: dict[str, dict] = {}

        for sym, d in sym_data.items():
            # 截取到當前時間點的 4H 資料
            i4h = bisect.bisect_right(d["c4h_times"], bar_open_ms) - 1
            if i4h < WARMUP_BARS - 1:
                continue
            c4h_use = d["c4h"][max(0, i4h - 249): i4h + 1]
            latest_bars[sym] = c4h_use[-1]

            # 截取當前 4H bar 收盤前的 1H 資料
            i1h_end = bisect.bisect_left(d["c1h_times"], bar_close_ms)
            if i1h_end < 60:
                continue
            c1h_use = d["c1h"][max(0, i1h_end - 100): i1h_end]
            if len(c1h_use) < 60:
                continue

            # 有 Regime Filter
            res_w = scan_symbol(sym, c4h_use, c1h_use, regime)
            if res_w:
                sc = score_setup(res_w, bar_open_ms)
                if passes_threshold(sc):
                    signals_w.append((res_w, sc))

            # 無 Regime Filter
            res_wo = scan_symbol(sym, c4h_use, c1h_use, True)
            if res_wo:
                sc = score_setup(res_wo, bar_open_ms)
                if passes_threshold(sc):
                    signals_wo.append((res_wo, sc))

            # 記錄被 Regime Filter 擋掉的山寨多單
            if (res_wo and not res_w and not regime
                    and res_wo["direction"] == "LONG"):
                sc_wo = score_setup(res_wo, bar_open_ms)
                if passes_threshold(sc_wo):
                    blocked_signals.append({
                        "symbol":    sym,
                        "bar_time":  bar_open_ms,
                        "strategy":  res_wo.get("strategy", ""),
                        "score":     sc_wo,
                    })

        # 先更新持倉（止盈止損）
        trader_w.update_positions(latest_bars)
        trader_wo.update_positions(latest_bars)

        # 再依分數高到低開新倉（持倉上限由 PaperTrader 自動控制）
        for res, sc in sorted(signals_w,  key=lambda x: x[1], reverse=True):
            if trader_w.open_position(res, sc):
                sig_w += 1

        for res, sc in sorted(signals_wo, key=lambda x: x[1], reverse=True):
            if trader_wo.open_position(res, sc):
                sig_wo += 1

        if bar_idx % 50 == 0:
            pct = (bar_idx - WARMUP_BARS) / span * 100
            print(f"  {pct:5.1f}%  bar {bar_idx}/{n_bars}  "
                  f"持倉W:{len(trader_w.positions)}  持倉WO:{len(trader_wo.positions)}  "
                  f"累積訊號 W:{sig_w} WO:{sig_wo}")

    # 5. 結果報告
    s_w  = trader_w.get_stats()
    s_wo = trader_wo.get_stats()

    print("\n" + "=" * 64)
    print("  回測結果比較")
    print("=" * 64)
    print_stats("有 Regime Filter", trader_w,  sig_w)
    print_stats("無 Regime Filter", trader_wo, sig_wo)

    wr_diff  = s_w.get("win_rate_pct", 0) - s_wo.get("win_rate_pct", 0)
    pnl_diff = s_w.get("total_pnl", 0)    - s_wo.get("total_pnl", 0)

    print("\n  " + "─" * 62)
    print(f"  Regime Filter 擋掉山寨多單：{len(blocked_signals)} 個訊號")
    print(f"  勝率差（有Filter - 無Filter）：{wr_diff:>+.1f}%")
    print(f"  損益差（有Filter - 無Filter）：${pnl_diff:>+,.2f}")
    print("=" * 64)

    # 6. 詳細明細
    if show_detail:
        print("\n【有 Regime Filter 詳細交易明細】")
        for t in sorted(trader_w.trade_history, key=lambda x: x["open_ms"]):
            if not t["full_close"]:
                continue
            print(f"  {fmt_tw(t['open_ms'])}  {t['symbol']:22s} {t['direction']:5s} "
                  f"{t['strategy']:20s}  {t['reason']:4s}  PnL: ${t['pnl']:>+10.2f}")

        if blocked_signals:
            print("\n【被 Regime Filter 擋掉的山寨多單訊號】")
            for b in blocked_signals:
                print(f"  {fmt_tw(b['bar_time'])}  {b['symbol']:22s} LONG  "
                      f"{b['strategy']:20s}  score={b['score']}")


if __name__ == "__main__":
    main()
