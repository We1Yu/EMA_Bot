"""
掃描邏輯模組
執行收斂偵測、突破偵測與趨勢過濾
"""

from indicators import calc_bandwidth, calc_atr, ema_snapshot, body_ratio

# 帶寬閾值
BANDWIDTH_THRESHOLD = 2.0       # 收斂上限 %
COMPRESSION_BARS    = 3         # 至少連續遞減幾根
BREAKOUT_VOL_RATIO  = 1.5       # 突破量 ≥ 1.5× 5 根均量
BODY_RATIO_MIN      = 0.60      # 1H 蠟燭實體比例門檻
EMA200_SKIP_PCT     = 0.01      # 距 EMA200 1% 以內 → 跳過


def _bandwidths_for_last_n(emas: dict, n: int) -> list[float]:
    """計算最後 n 根K線的帶寬序列（最舊 → 最新）"""
    length = len(emas["ema15"])
    bws = []
    for i in range(length - n, length):
        e15 = emas["ema15"][i]
        e30 = emas["ema30"][i]
        e45 = emas["ema45"][i]
        e60 = emas["ema60"][i]
        if any(v is None for v in [e15, e30, e45, e60]):
            bws.append(None)
        else:
            bws.append(calc_bandwidth(e15, e30, e45, e60))
    return bws


def detect_convergence(candles_4h: list[dict], emas_4h: dict) -> dict | None:
    """
    偵測 4H 收斂形態
    回傳收斂資訊 dict，若未達標則回傳 None
    """
    # 需要最後至少 COMPRESSION_BARS+1 根有效帶寬
    needed = COMPRESSION_BARS + 2
    bws = _bandwidths_for_last_n(emas_4h, needed)

    if any(b is None for b in bws):
        return None

    current_bw = bws[-1]

    # 條件一：當前帶寬 < 2%
    if current_bw >= BANDWIDTH_THRESHOLD:
        return None

    # 條件二：帶寬連續遞減至少 COMPRESSION_BARS 根
    # 從最後往前檢查遞減序列長度
    consecutive = 0
    for i in range(len(bws) - 1, 0, -1):
        if bws[i] < bws[i - 1]:
            consecutive += 1
        else:
            break

    if consecutive < COMPRESSION_BARS:
        return None

    return {
        "bandwidth":          current_bw,
        "compression_bars":   consecutive,
    }


def detect_breakout_4h(candles_4h: list[dict], emas_4h: dict) -> str | None:
    """
    偵測 4H 突破方向
    回傳 "LONG" / "SHORT" 或 None
    """
    idx = len(candles_4h) - 1
    close   = candles_4h[idx]["close"]
    volume  = candles_4h[idx]["volume"]
    ema60   = emas_4h["ema60"][idx]
    bw_curr = calc_bandwidth(
        emas_4h["ema15"][idx], emas_4h["ema30"][idx],
        emas_4h["ema45"][idx], emas_4h["ema60"][idx]
    )
    bw_prev = calc_bandwidth(
        emas_4h["ema15"][idx - 1], emas_4h["ema30"][idx - 1],
        emas_4h["ema45"][idx - 1], emas_4h["ema60"][idx - 1]
    )

    # 帶寬必須正在擴張
    if bw_curr <= bw_prev:
        return None

    # 計算 5 根均量
    if idx < 4:
        return None
    avg_vol = sum(c["volume"] for c in candles_4h[idx - 5:idx]) / 5
    if avg_vol == 0:
        return None

    vol_ratio = volume / avg_vol
    if vol_ratio < BREAKOUT_VOL_RATIO:
        return None

    if close > ema60:
        return "LONG"
    if close < ema60:
        return "SHORT"
    return None


def confirm_1h(candles_1h: list[dict], emas_1h: dict, direction: str) -> dict | None:
    """
    1H 確認條件
    回傳確認資訊 dict 或 None
    """
    idx  = len(candles_1h) - 1
    close = candles_1h[idx]["close"]
    ema30 = emas_1h["ema30"][idx]

    # 方向吻合
    if direction == "LONG"  and close <= emas_1h["ema60"][idx]:
        return None
    if direction == "SHORT" and close >= emas_1h["ema60"][idx]:
        return None

    # 實體比例
    ratio = body_ratio(candles_1h[idx])
    if ratio < BODY_RATIO_MIN:
        return None

    # EMA15 穿越 EMA30（最後兩根）
    prev_e15 = emas_1h["ema15"][idx - 1]
    curr_e15 = emas_1h["ema15"][idx]
    prev_e30 = emas_1h["ema30"][idx - 1]
    curr_e30 = emas_1h["ema30"][idx]

    if any(v is None for v in [prev_e15, curr_e15, prev_e30, curr_e30]):
        return None

    crossed = False
    if direction == "LONG"  and prev_e15 <= prev_e30 and curr_e15 > curr_e30:
        crossed = True
    if direction == "SHORT" and prev_e15 >= prev_e30 and curr_e15 < curr_e30:
        crossed = True

    if not crossed:
        return None

    return {
        "body_ratio":    ratio,
        "pullback_entry": ema30,   # 理想回測進場價
    }


def apply_trend_filter(candles_4h: list[dict], emas_4h: dict, direction: str) -> bool:
    """
    EMA200 趨勢過濾器
    回傳 True = 通過，False = 跳過
    """
    idx   = len(candles_4h) - 1
    close = candles_4h[idx]["close"]
    e200  = emas_4h["ema200"][idx]

    if e200 is None:
        return False

    # 距 EMA200 太近 → 跳過
    if abs(close - e200) / e200 < EMA200_SKIP_PCT:
        return False

    if direction == "LONG"  and close > e200:
        return True
    if direction == "SHORT" and close < e200:
        return True
    return False


def calc_trade_levels(
    candles_4h: list[dict],
    emas_4h: dict,
    emas_1h: dict,
    direction: str,
    convergence: dict,
) -> dict:
    """
    計算進場、止損、目標位
    """
    idx    = len(candles_4h) - 1
    entry  = candles_4h[idx]["close"]
    atrs   = calc_atr(candles_4h, 14)
    atr    = atrs[idx] if atrs[idx] is not None else 0.0

    # 收斂區間最高/低點（取最後 compression_bars+1 根）
    n = convergence["compression_bars"] + 1
    zone_candles = candles_4h[max(0, idx - n + 1): idx + 1]
    zone_high = max(c["high"] for c in zone_candles)
    zone_low  = min(c["low"]  for c in zone_candles)

    if direction == "LONG":
        stop_loss = zone_low  - 0.5 * atr
        target1   = entry + 1.5 * (entry - stop_loss)
        target2   = entry + 2.5 * (entry - stop_loss)
    else:
        stop_loss = zone_high + 0.5 * atr
        target1   = entry - 1.5 * (stop_loss - entry)
        target2   = entry - 2.5 * (stop_loss - entry)

    return {
        "entry":       entry,
        "stop_loss":   stop_loss,
        "target1":     target1,
        "target2":     target2,
        "atr":         atr,
    }


def scan_symbol(
    symbol: str,
    candles_4h: list[dict],
    candles_1h: list[dict],
) -> dict | None:
    """
    對單一交易對執行完整掃描流程
    通過所有條件才回傳結果 dict，否則回傳 None
    """
    # 計算 EMA 快照
    emas_4h = ema_snapshot(candles_4h)
    emas_1h = ema_snapshot(candles_1h)
    if emas_4h is None or emas_1h is None:
        return None

    # Step 4：收斂偵測
    convergence = detect_convergence(candles_4h, emas_4h)
    if convergence is None:
        return None

    # Step 5：突破偵測（4H）
    direction = detect_breakout_4h(candles_4h, emas_4h)
    if direction is None:
        return None

    # Step 6：趨勢過濾（EMA200）
    if not apply_trend_filter(candles_4h, emas_4h, direction):
        return None

    # Step 5：1H 確認
    confirm = confirm_1h(candles_1h, emas_1h, direction)
    if confirm is None:
        return None

    # 計算交易水位
    levels = calc_trade_levels(candles_4h, emas_4h, emas_1h, direction, convergence)

    # 4H 量比（供評分用）
    idx_4h = len(candles_4h) - 1
    avg_vol = sum(c["volume"] for c in candles_4h[idx_4h - 5:idx_4h]) / 5
    vol_ratio = candles_4h[idx_4h]["volume"] / avg_vol if avg_vol > 0 else 0.0

    return {
        "symbol":           symbol,
        "direction":        direction,
        "convergence":      convergence,
        "confirm_1h":       confirm,
        "levels":           levels,
        "vol_ratio":        vol_ratio,
        "ema200_clear":     True,   # 已通過趨勢過濾才到此
        "candle_time_ms":   candles_4h[idx_4h]["time"],
    }
