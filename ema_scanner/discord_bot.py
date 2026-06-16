"""
Discord 通知模組
建立嵌入訊息並透過 Webhook 發送
每種策略顯示對應的開單邏輯
"""

import os
import requests
from datetime import datetime, timezone, timedelta

TW_TZ       = timezone(timedelta(hours=8))
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

COLOR_LONG     = 0x00FF88
COLOR_SHORT    = 0xFF4444
COLOR_MARGINAL = 0xFFCC00
MAX_HOLD_HOURS = 48

# 策略中文名稱
STRATEGY_NAMES = {
    "EMA_CONVERGENCE": "EMA 收斂突破",
    "EMA_PULLBACK":    "EMA30 回測反彈",
    "RSI_BOUNCE":      "RSI 極值反彈",
    "MACD_CROSS":      "MACD 柱狀圖交叉",
    "BB_BREAKOUT":     "布林帶收縮突破",
    "EMA_CROSS_FAST":  "EMA9/21 快速交叉",
    "SWING_BREAK":     "擺幅高低點突破",
}


def _pct(value: float, ref: float) -> str:
    if ref == 0:
        return "N/A"
    return f"{(value - ref) / ref * 100:+.2f}%"


def _fp(price: float) -> str:
    if price >= 1000: return f"{price:,.2f}"
    if price >= 1:    return f"{price:.4f}"
    return f"{price:.6f}"


def _now_tw() -> datetime:
    return datetime.now(TW_TZ)


def _conditions_block(result: dict) -> str:
    """將 conditions 清單格式化為 ✅ 條件逐行輸出"""
    conditions = result.get("conditions", [])
    if not conditions:
        return ""
    lines = ["  觸發條件檢查："]
    for c in conditions:
        lines.append(f"  ✅ {c['name']}：{c['value']}")
    return "\n".join(lines)


def _strategy_logic_block(result: dict) -> str:
    """
    依策略類型回傳開單邏輯說明區塊（適合放在 code block 內）
    """
    strategy  = result.get("strategy", "EMA_CONVERGENCE")
    conv      = result["convergence"]
    conf      = result["confirm_1h"]
    vol       = result["vol_ratio"]
    body      = conf.get("body_ratio", 0)
    direction = result["direction"]

    if strategy == "EMA_CONVERGENCE":
        conditions_str = _conditions_block(result)
        base = (
            f"  ▸ 4H 帶寬壓縮 : {conv['bandwidth']:.2f}%  (閾值 {conv.get('bw_threshold', '?')}%  持續 {conv['compression_bars']} 根)\n"
            f"  ▸ 突破量能   : {vol:.2f}× 均量（前20根）\n"
            f"  ▸ EMA200 方向 : {'上方 → 看多' if direction == 'LONG' else '下方 → 看空'}\n"
            f"  ▸ 1H EMA15/30 穿越 : 近 2 根確認\n"
            f"  ▸ 1H 蠟燭實體 : {body*100:.0f}%\n"
        )
        if conditions_str:
            base += f"\n{conditions_str}\n"
        base += "  失效條件 : 價格收回 EMA 群內"
        return base

    if strategy == "EMA_PULLBACK":
        rsi_val = conf.get("rsi")
        rsi_str = f"RSI {rsi_val}" if rsi_val else "RSI N/A"
        conditions_str = _conditions_block(result)
        base = (
            f"  ▸ 大方向 (EMA200)  : {'多頭' if direction == 'LONG' else '空頭'}\n"
            f"  ▸ 4H EMA60 方向   : {'上升' if direction == 'LONG' else '下降'} 一致\n"
            f"  ▸ 1H EMA15 {'>' if direction=='LONG' else '<'} EMA30 : 短期趨勢確認\n"
            f"  ▸ 前根K棒觸碰 EMA30，當根確認反彈\n"
            f"  ▸ 1H {rsi_str}{'≥ 40（動能確認）' if direction=='LONG' else '（空單免檢）'}\n"
            f"  ▸ 量能   : {vol:.2f}× 均量（前20根）\n"
            f"  ▸ 蠟燭實體 : {body*100:.0f}%\n"
        )
        if conditions_str:
            base += f"\n{conditions_str}\n"
        base += "  失效條件 : 收盤跌回 EMA30 下方"
        return base

    if strategy == "RSI_BOUNCE":
        rsi = conf.get("rsi", 0)
        zone = "超賣區 (<35)" if direction == "LONG" else "超買區 (>65)"
        return (
            f"  ▸ 大方向 (EMA200) : {'多頭' if direction == 'LONG' else '空頭'}\n"
            f"  ▸ RSI(14) 觸及 {zone}\n"
            f"  ▸ RSI 當前值 : {rsi:.1f}  (已從極值反轉)\n"
            f"  ▸ 量能   : {vol:.1f}× 均量\n"
            f"  ▸ 蠟燭實體 : {body*100:.0f}%\n"
            f"  失效條件 : RSI 回到極值區"
        )

    if strategy == "MACD_CROSS":
        cross = "負 → 正 (做多)" if direction == "LONG" else "正 → 負 (做空)"
        return (
            f"  ▸ 大方向 (EMA200) : {'多頭' if direction == 'LONG' else '空頭'}\n"
            f"  ▸ MACD 柱狀圖 : {cross}\n"
            f"  ▸ 交叉前確認 : 對側至少 2 根柱\n"
            f"  ▸ 量能   : {vol:.1f}× 均量\n"
            f"  ▸ 蠟燭實體 : {body*100:.0f}%\n"
            f"  失效條件 : 柱狀圖再次反轉"
        )

    if strategy == "BB_BREAKOUT":
        bw = conv.get("bandwidth", 0)
        return (
            f"  ▸ 大方向 (EMA200) : {'多頭' if direction == 'LONG' else '空頭'}\n"
            f"  ▸ 突破前 BB 帶寬 : {bw:.2f}%  (收縮 2 根以上)\n"
            f"  ▸ 收盤突破 {'上軌' if direction == 'LONG' else '下軌'}\n"
            f"  ▸ 量能   : {vol:.1f}× 均量\n"
            f"  ▸ 蠟燭實體 : {body*100:.0f}%\n"
            f"  失效條件 : 收盤回到布林帶內"
        )

    if strategy == "EMA_CROSS_FAST":
        cross = "EMA9 上穿 EMA21 (做多)" if direction == "LONG" else "EMA9 下穿 EMA21 (做空)"
        return (
            f"  ▸ 大方向 (EMA200) : {'多頭' if direction == 'LONG' else '空頭'}\n"
            f"  ▸ 1H {cross}\n"
            f"  ▸ 量能   : {vol:.1f}× 均量\n"
            f"  ▸ 蠟燭實體 : {body*100:.0f}%\n"
            f"  失效條件 : EMA9 再次回穿 EMA21"
        )

    if strategy == "SWING_BREAK":
        level = "8根最高點" if direction == "LONG" else "8根最低點"
        return (
            f"  ▸ 大方向 (EMA200) : {'多頭' if direction == 'LONG' else '空頭'}\n"
            f"  ▸ 收盤突破近 {level}\n"
            f"  ▸ 量能   : {vol:.1f}× 均量  (需 ≥ 1.8×)\n"
            f"  ▸ 蠟燭實體 : {body*100:.0f}%\n"
            f"  失效條件 : 收盤跌回突破點下方"
        )

    return f"  ▸ 策略：{strategy}\n  ▸ 量能：{vol:.1f}× 均量"


def build_setup_embed(result: dict, score: float) -> dict:
    strategy  = result.get("strategy", "EMA_CONVERGENCE")
    strat_name = STRATEGY_NAMES.get(strategy, strategy)
    symbol    = result["symbol"]
    direction = result["direction"]
    levels    = result["levels"]
    entry     = levels["entry"]
    sl        = levels["stop_loss"]
    t1        = levels["target1"]
    t2        = levels["target2"]

    now_tw    = _now_tw()
    expire_tw = now_tw + timedelta(hours=MAX_HOLD_HOURS)
    in_session = 15 <= now_tw.hour < 22

    if score < 7.0:
        color = COLOR_MARGINAL
    elif direction == "LONG":
        color = COLOR_LONG
    else:
        color = COLOR_SHORT

    icon = "🟢" if direction == "LONG" else "🔴"
    rr1  = abs(t1 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
    rr2  = abs(t2 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
    session_str = "✅ EU/US Session" if in_session else "⚪ Off Session"

    logic_block = _strategy_logic_block(result)

    regime_label = result.get("regime_filter", "通過")
    regime_icon  = "✅" if "通過" in regime_label else "⛔"
    atr_val      = levels.get("atr", 0)

    description = (
        f"**📌 策略：{strat_name}**\n"
        f"```\n"
        f"{logic_block}\n"
        f"```\n"
        f"**💰 交易水位**\n"
        f"```\n"
        f"  進場價  : ${_fp(entry)}\n"
        f"  止  損  : ${_fp(sl)}  ({_pct(sl, entry)})  ATR={_fp(atr_val)}\n"
        f"  目標一  : ${_fp(t1)}  (+{rr1:.1f}R / {_pct(t1, entry)})  出場 60%\n"
        f"  目標二  : ${_fp(t2)}  (+{rr2:.1f}R / {_pct(t2, entry)})  出場 40%\n"
        f"  到期時間: {expire_tw.strftime('%m/%d %H:%M TWN')} ({MAX_HOLD_HOURS}h)\n"
        f"```\n"
        f"{regime_icon} Regime Filter：{regime_label}  •  {session_str}\n"
        f"{now_tw.strftime('%Y/%m/%d %H:%M TWN')}"
    )

    return {
        "title":       f"{icon} {direction} — {symbol}   [Score: {score}/10]",
        "description": description,
        "color":       color,
    }


def build_no_setup_embed(total: int, converging: int) -> dict:
    return {
        "title":       "🔍 掃描完成 — 無達標訊號",
        "description": (
            f"掃描幣種：**{total}**  |  觸發中：**{converging}**\n"
            f"下次掃描：60 分鐘後"
        ),
        "color": 0x888888,
    }


def send_embeds(embeds: list[dict]) -> bool:
    if not WEBHOOK_URL:
        print("[Discord] 未設定 DISCORD_WEBHOOK_URL，跳過發送")
        return False
    success = True
    for i in range(0, len(embeds), 10):
        batch   = embeds[i:i + 10]
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
    embeds = [build_setup_embed(r, s) for r, s in results_with_scores]
    if embeds:
        send_embeds(embeds)


def send_no_setup_summary(total: int, converging: int) -> None:
    send_embeds([build_no_setup_embed(total, converging)])


def build_shutdown_embed(
    stats: dict,
    session_trades: list[dict],
    start_time_str: str,
    stop_time_str: str,
    duration_str: str,
) -> dict:
    now_tw   = _now_tw()
    date     = now_tw.strftime("%Y/%m/%d")
    time_str = now_tw.strftime("%H:%M TWN")

    full_session   = [t for t in session_trades if t.get("full_close")]
    wins_session   = [t for t in full_session if t["pnl"] > 0]
    losses_session = [t for t in full_session if t["pnl"] <= 0]
    pnl_session    = round(sum(t["pnl"] for t in session_trades), 2)
    win_rate       = (
        round(len(wins_session) / len(full_session) * 100, 1) if full_session else 0
    )
    sl_count  = sum(1 for t in full_session if t.get("reason") == "SL")
    tp1_count = sum(1 for t in session_trades if t.get("reason") == "TP1")
    tp2_count = sum(1 for t in full_session if t.get("reason") == "TP2")

    emoji = "📈" if pnl_session >= 0 else "📉"

    fields = [
        {"name": "📅 日期",           "value": date,                                                                             "inline": True},
        {"name": "💰 帳戶餘額",       "value": f"${stats['current_balance']:,.2f}",                                              "inline": True},
        {"name": "🟢 開機時間",       "value": start_time_str,                                                                   "inline": True},
        {"name": "🔴 關機時間",       "value": stop_time_str,                                                                    "inline": True},
        {"name": "⏱️ 執行時長",      "value": duration_str,                                                                     "inline": True},
        {"name": "📊 本次損益",       "value": f"${pnl_session:+,.2f}",                                                          "inline": True},
        {"name": "📉 最大回撤",       "value": f"{stats.get('max_drawdown_pct', 0):.2f}%",                                       "inline": True},
        {"name": "🏆 本次勝率",       "value": f"{win_rate:.1f}%  ({len(wins_session)}勝 / {len(losses_session)}敗)",            "inline": True},
        {"name": "📋 已平倉",         "value": str(len(full_session)),                                                           "inline": True},
        {"name": "🎯 出場統計",       "value": f"SL {sl_count}  TP1 {tp1_count}  TP2 {tp2_count}",                              "inline": False},
    ]

    by_strategy: dict[str, dict] = {}
    for t in full_session:
        strat = t.get("strategy") or "未知"
        if strat not in by_strategy:
            by_strategy[strat] = {"trades": 0, "wins": 0, "pnl": 0.0}
        by_strategy[strat]["trades"] += 1
        by_strategy[strat]["pnl"]   += t["pnl"]
        if t["pnl"] > 0:
            by_strategy[strat]["wins"] += 1

    if by_strategy:
        lines = []
        for strat, s in sorted(by_strategy.items(), key=lambda x: -x[1]["pnl"]):
            wr = round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0
            lines.append(f"`{strat}` {s['trades']}筆  ${s['pnl']:+.2f}  勝率{wr}%")
        fields.append({
            "name":   "📂 各策略統計",
            "value":  "\n".join(lines),
            "inline": False,
        })

    return {
        "title":  f"{emoji} EMA Scanner 關閉報告 — {date}",
        "color":  0x00C851 if pnl_session >= 0 else 0xFF4444,
        "fields": fields,
        "footer": {"text": f"EMA Convergence Scanner | 關閉時間 {time_str}"},
    }


def send_shutdown_report(
    stats: dict,
    session_trades: list[dict],
    start_time_str: str,
    stop_time_str: str,
    duration_str: str,
) -> None:
    embed = build_shutdown_embed(stats, session_trades, start_time_str, stop_time_str, duration_str)
    send_embeds([embed])
