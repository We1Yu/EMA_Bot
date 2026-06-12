"""Discord webhook alerts — one embed per Tier A/B signal, batched 10 per call."""

import os
import logging
import aiohttp
from datetime import datetime, timezone, timedelta

log     = logging.getLogger(__name__)
TW_TZ   = timezone(timedelta(hours=8))

COLOR_A = 0x00C851
COLOR_B = 0xFF8800


def _fp(price: float) -> str:
    if price >= 1000: return f"{price:,.2f}"
    if price >= 1:    return f"{price:.4f}"
    return f"{price:.6f}"


def _pct(value: float, ref: float) -> str:
    if ref == 0:
        return "N/A"
    return f"{(value - ref) / ref * 100:+.2f}%"


def build_embed(signal: dict) -> dict:
    """Build one Discord embed dict from a signal."""
    sym   = signal["symbol"]
    tier  = signal["tier"]
    score = signal["score"]
    entry = signal["entry"]
    sl    = signal["stop_loss"]
    t1    = signal["target_1"]
    t_fib = signal["primary_target"]
    now   = datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M TWN")

    color = COLOR_A if tier == "A" else COLOR_B

    fields = [
        {"name": "Symbol",       "value": sym,                              "inline": True},
        {"name": "Tier",         "value": tier,                             "inline": True},
        {"name": "Score",        "value": str(score),                       "inline": True},
        {"name": "MA Spread%",   "value": f"{signal['ma_spread_pct']:.3f}%","inline": True},
        {"name": "Vol Ratio",    "value": f"{signal['vol_ratio']:.2f}×",    "inline": True},
        {"name": "Body%",        "value": f"{signal['body_pct']:.1f}%",     "inline": True},
        {"name": "RSI",          "value": f"{signal['rsi']:.1f}",           "inline": True},
        {"name": "ADX",          "value": f"{signal['adx']:.1f}",           "inline": True},
        {"name": "BBW Ratio",    "value": f"{signal['bbw_ratio']:.3f}",     "inline": True},
        {"name": "Funding",      "value": f"{signal['funding']:.4f}%",      "inline": True},
        {"name": "R:R",          "value": f"{signal['risk_reward']:.2f}",   "inline": True},
        {"name": "Weekly",       "value": signal["weekly"],                 "inline": True},
        {"name": "Stop Loss",    "value": f"${_fp(sl)} ({_pct(sl, entry)})", "inline": True},
        {"name": "Target 1",     "value": f"${_fp(t1)} ({_pct(t1, entry)})", "inline": True},
        {"name": "Target Fib",   "value": f"${_fp(t_fib)} ({_pct(t_fib, entry)})", "inline": True},
        {"name": "4H Status",    "value": signal.get("dual_tf_status") or "—", "inline": True},
        {"name": "Alert",        "value": signal["alert"],                  "inline": False},
    ]

    return {
        "title":  f"MA Cluster Breakout — {sym} | Score: {score}",
        "color":  color,
        "fields": fields,
        "footer": {"text": f"Binance Futures Scanner v2 | {now}"},
    }


def build_daily_report_embed(
    stats: dict, history_today: list[dict], exchange: str,
    start_time_str: str = "-", stop_time_str: str = "-", duration_str: str = "-",
) -> dict:
    """Build a daily summary embed from paper account stats."""
    now  = datetime.now(TW_TZ)
    date = now.strftime("%Y/%m/%d")
    time_str = now.strftime("%H:%M TWN")

    # Today's closed trades — use tp1_hit for win/loss (matches paper_account logic)
    full_today = [t for t in history_today if t.get("full_close")]
    wins_today   = [t for t in full_today if t.get("tp1_hit", t["pnl"] > 0)]
    losses_today = [t for t in full_today if not t.get("tp1_hit", t["pnl"] > 0)]
    pnl_today  = sum(t["pnl"] for t in history_today)
    win_rate_today = (
        round(len(wins_today) / (len(wins_today) + len(losses_today)) * 100, 1)
        if (wins_today or losses_today) else 0
    )

    emoji = "📈" if stats["total_pnl"] >= 0 else "📉"
    pf    = stats.get("profit_factor")

    # Exit type counts
    sl_count  = stats.get("sl_count", 0)
    tp1_count = stats.get("tp1_count", 0)
    tp2_count = stats.get("tp2_count", 0)
    tp3_count = stats.get("tp3_count", 0)

    fields = [
        {"name": "📅 日期",           "value": date,                                                           "inline": True},
        {"name": "💰 帳戶餘額",       "value": f"${stats['current_balance']:,.2f}",                            "inline": True},
        {"name": "🟢 開機時間",       "value": start_time_str,                                                 "inline": True},
        {"name": "🔴 關機時間",       "value": stop_time_str,                                                  "inline": True},
        {"name": "⏱️ 執行時長",      "value": duration_str,                                                   "inline": True},
        {"name": "📊 總報酬",         "value": f"{stats['return_pct']:+.2f}%  (${stats['total_pnl']:+,.2f})",  "inline": True},
        {"name": "📉 最大回撤",       "value": f"{stats['max_drawdown_pct']:.2f}%",                            "inline": True},
        {"name": "🏆 累計勝率",       "value": f"{stats['win_rate']:.1f}%  ({stats['wins']}勝 / {stats['losses']}敗)", "inline": True},
        {"name": "📋 已平倉",         "value": str(stats["full_closes"]),                                      "inline": True},
        {"name": "🎯 出場統計 (累計)", "value": f"SL {sl_count}  TP1 {tp1_count}  TP2 {tp2_count}  TP3 {tp3_count}", "inline": False},
        {"name": "📆 今日損益",       "value": f"${pnl_today:+,.2f}  (勝{len(wins_today)} 敗{len(losses_today)} 勝率{win_rate_today}%)", "inline": False},
    ]

    # Per-strategy breakdown
    by_strategy = stats.get("by_strategy", {})
    if by_strategy:
        lines = []
        for strat, s in by_strategy.items():
            wr = round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0
            lines.append(f"`{strat}` {s['trades']}筆  ${s['pnl']:+.2f}  勝率{wr}%")
        fields.append({
            "name":   "📂 各策略統計",
            "value":  "\n".join(lines) or "—",
            "inline": False,
        })


    return {
        "title":  f"{emoji} 自動交易 關閉報告 — {date}",
        "color":  0x00C851 if stats["total_pnl"] >= 0 else 0xFF4444,
        "fields": fields,
        "footer": {"text": f"自動交易機器人 | 關閉時間 {time_str}"},
    }


async def send_daily_report(
    stats: dict, history_today: list[dict], exchange: str, webhook_url: str,
    start_time_str: str = "-", stop_time_str: str = "-", duration_str: str = "-",
) -> None:
    """Send the daily report embed to Discord."""
    if not webhook_url:
        log.warning("DISCORD_WEBHOOK_URL not set — skipping daily report")
        return
    embed = build_daily_report_embed(
        stats, history_today, exchange,
        start_time_str=start_time_str,
        stop_time_str=stop_time_str,
        duration_str=duration_str,
    )
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                webhook_url,
                json={"embeds": [embed]},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status not in (200, 204):
                    text = await resp.text()
                    log.warning("Daily report Discord HTTP %d: %s", resp.status, text[:200])
                else:
                    log.info("Daily report sent to Discord")
        except Exception as e:
            log.warning("Daily report send error: %s", e)


async def send_start_notification(
    initial_balance: float, webhook_url: str
) -> None:
    """Send a bot-started embed to Discord."""
    if not webhook_url:
        return
    now = datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M:%S TWN")
    embed = {
        "title":  "🟢 自動交易 已啟動",
        "color":  0x00C851,
        "fields": [
            {"name": "啟動時間", "value": now,                              "inline": True},
            {"name": "初始資金", "value": f"${initial_balance:,.0f}",       "inline": True},
        ],
        "footer": {"text": "自動交易機器人"},
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                webhook_url,
                json={"embeds": [embed]},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status not in (200, 204):
                    log.warning("Start notification Discord %d", resp.status)
        except Exception as e:
            log.warning("Start notification send error: %s", e)


async def send_stop_notification(
    stop_time_str: str, start_time_str: str, duration_str: str,
    stats: dict, webhook_url: str
) -> None:
    """Send a bot-stopped embed to Discord."""
    if not webhook_url:
        return
    pnl   = stats.get("total_pnl", 0)
    color = 0xFF4444 if pnl < 0 else 0x00C851
    embed = {
        "title":  "🔴 自動交易 已關閉",
        "color":  color,
        "fields": [
            {"name": "關閉時間",   "value": stop_time_str,                  "inline": True},
            {"name": "啟動時間",   "value": start_time_str,                 "inline": True},
            {"name": "執行時長",   "value": duration_str,                   "inline": True},
            {"name": "本次損益",   "value": f"${pnl:+,.2f}",               "inline": True},
            {"name": "餘額",       "value": f"${stats.get('current_balance',0):,.2f}", "inline": True},
            {"name": "勝率",       "value": f"{stats.get('win_rate',0):.1f}%",         "inline": True},
        ],
        "footer": {"text": "自動交易機器人"},
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                webhook_url,
                json={"embeds": [embed]},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status not in (200, 204):
                    log.warning("Stop notification Discord %d", resp.status)
        except Exception as e:
            log.warning("Stop notification send error: %s", e)


async def send_discord_embeds(signals: list[dict], webhook_url: str) -> None:
    """Send signal embeds to Discord, 10 per call."""
    if not webhook_url:
        log.warning("DISCORD_WEBHOOK_URL not set — skipping alerts")
        return

    embeds = [build_embed(s) for s in signals]

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(embeds), 10):
            batch = embeds[i: i + 10]
            try:
                async with session.post(
                    webhook_url,
                    json={"embeds": batch},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status not in (200, 204):
                        text = await resp.text()
                        log.warning("Discord HTTP %d: %s", resp.status, text[:200])
            except Exception as e:
                log.warning("Discord send error: %s", e)
