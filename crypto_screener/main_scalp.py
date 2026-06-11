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
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp

import bingx_source as source
from scanner import run_scan
from paper_account import PaperAccount
from config import (
    SCALP_INTERVAL, SCALP_SCAN_INTERVAL_SECS, SCALP_CHECK_INTERVAL_SECS,
    SCALP_COOLDOWN_SECS, SCALP_PAPER_INITIAL_BALANCE, SCALP_PAPER_RISK_PCT,
)

TW_TZ      = timezone(timedelta(hours=8))
PAPER_FILE = Path(__file__).parent / "paper_account_scalp.json"
STATE_FILE = Path(__file__).parent / "scalp_state.json"

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


# ── Loop 1: fast position checks ─────────────────────────────

async def position_loop(account: PaperAccount, session: aiohttp.ClientSession) -> None:
    while True:
        try:
            open_syms = list(account.positions.keys())
            if open_syms:
                changed = False
                for sym in open_syms:
                    price = await source.fetch_price(session, sym)
                    if price is None:
                        continue
                    for ev in account.update_price(sym, price, price):
                        changed = True
                        print(f"  [SCALP EXIT] {sym:14s} {ev['reason']:4s}  PnL: ${ev['pnl']:>+.2f}")
                if changed:
                    account.save(PAPER_FILE)
        except Exception as e:
            log.warning("position_loop error: %s", e)

        await asyncio.sleep(SCALP_CHECK_INTERVAL_SECS)


# ── Loop 2: periodic full re-scan for new signals ────────────

async def scan_loop(account: PaperAccount, cooldown: dict[str, float]) -> None:
    while True:
        try:
            now_str = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S TWN")
            print(f"\n=== SCALP SCAN | {SCALP_INTERVAL} | {now_str} ===")

            signals, total = await run_scan("scalp", "bingx")
            print(f"Scanned: {total} | Signals: {len(signals)}")

            now_ts = time.time()
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
                    print(
                        f"  [SCALP OPEN] {sym:14s} Tier {sig['tier']}  Score {sig['score']}  "
                        f"entry={sig['entry']:.6g}  SL={sig['stop_loss']:.6g}  TP1={sig['target_1']:.6g}"
                    )

            account.save(PAPER_FILE)
            save_state(account, signals, total)

            stats = account.get_stats()
            print(
                f"Opened: {opened} | Open positions: {stats['open_positions']} | "
                f"Balance: ${stats['current_balance']:,.2f} ({stats['return_pct']:+.2f}%)"
            )
        except Exception as e:
            log.warning("scan_loop error: %s", e)

        await asyncio.sleep(SCALP_SCAN_INTERVAL_SECS)


async def main_async() -> None:
    account = PaperAccount.load(PAPER_FILE)
    if not PAPER_FILE.exists():
        account = PaperAccount(SCALP_PAPER_INITIAL_BALANCE, SCALP_PAPER_RISK_PCT)

    cooldown: dict[str, float] = {}

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            position_loop(account, session),
            scan_loop(account, cooldown),
        )


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
