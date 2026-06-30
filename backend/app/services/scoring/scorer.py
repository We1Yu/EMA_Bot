"""
評分系統模組
依策略類型計算 0–10 分
"""

from datetime import datetime, timezone, timedelta

TW_TZ     = timezone(timedelta(hours=8))
MIN_SCORE = 7.5

EU_US_SESSION_START = 15
EU_US_SESSION_END   = 22


def _session_bonus(bar_time_ms: int | None = None) -> float:
    if bar_time_ms is not None:
        dt = datetime.fromtimestamp(bar_time_ms / 1000, tz=TW_TZ)
    else:
        dt = datetime.now(TW_TZ)
    if EU_US_SESSION_START <= dt.hour < EU_US_SESSION_END:
        return 1.0
    return 0.0


def score_setup(result: dict, bar_time_ms: int | None = None) -> float:
    strategy = result.get("strategy", "EMA_CONVERGENCE")
    if strategy == "EMA_CONVERGENCE":
        return _score_convergence(result, bar_time_ms)
    if strategy == "EMA_SQUEEZE_BREAKOUT":
        return _score_squeeze_breakout(result, bar_time_ms)
    if strategy == "STRUCTURE_BREAKOUT":
        return _score_structure_breakout(result, bar_time_ms)
    return _score_momentum(result, bar_time_ms)


def _score_convergence(result: dict, bar_time_ms: int | None = None) -> float:
    score = 0.0
    bw    = result["convergence"]["bandwidth"]
    bars  = result["convergence"]["compression_bars"]
    vol   = result["vol_ratio"]
    body  = result["confirm_1h"]["body_ratio"]

    if bw < 1.0:    score += 2.0
    elif bw < 1.5:  score += 1.0
    elif bw < 2.0:  score += 0.5

    if bars >= 5:   score += 2.0
    elif bars >= 3: score += 1.0

    if vol >= 2.0:   score += 2.0
    elif vol >= 1.5: score += 1.0

    if body >= 0.70:   score += 1.0
    elif body >= 0.60: score += 0.5

    if result.get("ema200_clear"):
        score += 1.0
    score += 1.0
    score += _bonus_indicators(result)
    score += _session_bonus(bar_time_ms)

    return round(min(score, 10.0), 1)


def _score_squeeze_breakout(result: dict, bar_time_ms: int | None = None) -> float:
    """
    純 4H 出量突破評分。與 EMA_CONVERGENCE 同維度，但少了代表「1H 穿越確認」
    的 +1.0 基礎分 —— 缺少二次確認的進場本來就該更難達到 7.5 門檻，
    自然只放行量能/實體/收斂最強的突破。
    """
    score = 0.0
    bw    = result["convergence"]["bandwidth"]
    bars  = result["convergence"]["compression_bars"]
    vol   = result["vol_ratio"]
    body  = result["confirm_1h"]["body_ratio"]

    if bw < 1.0:    score += 2.0
    elif bw < 1.5:  score += 1.0
    elif bw < 2.0:  score += 0.5

    if bars >= 5:   score += 2.0
    elif bars >= 3: score += 1.0

    if vol >= 2.0:   score += 2.0
    elif vol >= 1.5: score += 1.0

    if body >= 0.70:   score += 1.0
    elif body >= 0.60: score += 0.5

    if result.get("ema200_clear"):
        score += 1.0

    score += _bonus_indicators(result)
    score += _session_bonus(bar_time_ms)
    return round(min(score, 10.0), 1)


def _score_momentum(result: dict, bar_time_ms: int | None = None) -> float:
    """通用動能評分（未匹配特定策略時的 fallback）"""
    score = 3.0
    vol   = result["vol_ratio"]
    body  = result["confirm_1h"]["body_ratio"]

    if vol >= 2.0:    score += 2.0
    elif vol >= 1.5:  score += 1.5
    elif vol >= 1.2:  score += 0.5

    if body >= 0.75:   score += 2.0
    elif body >= 0.65: score += 1.5
    elif body >= 0.55: score += 0.5

    if result.get("ema200_clear"):
        score += 1.0

    score += _bonus_indicators(result)
    score += _session_bonus(bar_time_ms)
    return round(min(score, 10.0), 1)


def _score_structure_breakout(result: dict, bar_time_ms: int | None = None) -> float:
    score = 4.0
    vol   = result["vol_ratio"]
    body  = result["confirm_1h"]["body_ratio"]

    if vol >= 2.5:    score += 2.5
    elif vol >= 2.0:  score += 2.0
    elif vol >= 1.5:  score += 1.0

    if body >= 0.75:   score += 2.0
    elif body >= 0.65: score += 1.5
    elif body >= 0.55: score += 0.5

    if result.get("ema200_clear"):
        score += 1.0

    score += _bonus_indicators(result)
    score += _session_bonus(bar_time_ms)
    return round(min(score, 10.0), 1)


def _bonus_indicators(result: dict) -> float:
    """RSI / MACD / BB 加分（最多 +2.0）"""
    bonus     = result.get("bonus_indicators", {})
    direction = result.get("direction", "LONG")
    score     = 0.0

    rsi = bonus.get("rsi_1h")
    if rsi is not None:
        if direction == "LONG"  and 45 <= rsi <= 65:
            score += 0.5
        elif direction == "SHORT" and 35 <= rsi <= 55:
            score += 0.5

    if bonus.get("macd_aligned"):
        score += 0.5
    if bonus.get("macd_crossed"):
        score += 0.5

    if bonus.get("bb_side_ok"):
        score += 0.5

    return min(score, 2.0)


def passes_threshold(score: float) -> bool:
    return score >= MIN_SCORE
