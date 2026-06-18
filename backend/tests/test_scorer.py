"""
評分系統測試
鎖住：各策略基底分、門檻、時段獎勵、bonus 指標上限
"""

import pytest
from app.services.scoring.scorer import (
    score_setup,
    passes_threshold,
    MIN_SCORE,
    EU_US_SESSION_START,
    EU_US_SESSION_END,
)

# ── 測試用 bar_time_ms（固定時段，避免 datetime.now() 不確定性）─────────

# TWN = UTC+8
# 10:00 TWN = 02:00 UTC → 2*3600*1000 ms (from epoch)
_MS_OUTSIDE_SESSION = 2 * 3600 * 1000   # 10:00 TWN，不在 EU/US 時段

# 18:00 TWN = 10:00 UTC → 10*3600*1000 ms
_MS_INSIDE_SESSION  = 10 * 3600 * 1000  # 18:00 TWN，在 EU/US 時段


# ── 基礎工廠函數 ──────────────────────────────────────────────────────────

def convergence_result(
    bandwidth=0.8, compression_bars=6, vol_ratio=2.5,
    body_ratio=0.75, ema200_clear=True, direction="LONG",
    bonus=None,
):
    return {
        "strategy":   "EMA_CONVERGENCE",
        "direction":  direction,
        "convergence": {
            "bandwidth":         bandwidth,
            "compression_bars":  compression_bars,
        },
        "vol_ratio":  vol_ratio,
        "confirm_1h": {"body_ratio": body_ratio},
        "ema200_clear": ema200_clear,
        "bonus_indicators": bonus or {},
    }


def momentum_result(vol_ratio=2.0, body_ratio=0.75, ema200_clear=False,
                    direction="LONG", bonus=None, strategy="EMA_PULLBACK"):
    return {
        "strategy":   strategy,
        "direction":  direction,
        "vol_ratio":  vol_ratio,
        "confirm_1h": {"body_ratio": body_ratio},
        "ema200_clear": ema200_clear,
        "bonus_indicators": bonus or {},
    }


def breakout_result(vol_ratio=2.5, body_ratio=0.75, ema200_clear=True,
                    direction="LONG", bonus=None):
    return {
        "strategy":   "STRUCTURE_BREAKOUT",
        "direction":  direction,
        "vol_ratio":  vol_ratio,
        "confirm_1h": {"body_ratio": body_ratio},
        "ema200_clear": ema200_clear,
        "bonus_indicators": bonus or {},
    }


def ema60_bounce_result(vol_ratio=2.5, body_ratio=0.75, ema200_clear=True,
                        direction="LONG", bonus=None):
    return {
        "strategy":   "EMA60_BOUNCE",
        "direction":  direction,
        "vol_ratio":  vol_ratio,
        "confirm_1h": {"body_ratio": body_ratio},
        "ema200_clear": ema200_clear,
        "bonus_indicators": bonus or {},
    }


# ── passes_threshold ──────────────────────────────────────────────────────

class TestPassesThreshold:
    def test_exact_threshold_passes(self):
        assert passes_threshold(MIN_SCORE) is True

    def test_below_threshold_fails(self):
        assert passes_threshold(MIN_SCORE - 0.1) is False

    def test_perfect_score_passes(self):
        assert passes_threshold(10.0) is True

    def test_zero_fails(self):
        assert passes_threshold(0.0) is False


# ── EMA_CONVERGENCE ───────────────────────────────────────────────────────

class TestConvergenceScorer:
    def test_max_score_components_no_session(self):
        # bw<1 → +2, bars>=5 → +2, vol>=2 → +2, body>=0.7 → +1, ema200 → +1, base → +1
        # total = 9.0（無時段加分）
        r = convergence_result()
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc == pytest.approx(9.0)

    def test_session_bonus_adds_1(self):
        r = convergence_result()
        sc_out = score_setup(r, _MS_OUTSIDE_SESSION)
        sc_in  = score_setup(r, _MS_INSIDE_SESSION)
        assert sc_in == pytest.approx(sc_out + 1.0)

    def test_score_capped_at_10(self):
        bonus = {"macd_aligned": True, "macd_crossed": True, "bb_side_ok": True, "rsi_1h": 55}
        r  = convergence_result(bonus=bonus)
        sc = score_setup(r, _MS_INSIDE_SESSION)
        assert sc == pytest.approx(10.0)

    def test_low_bandwidth_tier(self):
        # bw=1.2 → +1, bars=2 → 0, vol=1.0 → 0, body=0.5 → 0, no ema200, base=1
        r  = convergence_result(bandwidth=1.2, compression_bars=2, vol_ratio=1.0,
                                body_ratio=0.5, ema200_clear=False)
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc == pytest.approx(2.0)

    def test_medium_bandwidth_tier(self):
        # bw=1.7 → +0.5
        r  = convergence_result(bandwidth=1.7, compression_bars=2, vol_ratio=1.0,
                                body_ratio=0.5, ema200_clear=False)
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc == pytest.approx(1.5)

    def test_vol_tier_1_5(self):
        r  = convergence_result(bandwidth=2.5, compression_bars=2,
                                vol_ratio=1.5, body_ratio=0.5, ema200_clear=False)
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc == pytest.approx(2.0)  # base(1) + vol(1)

    def test_body_tier_0_6(self):
        r  = convergence_result(bandwidth=2.5, compression_bars=2,
                                vol_ratio=1.0, body_ratio=0.62, ema200_clear=False)
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc == pytest.approx(1.5)  # base(1) + body(0.5)

    def test_short_direction_accepted(self):
        r  = convergence_result(direction="SHORT")
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert 0.0 < sc <= 10.0


# ── STRUCTURE_BREAKOUT ────────────────────────────────────────────────────

class TestStructureBreakout:
    def test_base_score_with_max_vol(self):
        # base=4, vol>=2.5 → +2.5, body>=0.75 → +2, ema200 → +1 = 9.5
        r  = breakout_result()
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc == pytest.approx(9.5)

    def test_vol_tier_2_0(self):
        # vol>=2.0 → +2.0
        r  = breakout_result(vol_ratio=2.0, ema200_clear=False)
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        # 4 + 2 + 2 = 8.0
        assert sc == pytest.approx(8.0)

    def test_vol_tier_1_5(self):
        r  = breakout_result(vol_ratio=1.5, ema200_clear=False)
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        # 4 + 1 + 2 = 7.0
        assert sc == pytest.approx(7.0)


# ── EMA60_BOUNCE / PINBAR_AT_EMA / EMA_CROSS_1H ──────────────────────────

class TestEma60BounceScorer:
    def test_base_score(self):
        # base=4, vol>=2.5 → +2.5, body>=0.75 → +2, ema200 → +0.5 = 9.0
        r  = ema60_bounce_result()
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc == pytest.approx(9.0)

    def test_pinbar_at_ema_uses_same_scorer(self):
        r = ema60_bounce_result()
        r["strategy"] = "PINBAR_AT_EMA"
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc == pytest.approx(9.0)


# ── EMA_PULLBACK（momentum 通用）────────────────────────────────────────

class TestMomentumScorer:
    def test_base_score_high_vol_body(self):
        # base=3, vol>=2 → +2, body>=0.75 → +2 = 7.0
        r  = momentum_result()
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc == pytest.approx(7.0)

    def test_ema200_adds_1(self):
        r  = momentum_result(ema200_clear=True)
        sc = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc == pytest.approx(8.0)


# ── bonus_indicators ─────────────────────────────────────────────────────

class TestBonusIndicators:
    def test_rsi_long_in_zone_adds_0_5(self):
        bonus = {"rsi_1h": 55}
        r  = convergence_result(bonus=bonus, ema200_clear=False,
                                compression_bars=2, vol_ratio=1.0, body_ratio=0.5)
        sc_no  = score_setup(convergence_result(ema200_clear=False, compression_bars=2,
                                                vol_ratio=1.0, body_ratio=0.5),
                             _MS_OUTSIDE_SESSION)
        sc_rsi = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc_rsi == pytest.approx(sc_no + 0.5)

    def test_rsi_long_out_of_zone_no_bonus(self):
        bonus = {"rsi_1h": 30}  # 不在 45-65 區間
        r  = convergence_result(bonus=bonus, ema200_clear=False,
                                compression_bars=2, vol_ratio=1.0, body_ratio=0.5)
        sc_no  = score_setup(convergence_result(ema200_clear=False, compression_bars=2,
                                                vol_ratio=1.0, body_ratio=0.5),
                             _MS_OUTSIDE_SESSION)
        sc_rsi = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc_rsi == pytest.approx(sc_no)

    def test_macd_aligned_adds_0_5(self):
        bonus = {"macd_aligned": True}
        r  = convergence_result(bonus=bonus, ema200_clear=False,
                                compression_bars=2, vol_ratio=1.0, body_ratio=0.5)
        sc_no  = score_setup(convergence_result(ema200_clear=False, compression_bars=2,
                                                vol_ratio=1.0, body_ratio=0.5),
                             _MS_OUTSIDE_SESSION)
        sc_b   = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc_b == pytest.approx(sc_no + 0.5)

    def test_bonus_capped_at_2(self):
        # rsi+macd_aligned+macd_crossed+bb_side_ok = 0.5*4=2.0，不超過 2
        bonus = {"rsi_1h": 55, "macd_aligned": True, "macd_crossed": True, "bb_side_ok": True}
        r  = convergence_result(bonus=bonus, ema200_clear=False,
                                compression_bars=2, vol_ratio=1.0, body_ratio=0.5)
        sc_no  = score_setup(convergence_result(ema200_clear=False, compression_bars=2,
                                                vol_ratio=1.0, body_ratio=0.5),
                             _MS_OUTSIDE_SESSION)
        sc_b   = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc_b == pytest.approx(sc_no + 2.0)

    def test_rsi_short_zone(self):
        # SHORT 方向：35-55 加分
        bonus = {"rsi_1h": 45}
        r  = convergence_result(bonus=bonus, direction="SHORT", ema200_clear=False,
                                compression_bars=2, vol_ratio=1.0, body_ratio=0.5)
        sc_no  = score_setup(convergence_result(direction="SHORT", ema200_clear=False,
                                                compression_bars=2, vol_ratio=1.0, body_ratio=0.5),
                             _MS_OUTSIDE_SESSION)
        sc_b   = score_setup(r, _MS_OUTSIDE_SESSION)
        assert sc_b == pytest.approx(sc_no + 0.5)


# ── 時段邊界 ──────────────────────────────────────────────────────────────

class TestSessionBoundary:
    def _base_score(self, ms):
        return score_setup(convergence_result(), ms)

    def test_session_start_hour_gives_bonus(self):
        # 15:00 TWN = (15-8):00 UTC = 07:00 UTC → 7 * 3600 * 1000 ms
        ms_start = (EU_US_SESSION_START - 8) * 3600 * 1000
        assert self._base_score(ms_start) == pytest.approx(10.0)

    def test_session_end_hour_no_bonus(self):
        # EU_US_SESSION_END=22 → 22:00 TWN = 14:00 UTC → 14*3600*1000
        ms_end = EU_US_SESSION_END * 3600 * 1000
        assert self._base_score(ms_end) == pytest.approx(9.0)
