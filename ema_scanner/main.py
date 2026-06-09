"""
主排程迴圈
- 每 60 分鐘執行一次掃描
- 在 4H K線收盤時（UTC 00/04/08/12/16/20）立即額外觸發
- 同一幣種 4 小時內不重複推播
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from bingx       import get_contracts, get_klines
from scanner     import scan_symbol
from scorer      import score_setup, passes_threshold
from discord_bot import send_setup_alerts, send_no_setup_summary
from paper_trader import PaperTrader

# ── 常數設定 ──────────────────────────────────────────────
STATE_FILE      = Path(__file__).parent / "state.json"
SIGNALS_LOG     = Path(__file__).parent / "signals_log.json"
SCAN_INTERVAL   = 60 * 60          # 60 分鐘（秒）
DEDUP_WINDOW    = 4 * 60 * 60      # 4 小時去重窗口（秒）
KLINES_4H_LIMIT = 250   # EMA200 需要足夠歷史資料（至少 200 根）
KLINES_1H_LIMIT = 50
TW_TZ           = timezone(timedelta(hours=8))


# ── 去重狀態管理 ──────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_duplicate(state: dict, symbol: str) -> bool:
    """檢查該幣種是否在去重窗口內已推播過"""
    last_ts = state.get(symbol)
    if last_ts is None:
        return False
    return (time.time() - last_ts) < DEDUP_WINDOW


def mark_alerted(state: dict, symbol: str) -> None:
    state[symbol] = time.time()


def log_signal(result: dict, score: float) -> None:
    """將達標訊號寫入 signals_log.json 供網頁儀表板讀取"""
    try:
        existing: list = json.loads(SIGNALS_LOG.read_text(encoding="utf-8")) if SIGNALS_LOG.exists() else []
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


def prune_state(state: dict) -> dict:
    """清除過期的去重記錄"""
    now = time.time()
    return {k: v for k, v in state.items() if now - v < DEDUP_WINDOW}


# ── 4H 收盤時間偵測 ───────────────────────────────────────
def next_4h_close_utc() -> datetime:
    """回傳下一個 4H K線收盤的 UTC 時間點"""
    now = datetime.now(timezone.utc)
    hour_bucket = (now.hour // 4) * 4
    base = now.replace(hour=hour_bucket, minute=0, second=0, microsecond=0)
    candidate = base + timedelta(hours=4)
    if candidate <= now:
        candidate += timedelta(hours=4)
    return candidate


# ── 核心掃描函式 ──────────────────────────────────────────
def run_scan() -> None:
    now_tw = datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M TWN")
    print(f"\n[掃描開始] {now_tw}")

    # 取得所有合約
    symbols = get_contracts()
    if not symbols:
        print("[錯誤] 無法取得合約清單，本次掃描跳過")
        return

    print(f"[資訊] 共取得 {len(symbols)} 個交易對")

    state  = load_state()
    state  = prune_state(state)
    trader = PaperTrader.load()

    qualified     = []   # (result, score)
    converging    = 0
    total         = len(symbols)
    latest_bar_4h: dict[str, dict] = {}  # symbol → 最新 4H K棒（供部位更新用）

    for i, symbol in enumerate(symbols, 1):
        # 取得 K 線
        candles_4h = get_klines(symbol, "4H", KLINES_4H_LIMIT)
        candles_1h = get_klines(symbol, "1H", KLINES_1H_LIMIT)
        if candles_4h is None or candles_1h is None:
            continue

        latest_bar_4h[symbol] = candles_4h[-1]

        # 掃描邏輯
        result = scan_symbol(symbol, candles_4h, candles_1h)
        if result is None:
            continue

        converging += 1

        # 評分
        score = score_setup(result)
        if not passes_threshold(score):
            continue

        # 去重檢查
        if is_duplicate(state, symbol):
            print(f"  [跳過重複] {symbol}  score={score}")
            continue

        print(f"  [訊號] {symbol}  {result['direction']}  score={score}")
        qualified.append((result, score))
        mark_alerted(state, symbol)
        log_signal(result, score)

        # 每處理 20 個印出進度
        if i % 20 == 0:
            print(f"  ... 已掃描 {i}/{total}")

    save_state(state)

    # ── 紙上帳戶更新 ──────────────────────────────────────────
    # 對持倉中但未在本輪掃描的幣種補取最新 K 線
    for sym in list(trader.positions.keys()):
        if sym not in latest_bar_4h:
            extra = get_klines(sym, "4H", 5)
            if extra:
                latest_bar_4h[sym] = extra[-1]

    # 更新所有持倉（止損/止盈檢查）
    exit_events = trader.update_positions(latest_bar_4h)
    for ev in exit_events:
        print(f"  [紙倉出場] {ev['symbol']:20s}  {ev['reason']}  PnL: ${ev['pnl']:>+.2f}")

    # 開新虛擬倉（依分數降序）
    qualified.sort(key=lambda x: x[1], reverse=True)
    for result, score in qualified:
        if trader.open_position(result, score):
            lvl = result["levels"]
            print(f"  [紙倉開倉] {result['symbol']:20s}  {result['direction']}  "
                  f"@{lvl['entry']:.6g}  SL={lvl['stop_loss']:.6g}  score={score}")

    trader.save()
    trader.print_report()

    # 發送通知
    if qualified:
        send_setup_alerts(qualified)
        print(f"[完成] 發送 {len(qualified)} 個訊號")
    else:
        send_no_setup_summary(total, converging)
        print(f"[完成] 無達標訊號（收斂中：{converging}）")


# ── 排程主迴圈 ────────────────────────────────────────────
def main() -> None:
    print("=" * 50)
    print("  EMA Convergence Scanner 啟動")
    print("  掃描間隔：60 分鐘")
    print("  額外觸發：4H K線收盤時")
    print("=" * 50)

    # 立刻執行一次
    run_scan()

    last_scan_ts   = time.time()
    last_4h_window = datetime.now(timezone.utc).hour // 4  # 當前所屬 4H 窗口

    while True:
        time.sleep(30)  # 每 30 秒檢查一次觸發條件

        now_utc       = datetime.now(timezone.utc)
        current_4h_w  = now_utc.hour // 4
        elapsed       = time.time() - last_scan_ts

        # 觸發條件一：超過 60 分鐘
        triggered_by_interval = elapsed >= SCAN_INTERVAL

        # 觸發條件二：進入新的 4H 窗口（K線剛收盤）
        triggered_by_4h_close = current_4h_w != last_4h_window

        if triggered_by_interval or triggered_by_4h_close:
            if triggered_by_4h_close:
                print(f"[觸發] 新 4H K線收盤（UTC 窗口 {current_4h_w * 4:02d}:00）")
            last_4h_window = current_4h_w
            last_scan_ts   = time.time()
            run_scan()


if __name__ == "__main__":
    main()
