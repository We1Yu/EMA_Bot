"""
Discord 通知模組
建立嵌入訊息並透過 Webhook 發送
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# 顏色定義
COLOR_LONG     = 0x00FF88
COLOR_SHORT    = 0xFF4444
COLOR_MARGINAL = 0xFFCC00   # 6.0–6.9 分

MAX_HOLD_HOURS = 48


def _pct(value: float, reference: float) -> str:
    """計算相對百分比字串"""
    if reference == 0:
        return "N/A"
    return f"{(value - reference) / reference * 100:+.2f}%"


def _fmt_price(price: float) -> str:
    """根據數值大小選擇合適的小數位數"""
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:.4f}"
    return f"{price:.6f}"


def _now_tw_str() -> str:
    return datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M TWN")


def build_setup_embed(result: dict, score: float) -> dict:
    """建立交易設置的 Discord Embed 物件"""
    symbol    = result["symbol"]
    direction = result["direction"]
    levels    = result["levels"]
    conv      = result["convergence"]
    conf      = result["confirm_1h"]

    entry     = levels["entry"]
    sl        = levels["stop_loss"]
    t1        = levels["target1"]
    t2        = levels["target2"]
    pullback  = conf["pullback_entry"]

    # 到期時間
    now_tw    = datetime.now(TW_TZ)
    expire_tw = now_tw + timedelta(hours=MAX_HOLD_HOURS)
    expire_str = expire_tw.strftime("%Y/%m/%d %H:%M TWN")

    # 歐美盤判斷
    in_session = TW_TZ and (15 <= now_tw.hour < 22)
    session_str = "✅ EU/US Session" if in_session else "⚪ Off Session"

    # 顏色選擇
    if score < 7.0:
        color = COLOR_MARGINAL
    elif direction == "LONG":
        color = COLOR_LONG
    else:
        color = COLOR_SHORT

    icon  = "🟢" if direction == "LONG" else "🔴"
    rr1   = abs(t1 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
    rr2   = abs(t2 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

    description = (
        f"**📊 Setup**\n"
        f"```\n"
        f"  4H Bandwidth : {conv['bandwidth']:.2f}%  (compressed {conv['compression_bars']} bars)\n"
        f"  Breakout Vol : {result['vol_ratio']:.1f}× average\n"
        f"  EMA 200 Bias : {'Above → LONG only' if direction == 'LONG' else 'Below → SHORT only'}\n"
        f"  Session      : {session_str} ({now_tw.strftime('%H:%M TWN')})\n"
        f"```\n"
        f"**💰 Trade Levels**\n"
        f"```\n"
        f"  Entry Now    : ${_fmt_price(entry)}\n"
        f"  Ideal Entry  : ${_fmt_price(pullback)}  (pullback to EMA30 1H)\n"
        f"  Stop Loss    : ${_fmt_price(sl)}  ({_pct(sl, entry)})\n"
        f"  Target 1     : ${_fmt_price(t1)}  (+{rr1:.1f}R / {_pct(t1, entry)})\n"
        f"  Target 2     : ${_fmt_price(t2)}  (+{rr2:.1f}R / {_pct(t2, entry)})\n"
        f"  Max Hold     : {MAX_HOLD_HOURS} hrs → exit by {expire_str}\n"
        f"```\n"
        f"**⚠️ Invalidation**\n"
        f"If price closes back inside EMA cluster → exit immediately\n\n"
        f"─────────────────────────────\n"
        f"EMA Convergence Scanner • {_now_tw_str()}"
    )

    return {
        "title":       f"{icon} {direction} Setup — {symbol}                     [Score: {score} / 10]",
        "description": description,
        "color":       color,
    }


def build_no_setup_embed(total: int, converging: int) -> dict:
    """建立無訊號的摘要 Embed"""
    return {
        "title":       "🔍 Scan complete — no setups above threshold",
        "description": (
            f"Scanned: **{total}** coins  |  "
            f"Converging: **{converging}**  |  "
            f"Breaking out: **0**\n"
            f"Next scan: 60 min"
        ),
        "color": 0x888888,
    }


def send_embeds(embeds: list[dict]) -> bool:
    """
    批次發送 Embeds（Discord 單次最多 10 個）
    回傳是否全部成功
    """
    if not WEBHOOK_URL:
        print("[Discord] 未設定 DISCORD_WEBHOOK_URL，跳過發送")
        return False

    success = True
    # 每批最多 10 個 embed
    for i in range(0, len(embeds), 10):
        batch = embeds[i:i + 10]
        payload = {"embeds": batch}
        try:
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
            if resp.status_code not in (200, 204):
                print(f"[Discord] 發送失敗 HTTP {resp.status_code}: {resp.text[:200]}")
                success = False
        except Exception as e:
            print(f"[Discord] 發送異常：{e}")
            success = False

    return success


def send_setup_alerts(results_with_scores: list[tuple[dict, float]]) -> None:
    """發送所有達標交易設置通知"""
    embeds = [build_setup_embed(r, s) for r, s in results_with_scores]
    if embeds:
        send_embeds(embeds)


def send_no_setup_summary(total: int, converging: int) -> None:
    """發送無訊號摘要"""
    embed = build_no_setup_embed(total, converging)
    send_embeds([embed])
