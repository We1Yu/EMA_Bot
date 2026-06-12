"""Hard filter gate — any failure discards the symbol entirely."""

import pandas as pd
from indicators import calc_atr
from config import (
    CLUSTER_THRESHOLD, VOL_RATIO_MIN,
    EMA200_SKIP_PCT, ATR_PERIOD,
)


def apply_hard_filters(data: dict) -> tuple[bool, str]:
    """
    Core hard filters: MA cluster tightness + volume breakout only.
    RSI / ADX / BBW are soft scoring items, not gates.
    Returns (passed, reason_if_failed).
    """
    close   = data["close"]
    high    = data["high"]
    low     = data["low"]
    volume  = data["volume"]

    ma15  = data["ma15"]
    ma30  = data["ma30"]
    ma45  = data["ma45"]
    ma60  = data["ma60"]
    ma200 = data["ma200"]

    c_last = close.iloc[-1]
    c_prev = close.iloc[-2]

    # ── F1: MA Cluster tightness ──────────────────────────────
    ma_vals = [ma15.iloc[-2], ma30.iloc[-2], ma45.iloc[-2], ma60.iloc[-2]]
    if any(pd.isna(v) for v in ma_vals):
        return False, "insufficient MA data"

    spread_pct = (max(ma_vals) - min(ma_vals)) / c_prev
    if spread_pct >= CLUSTER_THRESHOLD:
        return False, f"cluster_spread={spread_pct:.4f}>={CLUSTER_THRESHOLD}"

    # ── F2: Breakout above cluster ────────────────────────────
    if not all(c_last > ma for ma in ma_vals):
        return False, "no breakout above MA cluster"

    # ── F3: Anti-chase (within 2 ATR of cluster center) ──────
    atr_s   = calc_atr(high, low, close, ATR_PERIOD)
    atr_now = atr_s.iloc[-1]
    if not pd.isna(atr_now) and atr_now > 0:
        cluster_center = sum(ma_vals) / len(ma_vals)
        dist = c_last - cluster_center
        if dist > 2 * atr_now:
            return False, f"chase filter: {dist/atr_now:.1f} ATR above cluster center"

    # ── F4: Volume surge ──────────────────────────────────────
    if len(volume) < 6:
        return False, "insufficient volume data"
    vol_ratio = volume.iloc[-1] / volume.iloc[-6:-1].mean()
    if vol_ratio < VOL_RATIO_MIN:
        return False, f"vol_ratio={vol_ratio:.2f}<{VOL_RATIO_MIN}"

    # ── F5: Candle sanity ─────────────────────────────────────
    if (high.iloc[-1] - low.iloc[-1]) == 0:
        return False, "zero-range candle"

    # ── F6: Weekly macro trend ────────────────────────────────
    w_close = data.get("weekly_close")
    w_ma20  = data.get("weekly_ma20")
    if w_close is None or w_ma20 is None:
        return False, "missing weekly data"
    if pd.isna(w_ma20.iloc[-1]) or w_close.iloc[-1] <= w_ma20.iloc[-1]:
        return False, "weekly_close below weekly_ma20"

    # ── F7: 200 MA position ───────────────────────────────────
    m200 = ma200.iloc[-1]
    if pd.isna(m200):
        return False, "ma200 not ready"
    dist_pct = abs(c_last - m200) / m200
    if c_last < m200 and dist_pct <= EMA200_SKIP_PCT:
        return False, f"SKIP zone: {dist_pct:.3f}<={EMA200_SKIP_PCT} below 200MA"
    if c_last < m200:
        return False, "below 200MA (not crossing on this candle)"

    return True, ""


def apply_hard_filters_short(data: dict) -> tuple[bool, str]:
    """
    Mirror of apply_hard_filters() for SHORT setups.
    Core hard filters: MA cluster tightness + volume breakdown only.
    Returns (passed, reason_if_failed).
    """
    close   = data["close"]
    high    = data["high"]
    low     = data["low"]
    volume  = data["volume"]

    ma15  = data["ma15"]
    ma30  = data["ma30"]
    ma45  = data["ma45"]
    ma60  = data["ma60"]
    ma200 = data["ma200"]

    c_last = close.iloc[-1]
    c_prev = close.iloc[-2]

    # ── F1: MA Cluster tightness ──────────────────────────────
    ma_vals = [ma15.iloc[-2], ma30.iloc[-2], ma45.iloc[-2], ma60.iloc[-2]]
    if any(pd.isna(v) for v in ma_vals):
        return False, "insufficient MA data"

    spread_pct = (max(ma_vals) - min(ma_vals)) / c_prev
    if spread_pct >= CLUSTER_THRESHOLD:
        return False, f"cluster_spread={spread_pct:.4f}>={CLUSTER_THRESHOLD}"

    # ── F2: Breakdown below cluster ───────────────────────────
    if not all(c_last < ma for ma in ma_vals):
        return False, "no breakdown below MA cluster"

    # ── F3: Anti-chase (within 2 ATR of cluster center) ──────
    atr_s   = calc_atr(high, low, close, ATR_PERIOD)
    atr_now = atr_s.iloc[-1]
    if not pd.isna(atr_now) and atr_now > 0:
        cluster_center = sum(ma_vals) / len(ma_vals)
        dist = cluster_center - c_last
        if dist > 2 * atr_now:
            return False, f"chase filter: {dist/atr_now:.1f} ATR below cluster center"

    # ── F4: Volume surge ──────────────────────────────────────
    if len(volume) < 6:
        return False, "insufficient volume data"
    vol_ratio = volume.iloc[-1] / volume.iloc[-6:-1].mean()
    if vol_ratio < VOL_RATIO_MIN:
        return False, f"vol_ratio={vol_ratio:.2f}<{VOL_RATIO_MIN}"

    # ── F5: Candle sanity ─────────────────────────────────────
    if (high.iloc[-1] - low.iloc[-1]) == 0:
        return False, "zero-range candle"

    # ── F6: Weekly macro trend (bearish) ─────────────────────
    w_close = data.get("weekly_close")
    w_ma20  = data.get("weekly_ma20")
    if w_close is None or w_ma20 is None:
        return False, "missing weekly data"
    if pd.isna(w_ma20.iloc[-1]) or w_close.iloc[-1] >= w_ma20.iloc[-1]:
        return False, "weekly_close above weekly_ma20"

    # ── F7: 200 MA position ───────────────────────────────────
    m200 = ma200.iloc[-1]
    if pd.isna(m200):
        return False, "ma200 not ready"
    dist_pct = abs(c_last - m200) / m200
    if c_last > m200 and dist_pct <= EMA200_SKIP_PCT:
        return False, f"SKIP zone: {dist_pct:.3f}<={EMA200_SKIP_PCT} above 200MA"
    if c_last > m200:
        return False, "above 200MA (not breaking down on this candle)"

    return True, ""
