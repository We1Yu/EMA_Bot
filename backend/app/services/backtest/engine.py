"""
回測引擎：逐 4H Bar 模擬策略績效

使用方式（從 backend/ 目錄）：
  python -m app.services.backtest.engine              # 30 個幣種
  python -m app.services.backtest.engine --all        # 全部幣種
  python -m app.services.backtest.engine --detail     # 附交易明細
"""

import bisect
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.services.data_ingestion.binance import get_contracts, get_klines
from app.services.data_ingestion.fetch_data import load as load_cached, KLINES_CACHE_DIR
from app.services.strategies.indicators import ema_snapshot
from app.services.strategies.scanner import scan_symbol
from app.services.scoring.scorer import score_setup, passes_threshold
from app.services.paper_trader import PaperTrader

logger = logging.getLogger(__name__)

TW_TZ = timezone(timedelta(hours=8))

KLINES_4H   = 500
KLINES_1H   = 1500
WARMUP_BARS = 210
INIT_BAL    = 10_000.0
MAX_SYMBOLS = 30


REPORTS_DIR = Path(__file__).parent / "reports"


def fmt_tw(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=TW_TZ).strftime("%Y/%m/%d %H:%M")


def _save_equity_chart(
    s: dict,
    out_path: Path,
) -> None:
    """把權益曲線 + R 倍數分佈存成 PNG。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
    except ImportError:
        logger.warning("matplotlib 未安裝，略過圖表輸出")
        return

    eq  = s.get("equity_curve",  [])
    r_w = s.get("r_multiples",   [])

    fig = plt.figure(figsize=(14, 8))
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.35)

    # ── 上：權益曲線 ────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    if eq:
        ax1.plot(eq, label="權益曲線", linewidth=1.5, color="#2196F3")
    ax1.axhline(s.get("initial_balance", 10_000), color="gray", linestyle="--", linewidth=0.8)
    ax1.set_title("權益曲線", fontsize=13)
    ax1.set_ylabel("餘額 (USD)")
    ax1.set_xlabel("交易事件序號")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # ── 左下：R 倍數直方圖 ──────────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    if r_w:
        bins = 20
        ax2.hist(r_w, bins=bins, color="#78909C", edgecolor="white", linewidth=0.5)
        ax2.axvline(0, color="red",    linestyle="--", linewidth=1)
        ax2.axvline(s.get("r_mean", 0), color="gold", linestyle="-", linewidth=1.5,
                    label=f'平均 {s.get("r_mean", 0):.2f} R')
        ax2.set_title("R 倍數分佈", fontsize=11)
        ax2.set_xlabel("R 倍數")
        ax2.set_ylabel("交易次數")
        ax2.legend(fontsize=9)
        ax2.grid(True, alpha=0.3)

    # ── 右下：關鍵指標文字卡 ─────────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.axis("off")

    def _fmt(v, fmt=".2f"):
        return f"{v:{fmt}}" if v is not None else "N/A"

    lines = [
        ("── 回測結果 ──", ""),
        ("勝率",            f'{s.get("win_rate_pct", 0):.1f}%'),
        ("獲利因子",        _fmt(s.get("profit_factor"))),
        ("Sharpe",          _fmt(s.get("sharpe"), ".3f")),
        ("Sortino",         _fmt(s.get("sortino"), ".3f")),
        ("平均 R",          f'{s.get("r_mean", 0):.3f} R'),
        ("最大回撤",        f'{s.get("max_drawdown_pct", 0):.2f}%'),
        ("最大連敗",        f'{s.get("max_consec_losses", 0)} 筆'),
    ]
    y = 0.97
    for k, v in lines:
        if not k and not v:
            y -= 0.04
            continue
        if v == "":
            ax3.text(0.02, y, k, fontsize=9, fontweight="bold",
                     transform=ax3.transAxes, va="top")
        else:
            ax3.text(0.02, y, k,  fontsize=9, transform=ax3.transAxes, va="top")
            ax3.text(0.65, y, v,  fontsize=9, transform=ax3.transAxes, va="top",
                     ha="right", fontweight="bold")
        y -= 0.07

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.suptitle(f"回測報告  {datetime.now(TW_TZ).strftime('%Y/%m/%d %H:%M')}", fontsize=14)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    logger.info("圖表已輸出：%s", out_path)


def _log_stats(label: str, trader: PaperTrader, sigs: int) -> None:
    s        = trader.get_stats()
    fc       = s.get("full_closes", 0)
    w        = s.get("wins", 0)
    n_losses = s.get("losses", 0)
    pf       = s.get("profit_factor")
    sharpe   = s.get("sharpe")
    sortino  = s.get("sortino")
    logger.info("┌─ %s", label)
    logger.info("│  訊號觸發：%4d 個    已平倉：%d 筆  (勝 %d / 敗 %d)", sigs, fc, w, n_losses)
    logger.info("│  勝率：     %5.1f%%", s.get("win_rate_pct", 0))
    logger.info("│  總損益：   $%+12,.2f", s.get("total_pnl", 0))
    logger.info("│  最大回撤： %.2f%%", s.get("max_drawdown_pct", 0))
    logger.info("│  獲利因子： %s", f"{pf:.2f}" if pf else "N/A")
    logger.info("│  Sharpe：   %s", f"{sharpe:.3f}" if sharpe is not None else "N/A")
    logger.info("│  Sortino：  %s", f"{sortino:.3f}" if sortino is not None else "N/A")
    logger.info("│  平均 R：   %.3f R", s.get("r_mean", 0))
    logger.info("│  最大連敗： %d 筆", s.get("max_consec_losses", 0))
    logger.info("│  平均獲利： $%+10,.2f", s.get("avg_win", 0))
    logger.info("└  平均虧損： $%+10,.2f", s.get("avg_loss", 0))


def run_backtest(
    use_all:     bool = False,
    max_symbols: int  = MAX_SYMBOLS,
    show_detail: bool = False,
) -> dict:
    """
    執行回測並回傳結果 dict，同時在終端印出摘要。
    供 API 路由呼叫（在背景執行緒中運行）。
    """
    logger.info("=" * 64)
    logger.info("  策略回測")
    logger.info("=" * 64)

    # 1. 幣種清單
    logger.info("[1/4] 取得幣種清單...")
    all_syms = get_contracts()
    if not all_syms:
        logger.error("無法取得合約清單，回測中止")
        return {"error": "無法取得合約清單"}

    if use_all:
        symbols = all_syms
    else:
        priority = [s for s in ["BTCUSDT", "ETHUSDT"] if s in all_syms]
        others   = [s for s in all_syms if s not in priority]
        symbols  = (priority + others)[:max_symbols]
    logger.info("      共 %d 個幣種", len(symbols))

    # 2. BTC 4H
    logger.info("[2/4] 抓取 BTC 4H K棒...")
    has_cache = KLINES_CACHE_DIR.exists() and any(KLINES_CACHE_DIR.glob("BTCUSDT_4h.json"))
    btc_4h    = (load_cached("BTCUSDT", "4h") if has_cache else None) or get_klines("BTCUSDT", "4h", KLINES_4H)
    if not btc_4h or len(btc_4h) < WARMUP_BARS:
        logger.error("BTC 資料不足（需 %d 根，實際 %d 根）", WARMUP_BARS, len(btc_4h) if btc_4h else 0)
        return {"error": "BTC 資料不足"}
    btc_emas = ema_snapshot(btc_4h)
    if not btc_emas:
        logger.error("BTC EMA 計算失敗")
        return {"error": "BTC EMA 計算失敗"}

    n_bars = len(btc_4h)
    span   = n_bars - WARMUP_BARS
    logger.info("      %d 根 4h  |  %s → %s",
                n_bars, fmt_tw(btc_4h[WARMUP_BARS]["time"]), fmt_tw(btc_4h[-1]["time"]))
    logger.info("      有效模擬 bar：%d 根（約 %d 天）", span, span * 4 // 24)

    bear_bars = sum(
        1 for i in range(WARMUP_BARS, n_bars)
        if btc_emas["ema15"][i] is not None
        and btc_emas["ema60"][i] is not None
        and btc_emas["ema15"][i] < btc_emas["ema60"][i]
    )
    logger.info("      BTC 空頭環境：%d/%d 根（%.1f%%）", bear_bars, span, bear_bars / span * 100)

    # 3. 各幣種資料
    src = "本地快取" if has_cache else "Binance API"
    logger.info("[3/4] 載入各幣種 K棒（%s）...", src)

    sym_data: dict[str, dict] = {}
    for i, sym in enumerate(symbols, 1):
        c4h = (load_cached(sym, "4h") if has_cache else None) or get_klines(sym, "4h", KLINES_4H)
        c1h = (load_cached(sym, "1h") if has_cache else None) or get_klines(sym, "1h", KLINES_1H)
        if not has_cache:
            time.sleep(0.12)

        ok  = c4h and c1h and len(c4h) >= WARMUP_BARS and len(c1h) >= 60
        tag = f"4h:{len(c4h):>4d} 1h:{len(c1h):>4d}" if (c4h and c1h) else "資料不足"
        logger.debug("[%3d/%d] %-15s %s  %s", i, len(symbols), sym, "OK  " if ok else "跳過", tag)
        if ok:
            sym_data[sym] = {
                "c4h":       c4h,
                "c1h":       c1h,
                "c4h_times": [c["time"] for c in c4h],
                "c1h_times": [c["time"] for c in c1h],
            }

    logger.info("      成功載入 %d 個幣種", len(sym_data))

    # 4. 逐 4H Bar 模擬
    logger.info("[4/4] 逐 4h Bar 模擬...")

    trader = PaperTrader(INIT_BAL)
    sig    = 0

    for bar_idx in range(WARMUP_BARS, n_bars):
        bar_open_ms  = btc_4h[bar_idx]["time"]
        bar_close_ms = bar_open_ms + 4 * 3600 * 1000

        signals:     list[tuple] = []
        latest_bars: dict[str, dict] = {}

        for sym, d in sym_data.items():
            i4h = bisect.bisect_right(d["c4h_times"], bar_open_ms) - 1
            if i4h < WARMUP_BARS - 1:
                continue
            c4h_use = d["c4h"][max(0, i4h - 249): i4h + 1]
            latest_bars[sym] = c4h_use[-1]

            i1h_end = bisect.bisect_left(d["c1h_times"], bar_close_ms)
            if i1h_end < 60:
                continue
            c1h_use = d["c1h"][max(0, i1h_end - 100): i1h_end]
            if len(c1h_use) < 60:
                continue

            res = scan_symbol(sym, c4h_use, c1h_use)
            if res:
                sc = score_setup(res, bar_open_ms)
                if passes_threshold(sc):
                    signals.append((res, sc))

        trader.update_positions(latest_bars)

        for res, sc in sorted(signals, key=lambda x: x[1], reverse=True):
            if trader.open_position(res, sc):
                sig += 1

        if bar_idx % 50 == 0:
            pct = (bar_idx - WARMUP_BARS) / span * 100
            logger.debug("  %.1f%%  bar %d/%d  持倉:%d  累積訊號:%d",
                         pct, bar_idx, n_bars, len(trader.positions), sig)

    # 5. 結果報告
    s = trader.get_stats()

    logger.info("=" * 64)
    logger.info("  回測結果")
    logger.info("=" * 64)
    _log_stats("策略回測", trader, sig)
    logger.info("=" * 64)

    if show_detail:
        logger.info("【詳細交易明細】")
        for t in sorted(trader.trade_history, key=lambda x: x["open_ms"]):
            if not t["full_close"]:
                continue
            logger.info("  %s  %-15s %-5s %-20s  %-4s  PnL: $%+10.2f",
                        fmt_tw(t["open_ms"]), t["symbol"], t["direction"],
                        t["strategy"], t["reason"], t["pnl"])

    ts = datetime.now(TW_TZ).strftime("%Y%m%d_%H%M")
    chart_path = REPORTS_DIR / f"equity_{ts}.png"
    _save_equity_chart(s, chart_path)

    return {
        "result":         s,
        "signals":        sig,
        "symbols_tested": len(sym_data),
        "bars_simulated": span,
        "trades":         trader.trade_history,
        "chart_path":     str(chart_path),
    }


def main():
    from app.core.logging_config import setup_logging
    setup_logging()

    show_detail = "--detail" in sys.argv
    use_all     = "--all"    in sys.argv
    run_backtest(use_all=use_all, show_detail=show_detail)


if __name__ == "__main__":
    main()
