"""All configuration constants — zero magic numbers in logic files."""

# MA periods
MA_PERIODS = [15, 30, 45, 60, 200]

# Cluster / breakout
CLUSTER_THRESHOLD    = 0.015   # spread_pct < 1.5%
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
ADX_MIN    = 20
ADX_PERIOD = 14

# Bollinger Band Width
BBW_PERIOD = 20
BBW_STD    = 2.0
BBW_STRONG = 0.60
BBW_MED    = 0.70
BBW_WEAK   = 0.80

# 200 MA skip zone
EMA200_SKIP_PCT = 0.05  # within 5% of 200 MA => SKIP tier

# ATR exit
ATR_PERIOD          = 14
ATR_STOP_MULT       = 1.5
ATR_TARGET_MULTS    = [2.0, 3.0, 4.0]  # target1, target2, target3

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
SCALP_SCAN_INTERVAL_SECS  = 90          # full re-scan (look for new signals)
SCALP_CHECK_INTERVAL_SECS = 12          # open-position price check / exit
SCALP_COOLDOWN_SECS       = 15 * 60     # per-symbol dedupe window
SCALP_PAPER_INITIAL_BALANCE = 10_000.0
SCALP_PAPER_RISK_PCT        = 0.01      # 1% per trade (tighter risk for HF)
SCALP_DASHBOARD_PORT        = 5000
