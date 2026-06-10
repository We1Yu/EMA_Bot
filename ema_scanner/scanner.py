"""
掃描邏輯模組
支援七種策略：
  EMA_CONVERGENCE  – EMA 群收斂後突破（4H）
  EMA_PULLBACK     – EMA30 回測後反彈（1H）
  RSI_BOUNCE       – RSI 極值回彈（1H）
  MACD_CROSS       – MACD 柱狀圖變號交叉（1H）
  BB_BREAKOUT      – 布林帶收縮後突破（1H）
  EMA_CROSS_FAST   – EMA9/EMA21 快速交叉（1H）
  SWING_BREAK      – 8根K線擺幅突破（1H）
"""

from indicators import (
    calc_bandwidth, calc_atr, calc_ema,
    calc_rsi, calc_macd, calc_bollinger,
    ema_snapshot, body_ratio,
)
from bingx import get_oi_history, get_long_short_ratio

# ── EMA_CONVERGENCE 參數 ─────────────────────────────────────
BANDWIDTH_THRESHOLD = 2.0
COMPRESSION_BARS    = 3
BREAKOUT_VOL_RATIO  = 1.5
BODY_RATIO_MIN      = 0.60
EMA200_SKIP_PCT     = 0.01
CROSS_LOOKBACK      = 3

# ── EMA_PULLBACK 參數 ────────────────────────────────────────
EMA_PULLBACK_TOUCH_PCT = 0.005   # 前一根K棒高/低距EMA30在0.5%內算觸碰
EMA_PULLBACK_VOL_RATIO = 1.2

# ── RSI_BOUNCE 參數 ──────────────────────────────────────────
RSI_PERIOD     = 14
RSI_OVERSOLD   = 35
RSI_OVERBOUGHT = 65
RSI_VOL_RATIO  = 1.2

# ── MACD_CROSS 參數 ──────────────────────────────────────────
MACD_LOOKBACK  = 2    # histogram 必須在對側至少 N 根才算有效交叉
MACD_VOL_RATIO = 1.2

# ── BB_BREAKOUT 參數 ─────────────────────────────────────────
BB_PERIOD       = 20
BB_STD          = 2.0
BB_SQUEEZE_PCT  = 6.0   # BB width < 6% 算收縮
BB_SQUEEZE_BARS = 2     # 至少連續 2 根收縮
BB_VOL_RATIO    = 1.5

# ── EMA_CROSS_FAST 參數 ──────────────────────────────────────
EMA_FAST_P      = 9
EMA_SLOW_P      = 21
FAST_CROSS_VOL  = 1.2

# ── SWING_BREAK 參數 ─────────────────────────────────────────
SWING_LOOKBACK  = 8     # 看最近 8 根 1H K 線的高低點
SWING_VOL_RATIO = 1.8

# ── OI_LS_SIGNAL 參數 ────────────────────────────────────────
OI_CHANGE_MIN   = 2.0   # OI 在最近 N 根中增加至少 2%（異常累積）
LS_LONG_MIN     = 0.52  # 多頭帳戶佔比 > 52% 才算淨多頭
LS_RISE_MIN     = 0.02  # 多頭佔比至少上升 2 個百分點
OI_LS_VOL_RATIO = 1.2


# ─────────────────────────────────────────────────────────────
# 共用輔助函式
# ─────────────────────────────────────────────────────────────

def _trend_direction_4h(candles_4h: list[dict], emas_4h: dict) -> str | None:
    """
    依 4H EMA200 判斷大方向，回傳 "LONG" / "SHORT" 或 None（太近/無效）
    """
    idx   = len(candles_4h) - 1
    close = candles_4h[idx]["close"]
    e200  = emas_4h["ema200"][idx]
    if e200 is None:
        return None
    if abs(close - e200) / e200 < EMA200_SKIP_PCT:
        return None
    return "LONG" if close > e200 else "SHORT"


def _bandwidths_for_last_n(emas: dict, n: int) -> list[float]:
    length = len(emas["ema15"])
    bws = []
    for i in range(length - n, length):
        e15 = emas["ema15"][i]; e30 = emas["ema30"][i]
        e45 = emas["ema45"][i]; e60 = emas["ema60"][i]
        if any(v is None for v in [e15, e30, e45, e60]):
            bws.append(None)
        else:
            bws.append(calc_bandwidth(e15, e30, e45, e60))
    return bws


# ─────────────────────────────────────────────────────────────
# 策略一：EMA 收斂突破（原始策略）
# ─────────────────────────────────────────────────────────────

def detect_convergence(candles_4h: list[dict], emas_4h: dict) -> dict | None:
    needed = COMPRESSION_BARS + 2
    bws    = _bandwidths_for_last_n(emas_4h, needed)
    if any(b is None for b in bws):
        return None
    current_bw = bws[-1]
    if current_bw >= BANDWIDTH_THRESHOLD:
        return None
    decreasing  = 0
    interrupts  = 0
    for i in range(len(bws) - 1, 0, -1):
        if bws[i] < bws[i - 1]:
            decreasing += 1
        else:
            interrupts += 1
            if interrupts > 1:
                break
    if decreasing < COMPRESSION_BARS:
        return None
    return {"bandwidth": current_bw, "compression_bars": decreasing}


def detect_breakout_4h(candles_4h: list[dict], emas_4h: dict) -> str | None:
    idx    = len(candles_4h) - 1
    close  = candles_4h[idx]["close"]
    volume = candles_4h[idx]["volume"]
    ema60  = emas_4h["ema60"][idx]
    bw_curr = calc_bandwidth(
        emas_4h["ema15"][idx], emas_4h["ema30"][idx],
        emas_4h["ema45"][idx], emas_4h["ema60"][idx]
    )
    prev_vals = [
        emas_4h["ema15"][idx - 1], emas_4h["ema30"][idx - 1],
        emas_4h["ema45"][idx - 1], emas_4h["ema60"][idx - 1],
    ]
    if any(v is None for v in prev_vals):
        return None
    bw_prev = calc_bandwidth(*prev_vals)
    if bw_curr <= bw_prev:
        return None
    if idx < 4:
        return None
    avg_vol   = sum(c["volume"] for c in candles_4h[idx - 5:idx]) / 5
    if avg_vol == 0:
        return None
    if volume / avg_vol < BREAKOUT_VOL_RATIO:
        return None
    if close > ema60:
        return "LONG"
    if close < ema60:
        return "SHORT"
    return None


def confirm_1h(candles_1h: list[dict], emas_1h: dict, direction: str) -> dict | None:
    idx   = len(candles_1h) - 1
    close = candles_1h[idx]["close"]
    ema30 = emas_1h["ema30"][idx]
    if direction == "LONG"  and close <= emas_1h["ema60"][idx]:
        return None
    if direction == "SHORT" and close >= emas_1h["ema60"][idx]:
        return None
    ratio = body_ratio(candles_1h[idx])
    if ratio < BODY_RATIO_MIN:
        return None
    crossed = False
    for j in range(1, CROSS_LOOKBACK + 1):
        if idx - j < 0:
            break
        e15_prev = emas_1h["ema15"][idx - j];     e15_curr = emas_1h["ema15"][idx - j + 1]
        e30_prev = emas_1h["ema30"][idx - j];     e30_curr = emas_1h["ema30"][idx - j + 1]
        if any(v is None for v in [e15_prev, e15_curr, e30_prev, e30_curr]):
            continue
        if direction == "LONG"  and e15_prev <= e30_prev and e15_curr > e30_curr:
            crossed = True; break
        if direction == "SHORT" and e15_prev >= e30_prev and e15_curr < e30_curr:
            crossed = True; break
    if not crossed:
        return None
    return {"body_ratio": ratio, "pullback_entry": ema30}


def apply_trend_filter(candles_4h: list[dict], emas_4h: dict, direction: str) -> bool:
    idx   = len(candles_4h) - 1
    close = candles_4h[idx]["close"]
    e200  = emas_4h["ema200"][idx]
    if e200 is None:
        return False
    if abs(close - e200) / e200 < EMA200_SKIP_PCT:
        return False
    if direction == "LONG"  and close > e200:
        return True
    if direction == "SHORT" and close < e200:
        return True
    return False


def calc_trade_levels(
    candles: list[dict],
    emas: dict,
    direction: str,
    convergence: dict,
) -> dict:
    idx   = len(candles) - 1
    entry = candles[idx]["close"]
    atrs  = calc_atr(candles, 14)
    atr   = atrs[idx] if atrs[idx] is not None else 0.0
    n = convergence["compression_bars"] + 1
    zone_candles = candles[max(0, idx - n + 1): idx + 1]
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
    return {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2, "atr": atr}


def _scan_ema_convergence(
    symbol: str,
    candles_4h: list[dict], candles_1h: list[dict],
    emas_4h: dict,          emas_1h: dict,
) -> dict | None:
    convergence = detect_convergence(candles_4h, emas_4h)
    if convergence is None:
        return None
    direction = detect_breakout_4h(candles_4h, emas_4h)
    if direction is None:
        return None
    if not apply_trend_filter(candles_4h, emas_4h, direction):
        return None
    confirm = confirm_1h(candles_1h, emas_1h, direction)
    if confirm is None:
        return None
    levels = calc_trade_levels(candles_4h, emas_4h, direction, convergence)
    idx_4h  = len(candles_4h) - 1
    avg_vol = sum(c["volume"] for c in candles_4h[idx_4h - 5:idx_4h]) / 5
    vol_ratio = candles_4h[idx_4h]["volume"] / avg_vol if avg_vol > 0 else 0.0
    return {
        "symbol":         symbol,
        "direction":      direction,
        "strategy":       "EMA_CONVERGENCE",
        "convergence":    convergence,
        "confirm_1h":     confirm,
        "levels":         levels,
        "vol_ratio":      vol_ratio,
        "ema200_clear":   True,
        "candle_time_ms": candles_4h[idx_4h]["time"],
    }


# ─────────────────────────────────────────────────────────────
# 策略二：EMA30 回測反彈（1H）
# ─────────────────────────────────────────────────────────────

def _scan_ema_pullback(
    symbol: str,
    candles_4h: list[dict], candles_1h: list[dict],
    emas_4h: dict,          emas_1h: dict,
) -> dict | None:
    direction = _trend_direction_4h(candles_4h, emas_4h)
    if direction is None:
        return None

    idx = len(candles_1h) - 1
    if idx < 6:
        return None

    ema15     = emas_1h["ema15"][idx]
    ema30     = emas_1h["ema30"][idx]
    ema30_p   = emas_1h["ema30"][idx - 1]
    ema60     = emas_1h["ema60"][idx]
    if any(v is None for v in [ema15, ema30, ema30_p, ema60]):
        return None

    # 1H 短期趨勢需與大方向一致（EMA15/EMA30 排列）
    if direction == "LONG"  and ema15 <= ema30:
        return None
    if direction == "SHORT" and ema15 >= ema30:
        return None

    # 當前價格仍在 EMA60 正確側
    close = candles_1h[idx]["close"]
    if direction == "LONG"  and close < ema60:
        return None
    if direction == "SHORT" and close > ema60:
        return None

    # 前一根K棒的高/低觸碰EMA30區域
    prev = candles_1h[idx - 1]
    if direction == "LONG":
        if prev["low"] > ema30_p * (1 + EMA_PULLBACK_TOUCH_PCT):
            return None
        if close <= ema30:          # 確認反彈收盤在EMA30上方
            return None
        if close <= candles_1h[idx]["open"]:  # 必須是陽線
            return None
    else:
        if prev["high"] < ema30_p * (1 - EMA_PULLBACK_TOUCH_PCT):
            return None
        if close >= ema30:
            return None
        if close >= candles_1h[idx]["open"]:  # 必須是陰線
            return None

    ratio = body_ratio(candles_1h[idx])
    if ratio < 0.55:
        return None

    avg_vol = sum(c["volume"] for c in candles_1h[idx - 5:idx]) / 5
    if avg_vol == 0:
        return None
    vol_ratio = candles_1h[idx]["volume"] / avg_vol
    if vol_ratio < EMA_PULLBACK_VOL_RATIO:
        return None

    atrs = calc_atr(candles_1h, 14)
    atr  = atrs[idx] if atrs[idx] is not None else 0.0
    entry = close

    if direction == "LONG":
        stop_loss = min(prev["low"], ema30) - 0.5 * atr
        target1   = entry + 1.5 * (entry - stop_loss)
        target2   = entry + 2.5 * (entry - stop_loss)
    else:
        stop_loss = max(prev["high"], ema30) + 0.5 * atr
        target1   = entry - 1.5 * (stop_loss - entry)
        target2   = entry - 2.5 * (stop_loss - entry)

    return {
        "symbol":         symbol,
        "direction":      direction,
        "strategy":       "EMA_PULLBACK",
        "convergence":    {"bandwidth": 0.0, "compression_bars": 0},
        "confirm_1h":     {"body_ratio": ratio, "pullback_entry": ema30},
        "levels":         {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2, "atr": atr},
        "vol_ratio":      vol_ratio,
        "ema200_clear":   True,
        "candle_time_ms": candles_1h[idx]["time"],
    }


# ─────────────────────────────────────────────────────────────
# 策略三：RSI 極值回彈（1H）
# ─────────────────────────────────────────────────────────────

def _scan_rsi_bounce(
    symbol: str,
    candles_4h: list[dict], candles_1h: list[dict],
    emas_4h: dict,
) -> dict | None:
    direction = _trend_direction_4h(candles_4h, emas_4h)
    if direction is None:
        return None

    closes_1h = [c["close"] for c in candles_1h]
    rsi = calc_rsi(closes_1h, RSI_PERIOD)

    idx = len(candles_1h) - 1
    if idx < RSI_PERIOD + 3:
        return None

    r0, r1, r2 = rsi[idx], rsi[idx - 1], rsi[idx - 2]
    if any(v is None for v in [r0, r1, r2]):
        return None

    # RSI 已觸碰極值區域，且開始反轉
    if direction == "LONG":
        if not (r2 <= RSI_OVERSOLD or r1 <= RSI_OVERSOLD):
            return None
        if r0 <= r1:   # RSI 必須向上反轉
            return None
    else:
        if not (r2 >= RSI_OVERBOUGHT or r1 >= RSI_OVERBOUGHT):
            return None
        if r0 >= r1:   # RSI 必須向下反轉
            return None

    candle = candles_1h[idx]
    ratio  = body_ratio(candle)
    if ratio < 0.50:
        return None

    if direction == "LONG"  and candle["close"] <= candle["open"]:
        return None
    if direction == "SHORT" and candle["close"] >= candle["open"]:
        return None

    if idx < 5:
        return None
    avg_vol   = sum(c["volume"] for c in candles_1h[idx - 5:idx]) / 5
    if avg_vol == 0:
        return None
    vol_ratio = candles_1h[idx]["volume"] / avg_vol
    if vol_ratio < RSI_VOL_RATIO:
        return None

    atrs  = calc_atr(candles_1h, 14)
    atr   = atrs[idx] if atrs[idx] is not None else 0.0
    entry = candle["close"]

    if direction == "LONG":
        stop_loss = min(c["low"]  for c in candles_1h[max(0, idx - 3):idx + 1]) - 0.3 * atr
        target1   = entry + 1.5 * (entry - stop_loss)
        target2   = entry + 2.5 * (entry - stop_loss)
    else:
        stop_loss = max(c["high"] for c in candles_1h[max(0, idx - 3):idx + 1]) + 0.3 * atr
        target1   = entry - 1.5 * (stop_loss - entry)
        target2   = entry - 2.5 * (stop_loss - entry)

    return {
        "symbol":         symbol,
        "direction":      direction,
        "strategy":       "RSI_BOUNCE",
        "convergence":    {"bandwidth": 0.0, "compression_bars": 0},
        "confirm_1h":     {"body_ratio": ratio, "pullback_entry": entry, "rsi": round(r0, 1)},
        "levels":         {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2, "atr": atr},
        "vol_ratio":      vol_ratio,
        "ema200_clear":   True,
        "candle_time_ms": candles_1h[idx]["time"],
    }


# ─────────────────────────────────────────────────────────────
# 策略四：MACD 柱狀圖交叉（1H）
# ─────────────────────────────────────────────────────────────

def _scan_macd_cross(
    symbol: str,
    candles_4h: list[dict], candles_1h: list[dict],
    emas_4h: dict,
) -> dict | None:
    direction = _trend_direction_4h(candles_4h, emas_4h)
    if direction is None:
        return None

    closes_1h = [c["close"] for c in candles_1h]
    macd_data = calc_macd(closes_1h)
    hist = macd_data["histogram"]

    idx = len(candles_1h) - 1
    if idx < MACD_LOOKBACK + 1:
        return None

    h0 = hist[idx]
    h1 = hist[idx - 1]
    if h0 is None or h1 is None:
        return None

    crossed_up   = h0 > 0 and h1 <= 0
    crossed_down = h0 < 0 and h1 >= 0

    if direction == "LONG"  and not crossed_up:
        return None
    if direction == "SHORT" and not crossed_down:
        return None

    # 交叉前至少 MACD_LOOKBACK 根柱子位於對側（避免假訊號）
    opposite_count = 0
    for j in range(1, MACD_LOOKBACK + 1):
        hv = hist[idx - j]
        if hv is None:
            break
        if direction == "LONG"  and hv <= 0:
            opposite_count += 1
        elif direction == "SHORT" and hv >= 0:
            opposite_count += 1
    if opposite_count < MACD_LOOKBACK:
        return None

    candle = candles_1h[idx]
    ratio  = body_ratio(candle)
    if ratio < 0.45:
        return None

    if direction == "LONG"  and candle["close"] <= candle["open"]:
        return None
    if direction == "SHORT" and candle["close"] >= candle["open"]:
        return None

    if idx < 5:
        return None
    avg_vol   = sum(c["volume"] for c in candles_1h[idx - 5:idx]) / 5
    if avg_vol == 0:
        return None
    vol_ratio = candles_1h[idx]["volume"] / avg_vol
    if vol_ratio < MACD_VOL_RATIO:
        return None

    atrs  = calc_atr(candles_1h, 14)
    atr   = atrs[idx] if atrs[idx] is not None else 0.0
    entry = candle["close"]

    if direction == "LONG":
        stop_loss = min(c["low"]  for c in candles_1h[max(0, idx - 4):idx + 1]) - 0.3 * atr
        target1   = entry + 1.5 * (entry - stop_loss)
        target2   = entry + 2.5 * (entry - stop_loss)
    else:
        stop_loss = max(c["high"] for c in candles_1h[max(0, idx - 4):idx + 1]) + 0.3 * atr
        target1   = entry - 1.5 * (stop_loss - entry)
        target2   = entry - 2.5 * (stop_loss - entry)

    return {
        "symbol":         symbol,
        "direction":      direction,
        "strategy":       "MACD_CROSS",
        "convergence":    {"bandwidth": 0.0, "compression_bars": 0},
        "confirm_1h":     {"body_ratio": ratio, "pullback_entry": entry},
        "levels":         {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2, "atr": atr},
        "vol_ratio":      vol_ratio,
        "ema200_clear":   True,
        "candle_time_ms": candles_1h[idx]["time"],
    }


# ─────────────────────────────────────────────────────────────
# 策略五：布林帶收縮突破（1H）
# ─────────────────────────────────────────────────────────────

def _scan_bb_breakout(
    symbol: str,
    candles_4h: list[dict], candles_1h: list[dict],
    emas_4h: dict,
) -> dict | None:
    direction = _trend_direction_4h(candles_4h, emas_4h)
    if direction is None:
        return None

    closes_1h = [c["close"] for c in candles_1h]
    bb  = calc_bollinger(closes_1h, BB_PERIOD, BB_STD)
    idx = len(candles_1h) - 1

    if idx < BB_PERIOD + BB_SQUEEZE_BARS:
        return None

    upper  = bb["upper"][idx]
    middle = bb["middle"][idx]
    lower  = bb["lower"][idx]
    if any(v is None for v in [upper, middle, lower]):
        return None

    # 前 BB_SQUEEZE_BARS 根必須都是收縮狀態
    for j in range(1, BB_SQUEEZE_BARS + 1):
        w = bb["width"][idx - j]
        if w is None or w >= BB_SQUEEZE_PCT:
            return None

    close = candles_1h[idx]["close"]

    # 突破方向（收盤在帶外）
    if direction == "LONG"  and close <= upper:
        return None
    if direction == "SHORT" and close >= lower:
        return None

    # 確認蠟燭方向
    if direction == "LONG"  and close <= candles_1h[idx]["open"]:
        return None
    if direction == "SHORT" and close >= candles_1h[idx]["open"]:
        return None

    ratio = body_ratio(candles_1h[idx])
    if ratio < 0.50:
        return None

    if idx < 5:
        return None
    avg_vol   = sum(c["volume"] for c in candles_1h[idx - 5:idx]) / 5
    if avg_vol == 0:
        return None
    vol_ratio = candles_1h[idx]["volume"] / avg_vol
    if vol_ratio < BB_VOL_RATIO:
        return None

    atrs  = calc_atr(candles_1h, 14)
    atr   = atrs[idx] if atrs[idx] is not None else 0.0
    entry = close

    if direction == "LONG":
        stop_loss = middle - 0.5 * atr
        target1   = entry + 1.5 * (entry - stop_loss)
        target2   = entry + 2.5 * (entry - stop_loss)
    else:
        stop_loss = middle + 0.5 * atr
        target1   = entry - 1.5 * (stop_loss - entry)
        target2   = entry - 2.5 * (stop_loss - entry)

    return {
        "symbol":         symbol,
        "direction":      direction,
        "strategy":       "BB_BREAKOUT",
        "convergence":    {"bandwidth": round(bb["width"][idx - 1] or 0, 2), "compression_bars": BB_SQUEEZE_BARS},
        "confirm_1h":     {"body_ratio": ratio, "pullback_entry": entry},
        "levels":         {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2, "atr": atr},
        "vol_ratio":      vol_ratio,
        "ema200_clear":   True,
        "candle_time_ms": candles_1h[idx]["time"],
    }


# ─────────────────────────────────────────────────────────────
# 策略六：EMA9/EMA21 快速交叉（1H）
# ─────────────────────────────────────────────────────────────

def _scan_ema_cross_fast(
    symbol: str,
    candles_4h: list[dict], candles_1h: list[dict],
    emas_4h: dict,
) -> dict | None:
    direction = _trend_direction_4h(candles_4h, emas_4h)
    if direction is None:
        return None

    closes_1h = [c["close"] for c in candles_1h]
    e9  = calc_ema(closes_1h, EMA_FAST_P)
    e21 = calc_ema(closes_1h, EMA_SLOW_P)

    idx = len(candles_1h) - 1
    if idx < 2:
        return None

    e9c, e9p   = e9[idx],  e9[idx - 1]
    e21c, e21p = e21[idx], e21[idx - 1]
    if any(v is None for v in [e9c, e9p, e21c, e21p]):
        return None

    # EMA9 剛穿越 EMA21（本根才交叉）
    crossed_up   = e9p <= e21p and e9c > e21c
    crossed_down = e9p >= e21p and e9c < e21c

    if direction == "LONG"  and not crossed_up:
        return None
    if direction == "SHORT" and not crossed_down:
        return None

    candle = candles_1h[idx]
    ratio  = body_ratio(candle)
    if ratio < 0.50:
        return None

    if direction == "LONG"  and candle["close"] <= candle["open"]:
        return None
    if direction == "SHORT" and candle["close"] >= candle["open"]:
        return None

    if idx < 5:
        return None
    avg_vol   = sum(c["volume"] for c in candles_1h[idx - 5:idx]) / 5
    if avg_vol == 0:
        return None
    vol_ratio = candles_1h[idx]["volume"] / avg_vol
    if vol_ratio < FAST_CROSS_VOL:
        return None

    atrs  = calc_atr(candles_1h, 14)
    atr   = atrs[idx] if atrs[idx] is not None else 0.0
    entry = candle["close"]

    if direction == "LONG":
        stop_loss = min(c["low"]  for c in candles_1h[max(0, idx - 3):idx + 1]) - 0.3 * atr
        target1   = entry + 1.5 * (entry - stop_loss)
        target2   = entry + 2.5 * (entry - stop_loss)
    else:
        stop_loss = max(c["high"] for c in candles_1h[max(0, idx - 3):idx + 1]) + 0.3 * atr
        target1   = entry - 1.5 * (stop_loss - entry)
        target2   = entry - 2.5 * (stop_loss - entry)

    return {
        "symbol":         symbol,
        "direction":      direction,
        "strategy":       "EMA_CROSS_FAST",
        "convergence":    {"bandwidth": 0.0, "compression_bars": 0},
        "confirm_1h":     {"body_ratio": ratio, "pullback_entry": entry},
        "levels":         {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2, "atr": atr},
        "vol_ratio":      vol_ratio,
        "ema200_clear":   True,
        "candle_time_ms": candles_1h[idx]["time"],
    }


# ─────────────────────────────────────────────────────────────
# 策略七：近 8 根擺幅高低點突破（1H）
# ─────────────────────────────────────────────────────────────

def _scan_swing_break(
    symbol: str,
    candles_4h: list[dict], candles_1h: list[dict],
    emas_4h: dict,
) -> dict | None:
    direction = _trend_direction_4h(candles_4h, emas_4h)
    if direction is None:
        return None

    idx = len(candles_1h) - 1
    if idx < SWING_LOOKBACK + 2:
        return None

    # 最近 SWING_LOOKBACK 根（不含當前）的高低點
    lookback = candles_1h[idx - SWING_LOOKBACK: idx]
    swing_high = max(c["high"] for c in lookback)
    swing_low  = min(c["low"]  for c in lookback)

    close = candles_1h[idx]["close"]

    if direction == "LONG"  and close <= swing_high:
        return None
    if direction == "SHORT" and close >= swing_low:
        return None

    # 確認蠟燭
    if direction == "LONG"  and close <= candles_1h[idx]["open"]:
        return None
    if direction == "SHORT" and close >= candles_1h[idx]["open"]:
        return None

    ratio = body_ratio(candles_1h[idx])
    if ratio < 0.50:
        return None

    if idx < 5:
        return None
    avg_vol   = sum(c["volume"] for c in candles_1h[idx - 5:idx]) / 5
    if avg_vol == 0:
        return None
    vol_ratio = candles_1h[idx]["volume"] / avg_vol
    if vol_ratio < SWING_VOL_RATIO:
        return None

    atrs  = calc_atr(candles_1h, 14)
    atr   = atrs[idx] if atrs[idx] is not None else 0.0
    entry = close

    if direction == "LONG":
        stop_loss = swing_high - 0.3 * atr   # 回到突破點下方止損
        target1   = entry + 1.5 * (entry - stop_loss)
        target2   = entry + 2.5 * (entry - stop_loss)
    else:
        stop_loss = swing_low + 0.3 * atr
        target1   = entry - 1.5 * (stop_loss - entry)
        target2   = entry - 2.5 * (stop_loss - entry)

    return {
        "symbol":         symbol,
        "direction":      direction,
        "strategy":       "SWING_BREAK",
        "convergence":    {"bandwidth": 0.0, "compression_bars": 0},
        "confirm_1h":     {"body_ratio": ratio, "pullback_entry": entry},
        "levels":         {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2, "atr": atr},
        "vol_ratio":      vol_ratio,
        "ema200_clear":   True,
        "candle_time_ms": candles_1h[idx]["time"],
    }


# ─────────────────────────────────────────────────────────────
# 策略八：OI 異常 + 淨多頭升高（做多）/ 淨空頭升高（做空）
# 額外呼叫 BingX OI & 多空比 API，掃描速度較慢，放最後執行
# ─────────────────────────────────────────────────────────────

def _scan_oi_ls_signal(
    symbol: str,
    candles_4h: list[dict], candles_1h: list[dict],
    emas_4h: dict,
) -> dict | None:
    """
    純數據流派策略：不依賴均線，僅看 OI 異常 + 多空帳戶比例變化
    方向完全由數據決定：淨多頭升高 → LONG，淨空頭升高 → SHORT
    """
    # ── 取得 OI 歷史（最近 6 小時）────────────────────────────
    oi_hist = get_oi_history(symbol, "1h", 6)
    if not oi_hist or len(oi_hist) < 3:
        return None

    # ── 取得多空比歷史（最近 6 小時）──────────────────────────
    ls_hist = get_long_short_ratio(symbol, "1h", 6)
    if not ls_hist or len(ls_hist) < 3:
        return None

    # ── OI 變化：必須異常升高（新資金持續進場）────────────────
    oi_old = oi_hist[0]["oi"]
    oi_new = oi_hist[-1]["oi"]
    if oi_old <= 0:
        return None
    oi_change_pct = (oi_new - oi_old) / oi_old * 100
    if oi_change_pct < OI_CHANGE_MIN:
        return None

    # ── 多空比：由數據決定方向 ────────────────────────────────
    ls_old = ls_hist[0]["long_pct"]
    ls_new = ls_hist[-1]["long_pct"]
    ls_change = ls_new - ls_old   # 正 = 多頭增加，負 = 空頭增加

    if ls_new >= LS_LONG_MIN and ls_change >= LS_RISE_MIN:
        # 淨多頭升高 → 做多
        direction = "LONG"
    elif ls_new <= (1.0 - LS_LONG_MIN) and ls_change <= -LS_RISE_MIN:
        # 淨空頭升高 → 做空
        direction = "SHORT"
    else:
        return None   # 方向不明確，跳過

    # ── 確認蠟燭（1H 最新根，方向需與數據一致）───────────────
    idx    = len(candles_1h) - 1
    candle = candles_1h[idx]
    ratio  = body_ratio(candle)
    if ratio < 0.40:
        return None

    if direction == "LONG"  and candle["close"] <= candle["open"]:
        return None
    if direction == "SHORT" and candle["close"] >= candle["open"]:
        return None

    # ── 量能確認 ─────────────────────────────────────────────
    if idx < 5:
        return None
    avg_vol   = sum(c["volume"] for c in candles_1h[idx - 5:idx]) / 5
    if avg_vol == 0:
        return None
    vol_ratio = candles_1h[idx]["volume"] / avg_vol
    if vol_ratio < OI_LS_VOL_RATIO:
        return None

    # ── 交易水位（純 ATR 基礎，不依賴均線）───────────────────
    atrs  = calc_atr(candles_1h, 14)
    atr   = atrs[idx] if atrs[idx] is not None else 0.0
    entry = candle["close"]

    if atr == 0:
        return None

    if direction == "LONG":
        stop_loss = entry - 2.0 * atr
        target1   = entry + 1.5 * (entry - stop_loss)
        target2   = entry + 2.5 * (entry - stop_loss)
    else:
        stop_loss = entry + 2.0 * atr
        target1   = entry - 1.5 * (stop_loss - entry)
        target2   = entry - 2.5 * (stop_loss - entry)

    return {
        "symbol":         symbol,
        "direction":      direction,
        "strategy":       "OI_LS_SIGNAL",
        "convergence":    {"bandwidth": 0.0, "compression_bars": 0},
        "confirm_1h": {
            "body_ratio":    ratio,
            "pullback_entry": entry,
            "oi_change_pct": round(oi_change_pct, 2),
            "long_pct":      round(ls_new * 100, 1),
        },
        "levels":         {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2, "atr": atr},
        "vol_ratio":      vol_ratio,
        "ema200_clear":   False,   # 此策略不使用 EMA200 過濾
        "candle_time_ms": candles_1h[idx]["time"],
    }


# ─────────────────────────────────────────────────────────────
# 統一入口
# ─────────────────────────────────────────────────────────────

def scan_symbol(
    symbol: str,
    candles_4h: list[dict],
    candles_1h: list[dict],
) -> dict | None:
    """
    依序嘗試七種策略，任一通過即回傳結果 dict，全部失敗則回傳 None
    優先順序：品質高 → 觸發頻率高
    """
    emas_4h = ema_snapshot(candles_4h)
    emas_1h = ema_snapshot(candles_1h)
    if emas_4h is None:
        return None

    # 策略一：EMA 收斂突破（4H 主導，品質最高）
    if emas_1h is not None:
        result = _scan_ema_convergence(symbol, candles_4h, candles_1h, emas_4h, emas_1h)
        if result:
            return result

    # 策略二：EMA30 回測反彈（1H）
    if emas_1h is not None:
        result = _scan_ema_pullback(symbol, candles_4h, candles_1h, emas_4h, emas_1h)
        if result:
            return result

    # 策略三：RSI 極值反彈（1H）
    result = _scan_rsi_bounce(symbol, candles_4h, candles_1h, emas_4h)
    if result:
        return result

    # 策略四：MACD 柱狀圖交叉（1H）
    result = _scan_macd_cross(symbol, candles_4h, candles_1h, emas_4h)
    if result:
        return result

    # 策略五：布林帶收縮突破（1H）
    result = _scan_bb_breakout(symbol, candles_4h, candles_1h, emas_4h)
    if result:
        return result

    # 策略六：EMA9/EMA21 快速交叉（1H）
    result = _scan_ema_cross_fast(symbol, candles_4h, candles_1h, emas_4h)
    if result:
        return result

    # 策略七：近 8 根擺幅突破（1H）
    result = _scan_swing_break(symbol, candles_4h, candles_1h, emas_4h)
    if result:
        return result

    # 策略八：OI 異常 + 淨多頭升高（額外 API，放最後）
    result = _scan_oi_ls_signal(symbol, candles_4h, candles_1h, emas_4h)
    if result:
        return result

    return None
