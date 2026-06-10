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


def build_daily_report_embed(stats: dict, history_today: list[dict], exchange: str) -> dict:
    """Build a daily summary embed from paper account stats."""
    now    = datetime.now(TW_TZ)
    date   = now.strftime("%Y/%m/%d")

    # Today's closed trades
    wins   = [t for t in history_today if t.get("full_close") and t["pnl"] > 0]
    losses = [t for t in history_today if t.get("full_close") and t["pnl"] <= 0]
    pnl_today = sum(t["pnl"] for t in history_today)

    win_rate = (
        round(len(wins) / (len(wins) + len(losses)) * 100, 1)
        if (wins or losses) else 0
    )

    # Equity curve emoji
    emoji = "📈" if stats["total_pnl"] >= 0 else "📉"
    pf    = stats.get("profit_factor")

    fields = [
        {"name": "📅 Date",             "value": date,                                         "inline": True},
        {"name": "🏦 Exchange",         "value": exchange.upper(),                             "inline": True},
        {"name": "💰 Balance",          "value": f"${stats['current_balance']:,.2f}",          "inline": True},
        {"name": "📊 Total Return",     "value": f"{stats['return_pct']:+.2f}%  (${stats['total_pnl']:+,.2f})", "inline": True},
        {"name": "📉 Max Drawdown",     "value": f"{stats['max_drawdown_pct']:.2f}%",          "inline": True},
        {"name": "⚖️ Profit Factor",   "value": f"{pf:.2f}" if pf else "N/A",                 "inline": True},
        {"name": "🏆 All-time Win Rate","value": f"{stats['win_rate']:.1f}%  ({stats['wins']}W / {stats['losses']}L)", "inline": True},
        {"name": "📋 Full Closes",      "value": str(stats["full_closes"]),                    "inline": True},
        {"name": "🔓 Open Positions",   "value": str(stats["open_positions"]),                 "inline": True},
        {"name": "📆 Today's PnL",      "value": f"${pnl_today:+,.2f}  (W:{len(wins)} L:{len(losses)} WR:{win_rate}%)", "inline": False},
    ]

    if history_today:
        recent = history_today[-5:][::-1]
        lines  = []
        for t in recent:
            icon = "✅" if t["pnl"] > 0 else "❌"
            lines.append(f"{icon} {t['symbol']}  {t['reason']}  ${t['pnl']:+.2f}")
        fields.append({
            "name":   "🕐 Recent Trades (last 5 today)",
            "value":  "\n".join(lines) or "—",
            "inline": False,
        })

    return {
        "title":  f"{emoji} Daily Virtual Account Report — {date}",
        "color":  0x00C851 if stats["total_pnl"] >= 0 else 0xFF4444,
        "fields": fields,
        "footer": {"text": f"Crypto Screener v2 | Virtual Paper Account | 00:00 TWN"},
    }


async def send_daily_report(
    stats: dict, history_today: list[dict], exchange: str, webhook_url: str
) -> None:
    """Send the daily report embed to Discord."""
    if not webhook_url:
        log.warning("DISCORD_WEBHOOK_URL not set — skipping daily report")
        return
    embed = build_daily_report_embed(stats, history_today, exchange)
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
