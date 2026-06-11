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
    RSI_BOUNCE_OVERSOLD, RSI_BOUNCE_OVERBOUGHT,
    EMA_FAST_PERIOD, EMA_SLOW_PERIOD, VOL_SPIKE_RATIO,
)
from indicators import (
    calc_sma, calc_ema, calc_atr, calc_rsi, calc_bbw, calc_adx,
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


# ── Strategy helpers ─────────────────────────────────────────────────

def _build_signal_base(symbol: str, direction: str, strategy: str, score: int,
                       entry: float, sl: float, t1: float, t2: float, t3: float,
                       rsi: float, vol_ratio: float, body_pct: float, adx: float,
                       funding: float, breakdown: dict, alert: str) -> dict:
    """Build a complete signal dict with all fields the dashboard expects."""
    if direction == "LONG":
        rr = (t1 - entry) / (entry - sl) if (entry - sl) > 0 else 0.0
    else:
        rr = (entry - t1) / (sl - entry) if (sl - entry) > 0 else 0.0
    return {
        "symbol":         symbol,
        "direction":      direction,
        "tier":           "C",
        "strategy":       strategy,
        "score":          score,
        "breakdown":      breakdown,
        "rsi":            round(rsi, 1),
        "vol_ratio":      round(vol_ratio, 2),
        "body_pct":       round(body_pct, 1),
        "adx":            round(adx, 1),
        "bbw_ratio":      0.0,
        "ma_spread_pct":  0.0,
        "funding":        round(funding * 100, 4),
        "change_24h":     0.0,
        "weekly":         "-",
        "dual_tf_status": "",
        "entry":          round(entry, 8),
        "stop_loss":      round(sl, 8),
        "target_1":       round(t1, 8),
        "target_2":       round(t2, 8),
        "target_3":       round(t3, 8),
        "primary_target": round(t2, 8),
        "risk_reward":    round(rr, 2),
        "fib_support":    0.0,
        "alert":          alert,
    }


def _try_rsi_bounce(symbol: str, df: pd.DataFrame, funding: float) -> Optional[dict]:
    """RSI oversold/overbought mean-reversion scalp."""
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df["volume"]

    rsi_s = calc_rsi(close, 14)
    atr_s = calc_atr(high, low, close, 14)

    rsi_now  = rsi_s.iloc[-1]
    rsi_prev = rsi_s.iloc[-2]
    atr_now  = atr_s.iloc[-1]
    entry    = close.iloc[-1]

    if any(pd.isna(v) for v in [rsi_now, rsi_prev, atr_now]) or atr_now <= 0 or entry <= 0:
        return None

    direction = None
    if rsi_now <= RSI_BOUNCE_OVERSOLD and rsi_now > rsi_prev and close.iloc[-1] > open_.iloc[-1]:
        direction = "LONG"
    elif rsi_now >= RSI_BOUNCE_OVERBOUGHT and rsi_now < rsi_prev and close.iloc[-1] < open_.iloc[-1]:
        direction = "SHORT"
    if direction is None:
        return None

    vol_avg   = volume.iloc[-6:-1].mean()
    vol_ratio = volume.iloc[-1] / vol_avg if vol_avg > 0 else 1.0

    score = 60
    if direction == "LONG":
        score += 10 if rsi_now <= 25 else (5 if rsi_now <= 30 else 0)
    else:
        score += 10 if rsi_now >= 75 else (5 if rsi_now >= 70 else 0)
    score += 8 if vol_ratio > 2.5 else (4 if vol_ratio > 1.5 else 0)

    candle_range = high.iloc[-1] - low.iloc[-1]
    body_pct = abs(close.iloc[-1] - open_.iloc[-1]) / candle_range * 100 if candle_range > 0 else 0.0

    if direction == "LONG":
        sl, t1, t2, t3 = (entry - 1.2 * atr_now, entry + 1.8 * atr_now,
                          entry + 2.8 * atr_now, entry + 3.8 * atr_now)
    else:
        sl, t1, t2, t3 = (entry + 1.2 * atr_now, entry - 1.8 * atr_now,
                          entry - 2.8 * atr_now, entry - 3.8 * atr_now)

    return _build_signal_base(
        symbol, direction, "RSI_BOUNCE", score,
        entry, sl, t1, t2, t3,
        rsi=rsi_now, vol_ratio=vol_ratio, body_pct=body_pct, adx=0.0,
        funding=funding,
        breakdown={"rsi_now": round(rsi_now, 1), "rsi_prev": round(rsi_prev, 1), "vol_ratio": round(vol_ratio, 2)},
        alert=f"{direction} RSI_BOUNCE | RSI {rsi_now:.0f}→{rsi_prev:.0f} | vol×{vol_ratio:.1f}",
    )


def _try_ema_cross(symbol: str, df: pd.DataFrame) -> Optional[dict]:
    """EMA(9/21) crossover with volume and RSI confirmation."""
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df["volume"]

    ema_fast = calc_ema(close, EMA_FAST_PERIOD)
    ema_slow = calc_ema(close, EMA_SLOW_PERIOD)
    rsi_s    = calc_rsi(close, 14)
    atr_s    = calc_atr(high, low, close, 14)

    ef_now, ef_prev = ema_fast.iloc[-1], ema_fast.iloc[-2]
    es_now, es_prev = ema_slow.iloc[-1], ema_slow.iloc[-2]
    rsi_now  = rsi_s.iloc[-1]
    atr_now  = atr_s.iloc[-1]
    entry    = close.iloc[-1]

    if any(pd.isna(v) for v in [ef_now, ef_prev, es_now, es_prev, rsi_now, atr_now]):
        return None
    if atr_now <= 0 or entry <= 0:
        return None

    vol_avg   = volume.iloc[-6:-1].mean()
    vol_ratio = volume.iloc[-1] / vol_avg if vol_avg > 0 else 1.0
    if vol_ratio < 1.2:
        return None

    direction = None
    if ef_prev <= es_prev and ef_now > es_now and 35 <= rsi_now <= 65:
        direction = "LONG"
    elif ef_prev >= es_prev and ef_now < es_now and 35 <= rsi_now <= 65:
        direction = "SHORT"
    if direction is None:
        return None

    score = 55
    score += 5 if 45 <= rsi_now <= 55 else 0
    score += 8 if vol_ratio > 2.5 else (4 if vol_ratio > 1.5 else 0)

    adx_val = 0.0
    try:
        adx_s, plus_di, minus_di = calc_adx(high, low, close, 14)
        adx_val = adx_s.iloc[-1]
        if not pd.isna(adx_val) and adx_val > 20:
            if direction == "LONG" and plus_di.iloc[-1] > minus_di.iloc[-1]:
                score += 5
            elif direction == "SHORT" and minus_di.iloc[-1] > plus_di.iloc[-1]:
                score += 5
        else:
            adx_val = 0.0
    except Exception:
        pass

    candle_range = high.iloc[-1] - low.iloc[-1]
    body_pct = abs(close.iloc[-1] - open_.iloc[-1]) / candle_range * 100 if candle_range > 0 else 0.0

    if direction == "LONG":
        sl, t1, t2, t3 = (entry - 1.5 * atr_now, entry + 2.0 * atr_now,
                          entry + 3.0 * atr_now, entry + 4.0 * atr_now)
    else:
        sl, t1, t2, t3 = (entry + 1.5 * atr_now, entry - 2.0 * atr_now,
                          entry - 3.0 * atr_now, entry - 4.0 * atr_now)

    return _build_signal_base(
        symbol, direction, "EMA_CROSS", score,
        entry, sl, t1, t2, t3,
        rsi=rsi_now, vol_ratio=vol_ratio, body_pct=body_pct, adx=adx_val,
        funding=0.0,
        breakdown={"ema_fast": round(ef_now, 6), "ema_slow": round(es_now, 6), "rsi": round(rsi_now, 1)},
        alert=f"{direction} EMA_CROSS({EMA_FAST_PERIOD}/{EMA_SLOW_PERIOD}) | RSI {rsi_now:.0f} | vol×{vol_ratio:.1f} | ADX {adx_val:.0f}",
    )


def _try_vol_spike(symbol: str, df: pd.DataFrame) -> Optional[dict]:
    """Monster-volume directional spike — momentum entry."""
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df["volume"]

    atr_s = calc_atr(high, low, close, 14)
    rsi_s = calc_rsi(close, 14)

    atr_now = atr_s.iloc[-1]
    rsi_now = rsi_s.iloc[-1]
    entry   = close.iloc[-1]
    c_high  = high.iloc[-1]
    c_low   = low.iloc[-1]
    c_open  = open_.iloc[-1]

    if pd.isna(atr_now) or atr_now <= 0 or entry <= 0:
        return None

    vol_avg   = volume.iloc[-21:-1].mean()
    vol_ratio = volume.iloc[-1] / vol_avg if vol_avg > 0 else 1.0
    if vol_ratio < VOL_SPIKE_RATIO:
        return None

    candle_range = c_high - c_low
    if candle_range <= 0:
        return None

    body_pct = abs(entry - c_open) / candle_range
    if body_pct < 0.55:
        return None

    close_pos = (entry - c_low) / candle_range

    direction = None
    if entry > c_open and close_pos > 0.70:
        direction = "LONG"
    elif entry < c_open and close_pos < 0.30:
        direction = "SHORT"
    if direction is None:
        return None

    score = 65
    score += 10 if vol_ratio > 6.0 else (5 if vol_ratio > 4.5 else 0)
    score += 5 if body_pct > 0.75 else 0
    if not pd.isna(rsi_now):
        if direction == "LONG" and 45 <= rsi_now <= 65:
            score += 5
        elif direction == "SHORT" and 35 <= rsi_now <= 55:
            score += 5

    rsi_display = rsi_now if not pd.isna(rsi_now) else 0.0

    if direction == "LONG":
        sl, t1, t2, t3 = (entry - 1.0 * atr_now, entry + 1.5 * atr_now,
                          entry + 2.5 * atr_now, entry + 3.5 * atr_now)
    else:
        sl, t1, t2, t3 = (entry + 1.0 * atr_now, entry - 1.5 * atr_now,
                          entry - 2.5 * atr_now, entry - 3.5 * atr_now)

    return _build_signal_base(
        symbol, direction, "VOL_SPIKE", score,
        entry, sl, t1, t2, t3,
        rsi=rsi_display, vol_ratio=vol_ratio, body_pct=body_pct * 100, adx=0.0,
        funding=0.0,
        breakdown={"vol_ratio": round(vol_ratio, 2), "body_pct": round(body_pct * 100, 1)},
        alert=f"{direction} VOL_SPIKE | vol×{vol_ratio:.1f} | body {body_pct*100:.0f}% | RSI {rsi_display:.0f}",
    )


# ── Per-symbol scan ───────────────────────────────────────────────────

async def scan_symbol(
    session: aiohttp.ClientSession,
    symbol: str,
    source: ModuleType,
    mode: str = "swing",
    check_dual_tf: bool = False,
) -> list[dict]:
    """
    Run all applicable strategies for one symbol.
    Returns a list of signal dicts (one per triggered strategy).
    source: either `binance_source` or `bingx_source` module
    mode:   "swing" → 4H | "scalp" → 5m | "intraday" → 1H
    """
    if mode == "swing":
        interval = "4h"
    elif mode == "scalp":
        interval = SCALP_INTERVAL
    else:
        interval = "1h"

    main_raw, weekly_raw, funding, change_24h = await asyncio.gather(
        source.fetch_klines(session, symbol, interval, CANDLES_MAIN),
        source.fetch_klines(session, symbol, "1w", CANDLES_WEEKLY),
        source.fetch_funding(session, symbol),
        source.fetch_ticker_24h(session, symbol),
    )

    if not main_raw or len(main_raw) < 50:
        return []

    df  = _klines_to_df(main_raw)
    wdf = _klines_to_df(weekly_raw) if weekly_raw and len(weekly_raw) >= 22 else None

    signals: list[dict] = []

    # ── Strategy 1: MA Cluster Breakout (original — needs 210 candles + weekly) ──
    if len(main_raw) >= 210 and wdf is not None:
        sig = _try_ma_breakout(symbol, df, wdf, funding, change_24h, mode)
        if sig:
            signals.append(sig)

    # ── Strategies 2-4: scalp-only, need only 50 candles ──────────────
    if mode == "scalp" and len(df) >= 50:
        for fn in (_try_rsi_bounce, _try_ema_cross, _try_vol_spike):
            try:
                sig = fn(symbol, df, funding) if fn is _try_rsi_bounce else fn(symbol, df)
                if sig:
                    signals.append(sig)
            except Exception as e:
                log.debug("%s %s error: %s", symbol, fn.__name__, e)

    return signals


def _try_ma_breakout(
    symbol: str, df: pd.DataFrame, wdf: pd.DataFrame,
    funding: float, change_24h: float,
    mode: str,
) -> Optional[dict]:
    """Original MA cluster breakout logic (sync, called from scan_symbol)."""
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

    c_last    = close.iloc[-1]
    c_prev    = close.iloc[-2]
    m200_last = ma200.iloc[-1]
    m200_prev = ma200.iloc[-2]

    tier_long  = _determine_tier(c_last, m200_last, m200_prev, c_prev)
    tier_short = _determine_tier_short(c_last, m200_last, m200_prev, c_prev) if mode == "scalp" else None

    if tier_long in (None, "SKIP") and tier_short in (None, "SKIP"):
        return None

    indicator_data = {
        "close": close, "high": high, "low": low, "open_": open_, "volume": volume,
        "ma15": ma15, "ma30": ma30, "ma45": ma45, "ma60": ma60, "ma200": ma200,
        "weekly_close": weekly_close, "weekly_ma20": weekly_ma20,
        "weekly_slope": weekly_slope,
        "funding_rate": funding,
        "change_24h":   change_24h,
        "dual_timeframe": False,
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
        "strategy":       "MA_BREAKOUT",
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
        "dual_tf_status": "",
        "entry":          round(exits.entry, 8),
        "stop_loss":      round(exits.stop_loss, 8),
        "target_1":       round(exits.target_1, 8),
        "target_2":       round(exits.target_2, 8),
        "target_3":       round(exits.target_3, 8),
        "primary_target": round(exits.primary_target, 8),
        "risk_reward":    exits.risk_reward,
        "fib_support":    round(fib.fib_0618, 8),
        "alert": (
            f"{direction} MA_BREAKOUT TIER {tier} | RSI {rsi_s.iloc[-1]:.0f} | "
            f"ADX {adx_s.iloc[-1]:.0f} | R:R {exits.risk_reward:.1f} | "
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
                elif res:
                    signals.extend(res)
            if i + BATCH_SIZE < len(symbols):
                await asyncio.sleep(BATCH_DELAY)

        signals.sort(key=lambda x: x["score"], reverse=True)
        return signals, total_scanned
