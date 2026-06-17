"""
歷史 K 棒下載腳本（Binance Futures）
從 Binance 抓取資料並存成本地 JSON，供回測腳本離線使用。

使用方式（從 backend/ 目錄執行）：
  python -m app.services.data_ingestion.fetch_data
  python -m app.services.data_ingestion.fetch_data --all
  python -m app.services.data_ingestion.fetch_data BTCUSDT ETHUSDT SOLUSDT
"""

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.services.data_ingestion.binance import get_contracts, get_klines_paginated
from app.core.config import KLINES_CACHE_DIR

TW_TZ = timezone(timedelta(hours=8))

TARGET_4H  = 1500
TARGET_1H  = 4000
PAGE_SIZE  = 1000
API_DELAY  = 0.25

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT", "TRXUSDT", "MATICUSDT",
    "LTCUSDT", "UNIUSDT", "ATOMUSDT", "FILUSDT",
    "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
]


def fmt_tw(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=TW_TZ).strftime("%Y/%m/%d")


def save(symbol: str, interval: str, candles: list[dict]) -> Path:
    KLINES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fname = KLINES_CACHE_DIR / f"{symbol}_{interval}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(candles, f)
    return fname


def load(symbol: str, interval: str) -> list[dict] | None:
    fname = KLINES_CACHE_DIR / f"{symbol}_{interval}.json"
    if not fname.exists():
        return None
    with open(fname, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_symbol(symbol: str, verbose: bool = True) -> bool:
    ok_4h = ok_1h = False
    for interval, target in [("4h", TARGET_4H), ("1h", TARGET_1H)]:
        candles = get_klines_paginated(symbol, interval, target, PAGE_SIZE, API_DELAY)
        if candles:
            path = save(symbol, interval, candles)
            span = f"{fmt_tw(candles[0]['time'])} → {fmt_tw(candles[-1]['time'])}"
            if verbose:
                print(f"    {interval}  {len(candles):>4d} 根  {span}  → {path.name}")
            if interval == "4h":
                ok_4h = True
            else:
                ok_1h = True
        else:
            if verbose:
                print(f"    {interval}  [失敗]")
        time.sleep(API_DELAY)
    return ok_4h and ok_1h


def main():
    args    = [a for a in sys.argv[1:] if not a.startswith("--")]
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
    print(f"  Binance Futures 歷史資料下載")
    print(f"  目標：{len(symbols)} 個幣種  4h×{TARGET_4H}根  1h×{TARGET_1H}根")
    print(f"  存放目錄：{KLINES_CACHE_DIR}")
    print("=" * 62)

    success = fail = 0
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
    print(f"  執行回測：python -m app.services.backtest.engine")
    print(f"{'='*62}")


if __name__ == "__main__":
    main()
