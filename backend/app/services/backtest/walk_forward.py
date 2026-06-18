"""
Walk-Forward 樣本外測試
把資料切成連續的 IS（樣本內）/ OOS（樣本外）滑動窗口，
驗證 v7 策略在「沒見過的時段」是否維持相近表現。

使用方式（從 backend/ 目錄）：
  python -m app.services.backtest.walk_forward
  python -m app.services.backtest.walk_forward --all    # 全部幣種
"""

import bisect
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.services.data_ingestion.binance import get_contracts, get_klines
from app.services.data_ingestion.fetch_data import load as load_cached, KLINES_CACHE_DIR
from app.services.strategies.indicators import ema_snapshot, is_btc_black_swan
from app.services.strategies.scanner import scan_symbol
from app.services.scoring.scorer import score_setup, passes_threshold
from app.services.paper_trader import PaperTrader

logger = logging.getLogger(__name__)

TW_TZ = timezone(timedelta(hours=8))

# 資料長度：跟 fetch_data.py 的 TARGET_4H 對齊，確保快取夠長
KLINES_4H   = 1500   # ~250 天
KLINES_1H   = 4000   # ~167 天
WARMUP_BARS = 210    # BTC EMA 暖機（同 engine.py）
INIT_BAL    = 10_000.0
MAX_SYMBOLS = 30

# Walk-forward 窗口設定
IS_BARS  = 430   # 樣本內：~72 天（每個窗口）
OOS_BARS = 215   # 樣本外：~36 天（每個窗口，也是步進量）

REPORTS_DIR = Path(__file__).parent / "reports"


# ── 工具 ─────────────────────────────────────────────────────────────────────

def _fmt_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=TW_TZ).strftime("%Y/%m/%d")


def _stat_line(label: str, s: dict, sig: int) -> str:
    pf = s.get("profit_factor")
    sh = s.get("sharpe")
    return (
        f"  {label}  訊號={sig:2d}  勝率={s.get('win_rate_pct', 0):5.1f}%  "
        f"PF={f'{pf:.2f}' if pf else ' N/A'}  "
        f"Sharpe={f'{sh:.3f}' if sh is not None else '  N/A'}  "
        f"R均={s.get('r_mean', 0):+.2f}  "
        f"回撤={s.get('max_drawdown_pct', 0):.2f}%  "
        f"連敗={s.get('max_consec_losses', 0)}"
    )


# ── 核心模擬（單一窗口）────────────────────────────────────────────────────

def _simulate(
    btc_4h:    list[dict],
    btc_emas:  dict,
    sym_data:  dict[str, dict],
    start_bar: int,
    end_bar:   int,
) -> tuple[PaperTrader, int]:
    """在 [start_bar, end_bar) 範圍內模擬 v7 策略（有 Regime Filter）。"""
    trader    = PaperTrader(INIT_BAL)
    sig_count = 0

    for bar_idx in range(start_bar, end_bar):
        bar_open_ms  = btc_4h[bar_idx]["time"]
        bar_close_ms = bar_open_ms + 4 * 3600 * 1000

        e15 = btc_emas["ema15"][bar_idx]
        e60 = btc_emas["ema60"][bar_idx]
        regime     = (e15 > e60) if (e15 is not None and e60 is not None) else True
        black_swan = is_btc_black_swan(btc_4h[max(0, bar_idx - 2): bar_idx + 1])

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

            res = scan_symbol(sym, c4h_use, c1h_use, regime, black_swan)
            if res:
                sc = score_setup(res, bar_open_ms)
                if passes_threshold(sc):
                    signals.append((res, sc))

        trader.update_positions(latest_bars)

        for res, sc in sorted(signals, key=lambda x: x[1], reverse=True):
            if trader.open_position(res, sc):
                sig_count += 1

    return trader, sig_count


# ── 圖表輸出 ─────────────────────────────────────────────────────────────────

def _save_wf_chart(results: list[dict], out_path: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        from matplotlib import font_manager as fm
    except ImportError:
        logger.warning("matplotlib not installed, skipping chart")
        return

    # Windows CJK font fallback
    _cjk_candidates = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    _font = next((f for f in _cjk_candidates
                  if any(f.lower() in p.name.lower() for p in fm.fontManager.ttflist)), None)
    if _font:
        plt.rcParams["font.family"] = _font

    n   = len(results)
    fig = plt.figure(figsize=(15, 4 * n + 3))

    # n rows: IS (blue) + OOS (orange); bottom row = summary table
    gs = plt.GridSpec(n + 1, 2, figure=fig, hspace=0.55, wspace=0.3,
                      height_ratios=[4] * n + [2])

    for i, r in enumerate(results):
        w = r["window"]
        for col, (label, s, period, color) in enumerate([
            (f"W{w} IS  (In-Sample)",  r["is"],  r["is_period"],  "#2196F3"),
            (f"W{w} OOS (Out-of-Sample)", r["oos"], r["oos_period"], "#FF5722"),
        ]):
            ax  = fig.add_subplot(gs[i, col])
            eq  = s.get("equity_curve", [])
            if eq:
                ax.plot(eq, color=color, linewidth=1.5)
                ax.fill_between(range(len(eq)), INIT_BAL, eq,
                                where=[v >= INIT_BAL for v in eq],
                                alpha=0.12, color="#4CAF50")
                ax.fill_between(range(len(eq)), INIT_BAL, eq,
                                where=[v < INIT_BAL for v in eq],
                                alpha=0.12, color="#F44336")
            ax.axhline(INIT_BAL, color="gray", linestyle="--", linewidth=0.8)

            pf  = s.get("profit_factor")
            sh  = s.get("sharpe")
            ann = (
                f"WinRate {s.get('win_rate_pct', 0):.1f}%  "
                f"PF {f'{pf:.2f}' if pf else 'N/A'}\n"
                f"Sharpe {f'{sh:.3f}' if sh is not None else 'N/A'}  "
                f"DD {s.get('max_drawdown_pct', 0):.1f}%"
            )
            ax.text(0.97, 0.05, ann, transform=ax.transAxes,
                    fontsize=7.5, ha="right", va="bottom",
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.7))

            ax.set_title(f"{label}\n{period}", fontsize=9)
            ax.set_ylabel("Balance (USD)", fontsize=8)
            ax.set_xlabel("Trade event #", fontsize=8)
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(
                lambda v, _: f"${v:,.0f}"))
            ax.grid(True, alpha=0.25)
            ax.tick_params(labelsize=7)

    # Summary table
    ax_t = fig.add_subplot(gs[n, :])
    ax_t.axis("off")

    cols = ["Window", "Period", "WinRate", "PF", "Sharpe", "R-mean", "MaxDD", "MaxLoss"]
    rows = []
    for r in results:
        for kind, s, period in [("IS",  r["is"],  r["is_period"]),
                                 ("OOS", r["oos"], r["oos_period"])]:
            pf = s.get("profit_factor")
            sh = s.get("sharpe")
            rows.append([
                f"W{r['window']} {kind}",
                period,
                f"{s.get('win_rate_pct', 0):.1f}%",
                f"{pf:.2f}" if pf else "N/A",
                f"{sh:.3f}" if sh is not None else "N/A",
                f"{s.get('r_mean', 0):+.3f}",
                f"{s.get('max_drawdown_pct', 0):.2f}%",
                str(s.get("max_consec_losses", 0)),
            ])

    tbl = ax_t.table(cellText=rows, colLabels=cols, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    tbl.scale(1, 1.5)

    for row_idx, row in enumerate(rows, 1):
        if "OOS" in row[0]:
            for col_idx in range(len(cols)):
                tbl[row_idx, col_idx].set_facecolor("#FFF3E0")

    fig.suptitle(
        f"Walk-Forward Out-of-Sample Test  "
        f"IS={IS_BARS} bars (~{IS_BARS*4//24}d) / OOS={OOS_BARS} bars (~{OOS_BARS*4//24}d)",
        fontsize=13,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    logger.info("Chart saved: %s", out_path)


# ── 主函式 ───────────────────────────────────────────────────────────────────

def run_walk_forward(
    use_all:     bool = False,
    max_symbols: int  = MAX_SYMBOLS,
    is_bars:     int  = IS_BARS,
    oos_bars:    int  = OOS_BARS,
) -> dict:
    """
    執行 walk-forward 測試，回傳結果 dict。
    供 API 路由呼叫（在背景執行緒中運行）。
    """
    logger.info("=" * 68)
    logger.info("  Walk-Forward  IS=%d bars(~%d天) / OOS=%d bars(~%d天)",
                is_bars, is_bars * 4 // 24, oos_bars, oos_bars * 4 // 24)
    logger.info("=" * 68)

    # 1. 幣種清單
    logger.info("[1/4] 取得幣種清單...")
    all_syms = get_contracts()
    if not all_syms:
        return {"error": "無法取得合約清單"}
    if use_all:
        symbols = all_syms
    else:
        priority = [s for s in ["BTCUSDT", "ETHUSDT"] if s in all_syms]
        others   = [s for s in all_syms if s not in priority]
        symbols  = (priority + others)[:max_symbols]
    logger.info("      共 %d 個幣種", len(symbols))

    # 2. BTC 4H
    logger.info("[2/4] 抓取 BTC 4H K棒（最多 %d 根）...", KLINES_4H)
    has_cache = KLINES_CACHE_DIR.exists() and any(KLINES_CACHE_DIR.glob("BTCUSDT_4h.json"))
    btc_4h    = (load_cached("BTCUSDT", "4h") if has_cache else None) \
                or get_klines("BTCUSDT", "4h", KLINES_4H)
    if not btc_4h:
        return {"error": "無法取得 BTC 資料"}

    min_needed = WARMUP_BARS + is_bars + oos_bars
    if len(btc_4h) < min_needed:
        logger.error("BTC 資料不足：需 %d 根，實際 %d 根", min_needed, len(btc_4h))
        return {"error": f"BTC 資料不足（需 {min_needed} 根，實際 {len(btc_4h)} 根）"}

    btc_emas = ema_snapshot(btc_4h)
    n_bars   = len(btc_4h)
    logger.info("      %d 根  %s → %s",
                n_bars, _fmt_date(btc_4h[0]["time"]), _fmt_date(btc_4h[-1]["time"]))

    # 3. 各幣種 K 棒
    src = "本地快取" if has_cache else "Binance API"
    logger.info("[3/4] 載入各幣種 K棒（%s）...", src)
    sym_data: dict[str, dict] = {}
    for i, sym in enumerate(symbols, 1):
        c4h = (load_cached(sym, "4h") if has_cache else None) or get_klines(sym, "4h", KLINES_4H)
        c1h = (load_cached(sym, "1h") if has_cache else None) or get_klines(sym, "1h", KLINES_1H)
        if not has_cache:
            time.sleep(0.12)
        if c4h and c1h and len(c4h) >= WARMUP_BARS and len(c1h) >= 60:
            sym_data[sym] = {
                "c4h":       c4h,
                "c1h":       c1h,
                "c4h_times": [c["time"] for c in c4h],
                "c1h_times": [c["time"] for c in c1h],
            }
    logger.info("      成功載入 %d 個幣種", len(sym_data))

    # 4. 生成 IS/OOS 窗口（步進 = oos_bars，IS 往前推 is_bars）
    windows: list[tuple[int, int, int, int]] = []
    oos_start = WARMUP_BARS + is_bars
    while oos_start + oos_bars <= n_bars:
        windows.append((oos_start - is_bars, oos_start,
                        oos_start,           oos_start + oos_bars))
        oos_start += oos_bars

    if not windows:
        return {"error": "資料量不足以建立任何 walk-forward 窗口"}

    logger.info("[4/4] 執行 %d 個 IS/OOS 窗口...", len(windows))
    results: list[dict] = []

    for w_idx, (is_s, is_e, oos_s, oos_e) in enumerate(windows, 1):
        is_period  = f"{_fmt_date(btc_4h[is_s]['time'])} → {_fmt_date(btc_4h[is_e-1]['time'])}"
        oos_period = f"{_fmt_date(btc_4h[oos_s]['time'])} → {_fmt_date(btc_4h[oos_e-1]['time'])}"

        logger.info("─" * 62)
        logger.info("窗口 W%d   IS: %s  OOS: %s", w_idx, is_period, oos_period)

        trader_is,  sig_is  = _simulate(btc_4h, btc_emas, sym_data, is_s, is_e)
        trader_oos, sig_oos = _simulate(btc_4h, btc_emas, sym_data, oos_s, oos_e)

        s_is  = trader_is.get_stats()
        s_oos = trader_oos.get_stats()

        logger.info(_stat_line("IS ", s_is,  sig_is))
        logger.info(_stat_line("OOS", s_oos, sig_oos))

        results.append({
            "window":     w_idx,
            "is_period":  is_period,
            "oos_period": oos_period,
            "is":         s_is,
            "oos":        s_oos,
            "sig_is":     sig_is,
            "sig_oos":    sig_oos,
        })

    # 5. OOS 彙總
    oos_closes = sum(r["oos"].get("full_closes", 0) for r in results)
    oos_wins   = sum(r["oos"].get("wins",        0) for r in results)
    oos_pnl    = sum(r["oos"].get("total_pnl",   0) for r in results)

    logger.info("=" * 68)
    logger.info("  OOS 彙總（%d 個窗口合計）", len(results))
    logger.info("  總完整平倉：%d 筆    合計損益：%s",
                oos_closes, f"${oos_pnl:+,.2f}")
    logger.info("  OOS 加權勝率：%.1f%%",
                oos_wins / oos_closes * 100 if oos_closes else 0)
    logger.info("─" * 62)
    for r in results:
        pf  = r["oos"].get("profit_factor")
        sh  = r["oos"].get("sharpe")
        pnl = r["oos"].get("total_pnl", 0)
        logger.info("  W%d OOS %s  勝率=%.1f%%  PF=%s  Sharpe=%s  損益=%s",
                    r["window"], r["oos_period"],
                    r["oos"].get("win_rate_pct", 0),
                    f"{pf:.2f}" if pf else "N/A",
                    f"{sh:.3f}" if sh is not None else "N/A",
                    f"${pnl:+,.2f}")
    logger.info("=" * 68)

    # 6. 圖表
    ts         = datetime.now(TW_TZ).strftime("%Y%m%d_%H%M")
    chart_path = REPORTS_DIR / f"walk_forward_{ts}.png"
    _save_wf_chart(results, chart_path)

    return {
        "windows":     results,
        "oos_summary": {
            "total_closes":  oos_closes,
            "total_wins":    oos_wins,
            "win_rate_pct":  round(oos_wins / oos_closes * 100, 1) if oos_closes else 0,
            "total_pnl":     round(oos_pnl, 2),
        },
        "chart_path": str(chart_path),
    }


def main():
    from app.core.logging_config import setup_logging
    setup_logging()

    use_all = "--all" in sys.argv
    run_walk_forward(use_all=use_all)


if __name__ == "__main__":
    main()
