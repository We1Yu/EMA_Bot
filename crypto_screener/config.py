"""All configuration constants — zero magic numbers in logic files."""

# MA periods
MA_PERIODS = [15, 30, 45, 60, 200]

# Cluster / breakout
CLUSTER_THRESHOLD    = 0.008   # spread_pct < 0.8%
VOL_RATIO_MIN        = 1.5     # breakout volume must be 1.5x 5-bar avg
BODY_PCT_MIN         = 0.60    # candle body must be >= 60%

# RSI
RSI_MIN = 45
RSI_MAX = 75
RSI_PERIOD = 14

# RSI — short-side mirror (bearish momentum zone)
RSI_MIN_SHORT = 25
RSI_MAX_SHORT = 55

# ADX
ADX_MIN    = 25
ADX_PERIOD = 14

# Bollinger Band Width
BBW_PERIOD = 20
BBW_STD    = 2.0
BBW_STRONG = 0.60
BBW_MED    = 0.70
BBW_WEAK   = 0.80
BBW_MIN_WIDTH = 0.05   # hard filter: normalised BBW must be > 5% (市場夠波動才交易)

# 200 MA skip zone
EMA200_SKIP_PCT = 0.05  # within 5% of 200 MA => SKIP tier

# ATR exit (swing / intraday)
ATR_PERIOD          = 14
ATR_STOP_MULT       = 1.5
ATR_TARGET_MULTS    = [2.0, 3.0, 4.0]  # target1, target2, target3

# ATR exit — scalp 專用（5m 雜訊大，用更寬的止損避免假洗出）
# SL 2.0 ATR → T1 3.0 ATR → R:R 1.5，維持與 SCALP_MIN_RR 相同門檻
SCALP_ATR_STOP_MULT    = 2.0
SCALP_ATR_TARGET_MULTS = [3.0, 4.5, 6.0]

# Data fetch
CANDLES_MAIN   = 250
CANDLES_WEEKLY = 30

# Polling
INTRADAY_POLL_SECS = 900   # 15 minutes
COOLDOWN_SECS      = 4 * 60 * 60  # 4 hours dedup window

# Batch / rate-limit
BATCH_SIZE    = 20
BATCH_DELAY   = 0.05   # seconds between batches

# Virtual account
PAPER_INITIAL_BALANCE = 10_000.0
PAPER_RISK_PCT        = 0.02    # 2% per trade

# ── High-frequency "scalp" mode ──────────────────────────────
SCALP_INTERVAL            = "5m"        # candle interval used for scoring
SCALP_SCAN_INTERVAL_SECS  = 60          # full re-scan (look for new signals)
SCALP_CHECK_INTERVAL_SECS = 12          # open-position price check / exit
SCALP_COOLDOWN_SECS       = 5 * 60      # per-symbol dedupe window

# ── Extra scalp strategies ─────────────────────────────────────
RSI_BOUNCE_OVERSOLD    = 33    # RSI threshold for oversold bounce (LONG)
RSI_BOUNCE_OVERBOUGHT  = 67    # RSI threshold for overbought bounce (SHORT)
EMA_FAST_PERIOD        = 9     # fast EMA for crossover strategy
EMA_SLOW_PERIOD        = 21    # slow EMA for crossover strategy
VOL_SPIKE_RATIO        = 3.5   # minimum volume multiple for spike strategy
SCALP_PAPER_INITIAL_BALANCE = 1_000_000.0
SCALP_PAPER_RISK_PCT        = 0.01      # 1% per trade (tighter risk for HF)
SCALP_DASHBOARD_PORT        = 5000

# ── BTC trend filter ──────────────────────────────────────────
BTC_SYMBOL          = "BTC-USDT"
BTC_MA_PERIOD       = 60    # MA60 on 5m — determines BTC bias
BTC_ADX_PAUSE       = 50    # ADX > 50 → BTC 極端波動，暫停所有進場

# ── Scalp quality gates ────────────────────────────────────────
SCALP_MIN_SCORE       = 70     # minimum score to open a position
SCALP_MIN_RR          = 1.5    # minimum risk:reward ratio
SCALP_MAX_POSITIONS   = 8      # max concurrent open positions
SCALP_MAX_ENTRY_DRIFT = 0.008  # skip if live price drifted >0.8% from signal entry

# ── Time filter (台灣時間，允許開新倉的小時) ───────────────────────
# 允許：15:00-23:00 (倫敦+紐約盤) 和 00:00-04:00 (紐約尾盤)
# 封鎖：09:00-14:00 TWN = UTC 01-06，亞洲收盤後的低流動性死區
SCALP_ALLOWED_HOURS_TWN: set = set(range(15, 24)) | {0, 1, 2, 3}

# ── Symbol blocklist (長期虧損幣種) ────────────────────────────────
SCALP_SYMBOL_BLOCKLIST: set = {
    "BLUR-USDT",
    "WAVES-USDT",
    "IOST-USDT",
    "ASTR-USDT",
    "CRV-USDT",
    "SPX-USDT",
}

# ── Periodic performance report ───────────────────────────────
REPORT_INTERVAL_HOURS = 6   # 每 N 小時發一次 Discord 績效報告

# ── Discord ────────────────────────────────────────────────────
# 設定環境變數 SCALP_DISCORD_WEBHOOK 或在 .env 填入 Webhook URL，留空則不發送
import os as _os
SCALP_DISCORD_WEBHOOK: str = _os.environ.get("SCALP_DISCORD_WEBHOOK", "")
