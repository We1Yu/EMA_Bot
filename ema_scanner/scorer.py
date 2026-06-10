"""
評分系統模組
依策略類型計算 0–10 分
"""

from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))
MIN_SCORE = 6.0

EU_US_SESSION_START = 15
EU_US_SESSION_END   = 22


def _session_bonus() -> float:
    now_tw = datetime.now(TW_TZ)
    if EU_US_SESSION_START <= now_tw.hour < EU_US_SESSION_END:
        return 1.0
    return 0.0


def score_setup(result: dict) -> float:
    strategy = result.get("strategy", "EMA_CONVERGENCE")
    if strategy == "EMA_CONVERGENCE":
        return _score_convergence(result)
    if strategy == "OI_LS_SIGNAL":
        return _score_oi_ls(result)
    return _score_momentum(result)


def _score_convergence(result: dict) -> float:
    """EMA 收斂突破策略評分（原始邏輯）"""
    score = 0.0
    bw   = result["convergence"]["bandwidth"]
    bars = result["convergence"]["compression_bars"]
    vol  = result["vol_ratio"]
    body = result["confirm_1h"]["body_ratio"]

    if bw < 1.0:    score += 2.0
    elif bw < 1.5:  score += 1.0
    elif bw < 2.0:  score += 0.5

    if bars >= 5:   score += 2.0
    elif bars >= 3: score += 1.0

    if vol >= 2.0:  score += 2.0
    elif vol >= 1.5: score += 1.0

    if body >= 0.70:  score += 1.0
    elif body >= 0.60: score += 0.5

    if result.get("ema200_clear"):
        score += 1.0
    score += 1.0          # 1H EMA 穿越已確認
    score += _session_bonus()

    return round(min(score, 10.0), 1)


def _score_momentum(result: dict) -> float:
    """EMA_PULLBACK / RSI_BOUNCE / MACD_CROSS 通用評分"""
    score = 3.0   # 有效形態基礎分
    vol  = result["vol_ratio"]
    body = result["confirm_1h"]["body_ratio"]

    if vol >= 2.0:    score += 2.0
    elif vol >= 1.5:  score += 1.5
    elif vol >= 1.2:  score += 0.5

    if body >= 0.75:   score += 2.0
    elif body >= 0.65: score += 1.5
    elif body >= 0.55: score += 0.5

    if result.get("ema200_clear"):
        score += 1.0

    # RSI 越極端加分
    if result.get("strategy") == "RSI_BOUNCE":
        rsi = result["confirm_1h"].get("rsi")
        if rsi is not None:
            if result["direction"] == "LONG"  and rsi < 25:
                score += 1.0
            elif result["direction"] == "SHORT" and rsi > 75:
                score += 1.0

    score += _session_bonus()
    return round(min(score, 10.0), 1)


def _score_oi_ls(result: dict) -> float:
    """OI + 多空比策略專用評分（純數據流派）"""
    score = 3.0   # 基礎分
    vol   = result["vol_ratio"]
    body  = result["confirm_1h"]["body_ratio"]
    info  = result["confirm_1h"]

    # OI 升幅越大越強
    oi_pct = info.get("oi_change_pct", 0)
    if oi_pct >= 8.0:   score += 2.5
    elif oi_pct >= 5.0: score += 2.0
    elif oi_pct >= 3.0: score += 1.0
    else:               score += 0.5

    # 多頭佔比越偏越強
    long_pct = info.get("long_pct", 50)
    deviation = abs(long_pct - 50)   # 偏離中性(50%)的程度
    if deviation >= 10:   score += 2.0
    elif deviation >= 6:  score += 1.0
    elif deviation >= 3:  score += 0.5

    # 量能
    if vol >= 2.0:    score += 1.5
    elif vol >= 1.5:  score += 1.0
    elif vol >= 1.2:  score += 0.5

    # 實體比例
    if body >= 0.65:  score += 1.0
    elif body >= 0.50: score += 0.5

    score += _session_bonus()
    return round(min(score, 10.0), 1)


def passes_threshold(score: float) -> bool:
    return score >= MIN_SCORE
