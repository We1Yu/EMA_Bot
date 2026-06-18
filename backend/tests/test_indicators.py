"""
指標函數單元測試
全部純函數，不需要任何外部 API 或資料庫
"""

import pytest
from app.services.strategies.indicators import (
    calc_ema,
    calc_atr,
    calc_bandwidth,
    calc_rsi,
    calc_bollinger,
    calc_adx,
    body_ratio,
)


# ── calc_ema ──────────────────────────────────────────────────────────────

class TestCalcEma:
    def test_constant_series_equals_constant(self):
        closes = [100.0] * 20
        result = calc_ema(closes, period=10)
        for v in result[9:]:
            assert v == pytest.approx(100.0)

    def test_leading_values_are_none(self):
        closes = list(range(1, 21))
        result = calc_ema(closes, period=5)
        assert all(v is None for v in result[:4])
        assert result[4] is not None

    def test_too_short_all_none(self):
        result = calc_ema([1.0, 2.0], period=5)
        assert result == [None, None]

    def test_known_values_period3(self):
        # closes=[1,2,3,4,5], period=3
        # multiplier=0.5, seed=2.0
        # result[2]=2.0, result[3]=4*0.5+2.0*0.5=3.0, result[4]=5*0.5+3.0*0.5=4.0
        result = calc_ema([1.0, 2.0, 3.0, 4.0, 5.0], period=3)
        assert result[0] is None
        assert result[1] is None
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)
        assert result[4] == pytest.approx(4.0)

    def test_output_length_matches_input(self):
        closes = [float(i) for i in range(50)]
        result = calc_ema(closes, period=10)
        assert len(result) == 50

    def test_ema_slowly_tracks_rising_prices(self):
        closes = [float(i) for i in range(1, 101)]
        result = calc_ema(closes, period=20)
        # EMA 應落後實際值（滯後性）
        assert result[-1] < closes[-1]
        assert result[-1] > result[-2]   # 仍在上升


# ── calc_atr ──────────────────────────────────────────────────────────────

def _candles(highs, lows, closes):
    candles = []
    for h, lo, c in zip(highs, lows, closes):
        candles.append({"high": h, "low": lo, "close": c, "open": c})
    return candles


class TestCalcAtr:
    def test_not_enough_data_all_none(self):
        candles = _candles([10]*3, [9]*3, [9.5]*3)
        result = calc_atr(candles, period=14)
        assert all(v is None for v in result)

    def test_constant_tr_equals_range(self):
        # 每根 K 棒: high=12, low=10, close=11, prev_close=11
        # TR = max(2, |12-11|, |10-11|) = max(2, 1, 1) = 2
        highs  = [12.0] * 20
        lows   = [10.0] * 20
        closes = [11.0] * 20
        candles = _candles(highs, lows, closes)
        result = calc_atr(candles, period=3)
        # ATR at index 3 (seed from TR[1..3])
        assert result[3] == pytest.approx(2.0)
        # Wilder smoothing with constant TR → stays 2.0
        assert result[-1] == pytest.approx(2.0)

    def test_output_length_matches_input(self):
        candles = _candles([12]*30, [10]*30, [11]*30)
        result = calc_atr(candles, period=5)
        assert len(result) == 30

    def test_leading_values_are_none(self):
        candles = _candles([12]*30, [10]*30, [11]*30)
        result = calc_atr(candles, period=14)
        # 前 period 個值應為 None
        assert all(v is None for v in result[:14])
        assert result[14] is not None


# ── calc_bandwidth ────────────────────────────────────────────────────────

class TestCalcBandwidth:
    def test_all_same_returns_zero(self):
        assert calc_bandwidth(100.0, 100.0, 100.0, 100.0) == pytest.approx(0.0)

    def test_known_values(self):
        # high=105, low=98, ema60=102 → (105-98)/102*100 ≈ 6.8627
        result = calc_bandwidth(100.0, 105.0, 98.0, 102.0)
        assert result == pytest.approx((105.0 - 98.0) / 102.0 * 100, rel=1e-5)

    def test_ema60_zero_returns_zero(self):
        assert calc_bandwidth(1.0, 2.0, 0.5, 0.0) == pytest.approx(0.0)


# ── calc_rsi ──────────────────────────────────────────────────────────────

class TestCalcRsi:
    def test_too_few_closes_all_none(self):
        result = calc_rsi([1.0, 2.0, 3.0], period=14)
        assert all(v is None for v in result)

    def test_all_increasing_gives_100(self):
        # 沒有虧損 → avg_loss=0 → RSI=100
        closes = list(range(1, 20))
        result = calc_rsi(closes, period=14)
        assert result[14] == pytest.approx(100.0)

    def test_all_same_gives_50_or_100(self):
        # 完全持平：gains=losses=0 → avg_loss=0 → RSI=100
        closes = [50.0] * 20
        result = calc_rsi(closes, period=14)
        assert result[14] == pytest.approx(100.0)

    def test_rsi_in_valid_range(self):
        import random
        random.seed(42)
        closes = [100.0 + random.gauss(0, 1) for _ in range(60)]
        result = calc_rsi(closes, period=14)
        for v in result:
            if v is not None:
                assert 0.0 <= v <= 100.0

    def test_leading_none_count(self):
        closes = [float(i) for i in range(1, 31)]
        result = calc_rsi(closes, period=14)
        assert all(v is None for v in result[:14])
        assert result[14] is not None


# ── body_ratio ────────────────────────────────────────────────────────────

class TestBodyRatio:
    def test_full_body_bullish(self):
        c = {"open": 100.0, "close": 110.0, "high": 110.0, "low": 100.0}
        assert body_ratio(c) == pytest.approx(1.0)

    def test_doji_is_zero(self):
        c = {"open": 100.0, "close": 100.0, "high": 105.0, "low": 95.0}
        assert body_ratio(c) == pytest.approx(0.0)

    def test_known_ratio(self):
        # body=5, total=10 → 0.5
        c = {"open": 100.0, "close": 105.0, "high": 107.5, "low": 97.5}
        assert body_ratio(c) == pytest.approx(0.5)

    def test_zero_range_returns_zero(self):
        c = {"open": 100.0, "close": 100.0, "high": 100.0, "low": 100.0}
        assert body_ratio(c) == pytest.approx(0.0)


# ── calc_bollinger ────────────────────────────────────────────────────────

class TestCalcBollinger:
    def test_flat_series_zero_width(self):
        closes = [100.0] * 30
        result = calc_bollinger(closes, period=20)
        for i in range(19, 30):
            assert result["width"][i] == pytest.approx(0.0)
            assert result["upper"][i]  == pytest.approx(100.0)
            assert result["lower"][i]  == pytest.approx(100.0)

    def test_leading_none(self):
        closes = [float(i) for i in range(30)]
        result = calc_bollinger(closes, period=20)
        assert all(v is None for v in result["upper"][:19])

    def test_upper_above_lower(self):
        import random
        random.seed(0)
        closes = [100.0 + random.gauss(0, 2) for _ in range(50)]
        result = calc_bollinger(closes, period=20)
        for i in range(19, 50):
            if result["upper"][i] is not None:
                assert result["upper"][i] >= result["lower"][i]


# ── calc_adx ──────────────────────────────────────────────────────────────

class TestCalcAdx:
    def test_not_enough_data_all_none(self):
        candles = _candles([10]*10, [9]*10, [9.5]*10)
        result = calc_adx(candles, period=14)
        assert all(v is None for v in result)

    def test_adx_in_valid_range(self):
        import random
        random.seed(7)
        n = 80
        price = 100.0
        prices = []
        for _ in range(n):
            price += random.gauss(0, 1)
            prices.append(price)
        candles = _candles(
            [p + abs(random.gauss(0, 0.5)) for p in prices],
            [p - abs(random.gauss(0, 0.5)) for p in prices],
            prices,
        )
        result = calc_adx(candles, period=14)
        for v in result:
            if v is not None:
                assert 0.0 <= v <= 100.0
