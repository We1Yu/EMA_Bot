"""Per-symbol orchestration: fetch -> filter -> score -> build signal."""

import logging
import asyncio
import aiohttp
import pandas as pd
from types import ModuleType
from typing import Optional

from config import (
    CANDLES_MAIN, CANDLES_WEEKLY, BATCH_SIZE, BATCH_DELAY,
    ATR_PERIOD, ATR_STOP_MULT, ATR_TARGET_MULTS, EMA200_SKIP_PCT,
    MA_PERIODS, SCALP_INTERVAL,
)
from indicators import (
    calc_sma, calc_atr, calc_rsi, calc_bbw, calc_adx,
    calc_fib_levels, calc_exit_levels,
)
from filters  import apply_hard_filters, apply_hard_filters_short
from scoring  import compute_score, compute_score_short

log = logging.getLogger(__name__)

# Kept for backward-compat (main.py imports BINANCE_BASE for fetch_latest_bars)
BINANCE_BASE = "https://fapi.binance.com"


# ── Binance raw fetch helpers (used by fetch_latest_bars in main.py) ─

async def _fetch_json(
    session: aiohttp.ClientSession, url: str, params: dict
) -> Optional[list]:
    try:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except Exception as e:
        log.debug("fetch error %s: %s", url, e)
        return None


async def fetch_klines(
    session: aiohttp.ClientSession, symbol: str, interval: str, limit: int
) -> Optional[list]:
    """Binance klines — returns raw list-of-lists."""
    return await _fetch_json(
        session,
        f"{BINANCE_BASE}/fapi/v1/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )


# ── DataFrame builder (handles both exchange formats) ────────────────

def _klines_to_df(raw: list) -> pd.DataFrame:
    """
    Convert raw klines to DataFrame.
    Handles both:
      - Binance: list-of-lists  [open_time, open, high, low, close, volume, ...]
      - BingX:   list-of-dicts  {open, high, low, close, volume, time}
    """
    if not raw:
        return pd.DataFrame()

    if isinstance(raw[0], (list, tuple)):
        # Binance format
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "taker_base", "taker_quote", "ignore",
        ])
    else:
        # BingX format (dicts already have open/high/low/close/volume/time)
        df = pd.DataFrame(raw)
        df = df.rename(columns={"time": "open_time"})

    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.reset_index(drop=True)


# ── Tier classification ───────────────────────────────────────────────

def _determine_tier(
    close_last: float, ma200_last: float, ma200_prev: float, close_prev: float
) -> Optional[str]:
    """Returns TIER A / B / SKIP / None."""
    if close_last > ma200_last and close_prev > ma200_prev:
        return "A"
    if close_last > ma200_last and close_prev <= ma200_prev:
        return "B"
    dist = abs(close_last - ma200_last) / ma200_last
    if close_last < ma200_last and dist <= EMA200_SKIP_PCT:
        return "SKIP"
    return None


def _determine_tier_short(
    close_last: float, ma200_last: float, ma200_prev: float, close_prev: float
) -> Optional[str]:
    """Mirror of _determine_tier() for SHORT setups. Returns TIER A / B / SKIP / None."""
    if close_last < ma200_last and close_prev < ma200_prev:
        return "A"
    if close_last < ma200_last and close_prev >= ma200_prev:
        return "B"
    dist = abs(close_last - ma200_last) / ma200_last
    if close_last > ma200_last and dist <= EMA200_SKIP_PCT:
        return "SKIP"
    return None


# ── Per-symbol scan ───────────────────────────────────────────────────

async def scan_symbol(
    session: aiohttp.ClientSession,
    symbol: str,
    source: ModuleType,
    mode: str = "swing",
    check_dual_tf: bool = False,
) -> Optional[dict]:
    """
    Full pipeline for one symbol using the given data source module.
    source: either `binance_source` or `bingx_source` module
    mode:   "swing" → 4H | "intraday" → 1H
    """
    if mode == "swing":
        interval = "4h"
    elif mode == "scalp":
        interval = SCALP_INTERVAL
    else:
        interval = "1h"
    weekly_interval = "1w"

    # Concurrent fetch
    main_raw, weekly_raw, funding, change_24h = await asyncio.gather(
        source.fetch_klines(session, symbol, interval, CANDLES_MAIN),
        source.fetch_klines(session, symbol, weekly_interval, CANDLES_WEEKLY),
        source.fetch_funding(session, symbol),
        source.fetch_ticker_24h(session, symbol),
    )

    if not main_raw or len(main_raw) < 210:
        log.debug("%s: insufficient main klines (%s)", symbol, len(main_raw) if main_raw else 0)
        return None
    if not weekly_raw or len(weekly_raw) < 22:
        log.debug("%s: insufficient weekly klines (%s)", symbol, len(weekly_raw) if weekly_raw else 0)
        return None

    df  = _klines_to_df(main_raw)
    wdf = _klines_to_df(weekly_raw)

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df["volume"]

    ma15, ma30, ma45, ma60, ma200 = [calc_sma(close, p) for p in MA_PERIODS]

    weekly_close = wdf["close"]
    weekly_ma20  = calc_sma(weekly_close, 20)
    weekly_slope = 0.0
    if not pd.isna(weekly_ma20.iloc[-1]) and not pd.isna(weekly_ma20.iloc[-4]):
        weekly_slope = (weekly_ma20.iloc[-1] - weekly_ma20.iloc[-4]) / weekly_ma20.iloc[-4]

    c_last  = close.iloc[-1]
    c_prev  = close.iloc[-2]
    m200_last = ma200.iloc[-1]
    m200_prev = ma200.iloc[-2]

    tier_long  = _determine_tier(c_last, m200_last, m200_prev, c_prev)
    tier_short = _determine_tier_short(c_last, m200_last, m200_prev, c_prev) if mode == "scalp" else None

    if tier_long in (None, "SKIP") and tier_short in (None, "SKIP"):
        log.debug("%s: tier=%s/%s, skipped", symbol, tier_long, tier_short)
        return None

    # 4H-loading annotation for intraday mode
    dual_tf = False
    if mode == "intraday" and check_dual_tf:
        h4_raw = await source.fetch_klines(session, symbol, "4h", 60)
        if h4_raw and len(h4_raw) >= 60:
            h4df    = _klines_to_df(h4_raw)
            h4c     = h4df["close"]
            h4_ma15 = calc_sma(h4c, 15).iloc[-2]
            h4_ma60 = calc_sma(h4c, 60).iloc[-2]
            if not pd.isna(h4_ma15) and not pd.isna(h4_ma60):
                dual_tf = abs(h4_ma15 - h4_ma60) / h4c.iloc[-2] < 0.025

    indicator_data = {
        "close": close, "high": high, "low": low, "open_": open_, "volume": volume,
        "ma15": ma15, "ma30": ma30, "ma45": ma45, "ma60": ma60, "ma200": ma200,
        "weekly_close": weekly_close, "weekly_ma20": weekly_ma20,
        "weekly_slope": weekly_slope,
        "funding_rate": funding,
        "change_24h":   change_24h,
        "dual_timeframe": dual_tf,
    }

    direction = "LONG"
    tier      = tier_long
    passed    = False
    reason    = ""

    if tier_long not in (None, "SKIP"):
        indicator_data["tier"] = tier_long
        passed, reason = apply_hard_filters(indicator_data)

    if not passed and tier_short not in (None, "SKIP"):
        indicator_data["tier"] = tier_short
        ok, short_reason = apply_hard_filters_short(indicator_data)
        if ok:
            direction, tier, passed, reason = "SHORT", tier_short, True, ""
        elif not reason:
            reason = short_reason

    if not passed:
        log.debug("%s: filter failed: %s", symbol, reason)
        return None

    if direction == "LONG":
        score, breakdown = compute_score(indicator_data)
    else:
        score, breakdown = compute_score_short(indicator_data)

    atr_series = calc_atr(high, low, close, ATR_PERIOD)
    atr_now    = atr_series.iloc[-1]
    fib        = calc_fib_levels(close, direction)
    exits      = calc_exit_levels(close.iloc[-1], atr_now, fib, ATR_STOP_MULT, ATR_TARGET_MULTS, direction)

    rsi_s       = calc_rsi(close, 14)
    adx_s, _, _ = calc_adx(high, low, close, 14)
    bbw_ratio   = breakdown.get("bbw_ratio", 0)
    ma_vals     = [ma15.iloc[-2], ma30.iloc[-2], ma45.iloc[-2], ma60.iloc[-2]]
    spread_pct  = (max(ma_vals) - min(ma_vals)) / close.iloc[-2]
    vol_ratio   = volume.iloc[-1] / volume.iloc[-6:-1].mean()
    candle_range = high.iloc[-1] - low.iloc[-1]
    body_pct    = abs(close.iloc[-1] - open_.iloc[-1]) / candle_range if candle_range else 0

    if direction == "LONG":
        weekly_status = (
            "STRONG" if (weekly_close.iloc[-1] > weekly_ma20.iloc[-1] and weekly_slope > 0)
            else ("OK" if weekly_close.iloc[-1] > weekly_ma20.iloc[-1] else "-")
        )
    else:
        weekly_status = (
            "STRONG" if (weekly_close.iloc[-1] < weekly_ma20.iloc[-1] and weekly_slope < 0)
            else ("OK" if weekly_close.iloc[-1] < weekly_ma20.iloc[-1] else "-")
        )

    return {
        "symbol":         symbol,
        "direction":      direction,
        "tier":           tier,
        "score":          score,
        "breakdown":      breakdown,
        "ma_spread_pct":  round(spread_pct * 100, 3),
        "vol_ratio":      round(vol_ratio, 2),
        "body_pct":       round(body_pct * 100, 1),
        "rsi":            round(rsi_s.iloc[-1], 1),
        "bbw_ratio":      round(bbw_ratio, 3),
        "adx":            round(adx_s.iloc[-1], 1),
        "funding":        round(funding * 100, 4),
        "change_24h":     round(change_24h, 2),
        "weekly":         weekly_status,
        "dual_tf_status": "4H LOADING" if dual_tf else "",
        "entry":          round(exits.entry, 8),
        "stop_loss":      round(exits.stop_loss, 8),
        "target_1":       round(exits.target_1, 8),
        "target_2":       round(exits.target_2, 8),
        "target_3":       round(exits.target_3, 8),
        "primary_target": round(exits.primary_target, 8),
        "risk_reward":    exits.risk_reward,
        "fib_support":    round(fib.fib_0618, 8),
        "alert": (
            f"{direction} TIER {tier} | RSI {rsi_s.iloc[-1]:.0f} | "
            f"ADX {adx_s.iloc[-1]:.0f} | "
            f"R:R {exits.risk_reward:.1f} | "
            f"Target {abs(exits.primary_target - exits.entry) / exits.entry * 100:.1f}%"
        ),
    }


# ── Full scan orchestration ───────────────────────────────────────────

async def run_scan(mode: str = "swing", exchange: str = "binance") -> tuple[list[dict], int]:
    """
    Scan all perpetual symbols on the given exchange.
    exchange: "binance" (default) or "bingx"
    Returns (signals, total_scanned).
    """
    if exchange == "bingx":
        import bingx_source as source
    else:
        import binance_source as source

    async with aiohttp.ClientSession() as session:
        symbols = await source.fetch_symbols(session)
        if not symbols:
            log.error("Could not fetch symbol list from %s", exchange)
            return [], 0

        total_scanned = len(symbols)
        log.info("[%s] Scanning %d symbols...", exchange.upper(), total_scanned)
        signals: list[dict] = []

        for i in range(0, len(symbols), BATCH_SIZE):
            batch   = symbols[i: i + BATCH_SIZE]
            tasks   = [scan_symbol(session, sym, source, mode) for sym in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for sym, res in zip(batch, results):
                if isinstance(res, Exception):
                    log.debug("%s error: %s", sym, res)
                elif res is not None:
                    signals.append(res)
            if i + BATCH_SIZE < len(symbols):
                await asyncio.sleep(BATCH_DELAY)

        signals.sort(key=lambda x: x["score"], reverse=True)
        return signals, total_scanned
