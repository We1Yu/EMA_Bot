"""
Crypto Coin Screener v2 — Entry point.

Usage:
  python main.py --mode swing
  python main.py --mode intraday --discord
  python main.py --mode swing --verbose
"""

import argparse
import asyncio
import csv
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import aiohttp

from scanner       import run_scan, fetch_klines, BINANCE_BASE
from discord_alert import send_discord_embeds, send_daily_report
from paper_account import PaperAccount
from live_trader   import LiveTrader
from config        import INTRADAY_POLL_SECS, COOLDOWN_SECS

load_dotenv()

OUTPUT_DIR = Path(__file__).parent / "output"
TW_TZ      = timezone(timedelta(hours=8))

COLUMNS = [
    "Rank", "Symbol", "Tier", "Score", "MA_Spread%", "Vol_Ratio",
    "Body%", "RSI", "BBW_Ratio", "ADX", "Funding", "RR",
    "Stop", "Target1", "Target_Fib", "Weekly", "4H_Status", "Alert",
]


# ── Formatting ────────────────────────────────────────────────

def _sig(v: float, n: int = 4) -> str:
    """Format to n significant figures."""
    if v == 0:
        return "0"
    from math import log10, floor
    d = n - 1 - int(floor(log10(abs(v))))
    return f"{v:.{max(0, d)}f}"


def _row(rank: int, s: dict) -> dict:
    return {
        "Rank":       rank,
        "Symbol":     s["symbol"],
        "Tier":       s["tier"],
        "Score":      s["score"],
        "MA_Spread%": f"{s['ma_spread_pct']:.3f}",
        "Vol_Ratio":  f"{s['vol_ratio']:.2f}",
        "Body%":      f"{s['body_pct']:.1f}",
        "RSI":        f"{s['rsi']:.1f}",
        "BBW_Ratio":  f"{s['bbw_ratio']:.3f}",
        "ADX":        f"{s['adx']:.1f}",
        "Funding":    f"{s['funding']:.4f}%",
        "RR":         f"{s['risk_reward']:.2f}",
        "Stop":       _sig(s["stop_loss"]),
        "Target1":    _sig(s["target_1"]),
        "Target_Fib": _sig(s["primary_target"]),
        "Weekly":     s["weekly"],
        "4H_Status":  s.get("dual_tf_status", ""),
        "Alert":      s["alert"],
    }


def print_table(signals: list[dict]) -> None:
    if not signals:
        print("  (no signals)")
        return
    header = f"{'Rank':>4}  {'Symbol':<14} {'Tier':>4} {'Score':>5}  "
    header += f"{'Spread%':>8} {'VolR':>5} {'Body%':>6} {'RSI':>5} {'ADX':>5}  "
    header += f"{'Stop':>12} {'T1':>12} {'TFib':>12}  {'Alert'}"
    print(header)
    print("-" * len(header))
    for i, s in enumerate(signals, 1):
        print(
            f"  {i:>2}  {s['symbol']:<14} {s['tier']:>4} {s['score']:>5}  "
            f"{s['ma_spread_pct']:>8.3f} {s['vol_ratio']:>5.2f} {s['body_pct']:>6.1f} "
            f"{s['rsi']:>5.1f} {s['adx']:>5.1f}  "
            f"{_sig(s['stop_loss']):>12} {_sig(s['target_1']):>12} {_sig(s['primary_target']):>12}  "
            f"{s['alert']}"
        )


def save_csv(signals: list[dict], mode: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    path = OUTPUT_DIR / f"scan_{ts}_{mode}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for i, s in enumerate(signals, 1):
            w.writerow(_row(i, s))
    return path


# ── Fetch latest bar high/low for open positions ─────────────

async def fetch_latest_bars(
    symbols: list[str], interval: str, exchange: str = "binance"
) -> dict[str, tuple[float, float]]:
    """
    Fetch the most recent completed candle high/low for each symbol.
    Returns {symbol: (high, low)}.
    """
    if exchange == "bingx":
        import bingx_source as src
    else:
        import binance_source as src

    result: dict[str, tuple[float, float]] = {}
    async with aiohttp.ClientSession() as session:
        tasks   = {sym: src.fetch_klines(session, sym, interval, 2) for sym in symbols}
        raw_res = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for sym, raw in zip(tasks.keys(), raw_res):
            if isinstance(raw, Exception) or not raw or len(raw) < 1:
                continue
            candle = raw[-1]
            try:
                if isinstance(candle, (list, tuple)):
                    result[sym] = (float(candle[2]), float(candle[3]))   # Binance
                else:
                    result[sym] = (float(candle["high"]), float(candle["low"]))  # BingX
            except Exception:
                pass
    return result


# ── Filter counts ─────────────────────────────────────────────

def _count_tiers(signals: list[dict]) -> tuple[int, int]:
    a = sum(1 for s in signals if s["tier"] == "A")
    b = sum(1 for s in signals if s["tier"] == "B")
    return a, b


# ── Single scan run ───────────────────────────────────────────

async def do_scan(
    mode: str,
    discord: bool,
    webhook_url: str,
    account: PaperAccount,
    cooldown: dict,
    live: Optional[LiveTrader] = None,
    exchange: str = "binance",
) -> None:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n=== SCAN START | Mode: {mode} | {now_utc} ===")

    signals, total = await run_scan(mode, exchange)

    n_a, n_b = _count_tiers(signals)
    print(
        f"Scanned: {total} | Passed filters: {len(signals)} | "
        f"Signals: {len(signals)} (A:{n_a} B:{n_b})"
    )

    if not signals:
        print("No signals this scan.")
    else:
        print_table(signals)
        path = save_csv(signals, mode)
        print(f"CSV: {path}")

    # ── Virtual account: update existing positions ────────────
    # Fetch real latest candle high/low for every open position
    interval = "4h" if mode == "swing" else "1h"
    open_syms = list(account.positions.keys())
    exit_events: list[dict] = []
    if open_syms:
        latest_bars = await fetch_latest_bars(open_syms, interval, exchange)
        for sym in open_syms:
            if sym in latest_bars:
                high, low = latest_bars[sym]
                evs = account.update_price(sym, high, low)
                exit_events.extend(evs)
            else:
                print(f"  [PAPER] could not fetch latest bar for {sym}")

    for ev in exit_events:
        print(f"  [PAPER EXIT] {ev['symbol']:20s}  {ev['reason']}  PnL: ${ev['pnl']:>+.2f}")

    # ── Open new positions ────────────────────────────────────
    now_ts = time.time()
    async with aiohttp.ClientSession() as live_session:
        for sig in signals:
            sym = sig["symbol"]
            last = cooldown.get(sym, 0)
            if now_ts - last < COOLDOWN_SECS:
                continue

            if live:
                # ── LIVE MODE ─────────────────────────────
                already_in = await live.has_position(live_session, sym)
                if already_in:
                    continue
                ok = await live.open_trade(live_session, sig)
                if ok:
                    cooldown[sym] = now_ts
                    print(
                        f"  [LIVE OPEN]  {sym:20s}  Tier {sig['tier']}  "
                        f"Score {sig['score']}  entry={sig['entry']:.6g}  "
                        f"SL={sig['stop_loss']:.6g}  "
                        f"TP1={sig['target_1']:.6g}  TP2={sig['target_2']:.6g}  TP3={sig['target_3']:.6g}"
                    )
                    # also track in paper account for local P&L record
                    account.open_position(sig)
            else:
                # ── PAPER MODE ────────────────────────────
                if account.open_position(sig):
                    cooldown[sym] = now_ts
                    print(
                        f"  [PAPER OPEN] {sym:20s}  Tier {sig['tier']}  "
                        f"Score {sig['score']}  entry={sig['entry']:.6g}  "
                        f"SL={sig['stop_loss']:.6g}"
                    )

    account.save()
    account.print_report()

    # ── Discord alerts ────────────────────────────────────────
    if discord and webhook_url and signals:
        await send_discord_embeds(signals, webhook_url)
        print(f"Discord: sent {len(signals)} alerts")

    print(f"=== SCAN COMPLETE | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ===")


# ── Main entry ────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto Coin Screener v2")
    parser.add_argument("--mode",     choices=["swing", "intraday"], default="swing")
    parser.add_argument("--discord",  action="store_true")
    parser.add_argument("--verbose",  action="store_true")
    parser.add_argument("--live",     action="store_true",
                        help="Execute real orders on Binance Futures (requires API keys in .env)")
    parser.add_argument("--risk",     type=float, default=None,
                        help="Risk per trade as decimal, e.g. 0.01 = 1%% (overrides config)")
    parser.add_argument("--exchange", choices=["binance", "bingx"], default="binance",
                        help="Exchange to scan (default: binance)")
    args = parser.parse_args()

    logging.basicConfig(
        level   = logging.DEBUG if args.verbose else logging.INFO,
        format  = "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt = "%H:%M:%S",
    )
    for lib in ("aiohttp", "asyncio"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    account     = PaperAccount.load()
    cooldown: dict[str, float] = {}

    # ── Live trader setup ─────────────────────────────────────
    live: Optional[LiveTrader] = None
    if args.live:
        api_key    = os.environ.get("BINANCE_API_KEY", "")
        api_secret = os.environ.get("BINANCE_API_SECRET", "")
        if not api_key or not api_secret:
            print("ERROR: --live requires BINANCE_API_KEY and BINANCE_API_SECRET in .env")
            return
        from config import PAPER_RISK_PCT
        risk = args.risk if args.risk is not None else PAPER_RISK_PCT
        live = LiveTrader(api_key, api_secret, risk_pct=risk)

    print("=" * 55)
    print(f"  Crypto Screener v2  |  Mode: {args.mode}  |  Exchange: {args.exchange.upper()}")
    if live:
        print(f"  ** LIVE TRADING ** risk={live.risk_pct*100:.1f}% per trade")
    else:
        print(f"  Paper account balance: ${account.balance:,.2f}")
    if args.mode == "intraday":
        print(f"  Poll interval: {INTRADAY_POLL_SECS // 60} min")
    print("=" * 55)

    async def _run_once():
        await do_scan(args.mode, args.discord, webhook_url, account, cooldown, live, args.exchange)

    async def _run_loop():
        last_report_date = datetime.now(TW_TZ).date()

        await do_scan(args.mode, args.discord, webhook_url, account, cooldown, live, args.exchange)
        print(f"\nNext scan in {INTRADAY_POLL_SECS // 60} min. Ctrl+C to stop.")

        while True:
            try:
                await asyncio.sleep(INTRADAY_POLL_SECS)

                # ── 午夜 00:00 TWN 每日報告 ──────────────────
                now_tw      = datetime.now(TW_TZ)
                today_date  = now_tw.date()
                if today_date > last_report_date:
                    last_report_date = today_date
                    print(f"\n[日報] {today_date} 00:00 TWN — 發送每日報告")

                    # 取出今日（昨日）的交易紀錄
                    yesterday = today_date - timedelta(days=1)
                    history_today = [
                        t for t in account.history
                        if datetime.fromtimestamp(
                            t.get("close_time", 0), tz=TW_TZ
                        ).date() == yesterday
                    ]

                    if webhook_url:
                        await send_daily_report(
                            account.get_stats(),
                            history_today,
                            args.exchange,
                            webhook_url,
                        )
                    else:
                        # 沒有 Discord 就印到 terminal
                        account.print_report()

                await do_scan(args.mode, args.discord, webhook_url, account, cooldown, live, args.exchange)

            except KeyboardInterrupt:
                break

    try:
        if args.mode == "swing":
            asyncio.run(_run_once())
        else:
            asyncio.run(_run_loop())
    except KeyboardInterrupt:
        print("\nStopped by user.")
        account.print_report()


if __name__ == "__main__":
    main()
