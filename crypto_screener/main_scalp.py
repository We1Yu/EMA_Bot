"""
High-Frequency Virtual Trading Bot — BingX USDT-M Perpetuals
=============================================================

Two independent loops:
  - Position loop (every SCALP_CHECK_INTERVAL_SECS, default 12s):
    fetches the current price for every open paper position and checks
    stop-loss / take-profit immediately, so exits trigger fast.
  - Scan loop (every SCALP_SCAN_INTERVAL_SECS, default 60s):
    re-runs the full crypto_screener scoring pipeline on SCALP_INTERVAL
    candles (default 5m) across all BingX perpetuals and opens new
    paper positions for fresh signals.

State is written to scalp_state.json and paper_account_scalp.json so
web_app.py can render a live dashboard.

Usage:
  python main_scalp.py
"""

import asyncio
import csv
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp

import bingx_source as source
from scanner import run_scan
from paper_account import PaperAccount
from discord_alert import send_daily_report
from config import (
    SCALP_INTERVAL, SCALP_SCAN_INTERVAL_SECS, SCALP_CHECK_INTERVAL_SECS,
    SCALP_COOLDOWN_SECS, SCALP_PAPER_INITIAL_BALANCE, SCALP_PAPER_RISK_PCT,
    SCALP_DISCORD_WEBHOOK,
)

TW_TZ      = timezone(timedelta(hours=8))
PAPER_FILE = Path(__file__).parent / "paper_account_scalp.json"
STATE_FILE = Path(__file__).parent / "scalp_state.json"

TRADE_CSV     = Path(__file__).parent / "trade_history_scalp.csv"
SIGNALS_JSONL = Path(__file__).parent / "signals_history_scalp.jsonl"
EQUITY_JSONL  = Path(__file__).parent / "equity_history_scalp.jsonl"
TRADES_JSONL  = Path(__file__).parent / "trades_scalp.jsonl"

TRADE_CSV_FIELDS = [
    "symbol", "strategy", "direction", "tier", "score", "entry", "exit",
    "stop_loss", "target_1", "target_2", "contracts", "pnl",
    "reason", "full_close", "open_time", "close_time",
]

log = logging.getLogger(__name__)


def save_state(account: PaperAccount, signals: list[dict], total_scanned: int) -> None:
    state = {
        "updated":       time.time(),
        "interval":      SCALP_INTERVAL,
        "total_scanned": total_scanned,
        "stats":         account.get_stats(),
        "signals":       signals[:20],
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def export_trades_csv(account: PaperAccount) -> None:
    """Rewrite the full closed-trade history as CSV for analysis."""
    with open(TRADE_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for t in account.history:
            row = dict(t)
            row["open_time"]  = datetime.fromtimestamp(t["open_time"],  tz=TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
            row["close_time"] = datetime.fromtimestamp(t["close_time"], tz=TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow(row)


def append_signals_jsonl(signals: list[dict], total_scanned: int) -> None:
    """Append every signal from this scan (not just the top 20) for later analysis."""
    ts = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
    with open(SIGNALS_JSONL, "a", encoding="utf-8") as f:
        for sg in signals:
            rec = {"time": ts, "total_scanned": total_scanned, **sg}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def append_trades_jsonl(events: list[dict], account: PaperAccount) -> None:
    """Append each exit event to an immutable JSONL log for permanent record."""
    ts = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
    stats = account.get_stats()
    with open(TRADES_JSONL, "a", encoding="utf-8") as f:
        for ev in events:
            rec = {
                "time":    ts,
                "balance": stats["current_balance"],
                **ev,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def append_equity_snapshot(account: PaperAccount) -> None:
    """Append a balance snapshot so an equity curve can be plotted later."""
    ts    = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
    stats = account.get_stats()
    rec = {
        "time":            ts,
        "balance":         stats["current_balance"],
        "total_pnl":       stats["total_pnl"],
        "open_positions":  stats["open_positions"],
    }
    with open(EQUITY_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ── Loop 1: fast position checks ─────────────────────────────

async def position_loop(account: PaperAccount, session: aiohttp.ClientSession) -> None:
    while True:
        try:
            open_syms = list(account.positions.keys())
            if open_syms:
                changed = False
                all_events: list[dict] = []
                for sym in open_syms:
                    price = await source.fetch_price(session, sym)
                    if price is None:
                        continue
                    for ev in account.update_price(sym, price, price):
                        changed = True
                        all_events.append(ev)
                        print(f"  [SCALP EXIT] {sym:14s} {ev['reason']:4s}  PnL: ${ev['pnl']:>+.2f}")
                if changed:
                    account.save(PAPER_FILE)
                    export_trades_csv(account)
                    append_trades_jsonl(all_events, account)
                    append_equity_snapshot(account)
        except Exception as e:
            log.warning("position_loop error: %s", e)

        await asyncio.sleep(SCALP_CHECK_INTERVAL_SECS)


# ── Loop 2: periodic full re-scan for new signals ────────────

async def scan_loop(account: PaperAccount, cooldown: dict[str, float]) -> None:
    while True:
        try:
            now_str = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S TWN")
            print(f"\n=== SCALP SCAN | {SCALP_INTERVAL} | {now_str} ===")

            now_ts = time.time()
            expired = [s for s, t in cooldown.items() if now_ts - t >= SCALP_COOLDOWN_SECS]
            for s in expired:
                del cooldown[s]

            signals, total = await run_scan("scalp", "bingx")
            print(f"Scanned: {total} | Signals: {len(signals)}")

            now_ts = time.time()  # refresh after scan completes
            opened = 0
            for sig in signals:
                sym = sig["symbol"]
                if sym in account.positions:
                    continue
                if now_ts - cooldown.get(sym, 0) < SCALP_COOLDOWN_SECS:
                    continue
                if account.open_position(sig):
                    cooldown[sym] = now_ts
                    opened += 1
                    strategy = sig.get("strategy", "MA_BREAKOUT")
                    print(
                        f"  [SCALP OPEN] {sym:14s} {strategy:12s}  Score {sig['score']}  "
                        f"entry={sig['entry']:.6g}  SL={sig['stop_loss']:.6g}  TP1={sig['target_1']:.6g}"
                    )

            account.save(PAPER_FILE)
            save_state(account, signals, total)
            export_trades_csv(account)
            append_signals_jsonl(signals, total)
            append_equity_snapshot(account)

            stats = account.get_stats()
            print(
                f"Opened: {opened} | Open positions: {stats['open_positions']} | "
                f"Balance: ${stats['current_balance']:,.2f} ({stats['return_pct']:+.2f}%)"
            )
        except Exception as e:
            log.warning("scan_loop error: %s", e)

        await asyncio.sleep(SCALP_SCAN_INTERVAL_SECS)


async def _send_shutdown_report(account: PaperAccount) -> None:
    """Send today's trading summary to Discord on shutdown."""
    if not SCALP_DISCORD_WEBHOOK:
        return
    try:
        today = datetime.now(TW_TZ).date()
        history_today = [
            t for t in account.history
            if datetime.fromtimestamp(t["close_time"], tz=TW_TZ).date() == today
        ]
        await send_daily_report(account.get_stats(), history_today, "bingx", SCALP_DISCORD_WEBHOOK)
        print("Discord 關閉報告已發送")
    except Exception as e:
        log.warning("Failed to send shutdown report: %s", e)


async def main_async() -> None:
    if PAPER_FILE.exists():
        account = PaperAccount.load(PAPER_FILE)
    else:
        account = PaperAccount(SCALP_PAPER_INITIAL_BALANCE, SCALP_PAPER_RISK_PCT)

    cooldown: dict[str, float] = {}

    try:
        async with aiohttp.ClientSession() as session:
            await asyncio.gather(
                position_loop(account, session),
                scan_loop(account, cooldown),
            )
    except asyncio.CancelledError:
        pass
    finally:
        account.save(PAPER_FILE)
        await _send_shutdown_report(account)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for lib in ("aiohttp", "asyncio"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    print("=" * 55)
    print("  Crypto Screener — High-Frequency Scalp Bot (BingX)")
    print(f"  Interval: {SCALP_INTERVAL} | Scan every {SCALP_SCAN_INTERVAL_SECS}s | "
          f"Position check every {SCALP_CHECK_INTERVAL_SECS}s")
    print("=" * 55)

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    main()
