"""
BingX API 介接模組
負責取得合約清單與K線資料
"""

import time
import requests

BASE_URL = "https://open-api.bingx.com"

# 穩定幣關鍵字，用於過濾
STABLECOIN_KEYWORDS = {"USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USDD", "FRAX", "USDP", "GUSD", "SUSD"}

MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒


def _get(url: str, params: dict) -> dict | None:
    """帶重試機制的 GET 請求"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 0:
                return data
            # 合約暫停（109415）→ 靜默略過，不印錯誤
            if data.get("code") == 109415:
                return None
            # 其他業務錯誤才印出
            print(f"[BingX] 業務錯誤 code={data.get('code')} msg={data.get('msg')}")
            return None
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"[BingX] 請求失敗 (第{attempt+1}次)：{e}，{RETRY_DELAY}秒後重試")
                time.sleep(RETRY_DELAY)
            else:
                print(f"[BingX] 請求失敗（已重試 {MAX_RETRIES} 次）：{e}")
    return None


def get_contracts() -> list[str]:
    """
    取得所有 USDT 永續合約交易對
    排除穩定幣對穩定幣的交易對
    回傳格式：["BTCUSDT", "ETHUSDT", ...]
    """
    url = f"{BASE_URL}/openApi/swap/v2/quote/contracts"
    data = _get(url, {})
    if not data:
        return []

    symbols = []
    for contract in data.get("data", []):
        symbol: str = contract.get("symbol", "")
        # 只要 USDT 永續合約
        if not symbol.endswith("-USDT"):
            continue
        base = symbol.replace("-USDT", "")
        # 過濾穩定幣
        if base.upper() in STABLECOIN_KEYWORDS:
            continue
        # BingX K線 API 使用 BTC-USDT 格式（保留連字號）
        symbols.append(symbol)
    return symbols


def _get_quiet(url: str, params: dict) -> dict | None:
    """不印錯誤的 GET，用於非必要資料（OI / 多空比）"""
    try:
        resp = requests.get(url, params=params, timeout=6)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0:
            return data
    except Exception:
        pass
    return None


def _parse_float(d: dict, *keys) -> float | None:
    """依序嘗試多個 key，回傳第一個有效正浮點數"""
    for k in keys:
        try:
            v = float(d.get(k) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return None


def get_oi_history(symbol: str, period: str = "1h", limit: int = 6) -> list[dict] | None:
    """
    取得未平倉合約歷史（OI）
    回傳列表 [{"oi": float, "time": int}, ...]，按時間升序
    """
    url  = f"{BASE_URL}/openApi/swap/v2/quote/openInterestHist"
    data = _get_quiet(url, {"symbol": symbol, "period": period, "limit": limit})
    if not data:
        return None
    raw = data.get("data") or []
    result = []
    for item in raw:
        oi = _parse_float(item, "openInterest", "sumOpenInterest", "oi")
        ts = item.get("timestamp") or item.get("time") or 0
        if oi and ts:
            result.append({"oi": oi, "time": int(ts)})
    if len(result) < 2:
        return None
    result.sort(key=lambda x: x["time"])
    return result


def get_long_short_ratio(symbol: str, period: str = "1h", limit: int = 6) -> list[dict] | None:
    """
    取得多空帳戶比例歷史
    回傳列表 [{"long_pct": float(0~1), "time": int}, ...]，按時間升序
    long_pct = 多頭帳戶佔比（0.55 = 55% 多頭）
    """
    url  = f"{BASE_URL}/openApi/swap/v2/quote/longShortAccountRatio"
    data = _get_quiet(url, {"symbol": symbol, "period": period, "limit": limit})
    if not data:
        return None
    raw = data.get("data") or []
    result = []
    for item in raw:
        # BingX 可能用 longShortRatio（比值）或 longAccount（分數）
        ts = item.get("timestamp") or item.get("time") or 0
        long_pct = None
        # 先嘗試分數形式 (0~1)
        for k in ("longAccount", "longRatio", "buyRatio"):
            v = _parse_float(item, k)
            if v is not None and 0 < v < 1:
                long_pct = v
                break
        # 再嘗試比值形式 (e.g. 1.5 → 60%)
        if long_pct is None:
            ratio = _parse_float(item, "longShortRatio", "ratio")
            if ratio is not None:
                long_pct = ratio / (1.0 + ratio)
        if long_pct and ts:
            result.append({"long_pct": long_pct, "time": int(ts)})
    if len(result) < 2:
        return None
    result.sort(key=lambda x: x["time"])
    return result


def get_ticker_price(symbol: str) -> float | None:
    """
    取得交易對現價（mark price 為主，fallback 到最新 1H K 線收盤價）
    """
    url  = f"{BASE_URL}/openApi/swap/v2/quote/ticker"
    data = _get(url, {"symbol": symbol})
    if data:
        item = data.get("data")
        items = item if isinstance(item, list) else ([item] if isinstance(item, dict) else [])
        for it in items:
            for key in ("lastPrice", "markPrice", "price"):
                try:
                    v = float(it.get(key) or 0)
                    if v > 0:
                        return v
                except (TypeError, ValueError):
                    pass
    # fallback：最後一根 1H K 線
    candles = get_klines(symbol, "1H", 1)
    if candles:
        return candles[-1]["close"]
    return None


def get_klines(symbol: str, interval: str, limit: int) -> list[dict] | None:
    """
    取得指定交易對的K線資料
    interval: "1H" 或 "4H"
    回傳列表，每筆包含 open/high/low/close/volume
    """
    url = f"{BASE_URL}/openApi/swap/v3/quote/klines"
    params = {
        "symbol": symbol,
        "interval": interval.lower(),   # API 要求小寫（4h / 1h）
        "limit": limit,
    }
    data = _get(url, params)
    if not data:
        return None

    raw = data.get("data", [])
    if not raw:
        return None

    candles = []
    for bar in raw:
        try:
            candles.append({
                "open":   float(bar["open"]),
                "high":   float(bar["high"]),
                "low":    float(bar["low"]),
                "close":  float(bar["close"]),
                "volume": float(bar["volume"]),
                "time":   int(bar["time"]),   # K線時間戳（毫秒）
            })
        except (KeyError, TypeError, ValueError):
            continue

    # 依時間升序排列（最舊 → 最新）
    candles.sort(key=lambda x: x["time"])
    return candles if candles else None
