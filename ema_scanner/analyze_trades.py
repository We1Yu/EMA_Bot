"""
分析回測交易明細：區分「事件型虧損」vs「正常市場虧損」
事件型 = 同一個 4H bar 有 2+ 筆同方向 SL（市場瞬間大幅波動）
"""
import sys
import time
import bisect
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from bingx        import get_contracts, get_klines
from fetch_data   import load as load_cached, DATA_DIR
from indicators   import ema_snapshot
from paper_trader import PaperTrader
from scanner      import scan_symbol
from scorer       import score_setup, passes_threshold

TW_TZ = timezone(timedelta(hours=8))
KLINES_4H   = 500
KLINES_1H   = 1500
WARMUP_BARS = 210
INIT_BAL    = 10_000.0
MAX_SYMBOLS = 30

def fmt_tw(ms):
    return datetime.fromtimestamp(ms / 1000, tz=TW_TZ).strftime("%Y/%m/%d %H:%M")

def main():
    print("=" * 70)
    print("  交易事件分析：正常 vs 事件型虧損")
    print("=" * 70)

    all_syms = get_contracts()
    priority = [s for s in ["BTC-USDT", "ETH-USDT"] if s in all_syms]
    others   = [s for s in all_syms if s not in priority]
    symbols  = (priority + others)[:MAX_SYMBOLS]

    btc_4h = load_cached("BTC-USDT", "4H") or get_klines("BTC-USDT", "4H", KLINES_4H)
    btc_emas = ema_snapshot(btc_4h)
    n_bars = len(btc_4h)
    span   = n_bars - WARMUP_BARS

    has_cache = DATA_DIR.exists() and any(DATA_DIR.glob("*_4H.json"))
    sym_data = {}
    for sym in symbols:
        c4h = (load_cached(sym, "4H") if has_cache else None) or get_klines(sym, "4H", KLINES_4H)
        c1h = (load_cached(sym, "1H") if has_cache else None) or get_klines(sym, "1H", KLINES_1H)
        if not has_cache:
            time.sleep(0.12)
        if c4h and c1h and len(c4h) >= WARMUP_BARS and len(c1h) >= 60:
            sym_data[sym] = {
                "c4h": c4h, "c1h": c1h,
                "c4h_times": [c["time"] for c in c4h],
                "c1h_times": [c["time"] for c in c1h],
            }

    trader = PaperTrader(INIT_BAL)
    sig_count = 0

    for bar_idx in range(WARMUP_BARS, n_bars):
        bar_open_ms  = btc_4h[bar_idx]["time"]
        bar_close_ms = bar_open_ms + 4 * 3600 * 1000
        e15 = btc_emas["ema15"][bar_idx]
        e60 = btc_emas["ema60"][bar_idx]
        regime = (e15 > e60) if (e15 is not None and e60 is not None) else True

        signals = []
        latest_bars = {}
        for sym, d in sym_data.items():
            i4h = bisect.bisect_right(d["c4h_times"], bar_open_ms) - 1
            if i4h < WARMUP_BARS - 1:
                continue
            c4h_use = d["c4h"][max(0, i4h - 249): i4h + 1]
            latest_bars[sym] = c4h_use[-1]

            i1h_end = bisect.bisect_left(d["c1h_times"], bar_close_ms)
            if i1h_end < 60:
                continue
            c1h_use = d["c1h"][max(0, i1h_end - 100): i1h_end]
            if len(c1h_use) < 60:
                continue

            res = scan_symbol(sym, c4h_use, c1h_use, regime)
            if res:
                sc = score_setup(res, bar_open_ms)
                if passes_threshold(sc):
                    signals.append((res, sc))

        trader.update_positions(latest_bars)
        for res, sc in sorted(signals, key=lambda x: x[1], reverse=True):
            if trader.open_position(res, sc):
                sig_count += 1

    # 分析結果
    trades = [t for t in trader.trade_history if t["full_close"]]

    # 按 bar 時間分組，找事件型（同一 bar_open_ms 有 2+ 筆同方向 SL）
    by_bar_dir: dict[tuple, list] = defaultdict(list)
    for t in trades:
        key = (t["open_ms"], t["direction"])
        by_bar_dir[key].append(t)

    # 標記事件型
    event_bars = set()
    for key, group in by_bar_dir.items():
        sls = [t for t in group if t["reason"] == "SL"]
        if len(sls) >= 2:
            event_bars.add(key)

    # 找「同一 4H 收盤時間」多筆 SL（用 close_ms）
    by_close: dict[tuple, list] = defaultdict(list)
    for t in trades:
        key = (t["close_ms"], t["direction"])
        by_close[key].append(t)

    event_close_keys = set()
    for key, group in by_close.items():
        sls = [t for t in group if t["reason"] == "SL"]
        if len(sls) >= 2:
            event_close_keys.add(key)

    print(f"\n總交易數：{sig_count} 個訊號，已平倉：{len(trades)} 筆")

    # 分類統計
    normal_wins = normal_losses = normal_be = 0
    event_wins  = event_losses  = event_be  = 0
    event_detail = []

    for t in trades:
        key = (t["close_ms"], t["direction"])
        is_event = key in event_close_keys

        if t["reason"] == "TP1" or t["reason"] == "TP2":
            result = "WIN"
        elif t["reason"] == "SL":
            result = "LOSS"
        else:
            result = "BE"  # 套保

        if is_event:
            if result == "WIN":  event_wins += 1
            elif result == "LOSS": event_losses += 1
            else: event_be += 1
            event_detail.append(t)
        else:
            if result == "WIN":  normal_wins += 1
            elif result == "LOSS": normal_losses += 1
            else: normal_be += 1

    total_wins   = normal_wins + event_wins
    total_losses = normal_losses + event_losses

    print(f"\n{'─'*70}")
    print(f"  【全部交易】勝率 = {total_wins}/{total_wins+total_losses} = {total_wins/(total_wins+total_losses)*100:.1f}%")
    print(f"  (含套保) 全部 {len(trades)} 筆：{total_wins} 勝 / {total_losses} 敗 / {normal_be+event_be} 平")

    print(f"\n{'─'*70}")
    normal_total = normal_wins + normal_losses
    if normal_total > 0:
        print(f"  【正常市場交易】（排除群發 SL 事件）")
        print(f"  共 {normal_total+normal_be} 筆：{normal_wins} 勝 / {normal_losses} 敗 / {normal_be} 平")
        print(f"  勝率 = {normal_wins}/{normal_total} = {normal_wins/normal_total*100:.1f}%")

    print(f"\n{'─'*70}")
    event_total = event_wins + event_losses
    if event_total > 0:
        print(f"  【事件型交易】（2+ 筆同方向同時 SL）")
        print(f"  共 {event_total+event_be} 筆：{event_wins} 勝 / {event_losses} 敗 / {event_be} 平")
        print(f"  勝率 = {event_wins}/{event_total} = {event_wins/event_total*100:.1f}%")

    # 列出所有事件
    print(f"\n{'─'*70}")
    print("  【事件型群發時間點】")
    seen_keys = set()
    for key in sorted(event_close_keys):
        close_ms, direction = key
        if key in seen_keys:
            continue
        seen_keys.add(key)
        group = [t for t in event_detail
                 if t["close_ms"] == close_ms and t["direction"] == direction]
        wins  = sum(1 for t in group if t["reason"] in ("TP1","TP2"))
        loses = sum(1 for t in group if t["reason"] == "SL")
        symbols_list = ", ".join(t["symbol"] for t in group)
        print(f"  {fmt_tw(close_ms)} | {direction:5s} | {wins}勝 {loses}敗 | {symbols_list}")

    print(f"\n{'─'*70}")
    print("  結論：")
    print(f"  → 排除市場事件後勝率 {normal_wins/(normal_total)*100:.1f}%，"
          f"比整體 {total_wins/(total_wins+total_losses)*100:.1f}% 高出 "
          f"{normal_wins/normal_total*100 - total_wins/(total_wins+total_losses)*100:.1f}%")
    print(f"  → 事件型虧損共 {event_losses} 筆，佔全部虧損的 {event_losses/total_losses*100:.0f}%")
    print("=" * 70)


if __name__ == "__main__":
    main()
