"""Hard filter gate — any failure discards the symbol entirely."""

import pandas as pd
from indicators import calc_sma, calc_rsi, calc_adx, calc_bbw
from config import (
    CLUSTER_THRESHOLD, VOL_RATIO_MIN, BODY_PCT_MIN,
    RSI_MIN, RSI_MAX, RSI_PERIOD, ADX_MIN, ADX_PERIOD,
    EMA200_SKIP_PCT, RSI_MIN_SHORT, RSI_MAX_SHORT,
)


def apply_hard_filters(data: dict) -> tuple[bool, str]:
    """
    Run all hard filters in order.
    Returns (passed, reason_if_failed).
    data keys: close, high, low, open_, volume, weekly_close, weekly_ma20,
               ma15, ma30, ma45, ma60, ma200 (all pd.Series)
    """
    close   = data["close"]
    high    = data["high"]
    low     = data["low"]
    open_   = data["open_"]
    volume  = data["volume"]

    # ── F1: Core setup ────────────────────────────────────────
    ma15  = data["ma15"]
    ma30  = data["ma30"]
    ma45  = data["ma45"]
    ma60  = data["ma60"]
    ma200 = data["ma200"]

    c_last  = close.iloc[-1]
    c_prev  = close.iloc[-2]

    # Cluster: spread of 4 MAs on the last CLOSED candle [-2]
    ma_vals = [ma15.iloc[-2], ma30.iloc[-2], ma45.iloc[-2], ma60.iloc[-2]]
    if any(pd.isna(v) for v in ma_vals):
        return False, "insufficient MA data"

    spread_pct = (max(ma_vals) - min(ma_vals)) / c_prev
    cluster_ok = spread_pct < CLUSTER_THRESHOLD
    if not cluster_ok:
        return False, f"cluster_spread={spread_pct:.4f}>={CLUSTER_THRESHOLD}"

    # Breakout: close[-1] > all 4 MAs[-2]
    breakout_ok = all(c_last > ma for ma in ma_vals)
    if not breakout_ok:
        return False, "no breakout above MA cluster"

    # Volume: vol[-1] >= 1.5x rolling 5-bar avg
    if len(volume) < 6:
        return False, "insufficient volume data"
    vol_ratio = volume.iloc[-1] / volume.iloc[-6:-1].mean()
    if vol_ratio < VOL_RATIO_MIN:
        return False, f"vol_ratio={vol_ratio:.2f}<{VOL_RATIO_MIN}"

    # ── F2: Candle quality ────────────────────────────────────
    candle_range = high.iloc[-1] - low.iloc[-1]
    if candle_range == 0:
        return False, "zero-range candle"
    body_pct = abs(c_last - open_.iloc[-1]) / candle_range
    if body_pct < BODY_PCT_MIN:
        return False, f"body_pct={body_pct:.2f}<{BODY_PCT_MIN}"

    # ── F3: RSI momentum ─────────────────────────────────────
    rsi = calc_rsi(close, RSI_PERIOD)
    rsi_now = rsi.iloc[-1]
    if pd.isna(rsi_now) or not (RSI_MIN <= rsi_now <= RSI_MAX):
        return False, f"rsi={rsi_now:.1f} outside [{RSI_MIN},{RSI_MAX}]"

    # ── F4: Trend strength ────────────────────────────────────
    adx_s, pdi_s, mdi_s = calc_adx(high, low, close, ADX_PERIOD)
    adx_now = adx_s.iloc[-1]
    if pd.isna(adx_now) or adx_now < ADX_MIN:
        return False, f"adx={adx_now:.1f}<{ADX_MIN}"
    if pdi_s.iloc[-1] <= mdi_s.iloc[-1]:
        return False, f"+DI({pdi_s.iloc[-1]:.1f})<=-DI({mdi_s.iloc[-1]:.1f})"

    # ── F5: Weekly macro trend ────────────────────────────────
    w_close = data.get("weekly_close")
    w_ma20  = data.get("weekly_ma20")
    if w_close is None or w_ma20 is None:
        return False, "missing weekly data"
    if pd.isna(w_ma20.iloc[-1]) or w_close.iloc[-1] <= w_ma20.iloc[-1]:
        return False, f"weekly_close below weekly_ma20"

    # ── F6: 200 MA tier classification ───────────────────────
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
    Mirror of apply_hard_filters() for SHORT setups (breakdown below MA cluster).
    Returns (passed, reason_if_failed).
    """
    close   = data["close"]
    high    = data["high"]
    low     = data["low"]
    open_   = data["open_"]
    volume  = data["volume"]

    ma15  = data["ma15"]
    ma30  = data["ma30"]
    ma45  = data["ma45"]
    ma60  = data["ma60"]
    ma200 = data["ma200"]

    c_last = close.iloc[-1]
    c_prev = close.iloc[-2]

    # Cluster: spread of 4 MAs on the last CLOSED candle [-2]
    ma_vals = [ma15.iloc[-2], ma30.iloc[-2], ma45.iloc[-2], ma60.iloc[-2]]
    if any(pd.isna(v) for v in ma_vals):
        return False, "insufficient MA data"

    spread_pct = (max(ma_vals) - min(ma_vals)) / c_prev
    if not (spread_pct < CLUSTER_THRESHOLD):
        return False, f"cluster_spread={spread_pct:.4f}>={CLUSTER_THRESHOLD}"

    # Breakdown: close[-1] < all 4 MAs[-2]
    breakdown_ok = all(c_last < ma for ma in ma_vals)
    if not breakdown_ok:
        return False, "no breakdown below MA cluster"

    # Volume: vol[-1] >= 1.5x rolling 5-bar avg
    if len(volume) < 6:
        return False, "insufficient volume data"
    vol_ratio = volume.iloc[-1] / volume.iloc[-6:-1].mean()
    if vol_ratio < VOL_RATIO_MIN:
        return False, f"vol_ratio={vol_ratio:.2f}<{VOL_RATIO_MIN}"

    # Candle quality
    candle_range = high.iloc[-1] - low.iloc[-1]
    if candle_range == 0:
        return False, "zero-range candle"
    body_pct = abs(c_last - open_.iloc[-1]) / candle_range
    if body_pct < BODY_PCT_MIN:
        return False, f"body_pct={body_pct:.2f}<{BODY_PCT_MIN}"

    # RSI momentum (mirrored bearish zone)
    rsi = calc_rsi(close, RSI_PERIOD)
    rsi_now = rsi.iloc[-1]
    if pd.isna(rsi_now) or not (RSI_MIN_SHORT <= rsi_now <= RSI_MAX_SHORT):
        return False, f"rsi={rsi_now:.1f} outside [{RSI_MIN_SHORT},{RSI_MAX_SHORT}]"

    # Trend strength — -DI must lead +DI
    adx_s, pdi_s, mdi_s = calc_adx(high, low, close, ADX_PERIOD)
    adx_now = adx_s.iloc[-1]
    if pd.isna(adx_now) or adx_now < ADX_MIN:
        return False, f"adx={adx_now:.1f}<{ADX_MIN}"
    if mdi_s.iloc[-1] <= pdi_s.iloc[-1]:
        return False, f"-DI({mdi_s.iloc[-1]:.1f})<=+DI({pdi_s.iloc[-1]:.1f})"

    # Weekly macro trend — must be bearish
    w_close = data.get("weekly_close")
    w_ma20  = data.get("weekly_ma20")
    if w_close is None or w_ma20 is None:
        return False, "missing weekly data"
    if pd.isna(w_ma20.iloc[-1]) or w_close.iloc[-1] >= w_ma20.iloc[-1]:
        return False, "weekly_close above weekly_ma20"

    # 200 MA tier classification (mirrored)
    m200 = ma200.iloc[-1]
    if pd.isna(m200):
        return False, "ma200 not ready"
    dist_pct = abs(c_last - m200) / m200
    if c_last > m200 and dist_pct <= EMA200_SKIP_PCT:
        return False, f"SKIP zone: {dist_pct:.3f}<={EMA200_SKIP_PCT} above 200MA"
    if c_last > m200:
        return False, "above 200MA (not breaking down on this candle)"

    return True, ""
