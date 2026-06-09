# Changelog

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
