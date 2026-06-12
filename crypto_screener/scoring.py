"""Scoring system — 0-150 base, bonuses uncapped."""

import pandas as pd
from indicators import calc_rsi, calc_bbw, calc_adx, calc_sma, calc_macd
from config import (
    CLUSTER_THRESHOLD, VOL_RATIO_MIN, RSI_PERIOD, ADX_PERIOD,
    BBW_PERIOD, BBW_STD, BBW_STRONG, BBW_MED, BBW_WEAK,
    OI_SPIKE_THRESHOLD, FLOW_STRONG, FLOW_MED,
)


def compute_score(data: dict) -> tuple[int, dict]:
    """
    Returns (total_score, breakdown_dict).
    data must contain all fields populated by scanner.py.
    """
    close  = data["close"]
    high   = data["high"]
    low    = data["low"]
    open_  = data["open_"]
    volume = data["volume"]
    ma15   = data["ma15"]
    ma30   = data["ma30"]
    ma45   = data["ma45"]
    ma60   = data["ma60"]
    ma200  = data["ma200"]
    tier   = data["tier"]

    breakdown: dict[str, float] = {}

    # ── CORE BREAKOUT QUALITY (55 pts) ────────────────────────

    # MA Cluster Tightness (25)
    c_prev    = close.iloc[-2]
    ma_vals   = [ma15.iloc[-2], ma30.iloc[-2], ma45.iloc[-2], ma60.iloc[-2]]
    spread_pct = (max(ma_vals) - min(ma_vals)) / c_prev
    cluster_score = max(0.0, 25 * (1 - spread_pct / CLUSTER_THRESHOLD))
    breakdown["cluster_tightness"] = round(cluster_score, 1)

    # Volume Surge (20)
    vol_ratio = volume.iloc[-1] / volume.iloc[-6:-1].mean()
    vol_score = min(20.0, 20 * (vol_ratio - VOL_RATIO_MIN) / VOL_RATIO_MIN)
    breakdown["volume_surge"] = round(max(0.0, vol_score), 1)

    # Candle Body Quality (10)
    candle_range = high.iloc[-1] - low.iloc[-1]
    body_pct     = abs(close.iloc[-1] - open_.iloc[-1]) / candle_range if candle_range else 0
    body_score   = 10 * body_pct
    breakdown["body_quality"] = round(body_score, 1)

    # ── FALSE BREAKOUT FILTERS (35 pts) ──────────────────────

    # RSI Zone (15)
    rsi_s   = calc_rsi(close, RSI_PERIOD)
    rsi_now = rsi_s.iloc[-1]
    if 50 <= rsi_now <= 65:
        rsi_score = 15
    elif 45 <= rsi_now < 50:
        rsi_score = 8
    elif 65 < rsi_now <= 75:
        rsi_score = 5
    else:
        rsi_score = 0
    breakdown["rsi_zone"] = rsi_score

    # BBW Compression (10)
    bbw = calc_bbw(close, BBW_PERIOD, BBW_STD)
    bbw_5avg  = bbw.iloc[-6:-1].mean()
    bbw_20avg = bbw.iloc[-21:-1].mean()
    bbw_ratio = bbw_5avg / bbw_20avg if bbw_20avg else 1.0
    if bbw_ratio <= BBW_STRONG:
        bbw_score = 10
    elif bbw_ratio <= BBW_MED:
        bbw_score = 7
    elif bbw_ratio <= BBW_WEAK:
        bbw_score = 4
    else:
        bbw_score = 0
    breakdown["bbw_compression"] = bbw_score
    breakdown["bbw_ratio"] = round(bbw_ratio, 3)

    # Candle Close Position (10)
    upper_wick_ratio = (high.iloc[-1] - close.iloc[-1]) / candle_range if candle_range else 1
    close_pos_score  = 10 * (1 - upper_wick_ratio)
    breakdown["close_position"] = round(max(0.0, close_pos_score), 1)

    # ── TREND CONFIRMATION (35 pts) ───────────────────────────

    # Position vs 200 MA (15)
    m200      = ma200.iloc[-1]
    m200_prev = ma200.iloc[-2]
    c_last    = close.iloc[-1]
    crossed_200 = c_last > m200 and close.iloc[-2] <= m200_prev
    if tier in ("A", "B") or c_last > m200:
        ma200_score = 15
    else:
        ma200_score = 0
    breakdown["ma200_position"] = ma200_score

    # 200 MA Slope (10)
    m200_6ago   = ma200.iloc[-6]
    slope_200   = (m200 - m200_6ago) / m200_6ago if m200_6ago else 0
    if slope_200 > 0.005:
        slope_score = 10
    elif slope_200 >= 0:
        slope_score = 5
    else:
        slope_score = 0
    breakdown["ma200_slope"] = slope_score

    # ADX Trend Strength (10)
    adx_s, pdi_s, mdi_s = calc_adx(high, low, close, ADX_PERIOD)
    adx_now = adx_s.iloc[-1]
    if adx_now > 30 and pdi_s.iloc[-1] > mdi_s.iloc[-1]:
        adx_score = 10
    elif adx_now > 25:
        adx_score = 7
    elif adx_now > ADX_PERIOD:
        adx_score = 4
    else:
        adx_score = 0
    breakdown["adx_strength"] = adx_score

    # ── MACD MOMENTUM (10 pts) ───────────────────────────────
    _, _, macd_hist = calc_macd(close)
    h_now  = macd_hist.iloc[-1]
    h_prev = macd_hist.iloc[-2]
    if not pd.isna(h_now) and not pd.isna(h_prev):
        if h_now > 0 and h_now > h_prev:
            macd_score = 10   # 柱體正值且擴張 → 強勢
        elif h_now > 0:
            macd_score = 5    # 柱體正值但收縮
        elif h_now > h_prev:
            macd_score = 3    # 柱體負值但回升（動能轉折初期）
        else:
            macd_score = 0
    else:
        macd_score = 0
    breakdown["macd_momentum"] = macd_score

    # ── MARKET CONTEXT (25 pts) ───────────────────────────────

    # Funding Rate (10) — LONG favoured when funding is low/negative
    # < 0.03%  (0.0003): cheap to hold long → full score
    # 0.03-0.1% (0.001): acceptable
    # > 0.1%           : crowded longs, penalise via bonus
    funding = data.get("funding_rate", 0.0)
    if funding <= 0.0003:
        fund_score = 10
    elif funding <= 0.001:
        fund_score = 5
    else:
        fund_score = 0
    breakdown["funding"] = fund_score

    # 24H Momentum (10)
    change_24h = data.get("change_24h", 0.0)
    if change_24h > 5:
        mom_score = 10
    elif change_24h >= 2:
        mom_score = 5
    else:
        mom_score = 0
    breakdown["momentum_24h"] = mom_score

    # Weekly Trend (5)
    w_close  = data.get("weekly_close")
    w_ma20   = data.get("weekly_ma20")
    w_slope  = data.get("weekly_slope", 0)
    if w_close is not None and w_ma20 is not None:
        weekly_above = w_close.iloc[-1] > w_ma20.iloc[-1]
        if weekly_above and w_slope > 0:
            weekly_score = 5
        elif weekly_above:
            weekly_score = 3
        else:
            weekly_score = 0
    else:
        weekly_score = 0
    breakdown["weekly_trend"] = weekly_score

    # ── HF 市場微結構 (20 pts) ────────────────────────────────

    # OI Momentum (10) — 上漲 + OI 增加 = 新多單入場 = 真實動能
    oi_chg = data.get("oi_change_pct", 0.0)
    if oi_chg >= OI_SPIKE_THRESHOLD:
        oi_score = 10   # 顯著建倉異常
    elif oi_chg >= 0.03:
        oi_score = 6
    elif oi_chg >= -0.05:
        oi_score = 3    # OI 持平
    else:
        oi_score = 0    # OI 下降 = 軋空行情，動能較弱
    breakdown["oi_momentum"] = oi_score

    # Trade Flow Pressure (10) — 淨買壓確認多單
    flow = data.get("flow_ratio", 0.0)
    if flow >= FLOW_STRONG:
        flow_score = 10
    elif flow >= FLOW_MED:
        flow_score = 6
    elif flow >= 0:
        flow_score = 2
    else:
        flow_score = 0   # 淨賣壓 — 對多單不利
    breakdown["flow_pressure"] = flow_score

    # ── BONUS MODIFIERS (additive) ────────────────────────────
    bonus = 0

    # +8 if 4H and 1H signals fire simultaneously
    if data.get("dual_timeframe"):
        bonus += 8
        breakdown["bonus_dual_tf"] = 8

    # +5 TIER B reversal
    if tier == "B":
        bonus += 5
        breakdown["bonus_tier_b"] = 5

    # +3 RSI crossed 50 upward
    rsi_prev = rsi_s.iloc[-2]
    if not pd.isna(rsi_prev) and rsi_prev < 50 <= rsi_now:
        bonus += 3
        breakdown["bonus_rsi_cross50"] = 3

    # +3 ADX rising
    adx_3ago = adx_s.iloc[-3]
    if not pd.isna(adx_3ago) and adx_now > adx_3ago:
        bonus += 3
        breakdown["bonus_adx_rising"] = 3

    # +3 negative funding (shorts paying longs — rare, very favourable)
    if funding < 0:
        bonus += 3
        breakdown["bonus_neg_funding"] = 3

    # -5 very high funding (> 0.1%): crowded long, increased reversal risk
    if funding > 0.001:
        bonus -= 5
        breakdown["penalty_high_funding"] = -5

    # +5 巨鯨買單出現且與多單方向一致
    if data.get("large_trade", False) and data.get("flow_ratio", 0.0) > 0:
        bonus += 5
        breakdown["bonus_whale"] = 5

    breakdown["bonus_total"] = bonus

    base  = (cluster_score + vol_score + body_score +
             rsi_score + bbw_score + close_pos_score +
             ma200_score + slope_score + adx_score +
             macd_score +
             fund_score + mom_score + weekly_score +
             oi_score + flow_score)
    total = int(round(base + bonus))
    breakdown["base"]  = round(base, 1)
    breakdown["total"] = total

    return total, breakdown


def compute_score_short(data: dict) -> tuple[int, dict]:
    """
    Mirror of compute_score() for SHORT setups (breakdown below MA cluster).
    Returns (total_score, breakdown_dict).
    """
    close  = data["close"]
    high   = data["high"]
    low    = data["low"]
    open_  = data["open_"]
    volume = data["volume"]
    ma15   = data["ma15"]
    ma30   = data["ma30"]
    ma45   = data["ma45"]
    ma60   = data["ma60"]
    ma200  = data["ma200"]
    tier   = data["tier"]

    breakdown: dict[str, float] = {}

    # ── CORE BREAKDOWN QUALITY (55 pts) ───────────────────────

    # MA Cluster Tightness (25)
    c_prev    = close.iloc[-2]
    ma_vals   = [ma15.iloc[-2], ma30.iloc[-2], ma45.iloc[-2], ma60.iloc[-2]]
    spread_pct = (max(ma_vals) - min(ma_vals)) / c_prev
    cluster_score = max(0.0, 25 * (1 - spread_pct / CLUSTER_THRESHOLD))
    breakdown["cluster_tightness"] = round(cluster_score, 1)

    # Volume Surge (20)
    vol_ratio = volume.iloc[-1] / volume.iloc[-6:-1].mean()
    vol_score = min(20.0, 20 * (vol_ratio - VOL_RATIO_MIN) / VOL_RATIO_MIN)
    breakdown["volume_surge"] = round(max(0.0, vol_score), 1)

    # Candle Body Quality (10)
    candle_range = high.iloc[-1] - low.iloc[-1]
    body_pct     = abs(close.iloc[-1] - open_.iloc[-1]) / candle_range if candle_range else 0
    body_score   = 10 * body_pct
    breakdown["body_quality"] = round(body_score, 1)

    # ── FALSE BREAKDOWN FILTERS (35 pts) ─────────────────────

    # RSI Zone (15) — mirrored bearish zone
    rsi_s   = calc_rsi(close, RSI_PERIOD)
    rsi_now = rsi_s.iloc[-1]
    if 35 <= rsi_now <= 50:
        rsi_score = 15
    elif 50 < rsi_now <= 55:
        rsi_score = 8
    elif 25 <= rsi_now < 35:
        rsi_score = 5
    else:
        rsi_score = 0
    breakdown["rsi_zone"] = rsi_score

    # BBW Compression (10)
    bbw = calc_bbw(close, BBW_PERIOD, BBW_STD)
    bbw_5avg  = bbw.iloc[-6:-1].mean()
    bbw_20avg = bbw.iloc[-21:-1].mean()
    bbw_ratio = bbw_5avg / bbw_20avg if bbw_20avg else 1.0
    if bbw_ratio <= BBW_STRONG:
        bbw_score = 10
    elif bbw_ratio <= BBW_MED:
        bbw_score = 7
    elif bbw_ratio <= BBW_WEAK:
        bbw_score = 4
    else:
        bbw_score = 0
    breakdown["bbw_compression"] = bbw_score
    breakdown["bbw_ratio"] = round(bbw_ratio, 3)

    # Candle Close Position (10) — reward close near the LOW
    lower_wick_ratio = (close.iloc[-1] - low.iloc[-1]) / candle_range if candle_range else 1
    close_pos_score  = 10 * (1 - lower_wick_ratio)
    breakdown["close_position"] = round(max(0.0, close_pos_score), 1)

    # ── TREND CONFIRMATION (35 pts) ───────────────────────────

    # Position vs 200 MA (15)
    m200      = ma200.iloc[-1]
    m200_prev = ma200.iloc[-2]
    c_last    = close.iloc[-1]
    if tier in ("A", "B") or c_last < m200:
        ma200_score = 15
    else:
        ma200_score = 0
    breakdown["ma200_position"] = ma200_score

    # 200 MA Slope (10) — falling is good
    m200_6ago = ma200.iloc[-6]
    slope_200 = (m200 - m200_6ago) / m200_6ago if m200_6ago else 0
    if slope_200 < -0.005:
        slope_score = 10
    elif slope_200 <= 0:
        slope_score = 5
    else:
        slope_score = 0
    breakdown["ma200_slope"] = slope_score

    # ADX Trend Strength (10) — -DI must lead +DI
    adx_s, pdi_s, mdi_s = calc_adx(high, low, close, ADX_PERIOD)
    adx_now = adx_s.iloc[-1]
    if adx_now > 30 and mdi_s.iloc[-1] > pdi_s.iloc[-1]:
        adx_score = 10
    elif adx_now > 25:
        adx_score = 7
    elif adx_now > ADX_PERIOD:
        adx_score = 4
    else:
        adx_score = 0
    breakdown["adx_strength"] = adx_score

    # ── MACD MOMENTUM (10 pts) ───────────────────────────────
    _, _, macd_hist = calc_macd(close)
    h_now  = macd_hist.iloc[-1]
    h_prev = macd_hist.iloc[-2]
    if not pd.isna(h_now) and not pd.isna(h_prev):
        if h_now < 0 and h_now < h_prev:
            macd_score = 10   # 柱體負值且擴張 → 空頭強勢
        elif h_now < 0:
            macd_score = 5    # 柱體負值但收縮
        elif h_now < h_prev:
            macd_score = 3    # 柱體正值但下滑（動能轉弱初期）
        else:
            macd_score = 0
    else:
        macd_score = 0
    breakdown["macd_momentum"] = macd_score

    # ── MARKET CONTEXT (25 pts) ───────────────────────────────

    # Funding Rate (10) — SHORT favoured when longs are paying high rates
    # > 0.03% (0.0003): longs paying shorts → full score
    # 0 to 0.03%      : neutral, acceptable
    # < -0.1% (-0.001): crowded shorts, penalise via bonus
    funding = data.get("funding_rate", 0.0)
    if funding >= 0.0003:
        fund_score = 10
    elif funding >= 0:
        fund_score = 6
    elif funding >= -0.001:
        fund_score = 3
    else:
        fund_score = 0
    breakdown["funding"] = fund_score

    # 24H Momentum (10) — strong negative momentum favors shorts
    change_24h = data.get("change_24h", 0.0)
    if change_24h < -5:
        mom_score = 10
    elif change_24h <= -2:
        mom_score = 5
    else:
        mom_score = 0
    breakdown["momentum_24h"] = mom_score

    # Weekly Trend (5) — bearish weekly favors shorts
    w_close  = data.get("weekly_close")
    w_ma20   = data.get("weekly_ma20")
    w_slope  = data.get("weekly_slope", 0)
    if w_close is not None and w_ma20 is not None:
        weekly_below = w_close.iloc[-1] < w_ma20.iloc[-1]
        if weekly_below and w_slope < 0:
            weekly_score = 5
        elif weekly_below:
            weekly_score = 3
        else:
            weekly_score = 0
    else:
        weekly_score = 0
    breakdown["weekly_trend"] = weekly_score

    # ── HF 市場微結構 (20 pts) ────────────────────────────────

    # OI Momentum (10) — 下跌 + OI 增加 = 新空單入場 = 真實動能
    oi_chg = data.get("oi_change_pct", 0.0)
    if oi_chg >= OI_SPIKE_THRESHOLD:
        oi_score = 10
    elif oi_chg >= 0.03:
        oi_score = 6
    elif oi_chg >= -0.05:
        oi_score = 3
    else:
        oi_score = 0    # OI 下降 = 多單平倉，空頭動能較弱
    breakdown["oi_momentum"] = oi_score

    # Trade Flow Pressure (10) — 淨賣壓確認空單
    flow = data.get("flow_ratio", 0.0)
    if flow <= -FLOW_STRONG:
        flow_score = 10
    elif flow <= -FLOW_MED:
        flow_score = 6
    elif flow <= 0:
        flow_score = 2
    else:
        flow_score = 0   # 淨買壓 — 對空單不利
    breakdown["flow_pressure"] = flow_score

    # ── BONUS MODIFIERS (additive) ────────────────────────────
    bonus = 0

    # +8 if 4H and 1H signals fire simultaneously
    if data.get("dual_timeframe"):
        bonus += 8
        breakdown["bonus_dual_tf"] = 8

    # +5 TIER B reversal
    if tier == "B":
        bonus += 5
        breakdown["bonus_tier_b"] = 5

    # +3 RSI crossed 50 downward
    rsi_prev = rsi_s.iloc[-2]
    if not pd.isna(rsi_prev) and rsi_prev > 50 >= rsi_now:
        bonus += 3
        breakdown["bonus_rsi_cross50"] = 3

    # +3 ADX rising
    adx_3ago = adx_s.iloc[-3]
    if not pd.isna(adx_3ago) and adx_now > adx_3ago:
        bonus += 3
        breakdown["bonus_adx_rising"] = 3

    # +3 high positive funding (> 0.1%): longs paying heavily, favours shorts
    if funding > 0.001:
        bonus += 3
        breakdown["bonus_high_funding"] = 3

    # -5 very negative funding (< -0.1%): crowded shorts, increased reversal risk
    if funding < -0.001:
        bonus -= 5
        breakdown["penalty_neg_funding"] = -5

    # +5 巨鯨賣單出現且與空單方向一致
    if data.get("large_trade", False) and data.get("flow_ratio", 0.0) < 0:
        bonus += 5
        breakdown["bonus_whale"] = 5

    breakdown["bonus_total"] = bonus

    base  = (cluster_score + vol_score + body_score +
             rsi_score + bbw_score + close_pos_score +
             ma200_score + slope_score + adx_score +
             macd_score +
             fund_score + mom_score + weekly_score +
             oi_score + flow_score)
    total = int(round(base + bonus))
    breakdown["base"]  = round(base, 1)
    breakdown["total"] = total

    return total, breakdown
