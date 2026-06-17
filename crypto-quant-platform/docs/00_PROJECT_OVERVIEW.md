# Crypto Quant Signal Platform — 專案總覽

## 一句話定位

一個整合多維度評分邏輯、歷史回測引擎、即時訊號儀表板的加密貨幣量化交易輔助平台。將過去散落的策略腳本（MA cluster breakout、EMA convergence、Wyckoff 分析、異常偵測）重構成一個有清晰架構、可被求職與接案雙重展示的全端產品。

## 目標讀者

- **面試官**：看到後端 API 設計、資料庫 schema、非同步處理、測試覆蓋率、前後端分離架構
- **潛在客戶**：看到一個能實際運作、有視覺化介面、可客製化策略參數的工具

## 技術棚架

| 層級 | 技術 | 理由 |
|---|---|---|
| 後端框架 | FastAPI | async 原生支援、自動 OpenAPI 文件、Pydantic 驗證 |
| 資料庫 | PostgreSQL | 業界主流，適合展示正式環境資料庫設計能力 |
| ORM | SQLAlchemy 2.0 (async) | 業界標準，搭配 Alembic 做 migration |
| 任務排程 | APScheduler 或 Celery + Redis | 定期抓資料、跑回測批次任務 |
| 即時通訊 | WebSocket（FastAPI 內建） | 即時推送訊號到前端，比 polling 有效率 |
| 前端框架 | React + TypeScript | 業界全端職缺最常見組合 |
| 前端樣式 | TailwindCSS | 開發速度快，履歷上也是常見技能 |
| 圖表 | TradingView Lightweight Charts / Recharts | K 線用 Lightweight Charts，一般統計圖用 Recharts |
| 容器化 | Docker + docker-compose | 展示你懂部署，方便面試官或客戶直接跑起來 |
| 測試 | pytest（後端）、Vitest（前端） | 測試覆蓋率是面試常被問的點 |

## 核心模組對應

你現有的策略邏輯會被重新組織成以下服務模組（對應 `backend/app/services/`）：

- `scoring/`：5 維度評分系統（trend、momentum、structure、volume、risk）
- `strategies/`：EMA 收斂突破、MA coil breakout、Wyckoff 多時間框架分析
- `backtest/`：回測引擎、勝率計算、最大回撤、Sharpe ratio
- `data_ingestion/`：歷史 K 線抓取（Binance REST API）、即時資料訂閱（WebSocket）

## 開發階段（對應週次規劃見 01_ROADMAP.md）

1. **Phase 1 — 核心邏輯重構與回測引擎**：把現有評分/策略腳本模組化，建立回測框架
2. **Phase 2 — 後端 API 層**：包裝成 RESTful API，建立資料庫 schema 與 migration
3. **Phase 3 — 前端儀表板**：串接 API，視覺化回測結果與歷史訊號
4. **Phase 4 — 即時模組**：WebSocket 即時資料、即時訊號推送、前端即時更新
5. **Phase 5 — 打磨與部署**：Docker 化、README、Demo 影片、部署上線（Railway / Render / 自架 VPS）

## 給求職 vs 接案的展示差異

- **求職作品集**：強調架構決策、測試、API 文件、commit history 的整潔度，README 要寫清楚「為什麼這樣設計」
- **接案展示**：強調可客製化（策略參數可調）、視覺化儀表板的易用性、Demo 影片或線上可互動版本
