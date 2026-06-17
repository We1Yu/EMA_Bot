# Changelog

## [1.7.1] - 2026-06-17

### 調整
- **清理 repo 結構**：移除過時的 `crypto-quant-platform/` 子目錄（規劃文件已由根目錄 `backend/` 與主 `README.md` 取代）
- **`.gitignore` 補完**：新增 `backend/data/`（執行期 JSON/JSONL 資料）、`backend/trade_records/`、`.claude/hooks/`、`.claude/worktrees/`，防止個人環境設定與執行期檔案意外上傳
- **文件更新**：
  - `docs/00_PROJECT_OVERVIEW.md` — 改寫為反映實際實作（檔案式儲存、真實回測數據），移除未實作的 PostgreSQL / SQLAlchemy 規劃
  - `docs/03_DIRECTORY_STRUCTURE.md` — 對應現行目錄結構重新整理
  - `README.md` — 移除目錄樹中的 `crypto-quant-platform/`，前端技術棧更新為「React + TypeScript（Phase 3，開發中）」

### 提交紀錄
- `5882259` chore: clean up repo structure and update docs

---

## [1.7.0] - 2026-06-17

### 調整
- **出場結構優化（v7）：TP1/TP2 分倉比例 50/50 → 25/75**
  - `ema_scanner/paper_trader.py` + `backend/app/services/paper_trader.py` 新增 `TP1_FRACTION = 0.25`
  - TP1 觸碰時平倉 25%（原 50%），停損移至成本價；TP2 觸碰時平倉剩餘 75%（原 50%）
  - 回測 PF：0.72 → **1.08**（首次突破 1.0）；總損益：+$1,645 → +$1,898；最大回撤：8.20% → 9.08%
- **TP 倍數統一為常數**
  - `ema_scanner/scanner.py` + `backend/app/services/strategies/scanner.py` 新增 `TP1_MULT = 1.5`、`TP2_MULT = 2.5`
  - 三個策略（EMA_CONVERGENCE / EMA_PULLBACK / STRUCTURE_BREAKOUT）共六處 hardcode 改為引用常數
- **前端說明面板**：`ema_scanner/templates/index.html` 三頁新增可展開 Help Panel（總覽/掃描/歷史），說明各欄位意義與策略說明
- `backend/app/services/data_ingestion/binance.py` 新增 `COINGECKO_URL` 常數備用

### 提交紀錄
- `9efbcbe` feat: sync TP1_MULT/TP2_MULT constants to backend scanner
- `c09b197` feat: sync 25/75 exit split to backend paper_trader
- `cd4c3e0` feat: improve profit factor to 1.08 via 25/75 split exit structure
- `a9e6731` feat: add help panels to frontend and init crypto-quant-platform

---

## [1.6.0] - 2026-06-17

### 新增
- **後端 API 全路由補完**
  - `GET /api/scan/btc-regime`：即時查詢 BTC 4H EMA15 vs EMA60 Regime 狀態
  - `GET /api/signals/history`：從 `signals_history.jsonl` 讀取完整歷史訊號（最多 2000 筆）
  - `GET /api/signals/stats`：各策略 / 方向觸發次數統計 + 平均評分
  - `GET /api/account/equity`：從 `equity_history.jsonl` 讀取完整資產曲線快照
  - `POST /api/account/reset`：重置紙上帳戶（清倉清紀錄，保留初始資金設定）
  - `GET /api/backtest/`：取得上次回測結果，不重新執行
- **`GET /api/signals/`** 新增 `strategy` / `direction` query 參數過濾

### 修正
- **`scan.py` Regime Filter 失效**：`scan_symbol()` 少傳 `btc_regime_bull`，API 掃描永遠不套 BTC Regime 過濾；現在掃描前先查 BTC 4H EMA，正確傳入
- **`scan.py` 訊號未寫入 JSONL**：API 掃描只寫 `signals_log.json`，未同步寫 `signals_history.jsonl`；現已補上
- **`GET /api/backtest/status`** 新增 `has_result` 欄位，供前端判斷是否有可用結果

### 調整
- `config.py` 修正過時的路徑註解（`crypto-quant-platform/backend/` → `Trade_Bot/backend/`）

### 提交紀錄
- `dc69882` docs: update README to reflect current project state
- `34be012` feat: complete backend API layer
- `36bd031` docs: merge crypto-quant-platform CHANGELOG and README into root docs

---

## [1.5.0] - 2026-06-17

### 新增
- **`crypto-quant-platform/` 全端平台**：整合 `ema_scanner/` 策略邏輯，以 FastAPI 重構後端，交易所從 BingX 改為 Binance Futures（`fapi.binance.com`）
  - `backend/app/` — FastAPI 應用（API 路由：帳戶、訊號、掃描、回測）
  - `backend/app/services/` — 策略掃描、技術指標、評分系統、回測引擎、紙上帳號
  - `backend/app/services/data_ingestion/` — Binance Futures K 線下載器（含本機快取）
  - `backend/scheduler.py` — 主排程迴圈（60 分鐘 + 4H K 線收盤觸發）
  - `backend/Dockerfile` + `docker-compose.yml` — 容器化部署設定
  - `docs/` — 專案概覽、路線圖、資料庫結構、目錄說明文件

### 提交紀錄
- `da1e901` refactor: move crypto-quant-platform contents to project root
- `42317f3` docs: update CHANGELOG and README for v1.5.0
- `853072a` feat: add crypto-quant-platform full-stack backend
- `74db363` docs: auto-update CHANGELOG (2026-06-17)

## [1.4.0] - 2026-06-16

### 新增
- **回測框架**：`backtest_regime.py` 全量虛擬交易模擬，支援 Regime Filter 開啟 / 關閉對照；`fetch_data.py` BingX 分頁 K 線資料下載器（帶本機快取）
- **`analyze_trades.py`**：交易事件分析工具，自動區分「一般行情」（勝率 41.2%）與「事件驅動」（多方向同時止損）虧損，找出集中虧損根因
- **`STRUCTURE_BREAKOUT` 策略**：偵測歷史結構高低點突破後回測確認，要求 ≥ 2 根收盤確認突破（避免假突破），`scorer.py` 新增 `_score_structure_breakout()` 基礎分 4.0
- **`indicators.py` 新增 `calc_adx()`**：ADX 趨勢強度指標，用於濾除震盪盤

### 調整
- **策略勝率優化**（v2 → v6）
  - `EMA_PULLBACK` 新增 ADX > 20 趨勢強度濾網，封鎖橫盤進場
  - `EMA_PULLBACK` / `STRUCTURE_BREAKOUT` 新增 4H RSI 動能濾網（多單 RSI 46–76、空單 24–54），過濾超買追高 / 動能已死信號
  - 新增 4H EMA15 > EMA30 短期對齊濾網（多單）
  - 勝率：26.5% → 32.3%；最大回撤：20.67% → 15.95%
- **同向持倉上限 `max_same_dir=2`**：同一方向最多同時持有 2 倉，針對事件驅動分析發現 34% 虧損來自 6 個時間點同向 12 倉齊止損，實施後最大回撤進一步從 15.95% 降至 8.20%
- **最大持倉數 `max_positions=4`**：防止相關性過高的同時開倉
- **評分門檻 `MIN_SCORE`**：6.0 → 7.5，提升訊號品質
- **`bingx.py` 新增 `get_klines_paginated()`**：支援 `endTime` 參數分頁拉取長期歷史 K 線
- **`.gitignore`** 新增排除 `ema_scanner/data/`（K 線快取）與 `ema_scanner/trade_records/`（平倉紀錄）

### 移除
- **`start.bat`**：啟動腳本已無使用需求，完整移除

### 提交紀錄
- `f47b764` docs: update CHANGELOG and README for v1.4.0
- `182453c` chore: update .gitignore + remove start.bat
- `9dbba72` feat: strategy v5→v6 + same-direction position limit
- `608c57b` feat: add backtest framework + strategy improvements (v2→v4)

## [1.3.1] - 2026-06-16

### 移除
- **高頻 Scalp Bot 全面移除**：刪除 `crypto_screener/` 整個資料夾（主程式、儀表板、評分系統、掃描器、虛擬帳號、Discord 通知、所有設定與資料檔）
- **EMA Scanner 移除 OI/多空比指標**：刪除 `get_oi_history`、`get_long_short_ratio` API 及 `OI_LS_SIGNAL` 策略（評分、Discord 通知、儀表板顯示）
- **`start.bat`** 移除已停用的 Scalp Bot 啟動指令

## [1.3.0] - 2026-06-12

### 資安修正
- **移除硬編碼 Discord Webhook URL**
  - `crypto_screener/config.py`：`SCALP_DISCORD_WEBHOOK` 改由環境變數 `SCALP_DISCORD_WEBHOOK` 讀取，預設空字串
  - `ema_scanner/discord_bot.py`：`WEBHOOK_URL` 改由環境變數 `DISCORD_WEBHOOK_URL` 讀取，移除硬編碼 fallback URL
- **新增 `ema_scanner/.env`** 範本檔，提供環境變數設定參考（已加入 `.gitignore`，不會上傳）
- **新增 `crypto_screener/trades_scalp.jsonl` 至 `.gitignore`**，避免個人交易紀錄上傳至 GitHub
- **新增 git pre-push hook**（`.git/hooks/pre-push`）：每次 push 前自動掃描是否有硬編碼 API key、Webhook URL、token 等機密資料，發現即阻擋 push

## [1.2.0] - 2026-06-11

### 新增
- **高頻 Scalp Bot 新增 3 種交易策略**
  - `RSI_BOUNCE`：RSI ≤ 33 超賣反彈做多 / ≥ 67 超買反彈做空，止損 1.2×ATR，目標 1.8/2.8/3.8×ATR
  - `EMA_CROSS`：EMA(9) 穿越 EMA(21) + RSI 35–65 + 量能 1.2× 確認，止損 1.5×ATR，目標 2.0/3.0/4.0×ATR
  - `VOL_SPIKE`：成交量 ≥ 3.5 倍均量 + 實體 > 55% 方向性爆量，止損 1.0×ATR，目標 1.5/2.5/3.5×ATR
  - `indicators.py` 新增 `calc_ema()` 函數
- **交易記錄強化**
  - 新增 `trades_scalp.jsonl` append-only 永久交易日誌（不覆寫）
  - 每筆交易記錄新增 `strategy`（觸發策略）與 `entry_logic`（進場邏輯描述）欄位
  - `paper_account.py` `Position` 新增 `strategy`、`entry_logic`、`realized_pnl` 欄位
- **統計數據強化**
  - `get_stats()` 新增 `sl_count`、`tp1_count`、`tp2_count`、`tp3_count` 各類出場次數
  - `get_stats()` 新增 `by_strategy` 各策略獨立損益統計（交易數 / 損益 / 勝敗）
  - CSV 欄位新增 `strategy` 欄
- **儀表板強化**（`index.html` / `web_app.py`）
  - 持倉卡片新增「策略」與「進場邏輯」顯示列
  - 成交紀錄表新增「策略」與「進場邏輯」欄位
- **BingX API 速率限制保護**（`bingx_source.py` / `ema_scanner/bingx.py`）
  - 偵測 error code 100410（頻率封鎖），解析解封時間戳，封鎖期間跳過所有請求
  - 避免封鎖期間持續重試造成滿版錯誤輸出
- `start.bat` 移除 EMA Scanner 自動啟動（改為手動啟動），修正中文 echo 編碼問題

### 修正
- **勝率計算 Bug**
  - 舊邏輯：TP1 後止損移到進場價觸發（pnl=0）被算成「敗」
  - 新邏輯：**TP1 命中即算勝**，不論後續如何收場（含套保保本出場）
  - 舊 history 記錄無 `tp1_hit` 欄位時 fallback 為 `pnl > 0`，避免全算敗
  - 勝率分母改為 `wins + losses`，break-even 不計入
- **total_trade_pnl**：full_close 記錄新增整筆交易總損益（含 TP1/TP2 分倉獲利）
- **首次啟動 risk_pct 錯誤**：`main_scalp.py` 先呼叫 `load()` 再判斷檔案存在，導致首次建立帳戶用 2% 而非 1%，已修正初始化順序
- **`_try_ma_breakout` dead params**：移除未使用的 `session`、`source`、`check_dual_tf` 參數
- **cooldown dict 永久累積**：每輪掃描前清除已逾期（> 5 分鐘）的冷卻記錄

### 調整
- `SCALP_SCAN_INTERVAL_SECS`：90 秒 → **60 秒**
- `SCALP_COOLDOWN_SECS`：15 分鐘 → **5 分鐘**

## [1.1.0] - 2026-06-10

### 新增
- 網頁儀表板策略說明頁新增全部 8 個策略的觸發條件與參數說明
- 新增「如何修改參數」完整參考表（scanner.py / scorer.py / paper_trader.py / main.py）
- 新增 `start.bat` 一鍵雙擊同時啟動掃描機器人與網頁儀表板

### 修正
- `paper_trader.py`：無交易紀錄時 `print_report()` 存取不存在的 key 導致 `KeyError` crash
- `paper_trader.py` / `backtest.py`：`profit_factor` 為 `None`（全勝紀錄）時格式化導致 `TypeError` crash
- `backtest.py`：`print_backtest_report()` / `print_multi_summary()` 同上問題一併修正
- `scanner.py`：`detect_breakout_4h()` 未檢查前一根 K 棒 EMA 值是否為 `None`，歷史資料不足時導致 `TypeError` crash
- `start.bat`：修正 Python 執行檔路徑，確保正確啟動

## [1.0.0] - 2026-06-09

### 新增
- 自動掃描 BingX 所有 USDT 永續合約（694 個交易對）
- EMA 收斂偵測（EMA 15/30/45/60 帶寬 < 2%，連續壓縮 ≥ 3 根 4H K線）
- 4H 突破偵測（突破 EMA60 + 帶寬擴張 + 量能 ≥ 1.5× 均量）
- 1H 確認機制（方向吻合 + 實體比例 > 60% + EMA15 穿越 EMA30）
- EMA200 趨勢過濾器（距離 < 1% 自動跳過）
- 0–10 分評分系統，門檻 6.0 分才推播
- 自動計算進場價、止損、Target 1（1.5R）、Target 2（2.5R）
- Discord Webhook 通知（多單綠色 / 空單紅色 / 邊緣黃色）
- 無訊號時發送掃描摘要訊息
- 每 60 分鐘定時掃描 + 4H K線收盤時額外觸發
- 同一幣種 4 小時內不重複推播（state.json 去重）
- Windows 服務支援（透過 NSSM，開機自動啟動）

### 技術細節
- 純手刻 EMA、ATR、帶寬計算，不依賴 pandas 或 TA-Lib
- 唯一外部依賴：`requests`
- BingX 公開 API，無需 API 金鑰
- 所有時間顯示為台灣時間（UTC+8）
- 程式碼註解使用繁體中文

### 已知修正
- BingX K線 API symbol 格式需保留連字號（`BTC-USDT`）
- BingX interval 參數需小寫（`4h` / `1h`）
- K線欄位為完整名稱（`open/high/low/close/volume`）
- EMA200 計算需 250 根 4H K線（非規格書所述 100 根）
- 暫停合約（error code 109415）靜默略過，不印錯誤日誌
