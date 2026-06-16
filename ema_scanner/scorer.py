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
    score += _bonus_indicators(result)
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

    score += _bonus_indicators(result)
    score += _session_bonus()
    return round(min(score, 10.0), 1)



def _bonus_indicators(result: dict) -> float:
    """
    RSI / MACD / BB 加分（最多 +2.0）。
    EMA 仍是唯一入場條件，這些指標只影響分數高低。
    """
    bonus     = result.get("bonus_indicators", {})
    direction = result.get("direction", "LONG")
    score     = 0.0

    # RSI：動能方向與交易方向一致且不過熱
    rsi = bonus.get("rsi_1h")
    if rsi is not None:
        if direction == "LONG"  and 45 <= rsi <= 65:
            score += 0.5   # 動能正在建立，還有上漲空間
        elif direction == "SHORT" and 35 <= rsi <= 55:
            score += 0.5

    # MACD 柱狀圖方向與交易方向一致
    if bonus.get("macd_aligned"):
        score += 0.5
    # 柱狀圖剛穿越零軸（更強的訊號）
    if bonus.get("macd_crossed"):
        score += 0.5

    # BB：收盤在中軌正確側
    if bonus.get("bb_side_ok"):
        score += 0.5

    return min(score, 2.0)


def passes_threshold(score: float) -> bool:
    return score >= MIN_SCORE
