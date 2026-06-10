"""
掃描邏輯模組
支援兩種策略：
  EMA_CONVERGENCE  – EMA 群收斂後突破（4H 主圖 + 1H 確認）
  EMA_PULLBACK     – EMA30 回測後反彈（1H 主圖）
"""

from indicators import (
    calc_bandwidth, calc_atr,
    calc_rsi,
    ema_snapshot, body_ratio,
)

# ── 幣種分類 ─────────────────────────────────────────────────
MAIN_COINS = {"BTC-USDT", "ETH-USDT"}

# ── EMA_CONVERGENCE 參數 ─────────────────────────────────────
BANDWIDTH_PERCENTILE_WINDOW    = 50    # 計算帶寬分位的回溯根數
BANDWIDTH_PERCENTILE_THRESHOLD = 0.25  # 在最低 25% 分位以下算收斂
COMPRESSION_BARS               = 4     # 連續收縮 ≥ 4 根（含當根）
BREAKOUT_VOL_RATIO_ALT         = 2.0   # 山寨量能門檻
BREAKOUT_VOL_RATIO_MAIN        = 1.3   # 主流量能門檻
BREAKOUT_VOL_LOOKBACK          = 20    # 均量計算根數
BREAKOUT_RSI_MAX               = 75    # 4H RSI 上限（排除超買追高）
BODY_RATIO_MIN                 = 0.50  # 1H 實體比下限
EMA200_SKIP_PCT                = 0.01
CROSS_LOOKBACK                 = 2     # 1H EMA15/30 穿越回溯根數

# ── EMA_PULLBACK 參數 ────────────────────────────────────────
EMA_PULLBACK_TOUCH_PCT_ALT  = 0.012   # 山寨觸碰 EMA30 距離上限 1.2%
EMA_PULLBACK_TOUCH_PCT_MAIN = 0.007   # 主流觸碰 EMA30 距離上限 0.7%
EMA_PULLBACK_VOL_RATIO      = 1.3
EMA_PULLBACK_VOL_LOOKBACK   = 20
EMA_PULLBACK_BODY           = 0.45
EMA_PULLBACK_RSI_MIN        = 40      # 多單 1H RSI 下限

RSI_PERIOD = 14


# ─────────────────────────────────────────────────────────────
# 共用輔助函式
# ─────────────────────────────────────────────────────────────

def _trend_direction_4h(candles_4h: list[dict], emas_4h: dict) -> str | None:
    """依 4H EMA200 判斷大方向，回傳 "LONG" / "SHORT" 或 None"""
    idx   = len(candles_4h) - 1
    close = candles_4h[idx]["close"]
    e200  = emas_4h["ema200"][idx]
    if e200 is None:
        return None
    if abs(close - e200) / e200 < EMA200_SKIP_PCT:
        return None
    return "LONG" if close > e200 else "SHORT"


def _bandwidth_percentile_threshold(emas: dict, window: int, percentile: float) -> float | None:
    """計算最近 window 根 bandwidth 的 percentile 分位值"""
    length = len(emas["ema15"])
    if length < window:
        return None
    bws = []
    for i in range(length - window, length):
        e15 = emas["ema15"][i]; e30 = emas["ema30"][i]
        e45 = emas["ema45"][i]; e60 = emas["ema60"][i]
        if any(v is None for v in [e15, e30, e45, e60]):
            continue
        bws.append(calc_bandwidth(e15, e30, e45, e60))
    if len(bws) < window // 2:
        return None
    bws.sort()
    idx = max(0, int(len(bws) * percentile) - 1)
    return bws[idx]


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
# 策略一輔助函式
# ─────────────────────────────────────────────────────────────

def detect_convergence(candles_4h: list[dict], emas_4h: dict) -> dict | None:
    """EMA 群帶寬收斂判斷（百分位法）"""
    bw_threshold = _bandwidth_percentile_threshold(
        emas_4h, BANDWIDTH_PERCENTILE_WINDOW, BANDWIDTH_PERCENTILE_THRESHOLD
    )
    if bw_threshold is None:
        return None

    needed = COMPRESSION_BARS + 2
    bws    = _bandwidths_for_last_n(emas_4h, needed)
    if any(b is None for b in bws):
        return None

    current_bw = bws[-1]
    if current_bw >= bw_threshold:
        return None

    # 連續收縮計數
    decreasing = 0
    interrupts = 0
    for i in range(len(bws) - 1, 0, -1):
        if bws[i] < bws[i - 1]:
            decreasing += 1
        else:
            interrupts += 1
            if interrupts > 1:
                break
    if decreasing < COMPRESSION_BARS:
        return None

    return {
        "bandwidth":       current_bw,
        "compression_bars": decreasing,
        "bw_threshold":    round(bw_threshold, 3),
    }


def detect_breakout_4h(
    candles_4h: list[dict],
    emas_4h: dict,
    is_main: bool = False,
) -> tuple[str | None, float, float | None]:
    """
    判斷 4H 是否突破 EMA60
    回傳 (direction, vol_ratio, rsi_4h) 或 (None, 0.0, None)
    """
    idx    = len(candles_4h) - 1
    close  = candles_4h[idx]["close"]
    volume = candles_4h[idx]["volume"]

    bw_curr = calc_bandwidth(
        emas_4h["ema15"][idx], emas_4h["ema30"][idx],
        emas_4h["ema45"][idx], emas_4h["ema60"][idx]
    )
    prev_vals = [
        emas_4h["ema15"][idx - 1], emas_4h["ema30"][idx - 1],
        emas_4h["ema45"][idx - 1], emas_4h["ema60"][idx - 1],
    ]
    if any(v is None for v in prev_vals):
        return None, 0.0, None
    bw_prev = calc_bandwidth(*prev_vals)
    if bw_curr <= bw_prev:
        return None, 0.0, None

    if idx < BREAKOUT_VOL_LOOKBACK:
        return None, 0.0, None
    avg_vol = sum(c["volume"] for c in candles_4h[idx - BREAKOUT_VOL_LOOKBACK:idx]) / BREAKOUT_VOL_LOOKBACK
    if avg_vol == 0:
        return None, 0.0, None

    vol_threshold = BREAKOUT_VOL_RATIO_MAIN if is_main else BREAKOUT_VOL_RATIO_ALT
    vol_ratio = volume / avg_vol
    if vol_ratio < vol_threshold:
        return None, 0.0, None

    # 4H RSI < 75（排除超買追高）
    closes_4h = [c["close"] for c in candles_4h]
    rsi_vals  = calc_rsi(closes_4h, RSI_PERIOD)
    rsi_now   = rsi_vals[idx]
    if rsi_now is None or rsi_now >= BREAKOUT_RSI_MAX:
        return None, 0.0, None

    ema60 = emas_4h["ema60"][idx]
    if close > ema60:
        return "LONG", vol_ratio, round(rsi_now, 1)
    if close < ema60:
        return "SHORT", vol_ratio, round(rsi_now, 1)
    return None, 0.0, None


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
        stop_loss = zone_low  - 1.0 * atr
        target1   = entry + 1.5 * (entry - stop_loss)
        target2   = entry + 2.5 * (entry - stop_loss)
    else:
        stop_loss = zone_high + 1.0 * atr
        target1   = entry - 1.5 * (stop_loss - entry)
        target2   = entry - 2.5 * (stop_loss - entry)
    return {"entry": entry, "stop_loss": stop_loss, "target1": target1, "target2": target2, "atr": atr}


# ─────────────────────────────────────────────────────────────
# 策略一：EMA 收斂突破（4H 主圖 + 1H 確認）
# ─────────────────────────────────────────────────────────────

def _scan_ema_convergence(
    symbol: str,
    candles_4h: list[dict], candles_1h: list[dict],
    emas_4h: dict,          emas_1h: dict,
) -> dict | None:
    is_main = symbol in MAIN_COINS
    vol_threshold = BREAKOUT_VOL_RATIO_MAIN if is_main else BREAKOUT_VOL_RATIO_ALT

    convergence = detect_convergence(candles_4h, emas_4h)
    if convergence is None:
        return None

    direction, vol_ratio, rsi_4h = detect_breakout_4h(candles_4h, emas_4h, is_main)
    if direction is None:
        return None

    if not apply_trend_filter(candles_4h, emas_4h, direction):
        return None

    confirm = confirm_1h(candles_1h, emas_1h, direction)
    if confirm is None:
        return None

    levels = calc_trade_levels(candles_4h, emas_4h, direction, convergence)

    conditions = [
        {"name": "4H 帶寬分位",       "value": f"{convergence['bandwidth']:.2f}% ≤ {convergence['bw_threshold']:.2f}%（25 分位）"},
        {"name": "連續收縮根數",       "value": f"{convergence['compression_bars']} 根 ≥ {COMPRESSION_BARS}"},
        {"name": "4H 突破量能",        "value": f"{vol_ratio:.2f}× ≥ {vol_threshold}×"},
        {"name": "4H RSI",            "value": f"{rsi_4h} < {BREAKOUT_RSI_MAX}"},
        {"name": "EMA200 大方向",      "value": "多頭" if direction == "LONG" else "空頭"},
        {"name": "1H EMA15/30 穿越",  "value": f"近 {CROSS_LOOKBACK} 根內確認"},
        {"name": "1H EMA60 正確側",   "value": "通過"},
        {"name": "1H 蠟燭實體比",     "value": f"{confirm['body_ratio']*100:.0f}% ≥ {BODY_RATIO_MIN*100:.0f}%"},
    ]

    return {
        "symbol":         symbol,
        "direction":      direction,
        "strategy":       "EMA_CONVERGENCE",
        "convergence":    convergence,
        "confirm_1h":     confirm,
        "levels":         levels,
        "vol_ratio":      vol_ratio,
        "ema200_clear":   True,
        "candle_time_ms": candles_4h[len(candles_4h) - 1]["time"],
        "conditions":     conditions,
    }


# ─────────────────────────────────────────────────────────────
# 策略二：EMA30 回測反彈（1H 主圖）
# ─────────────────────────────────────────────────────────────

def _scan_ema_pullback(
    symbol: str,
    candles_4h: list[dict], candles_1h: list[dict],
    emas_4h: dict,          emas_1h: dict,
) -> dict | None:
    is_main   = symbol in MAIN_COINS
    touch_pct = EMA_PULLBACK_TOUCH_PCT_MAIN if is_main else EMA_PULLBACK_TOUCH_PCT_ALT

    # 4H EMA200 大方向
    direction = _trend_direction_4h(candles_4h, emas_4h)
    if direction is None:
        return None

    # 4H EMA60 方向需與交易方向一致
    idx_4h = len(candles_4h) - 1
    e60_4h_curr = emas_4h["ema60"][idx_4h]
    e60_4h_prev = emas_4h["ema60"][idx_4h - 1] if idx_4h >= 1 else None
    if e60_4h_curr is None or e60_4h_prev is None:
        return None
    ema60_4h_rising = e60_4h_curr > e60_4h_prev
    if direction == "LONG"  and not ema60_4h_rising:
        return None
    if direction == "SHORT" and ema60_4h_rising:
        return None

    idx = len(candles_1h) - 1
    if idx < max(CROSS_LOOKBACK, EMA_PULLBACK_VOL_LOOKBACK) + 1:
        return None

    ema15   = emas_1h["ema15"][idx]
    ema30   = emas_1h["ema30"][idx]
    ema30_p = emas_1h["ema30"][idx - 1]
    ema60   = emas_1h["ema60"][idx]
    if any(v is None for v in [ema15, ema30, ema30_p, ema60]):
        return None

    # 1H EMA 多/空頭排列（EMA15 vs EMA30）
    if direction == "LONG"  and ema15 <= ema30:
        return None
    if direction == "SHORT" and ema15 >= ema30:
        return None

    # 1H 收盤在 EMA60 正確側
    close = candles_1h[idx]["close"]
    if direction == "LONG"  and close < ema60:
        return None
    if direction == "SHORT" and close > ema60:
        return None

    # 前一根K棒觸碰 EMA30 區域
    prev = candles_1h[idx - 1]
    if direction == "LONG":
        if prev["low"] > ema30_p * (1 + touch_pct):
            return None
        if close <= ema30:
            return None
        if close <= candles_1h[idx]["open"]:
            return None
    else:
        if prev["high"] < ema30_p * (1 - touch_pct):
            return None
        if close >= ema30:
            return None
        if close >= candles_1h[idx]["open"]:
            return None

    # 實體比
    ratio = body_ratio(candles_1h[idx])
    if ratio < EMA_PULLBACK_BODY:
        return None

    # 量能（前20根均量）
    avg_vol = sum(c["volume"] for c in candles_1h[idx - EMA_PULLBACK_VOL_LOOKBACK:idx]) / EMA_PULLBACK_VOL_LOOKBACK
    if avg_vol == 0:
        return None
    vol_ratio = candles_1h[idx]["volume"] / avg_vol
    if vol_ratio < EMA_PULLBACK_VOL_RATIO:
        return None

    # 1H RSI > 40（多單才檢查，確認動能未死）
    closes_1h = [c["close"] for c in candles_1h]
    rsi_vals  = calc_rsi(closes_1h, RSI_PERIOD)
    rsi_now   = rsi_vals[idx]
    if direction == "LONG":
        if rsi_now is None or rsi_now < EMA_PULLBACK_RSI_MIN:
            return None

    atrs = calc_atr(candles_1h, 14)
    atr  = atrs[idx] if atrs[idx] is not None else 0.0
    entry = close

    if direction == "LONG":
        stop_loss = min(prev["low"], ema30) - 1.0 * atr
        target1   = entry + 1.5 * (entry - stop_loss)
        target2   = entry + 2.5 * (entry - stop_loss)
    else:
        stop_loss = max(prev["high"], ema30) + 1.0 * atr
        target1   = entry - 1.5 * (stop_loss - entry)
        target2   = entry - 2.5 * (stop_loss - entry)

    # 計算觸碰距離（展示用）
    if direction == "LONG":
        actual_touch_pct = abs(prev["low"] - ema30_p) / ema30_p * 100
    else:
        actual_touch_pct = abs(prev["high"] - ema30_p) / ema30_p * 100

    conditions = [
        {"name": "4H EMA200 大方向",       "value": "多頭" if direction == "LONG" else "空頭"},
        {"name": "4H EMA60 方向一致",       "value": "上升" if ema60_4h_rising else "下降"},
        {"name": "1H EMA 排列",            "value": f"EMA15({'>' if direction=='LONG' else '<'})EMA30 通過"},
        {"name": "1H EMA60 正確側",        "value": "通過"},
        {"name": "前根觸碰 EMA30",          "value": f"{actual_touch_pct:.2f}% ≤ {touch_pct*100:.1f}%"},
        {"name": "當根反彈確認",            "value": "陽線確認" if direction == "LONG" else "陰線確認"},
        {"name": "1H RSI（多單動能確認）",  "value": f"{round(rsi_now,1) if rsi_now else 'N/A'} {'≥ 40' if direction=='LONG' else '（空單免檢）'}"},
        {"name": "量能",                   "value": f"{vol_ratio:.2f}× ≥ {EMA_PULLBACK_VOL_RATIO}×"},
        {"name": "蠟燭實體比",             "value": f"{ratio*100:.0f}% ≥ {EMA_PULLBACK_BODY*100:.0f}%"},
    ]

    return {
        "symbol":         symbol,
        "direction":      direction,
        "strategy":       "EMA_PULLBACK",
        "convergence":    {"bandwidth": 0.0, "compression_bars": 0},
        "confirm_1h":     {"body_ratio": ratio, "pullback_entry": ema30,
                           "rsi": round(rsi_now, 1) if rsi_now else None},
        "levels":         {"entry": entry, "stop_loss": stop_loss,
                           "target1": target1, "target2": target2, "atr": atr},
        "vol_ratio":      vol_ratio,
        "ema200_clear":   True,
        "candle_time_ms": candles_1h[idx]["time"],
        "conditions":     conditions,
    }



# ─────────────────────────────────────────────────────────────
# 統一入口
# ─────────────────────────────────────────────────────────────

def scan_symbol(
    symbol: str,
    candles_4h: list[dict],
    candles_1h: list[dict],
    btc_regime_bull: bool = True,
) -> dict | None:
    """
    依序嘗試兩種策略，任一通過即回傳結果 dict，全部失敗則回傳 None。
    btc_regime_bull=False 時（BTC 4H EMA15 < EMA60），山寨多單全部封鎖。
    """
    is_main          = symbol in MAIN_COINS
    regime_ok        = btc_regime_bull or is_main  # 主流幣不受 Regime 限制
    regime_label     = "通過" if regime_ok else "暫停（BTC 空頭環境）"

    emas_4h = ema_snapshot(candles_4h)
    emas_1h = ema_snapshot(candles_1h)
    if emas_4h is None:
        return None

    def _apply_regime(result: dict | None) -> dict | None:
        if result is None:
            return None
        if not regime_ok and result["direction"] == "LONG":
            return None   # Regime Filter 封鎖山寨多單
        result["regime_filter"] = regime_label
        return result

    # 策略一：EMA 收斂突破（4H 主導，品質最高）
    if emas_1h is not None:
        result = _apply_regime(_scan_ema_convergence(symbol, candles_4h, candles_1h, emas_4h, emas_1h))
        if result:
            return result

    # 策略二：EMA30 回測反彈（1H）
    if emas_1h is not None:
        result = _apply_regime(_scan_ema_pullback(symbol, candles_4h, candles_1h, emas_4h, emas_1h))
        if result:
            return result

    return None
