# Changelog

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
