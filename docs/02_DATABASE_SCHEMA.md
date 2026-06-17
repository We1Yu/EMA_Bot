# 資料庫 Schema 草稿

設計目標：能同時容納「歷史回測結果」與「即時訊號紀錄」，並支援未來擴充新策略時不需要大改 schema。

## ER 概念說明

```
strategies (策略定義)
    │
    ├──< backtests (回測批次) ──< backtest_trades (回測中的單筆交易)
    │
    └──< signals (即時/歷史產生的訊號) ──< signal_scores (5維度評分明細)

symbols (交易對基本資料)
    │
    ├──< backtests
    └──< signals

candles (K線資料快取，選用，視資料量決定是否落地)
```

## SQL 定義（PostgreSQL）

```sql
-- 交易對基本資料
CREATE TABLE symbols (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,      -- e.g. 'BTCUSDT'
    exchange VARCHAR(20) NOT NULL DEFAULT 'binance',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 策略定義（每個策略版本一筆，方便追蹤策略演進）
CREATE TABLE strategies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,               -- e.g. 'ema_convergence'
    version VARCHAR(20) NOT NULL,            -- e.g. 'v3'
    description TEXT,
    parameters JSONB,                        -- 策略參數快照，e.g. {"ema_fast": 15, "ema_slow": 30}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, version)
);

-- 回測批次（每次跑一個策略 x 一個交易對 x 一段時間區間，產生一筆）
CREATE TABLE backtests (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER REFERENCES strategies(id) NOT NULL,
    symbol_id INTEGER REFERENCES symbols(id) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,          -- e.g. '4h', '1h'
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,
    win_rate NUMERIC(5,2),                   -- 0.00 - 100.00
    total_trades INTEGER,
    max_drawdown NUMERIC(6,2),
    sharpe_ratio NUMERIC(6,3),
    total_return_pct NUMERIC(8,2),
    status VARCHAR(20) DEFAULT 'completed',  -- 'running', 'completed', 'failed'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 回測中的每一筆模擬交易
CREATE TABLE backtest_trades (
    id SERIAL PRIMARY KEY,
    backtest_id INTEGER REFERENCES backtests(id) ON DELETE CASCADE NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ,
    entry_price NUMERIC(18,8) NOT NULL,
    exit_price NUMERIC(18,8),
    direction VARCHAR(5) NOT NULL,           -- 'long' / 'short'
    pnl_pct NUMERIC(8,4),
    exit_reason VARCHAR(30),                 -- 'tp_hit', 'sl_hit', 'manual', 'timeout'
    score_at_entry NUMERIC(5,2)              -- 進場當下的綜合評分
);

-- 訊號（即時或歷史產生的訊號，跟回測分開存，因為訊號可能沒有對應的完整交易）
CREATE TABLE signals (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER REFERENCES strategies(id) NOT NULL,
    symbol_id INTEGER REFERENCES symbols(id) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    direction VARCHAR(5) NOT NULL,
    composite_score NUMERIC(5,2) NOT NULL,   -- 綜合評分 0-100
    triggered_at TIMESTAMPTZ NOT NULL,
    price_at_signal NUMERIC(18,8) NOT NULL,
    suggested_tp NUMERIC(18,8),
    suggested_sl NUMERIC(18,8),
    is_live BOOLEAN DEFAULT TRUE,            -- TRUE=即時產生, FALSE=歷史回放
    outcome VARCHAR(20),                     -- 'win', 'loss', 'pending', 'expired'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5 維度評分明細（跟 signal 一對一）
CREATE TABLE signal_scores (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id) ON DELETE CASCADE NOT NULL,
    trend_score NUMERIC(5,2),
    momentum_score NUMERIC(5,2),
    structure_score NUMERIC(5,2),
    volume_score NUMERIC(5,2),
    risk_score NUMERIC(5,2),
    regime VARCHAR(20),                      -- e.g. 'trending', 'ranging', 'volatile'
    funding_rate NUMERIC(8,5)
);

-- 索引建議
CREATE INDEX idx_backtests_strategy_symbol ON backtests(strategy_id, symbol_id);
CREATE INDEX idx_signals_triggered_at ON signals(triggered_at DESC);
CREATE INDEX idx_signals_symbol_live ON signals(symbol_id, is_live);
CREATE INDEX idx_backtest_trades_backtest_id ON backtest_trades(backtest_id);
```

## 設計理由（面試時可以講的點）

- **策略版本化**（`strategies.version`）：你的策略會持續迭代（v1→v2→v3），用版本欄位而非覆寫舊紀錄，能讓回測結果跟「當時的策略版本」永久對應，避免「策略改了但歷史回測結果對不起來」的問題。
- **`parameters` 用 JSONB**：不同策略的參數結構差異很大（EMA 策略需要 fast/slow 週期，Wyckoff 可能需要其他參數），用 JSONB 避免每種策略都要開新表或加一堆 nullable 欄位。
- **signals 跟 backtest_trades 分表**：即時訊號不一定會成交或追蹤到結束（可能訊號出現後使用者沒有真的下單），跟回測的「一定有完整進出場」資料性質不同，分開儲存邏輯更乾淨。
- **`is_live` 欄位**：方便同一套表結構同時支援「歷史回放訊號」跟「即時產生訊號」，未來要做「即時訊號 vs 回測預期」的對照分析時不需要 join 兩張不同的表。

## 之後可能的擴充方向

- 如果要做使用者系統（多人使用、各自的策略參數），需要加 `users` 表，並在 `strategies`、`signals` 加 `user_id` 外鍵
- 如果資料量大到需要做歷史K線分析，建議 `candles` 表改用 TimescaleDB 的 hypertable，或乾脆用 parquet 檔案存歷史資料，資料庫只存「衍生結果」（評分、訊號、回測），避免 PostgreSQL 塞入大量時序資料
