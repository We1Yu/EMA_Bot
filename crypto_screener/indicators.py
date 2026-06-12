"""
Indicator calculations — pure pandas, no TA-Lib.
All functions accept pd.Series and return pd.Series unless noted.
"""

import pandas as pd
import numpy as np
from typing import NamedTuple


def calc_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(period).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI using Wilder's EMA smoothing (ewm com=period-1)."""
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_bbw(series: pd.Series, period: int = 20, std: float = 2.0) -> pd.Series:
    """Normalised Bollinger Band Width = (upper - lower) / middle."""
    mid   = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    return (2 * std * sigma) / mid


def calc_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (adx, plus_di, minus_di)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    up   = high.diff()
    down = -low.diff()
    plus_dm  = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)

    kw = dict(com=period - 1, min_periods=period)
    atr14    = tr.ewm(**kw).mean()
    plus_di  = 100 * plus_dm.ewm(**kw).mean()  / atr14
    minus_di = 100 * minus_dm.ewm(**kw).mean() / atr14
    dx = (100 * (plus_di - minus_di).abs()
              / (plus_di + minus_di).replace(0, float("nan")))
    adx = dx.ewm(**kw).mean()
    return adx, plus_di, minus_di


def calc_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Average True Range."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def calc_macd(
    series: pd.Series,
    fast: int = 12, slow: int = 26, signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd     = ema_fast - ema_slow
    sig      = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig, macd - sig


class FibLevels(NamedTuple):
    fib_0618:  float   # pullback support
    fib_1272:  float   # target 1 (conservative)
    fib_1618:  float   # target 2 (standard)
    fib_2618:  float   # target 3 (extended)


def calc_fib_levels(close: pd.Series, direction: str = "LONG") -> FibLevels:
    """Fibonacci extension levels from 20-candle cluster swing."""
    if direction == "LONG":
        cluster_low  = close.iloc[-20:-1].min()
        cluster_high = close.iloc[-1]
        swing        = cluster_high - cluster_low
        return FibLevels(
            fib_0618 = cluster_high - 0.618 * swing,
            fib_1272 = cluster_high + 0.272 * swing,
            fib_1618 = cluster_high + 0.618 * swing,
            fib_2618 = cluster_high + 1.618 * swing,
        )
    # SHORT — mirrored around the cluster high / current low
    cluster_high = close.iloc[-20:-1].max()
    cluster_low  = close.iloc[-1]
    swing        = cluster_high - cluster_low
    return FibLevels(
        fib_0618 = cluster_low + 0.618 * swing,
        fib_1272 = cluster_low - 0.272 * swing,
        fib_1618 = cluster_low - 0.618 * swing,
        fib_2618 = cluster_low - 1.618 * swing,
    )


class ExitLevels(NamedTuple):
    entry:          float
    stop_loss:      float
    target_1:       float   # exit 30%, move stop to entry
    target_2:       float   # exit 40%, move stop to target_1
    target_3:       float   # trail remaining 30%
    risk_reward:    float
    primary_target: float   # min(fib_1618, target_2)


def calc_exit_levels(
    entry: float, atr: float, fib: FibLevels,
    stop_mult: float = 1.5,
    target_mults: tuple = (2.0, 3.0, 4.0),
    direction: str = "LONG",
) -> ExitLevels:
    """ATR-based stop / target / exit levels with Fibonacci overlay."""
    if direction == "LONG":
        stop_loss = entry - stop_mult * atr
        t1        = entry + target_mults[0] * atr
        t2        = entry + target_mults[1] * atr
        t3        = entry + target_mults[2] * atr
        rr        = (t1 - entry) / (entry - stop_loss) if (entry - stop_loss) > 0 else 0.0
        primary   = min(fib.fib_1618, t2)
    else:  # SHORT — mirrored
        stop_loss = entry + stop_mult * atr
        t1        = entry - target_mults[0] * atr
        t2        = entry - target_mults[1] * atr
        t3        = entry - target_mults[2] * atr
        rr        = (entry - t1) / (stop_loss - entry) if (stop_loss - entry) > 0 else 0.0
        primary   = max(fib.fib_1618, t2)
    return ExitLevels(
        entry=entry, stop_loss=stop_loss,
        target_1=t1, target_2=t2, target_3=t3,
        risk_reward=round(rr, 2),
        primary_target=primary,
    )
