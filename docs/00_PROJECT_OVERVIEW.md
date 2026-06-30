# Crypto Quant Signal Platform — 專案總覽

## 一句話定位

整合多維度評分邏輯、歷史回測引擎、紙上帳戶管理的 Binance Futures 量化交易輔助平台。  
將散落的策略腳本重構成有清晰架構的後端服務，含完整 RESTful API 與 Docker 部署。

## 技術棚架

| 層級 | 技術 | 理由 |
|---|---|---|
| 後端框架 | FastAPI | async 原生支援、自動 OpenAPI 文件、Pydantic 驗證 |
| 資料儲存 | JSON / JSONL / CSV | 輕量無資料庫，降低部署複雜度 |
| 任務排程 | Python 內建 threading | 每 60 分鐘掃描 + 4H K 線收盤即時觸發 |
| 容器化 | Docker + docker-compose | 一鍵啟動，方便 Demo |
| 前端（規劃中）| React + TypeScript | Phase 3 開發中 |

## 核心模組

| 模組 | 路徑 | 說明 |
|---|---|---|
| 策略 | `backend/app/services/strategies/` | EMA_CONVERGENCE / EMA_SQUEEZE_BREAKOUT / STRUCTURE_BREAKOUT |
| 評分 | `backend/app/services/scoring/` | 0–10 分，達標門檻 7.5 |
| 回測 | `backend/app/services/backtest/` | 逐 4H Bar 模擬，含 TP1/TP2 出場結構 |
| 資料擷取 | `backend/app/services/data_ingestion/` | Binance Futures K 線下載（含本機快取） |
| 紙上帳戶 | `backend/app/services/paper_trader.py` | 每筆風險 2%，最多 4 倉 |

## 開發進度

- [x] Phase 1 — 核心邏輯重構：策略模組化、評分系統、回測引擎
- [x] Phase 2 — 後端 API 層：FastAPI + 帳戶 / 訊號 / 掃描 / 回測全端點
- [ ] Phase 3 — 前端儀表板（開發中）
- [ ] Phase 4 — 即時 WebSocket 模組
- [ ] Phase 5 — 生產環境部署

## 回測成果（v7，有 Regime Filter）

回測期間：2025/11/13 – 2026/06/16（215 天），30 個幣種

| 指標 | 數值 |
|---|---|
| 勝率 | 31.8% |
| 總損益 | +$1,898（+19.0%） |
| 獲利因子 | **1.08** |
| 最大回撤 | 9.08% |
