"""
技術指標計算模組
手動實作 EMA、ATR、帶寬，不依賴 pandas 或 TA-Lib
"""


def calc_ema(closes: list[float], period: int) -> list[float]:
    """
    計算指數移動平均線
    以前 N 根K線的 SMA 作為種子值
    回傳長度與輸入相同（前 period-1 個值為 None）
    """
    if len(closes) < period:
        return [None] * len(closes)

    multiplier = 2.0 / (period + 1)
    result = [None] * len(closes)

    # 種子：前 period 根的 SMA
    seed = sum(closes[:period]) / period
    result[period - 1] = seed

    for i in range(period, len(closes)):
        result[i] = closes[i] * multiplier + result[i - 1] * (1 - multiplier)

    return result


def calc_atr(candles: list[dict], period: int = 14) -> list[float | None]:
    """
    計算真實波動幅度均值 (ATR)
    candles 每筆需有 high / low / close
    """
    if len(candles) < period + 1:
        return [None] * len(candles)

    # True Range
    trs = [None]  # 第一根無前收
    for i in range(1, len(candles)):
        high  = candles[i]["high"]
        low   = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    result = [None] * len(candles)
    # 初始 ATR = 前 period 個 TR 的 SMA
    valid_trs = [t for t in trs[1:period + 1] if t is not None]
    if len(valid_trs) < period:
        return result

    atr = sum(valid_trs) / period
    result[period] = atr

    for i in range(period + 1, len(candles)):
        if trs[i] is not None:
            atr = (atr * (period - 1) + trs[i]) / period
            result[i] = atr

    return result


def calc_bandwidth(ema15: float, ema30: float, ema45: float, ema60: float) -> float:
    """
    計算短期 EMA 群帶寬（相對於 EMA60 的百分比）
    """
    high = max(ema15, ema30, ema45, ema60)
    low  = min(ema15, ema30, ema45, ema60)
    if ema60 == 0:
        return 0.0
    return (high - low) / ema60 * 100


def ema_snapshot(candles: list[dict]) -> dict | None:
    """
    一次計算所有所需 EMA 並回傳最近幾根K線的快照
    回傳 dict 包含各 EMA 的最新值列表（方便比較相鄰 bar）
    """
    closes = [c["close"] for c in candles]

    e15  = calc_ema(closes, 15)
    e30  = calc_ema(closes, 30)
    e45  = calc_ema(closes, 45)
    e60  = calc_ema(closes, 60)
    e200 = calc_ema(closes, 200)

    # EMA200 需要 200 根以上，短時間 K 線可能不足（不強制要求）
    idx = len(closes) - 1
    if any(v is None for v in [e15[idx], e30[idx], e45[idx], e60[idx]]):
        return None

    return {
        "ema15":  e15,
        "ema30":  e30,
        "ema45":  e45,
        "ema60":  e60,
        "ema200": e200,
    }


def calc_bollinger(
    closes: list[float],
    period: int = 20,
    std_mult: float = 2.0,
) -> dict:
    """
    Bollinger Bands
    回傳 {"upper": [...], "middle": [...], "lower": [...], "width": [...]}
    width = (upper - lower) / middle × 100 (%)
    """
    n = len(closes)
    upper  = [None] * n
    middle = [None] * n
    lower  = [None] * n
    width  = [None] * n
    for i in range(period - 1, n):
        w   = closes[i - period + 1: i + 1]
        m   = sum(w) / period
        std = (sum((x - m) ** 2 for x in w) / period) ** 0.5
        upper[i]  = m + std_mult * std
        middle[i] = m
        lower[i]  = m - std_mult * std
        width[i]  = (upper[i] - lower[i]) / m * 100 if m > 0 else 0.0
    return {"upper": upper, "middle": middle, "lower": lower, "width": width}


def calc_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """RSI（相對強弱指標）"""
    result = [None] * len(closes)
    if len(closes) <= period:
        return result
    gains  = [0.0] * len(closes)
    losses = [0.0] * len(closes)
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains[i] = diff
        else:
            losses[i] = -diff
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    if avg_loss == 0:
        result[period] = 100.0
    else:
        result[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            result[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return result


def calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict:
    """
    MACD 指標
    回傳 {"macd": [...], "signal": [...], "histogram": [...]}，長度與 closes 相同，不足處為 None
    """
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    macd_line = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    valid_idxs = [i for i, v in enumerate(macd_line) if v is not None]
    signal_line = [None] * len(closes)
    if len(valid_idxs) >= signal:
        macd_vals = [macd_line[i] for i in valid_idxs]
        sig_ema   = calc_ema(macd_vals, signal)
        for j, idx in enumerate(valid_idxs):
            signal_line[idx] = sig_ema[j]
    histogram = [
        (m - s) if m is not None and s is not None else None
        for m, s in zip(macd_line, signal_line)
    ]
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def body_ratio(candle: dict) -> float:
    """計算蠟燭實體比例（實體 / 全影）"""
    total_range = candle["high"] - candle["low"]
    if total_range == 0:
        return 0.0
    body = abs(candle["close"] - candle["open"])
    return body / total_range
