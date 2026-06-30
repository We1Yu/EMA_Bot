"""
歷史 K 棒下載腳本
從 BingX 抓取資料並存成本地 JSON，供回測腳本離線使用。

使用方式：
  python fetch_data.py                   # 下載預設幣種清單（4H×1500根、1H×3000根）
  python fetch_data.py --all             # 下載所有 USDT 永續合約
  python fetch_data.py BTC-USDT ETH-USDT SOL-USDT   # 指定幣種

下載後執行回測：
  python backtest_regime.py              # 自動優先讀本地快取
"""

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bingx import get_contracts, get_klines_paginated

TW_TZ    = timezone(timedelta(hours=8))
DATA_DIR = Path(__file__).parent / "data"

# ── 下載參數 ─────────────────────────────────────────────────
TARGET_4H   = 1500   # 目標 4H 根數（≈ 250 天）
TARGET_1H   = 4000   # 目標 1H 根數（≈ 167 天）
PAGE_SIZE   =  500   # 每次 API 呼叫根數
API_DELAY   =  0.25  # 每次請求間隔秒數

# 預設幣種清單（沒指定時使用）
DEFAULT_SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT",
    "XRP-USDT", "DOGE-USDT", "ADA-USDT", "AVAX-USDT",
    "LINK-USDT", "DOT-USDT", "TRX-USDT", "MATIC-USDT",
    "LTC-USDT", "UNI-USDT", "ATOM-USDT", "FIL-USDT",
    "NEAR-USDT", "APT-USDT", "ARB-USDT", "OP-USDT",
]


def fmt_tw(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=TW_TZ).strftime("%Y/%m/%d")


def save(symbol: str, interval: str, candles: list[dict]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fname = DATA_DIR / f"{symbol.replace('-', '_')}_{interval}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(candles, f)
    return fname


def load(symbol: str, interval: str) -> list[dict] | None:
    fname = DATA_DIR / f"{symbol.replace('-', '_')}_{interval}.json"
    if not fname.exists():
        return None
    with open(fname, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_symbol(symbol: str, verbose: bool = True) -> bool:
    """下載單一幣種的 4H 和 1H 資料，回傳是否成功"""
    ok_4h = ok_1h = False

    for interval, target in [("4H", TARGET_4H), ("1H", TARGET_1H)]:
        candles = get_klines_paginated(symbol, interval, target, PAGE_SIZE, API_DELAY)
        if candles:
            path = save(symbol, interval, candles)
            span = f"{fmt_tw(candles[0]['time'])} → {fmt_tw(candles[-1]['time'])}"
            if verbose:
                print(f"    {interval}  {len(candles):>4d} 根  {span}  → {path.name}")
            if interval == "4H":
                ok_4h = True
            else:
                ok_1h = True
        else:
            if verbose:
                print(f"    {interval}  [失敗]")
        time.sleep(API_DELAY)

    return ok_4h and ok_1h


def main():
    # 決定幣種清單
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_all = "--all" in sys.argv

    if args:
        symbols = args
    elif use_all:
        print("取得所有合約清單...")
        symbols = get_contracts()
        if not symbols:
            print("[錯誤] 無法取得合約清單"); return
    else:
        symbols = DEFAULT_SYMBOLS

    print("=" * 62)
    print(f"  BingX 歷史資料下載")
    print(f"  目標：{len(symbols)} 個幣種  4H×{TARGET_4H}根  1H×{TARGET_1H}根")
    print(f"  存放目錄：{DATA_DIR}")
    print("=" * 62)

    success = 0
    fail    = 0
    t0      = time.time()

    for i, sym in enumerate(symbols, 1):
        print(f"\n[{i:3d}/{len(symbols)}] {sym}")
        if fetch_symbol(sym):
            success += 1
        else:
            fail += 1

    elapsed = time.time() - t0
    print(f"\n{'='*62}")
    print(f"  完成  成功：{success}  失敗：{fail}  耗時：{elapsed:.0f} 秒")
    print(f"  執行回測：python backtest_regime.py")
    print(f"{'='*62}")


if __name__ == "__main__":
    main()
