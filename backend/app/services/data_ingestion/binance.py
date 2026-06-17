"""
Binance Futures API 介接模組
負責取得合約清單、K 線資料與現價
"""

import time
import requests

BASE_URL      = "https://fapi.binance.com"
COINGECKO_URL = "https://api.coingecko.com/api/v3"

STABLECOIN_KEYWORDS = {
    "USDC", "BUSD", "TUSD", "FDUSD", "DAI",
    "USDD", "FRAX", "USDP", "GUSD", "SUSD",
}

MAX_RETRIES  = 3
RETRY_DELAY  = 2   # 秒

_rate_limit_until: float = 0.0


def _get(url: str, params: dict) -> dict | list | None:
    global _rate_limit_until
    now = time.time()
    if now < _rate_limit_until:
        remaining = int(_rate_limit_until - now)
        print(f"[Binance] 速率限制中，還需等待 {remaining} 秒")
        return None

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                _rate_limit_until = time.time() + retry_after
                print(f"[Binance] 速率限制（429），{retry_after} 秒後解除")
                return None
            if resp.status_code == 418:
                _rate_limit_until = time.time() + 3600
                print("[Binance] IP 被封鎖（418），等待 1 小時")
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"[Binance] 請求失敗 (第{attempt+1}次)：{e}，{RETRY_DELAY}秒後重試")
                time.sleep(RETRY_DELAY)
            else:
                print(f"[Binance] 請求失敗（已重試 {MAX_RETRIES} 次）：{e}")
    return None


def get_contracts() -> list[str]:
    """
    取得所有 USDT 永續合約交易對
    回傳格式：["BTCUSDT", "ETHUSDT", ...]
    """
    url  = f"{BASE_URL}/fapi/v1/exchangeInfo"
    data = _get(url, {})
    if not data:
        return []

    symbols = []
    for s in data.get("symbols", []):
        if s.get("contractType") != "PERPETUAL":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        if s.get("status") != "TRADING":
            continue
        base = s.get("baseAsset", "")
        if base.upper() in STABLECOIN_KEYWORDS:
            continue
        symbols.append(s["symbol"])
    return symbols


def get_ticker_price(symbol: str) -> float | None:
    """取得交易對現價"""
    url  = f"{BASE_URL}/fapi/v1/ticker/price"
    data = _get(url, {"symbol": symbol})
    if data:
        try:
            return float(data["price"])
        except (KeyError, TypeError, ValueError):
            pass
    candles = get_klines(symbol, "1h", 1)
    if candles:
        return candles[-1]["close"]
    return None


def _parse_candles(raw: list) -> list[dict]:
    """
    Binance klines 格式：
    [open_time, open, high, low, close, volume, close_time, ...]
    """
    candles = []
    for bar in raw:
        try:
            candles.append({
                "time":   int(bar[0]),
                "open":   float(bar[1]),
                "high":   float(bar[2]),
                "low":    float(bar[3]),
                "close":  float(bar[4]),
                "volume": float(bar[5]),
            })
        except (IndexError, TypeError, ValueError):
            continue
    return candles


def get_klines(symbol: str, interval: str, limit: int) -> list[dict] | None:
    """
    取得指定交易對的 K 線資料
    interval: "1h" 或 "4h"（Binance 使用小寫，傳入大寫也可）
    回傳列表，每筆包含 time/open/high/low/close/volume
    """
    url    = f"{BASE_URL}/fapi/v1/klines"
    params = {
        "symbol":   symbol,
        "interval": interval.lower(),
        "limit":    min(limit, 1500),   # Binance 單次上限 1500
    }
    data = _get(url, params)
    if not data:
        return None

    candles = _parse_candles(data)
    candles.sort(key=lambda x: x["time"])
    return candles if candles else None


def get_klines_paginated(
    symbol:    str,
    interval:  str,
    total:     int,
    page_size: int   = 1000,
    delay:     float = 0.2,
) -> list[dict] | None:
    """
    分頁向前抓取歷史 K 棒，突破單次 limit 上限。
    使用 endTime 往過去疊加，直到取得 total 根或沒有更早資料。
    """
    url      = f"{BASE_URL}/fapi/v1/klines"
    iv_lower = interval.lower()
    all_bars: dict[int, dict] = {}
    end_time_ms: int | None   = None

    while len(all_bars) < total:
        params: dict = {
            "symbol":   symbol,
            "interval": iv_lower,
            "limit":    min(page_size, 1500),
        }
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        data = _get(url, params)
        if not data:
            break

        page = _parse_candles(data)
        if not page:
            break

        before = len(all_bars)
        for bar in page:
            all_bars[bar["time"]] = bar

        if len(all_bars) == before:
            break

        end_time_ms = min(b["time"] for b in page) - 1

        if len(all_bars) >= total:
            break

        time.sleep(delay)

    if not all_bars:
        return None

    candles = sorted(all_bars.values(), key=lambda x: x["time"])
    return candles[-total:] if len(candles) > total else candles
