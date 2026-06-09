"""
評分系統模組
依據掃描結果計算 0–10 分
"""

from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))
MIN_SCORE = 6.0

# 台灣時間歐美盤時間範圍（15:00–22:00）
EU_US_SESSION_START = 15
EU_US_SESSION_END   = 22


def _session_bonus() -> float:
    """判斷當前是否為歐美盤時段（台灣時間）"""
    now_tw = datetime.now(TW_TZ)
    if EU_US_SESSION_START <= now_tw.hour < EU_US_SESSION_END:
        return 1.0
    return 0.0


def score_setup(result: dict) -> float:
    """
    計算單一交易對的綜合得分
    result 來自 scanner.scan_symbol 的回傳值
    """
    score = 0.0
    bw   = result["convergence"]["bandwidth"]
    bars = result["convergence"]["compression_bars"]
    vol  = result["vol_ratio"]
    body = result["confirm_1h"]["body_ratio"]

    # 帶寬壓縮程度（0–2 分）
    if bw < 1.0:
        score += 2.0
    elif bw < 1.5:
        score += 1.0
    elif bw < 2.0:
        score += 0.5

    # 壓縮持續時間（0–2 分）
    if bars >= 5:
        score += 2.0
    elif bars >= 3:
        score += 1.0

    # 突破量能（0–2 分）
    if vol >= 2.0:
        score += 2.0
    elif vol >= 1.5:
        score += 1.0

    # 1H 蠟燭實體比例（0–1 分）
    if body >= 0.70:
        score += 1.0
    elif body >= 0.60:
        score += 0.5

    # EMA200 方向明確（0–1 分）
    if result.get("ema200_clear"):
        score += 1.0

    # 1H EMA 穿越確認（0–1 分）— 能走到這裡代表已確認
    score += 1.0

    # 歐美盤時段加分（0–1 分）
    score += _session_bonus()

    return round(min(score, 10.0), 1)


def passes_threshold(score: float) -> bool:
    return score >= MIN_SCORE
