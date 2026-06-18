"""
PaperTrader 行為測試
鎖住：TP1 取 25%、保本移 SL、TP2 取 75%、SL 全平、手續費/滑點扣除
"""

import pytest
from app.services.paper_trader import PaperTrader, TP1_FRACTION


# ── 測試用 fixture ────────────────────────────────────────────────────────

INIT_BAL = 10_000.0


def make_trader(fee_rate=0.0, slippage_rate=0.0):
    return PaperTrader(
        initial_balance=INIT_BAL,
        risk_pct=0.02,
        max_positions=4,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )


def long_result(sym="BTCUSDT", entry=100.0, sl=95.0, tp1=110.0, tp2=120.0):
    return {
        "symbol": sym,
        "direction": "LONG",
        "strategy": "EMA_CONVERGENCE",
        "candle_time_ms": 1_000,
        "levels": {"entry": entry, "stop_loss": sl, "target1": tp1, "target2": tp2},
    }


def short_result(sym="ETHUSDT", entry=100.0, sl=105.0, tp1=90.0, tp2=80.0):
    return {
        "symbol": sym,
        "direction": "SHORT",
        "strategy": "EMA_CONVERGENCE",
        "candle_time_ms": 1_000,
        "levels": {"entry": entry, "stop_loss": sl, "target1": tp1, "target2": tp2},
    }


# ── 開倉限制 ──────────────────────────────────────────────────────────────

class TestOpenPosition:
    def test_open_long_succeeds(self):
        trader = make_trader()
        assert trader.open_position(long_result(), 8.0) is True
        assert "BTCUSDT" in trader.positions

    def test_duplicate_symbol_rejected(self):
        trader = make_trader()
        trader.open_position(long_result(), 8.0)
        assert trader.open_position(long_result(), 8.0) is False

    def test_max_positions_enforced(self):
        trader = make_trader()
        # 混方向以繞過 max_same_dir=2：2 LONG + 2 SHORT = 4 滿倉，第 5 個被拒
        results = [
            long_result("A"),  short_result("C"),
            long_result("B"),  short_result("D"),
            long_result("E"),  # 應被拒
        ]
        count = sum(1 for r in results if trader.open_position(r, 8.0))
        assert count == 4  # max_positions=4

    def test_max_same_dir_enforced(self):
        trader = make_trader()
        # max_same_dir=2，第三個同方向應被拒絕
        trader.open_position(long_result("A"), 8.0)
        trader.open_position(long_result("B"), 8.0)
        assert trader.open_position(long_result("C"), 8.0) is False

    def test_zero_risk_dist_rejected(self):
        trader = make_trader()
        result = long_result(entry=100.0, sl=100.0)  # entry==sl
        assert trader.open_position(result, 8.0) is False


# ── LONG 出場邏輯 ─────────────────────────────────────────────────────────

class TestLongExits:
    def _open(self, trader):
        # entry=100, sl=95, tp1=110, tp2=120
        # risk_dist=5, contracts=10000*0.02/5=40
        trader.open_position(long_result(), 8.0)
        return trader.positions["BTCUSDT"]

    def test_sl_closes_full_position(self):
        trader = make_trader()
        pos = self._open(trader)
        contracts = pos.contracts  # 40.0

        events = trader.check_bar("BTCUSDT", high=99.0, low=93.0, bar_time_ms=2_000)

        assert len(events) == 1
        e = events[0]
        assert e["reason"] == "SL"
        assert e["full_close"] is True
        # pnl = (95-100)*40 = -200
        assert e["pnl"] == pytest.approx((95.0 - 100.0) * contracts)
        assert "BTCUSDT" not in trader.positions

    def test_tp1_partial_close_25pct(self):
        trader = make_trader()
        pos = self._open(trader)
        contracts = pos.contracts  # 40.0

        events = trader.check_bar("BTCUSDT", high=112.0, low=101.0, bar_time_ms=2_000)

        assert len(events) == 1
        e = events[0]
        assert e["reason"] == "TP1"
        assert e["full_close"] is False
        # 25% 平倉
        assert e["contracts"] == pytest.approx(contracts * TP1_FRACTION)
        assert e["pnl"] == pytest.approx((110.0 - 100.0) * contracts * TP1_FRACTION)
        # 倉位仍開著
        assert "BTCUSDT" in trader.positions

    def test_tp1_moves_sl_to_entry(self):
        trader = make_trader()
        self._open(trader)
        trader.check_bar("BTCUSDT", high=112.0, low=101.0, bar_time_ms=2_000)

        pos = trader.positions["BTCUSDT"]
        assert pos.tp1_hit is True
        assert pos.stop_loss == pytest.approx(100.0)  # 移到成本（entry=100）

    def test_tp2_closes_remaining_75pct(self):
        trader = make_trader()
        pos = self._open(trader)
        contracts = pos.contracts

        trader.check_bar("BTCUSDT", high=112.0, low=101.0, bar_time_ms=2_000)
        events = trader.check_bar("BTCUSDT", high=122.0, low=111.0, bar_time_ms=3_000)

        assert len(events) == 1
        e = events[0]
        assert e["reason"] == "TP2"
        assert e["full_close"] is True
        remaining = 1.0 - TP1_FRACTION
        assert e["contracts"] == pytest.approx(contracts * remaining)
        assert e["pnl"] == pytest.approx((120.0 - 100.0) * contracts * remaining)
        assert "BTCUSDT" not in trader.positions

    def test_breakeven_sl_after_tp1(self):
        trader = make_trader()
        self._open(trader)

        trader.check_bar("BTCUSDT", high=112.0, low=101.0, bar_time_ms=2_000)
        # SL 已移到 100；bar low=98 觸發保本止損
        events = trader.check_bar("BTCUSDT", high=105.0, low=98.0, bar_time_ms=3_000)

        assert len(events) == 1
        e = events[0]
        assert e["reason"] == "套保"
        # exit_price = entry_price = 100 → pnl = 0
        assert e["pnl"] == pytest.approx(0.0, abs=1e-8)

    def test_balance_accumulates_across_tp1_tp2(self):
        trader = make_trader()
        pos = self._open(trader)
        contracts = pos.contracts

        trader.check_bar("BTCUSDT", high=112.0, low=101.0, bar_time_ms=2_000)
        trader.check_bar("BTCUSDT", high=122.0, low=111.0, bar_time_ms=3_000)

        expected_pnl = (
            (110.0 - 100.0) * contracts * TP1_FRACTION
            + (120.0 - 100.0) * contracts * (1.0 - TP1_FRACTION)
        )
        assert trader.balance == pytest.approx(INIT_BAL + expected_pnl)

    def test_old_bar_not_reprocessed(self):
        trader = make_trader()
        self._open(trader)
        trader.check_bar("BTCUSDT", high=99.0, low=93.0, bar_time_ms=2_000)
        events = trader.check_bar("BTCUSDT", high=99.0, low=93.0, bar_time_ms=2_000)
        assert events == []


# ── SHORT 出場邏輯 ────────────────────────────────────────────────────────

class TestShortExits:
    def _open(self, trader):
        # entry=100, sl=105, tp1=90, tp2=80
        # risk_dist=5, contracts=40
        trader.open_position(short_result(), 8.0)
        return trader.positions["ETHUSDT"]

    def test_sl_closes_short(self):
        trader = make_trader()
        pos = self._open(trader)
        contracts = pos.contracts

        events = trader.check_bar("ETHUSDT", high=107.0, low=101.0, bar_time_ms=2_000)

        e = events[0]
        assert e["reason"] == "SL"
        assert e["pnl"] == pytest.approx((100.0 - 105.0) * contracts)

    def test_tp1_partial_short(self):
        trader = make_trader()
        pos = self._open(trader)
        contracts = pos.contracts

        events = trader.check_bar("ETHUSDT", high=96.0, low=88.0, bar_time_ms=2_000)

        e = events[0]
        assert e["reason"] == "TP1"
        assert e["pnl"] == pytest.approx((100.0 - 90.0) * contracts * TP1_FRACTION)

    def test_tp2_closes_short(self):
        trader = make_trader()
        pos = self._open(trader)
        contracts = pos.contracts

        trader.check_bar("ETHUSDT", high=96.0, low=88.0, bar_time_ms=2_000)
        events = trader.check_bar("ETHUSDT", high=87.0, low=78.0, bar_time_ms=3_000)

        e = events[0]
        assert e["reason"] == "TP2"
        remaining = 1.0 - TP1_FRACTION
        assert e["pnl"] == pytest.approx((100.0 - 80.0) * contracts * remaining)


# ── 手續費與滑點 ──────────────────────────────────────────────────────────

class TestFeesAndSlippage:
    def test_open_fee_deducted_from_balance(self):
        fee_rate = 0.001  # 0.1%
        trader = make_trader(fee_rate=fee_rate)
        trader.open_position(long_result(entry=100.0, sl=90.0), 8.0)

        pos = trader.positions["BTCUSDT"]
        expected_fee = pos.notional * fee_rate
        assert trader.balance == pytest.approx(INIT_BAL - expected_fee)

    def test_close_fee_reduces_pnl(self):
        fee_rate = 0.001
        trader = make_trader(fee_rate=fee_rate)
        # entry=100, sl=90, risk_dist=10 → contracts=20
        trader.open_position(long_result(entry=100.0, sl=90.0, tp1=110.0, tp2=130.0), 8.0)

        # TP1 觸發（25% of 20 = 5 contracts，exit=110）
        events = trader.check_bar("BTCUSDT", high=112.0, low=101.0, bar_time_ms=2_000)
        e = events[0]
        assert e["reason"] == "TP1"

        contracts_closed = 5.0           # 20 * 0.25
        gross_pnl  = (110.0 - 100.0) * contracts_closed   # 50.0
        close_fee  = contracts_closed * 110.0 * fee_rate   # 0.55
        assert e["pnl"] == pytest.approx(gross_pnl - close_fee, rel=1e-6)

    def test_total_fees_tracked(self):
        fee_rate = 0.001
        trader = make_trader(fee_rate=fee_rate)
        # entry=100, sl=90 → contracts=20, notional=2000
        trader.open_position(long_result(entry=100.0, sl=90.0, tp1=110.0, tp2=130.0), 8.0)
        open_fee = 20.0 * 100.0 * fee_rate   # 2.0

        # TP1 觸發：5 contracts @ 110
        trader.check_bar("BTCUSDT", high=112.0, low=101.0, bar_time_ms=2_000)
        close_fee = 5.0 * 110.0 * fee_rate   # 0.55

        assert trader.total_fees == pytest.approx(open_fee + close_fee, rel=1e-6)

    def test_slippage_worsens_long_entry(self):
        slippage_rate = 0.001
        no_slip  = make_trader(slippage_rate=0.0)
        with_slip = make_trader(slippage_rate=slippage_rate)

        no_slip.open_position(long_result(), 8.0)
        with_slip.open_position(long_result(), 8.0)

        # LONG 滑點應使成交價高於報價
        assert with_slip.positions["BTCUSDT"].entry_price > no_slip.positions["BTCUSDT"].entry_price

    def test_slippage_worsens_short_entry(self):
        slippage_rate = 0.001
        no_slip   = make_trader(slippage_rate=0.0)
        with_slip = make_trader(slippage_rate=slippage_rate)

        no_slip.open_position(short_result(), 8.0)
        with_slip.open_position(short_result(), 8.0)

        # SHORT 滑點應使成交價低於報價
        assert with_slip.positions["ETHUSDT"].entry_price < no_slip.positions["ETHUSDT"].entry_price


# ── get_stats ────────────────────────────────────────────────────────────

class TestGetStats:
    def test_empty_history(self):
        trader = make_trader()
        s = trader.get_stats()
        assert s["trades"] == 0
        assert s["current_balance"] == INIT_BAL

    def test_win_rate_one_win(self):
        trader = make_trader()
        trader.open_position(long_result(), 8.0)
        # TP1 先觸發；同一根 bar 無法同時打到 TP2
        trader.check_bar("BTCUSDT", high=115.0, low=101.0, bar_time_ms=2_000)  # TP1
        trader.check_bar("BTCUSDT", high=125.0, low=111.0, bar_time_ms=3_000)  # TP2

        s = trader.get_stats()
        # full_close=True 的只有 TP2 那筆（pnl>0）
        assert s["wins"] == 1
        assert s["losses"] == 0
        assert s["win_rate_pct"] == pytest.approx(100.0)

    def test_win_rate_one_loss(self):
        trader = make_trader()
        trader.open_position(long_result(), 8.0)
        trader.check_bar("BTCUSDT", high=99.0, low=93.0, bar_time_ms=2_000)  # SL

        s = trader.get_stats()
        assert s["wins"] == 0
        assert s["losses"] == 1
        assert s["win_rate_pct"] == pytest.approx(0.0)

    def test_total_fees_in_stats(self):
        fee_rate = 0.001
        trader = make_trader(fee_rate=fee_rate)
        trader.open_position(long_result(entry=100.0, sl=90.0, tp1=110.0, tp2=130.0), 8.0)
        trader.check_bar("BTCUSDT", high=135.0, low=101.0, bar_time_ms=2_000)

        s = trader.get_stats()
        assert s["total_fees"] > 0
        assert s["fee_rate"] == fee_rate
