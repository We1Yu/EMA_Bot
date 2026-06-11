"""
Performance Analysis Script — reads trades_scalp.jsonl and reports stats.

Usage:
  python analyze_performance.py            # print to console only
  python analyze_performance.py --discord  # also send to Discord
"""

import json
import sys
import asyncio
import aiohttp
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from config import SCALP_DISCORD_WEBHOOK

TW_TZ      = timezone(timedelta(hours=8))
TRADES_FILE = Path(__file__).parent / "trades_scalp.jsonl"

log = logging.getLogger(__name__)


# ── Data loading ──────────────────────────────────────────────

def load_trades(days: int = 7) -> list[dict]:
    """Load trades from the last N days."""
    if not TRADES_FILE.exists():
        return []
    cutoff = datetime.now(TW_TZ) - timedelta(days=days)
    trades = []
    for line in TRADES_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        try:
            ts = datetime.strptime(t["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TW_TZ)
            if ts >= cutoff:
                trades.append(t)
        except Exception:
            trades.append(t)
    return trades


# ── Core stats ────────────────────────────────────────────────

def compute_stats(trades: list[dict]) -> dict:
    """Compute full performance breakdown from JSONL trade records."""
    if not trades:
        return {}

    full = [t for t in trades if "total_trade_pnl" in t]
    wins   = [t for t in full if t["total_trade_pnl"] > 0]
    losses = [t for t in full if t["total_trade_pnl"] <= 0]
    total  = len(wins) + len(losses)

    by_reason = defaultdict(int)
    for t in trades:
        by_reason[t.get("reason", "?")] += 1

    # ── By strategy ───────────────────────────────────────────
    by_strategy: dict[str, dict] = {}
    for t in full:
        s = t.get("strategy", "UNKNOWN")
        if s not in by_strategy:
            by_strategy[s] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
        by_strategy[s]["trades"] += 1
        by_strategy[s]["pnl"]    = round(by_strategy[s]["pnl"] + t["total_trade_pnl"], 4)
        if t["total_trade_pnl"] > 0:
            by_strategy[s]["wins"]   += 1
        else:
            by_strategy[s]["losses"] += 1

    # ── By score bucket ───────────────────────────────────────
    by_score: dict[str, dict] = {}
    for t in full:
        sc = t.get("score", 0)
        bkt = f"{(sc // 5) * 5}-{(sc // 5) * 5 + 4}"
        if bkt not in by_score:
            by_score[bkt] = {"trades": 0, "wins": 0, "pnl": 0.0}
        by_score[bkt]["trades"] += 1
        by_score[bkt]["pnl"]    = round(by_score[bkt]["pnl"] + t["total_trade_pnl"], 4)
        if t["total_trade_pnl"] > 0:
            by_score[bkt]["wins"] += 1

    # ── By hour ───────────────────────────────────────────────
    by_hour: dict[int, dict] = {}
    for t in trades:
        try:
            h = datetime.strptime(t["time"], "%Y-%m-%d %H:%M:%S").hour
        except Exception:
            continue
        if h not in by_hour:
            by_hour[h] = {"events": 0, "pnl": 0.0}
        by_hour[h]["events"] += 1
        by_hour[h]["pnl"] = round(by_hour[h]["pnl"] + t["pnl"], 4)

    # ── By symbol ─────────────────────────────────────────────
    sym_pnl: dict[str, float] = {}
    sym_trades: dict[str, int] = {}
    for t in full:
        s = t["symbol"]
        sym_pnl[s]    = round(sym_pnl.get(s, 0) + t["total_trade_pnl"], 4)
        sym_trades[s] = sym_trades.get(s, 0) + 1

    worst_syms = sorted(sym_pnl.items(), key=lambda x: x[1])[:5]
    best_syms  = sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)[:5]

    # ── Drawdown ──────────────────────────────────────────────
    balances = [t["balance"] for t in trades]
    peak = balances[0] if balances else 0
    max_dd = 0.0
    for b in balances:
        if b > peak:
            peak = b
        dd = (peak - b) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    win_pnl  = sum(t["total_trade_pnl"] for t in wins)
    loss_pnl = sum(t["total_trade_pnl"] for t in losses)

    return {
        "total_events":  len(trades),
        "full_trades":   total,
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / total * 100, 1) if total else 0,
        "total_pnl":     round(sum(t["pnl"] for t in trades), 2),
        "avg_win":       round(win_pnl / len(wins), 2) if wins else 0,
        "avg_loss":      round(loss_pnl / len(losses), 2) if losses else 0,
        "profit_factor": round(abs(win_pnl / loss_pnl), 2) if loss_pnl else None,
        "max_drawdown":  round(max_dd, 2),
        "by_reason":     dict(by_reason),
        "by_strategy":   by_strategy,
        "by_score":      dict(sorted(by_score.items())),
        "by_hour":       {h: by_hour[h] for h in sorted(by_hour)},
        "worst_syms":    worst_syms,
        "best_syms":     best_syms,
        "balance_start": balances[0] if balances else 0,
        "balance_end":   balances[-1] if balances else 0,
    }


# ── Console report ────────────────────────────────────────────

def print_report(s: dict, days: int) -> None:
    now = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M TWN")
    print(f"\n{'='*60}")
    print(f"  Scalp Bot Performance Report  (last {days} days)  {now}")
    print(f"{'='*60}")
    print(f"  Completed trades: {s['full_trades']}  ({s['total_events']} total events)")
    print(f"  Win Rate:         {s['win_rate']:.1f}%  ({s['wins']}W / {s['losses']}L)")
    print(f"  Total PnL:        ${s['total_pnl']:+,.2f}")
    print(f"  Avg Win:          ${s['avg_win']:+.2f}")
    print(f"  Avg Loss:         ${s['avg_loss']:+.2f}")
    pf = s.get("profit_factor")
    print(f"  Profit Factor:    {f'{pf:.2f}' if pf else 'N/A'}")
    print(f"  Max Drawdown:     {s['max_drawdown']:.2f}%")
    print(f"  Exit breakdown:   {s['by_reason']}")

    print(f"\n  -- Strategy Breakdown --")
    for st, d in s["by_strategy"].items():
        wr = round(d["wins"] / d["trades"] * 100, 1) if d["trades"] else 0
        print(f"  {st:18s}  {d['trades']:3d} trades  WR {wr:5.1f}%  PnL ${d['pnl']:+.2f}")

    if s["by_score"]:
        print(f"\n  -- Score vs Win Rate --")
        for bkt, d in s["by_score"].items():
            if d["trades"] == 0:
                continue
            wr = round(d["wins"] / d["trades"] * 100, 1)
            bar = "#" * int(wr / 5)
            print(f"  Score {bkt:7s}  {d['trades']:3d} trades  WR {wr:5.1f}% {bar}  PnL ${d['pnl']:+.2f}")

    print(f"\n  -- PnL by Hour (TWN) --")
    for h, d in s["by_hour"].items():
        sign = "+" if d["pnl"] > 0 else ""
        bar  = "#" * min(int(abs(d["pnl"]) / 50), 20)
        side = ">" if d["pnl"] > 0 else "<"
        print(f"  {h:02d}:00  {side}{bar}  ${sign}{d['pnl']:.2f}  ({d['events']} events)")

    print(f"\n  -- Best Symbols --")
    for sym, p in s["best_syms"]:
        print(f"  {sym:20s} ${p:+.2f}")
    print(f"\n  -- Worst Symbols --")
    for sym, p in s["worst_syms"]:
        print(f"  {sym:20s} ${p:+.2f}")
    print(f"{'='*60}\n")


# ── Discord embed builder ─────────────────────────────────────

def build_performance_embed(s: dict, days: int) -> dict:
    now  = datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M TWN")
    pf   = s.get("profit_factor")
    pnl  = s["total_pnl"]
    wr   = s["win_rate"]
    color = 0x00C851 if pnl >= 0 else 0xFF4444

    # Win rate health indicator
    if wr >= 50:
        wr_icon = "🟢"
    elif wr >= 40:
        wr_icon = "🟡"
    else:
        wr_icon = "🔴"

    # Strategy breakdown text
    strat_lines = []
    for st, d in s["by_strategy"].items():
        strat_wr = round(d["wins"] / d["trades"] * 100, 1) if d["trades"] else 0
        strat_lines.append(f"`{st}` {d['trades']}筆  WR {strat_wr:.0f}%  ${d['pnl']:+.2f}")

    # Score vs win rate
    score_lines = []
    for bkt, d in s["by_score"].items():
        if d["trades"] < 2:
            continue
        bkt_wr = round(d["wins"] / d["trades"] * 100, 0)
        score_lines.append(f"分數 {bkt}: {d['trades']}筆  WR {bkt_wr:.0f}%  ${d['pnl']:+.2f}")

    # Top hours
    hour_lines = sorted(s["by_hour"].items(), key=lambda x: x[1]["pnl"], reverse=True)[:4]
    hour_text  = "  ".join(f"{h:02d}:xx ${d['pnl']:+.0f}" for h, d in hour_lines)

    # Symbols
    best_text  = "\n".join(f"{sym}  ${p:+.2f}" for sym, p in s["best_syms"][:3])
    worst_text = "\n".join(f"{sym}  ${p:+.2f}" for sym, p in s["worst_syms"][:3])

    # Warnings
    warnings = []
    if wr < 40:
        warnings.append(f"⚠️ 勝率偏低 {wr:.1f}%（建議檢查分數門檻）")
    if s["max_drawdown"] > 20:
        warnings.append(f"⚠️ 回撤過大 {s['max_drawdown']:.1f}%")
    if pf and pf < 0.8:
        warnings.append(f"⚠️ 盈虧因子 {pf:.2f} < 0.8")

    fields = [
        {"name": f"🏆 勝率 {wr_icon}",
         "value": f"{wr:.1f}%  ({s['wins']}勝 / {s['losses']}敗)",
         "inline": True},
        {"name": "💰 總損益",
         "value": f"${pnl:+,.2f}",
         "inline": True},
        {"name": "⚖️ 盈虧因子",
         "value": f"{pf:.2f}" if pf else "N/A",
         "inline": True},
        {"name": "📊 平均獲利 / 虧損",
         "value": f"+${s['avg_win']:.2f}  /  ${s['avg_loss']:.2f}",
         "inline": True},
        {"name": "📉 最大回撤",
         "value": f"{s['max_drawdown']:.2f}%",
         "inline": True},
        {"name": "📋 完整交易數",
         "value": str(s["full_trades"]),
         "inline": True},
        {"name": "🎯 出場分佈",
         "value": "  ".join(f"{k} {v}" for k, v in s["by_reason"].items()),
         "inline": False},
    ]

    if strat_lines:
        fields.append({
            "name":   "📂 各策略績效",
            "value":  "\n".join(strat_lines) or "—",
            "inline": False,
        })

    if score_lines:
        fields.append({
            "name":   "🎰 分數 vs 勝率",
            "value":  "\n".join(score_lines) or "—",
            "inline": False,
        })

    if hour_text:
        fields.append({
            "name":   "🕐 最佳時段 TOP4 (TWN)",
            "value":  hour_text,
            "inline": False,
        })

    if best_text:
        fields.append({"name": "🥇 最佳幣種", "value": best_text, "inline": True})
    if worst_text:
        fields.append({"name": "💀 最差幣種", "value": worst_text, "inline": True})

    if warnings:
        fields.append({
            "name":   "🚨 警告",
            "value":  "\n".join(warnings),
            "inline": False,
        })

    return {
        "title":       f"📊 定期績效分析報告 (最近 {days} 天)",
        "color":       color,
        "fields":      fields,
        "footer":      {"text": f"BingX 高頻 Scalp Bot | {now}"},
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }


async def send_performance_report(
    s: dict, days: int, webhook_url: str
) -> None:
    if not webhook_url:
        return
    embed = build_performance_embed(s, days)
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                webhook_url,
                json={"embeds": [embed]},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status not in (200, 204):
                    text = await resp.text()
                    log.warning("Performance report Discord %d: %s", resp.status, text[:200])
                else:
                    log.info("Performance report sent to Discord")
        except Exception as e:
            log.warning("Performance report send error: %s", e)


# ── CLI entry point ───────────────────────────────────────────

async def _main_async(send_discord: bool) -> None:
    trades = load_trades(days=7)
    if not trades:
        print("No trade data found in trades_scalp.jsonl")
        return
    s = compute_stats(trades)
    print_report(s, days=7)
    if send_discord:
        await send_performance_report(s, days=7, webhook_url=SCALP_DISCORD_WEBHOOK)
        print("Discord 報告已發送")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    send_discord = "--discord" in sys.argv
    asyncio.run(_main_async(send_discord))
