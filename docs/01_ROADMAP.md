# 開發路線圖（週次任務拆解）

預設每週投入時間彈性（業餘練習專案常見：每週 5-10 小時），以下用「週」為單位但不綁死日曆時間，做完再進下一週即可。共 5 個 Phase，建議 10-14 週可以完成到可展示版本。

---

## Phase 1：核心邏輯重構與回測引擎（第 1-3 週）

**目標**：把現有腳本邏輯整理成乾淨、可測試的 Python 模組，建立回測框架。

- **第 1 週**：盤點現有腳本（MA cluster screener v1-v3、EMA convergence bot、coil scanner、5 維度評分系統），抽出共用邏輯，設計 `scoring/` 模組的介面（輸入 K 線資料，輸出 0-100 分數 + 子維度明細）
- **第 2 週**：實作歷史資料抓取模組（Binance REST API 抓歷史 K 線，存成 parquet 或寫進資料庫），實作基礎回測引擎骨架（給定策略函式 + 歷史資料，跑出進出場紀錄）
- **第 3 週**：把 EMA 收斂、MA coil breakout、Wyckoff 多時間框架邏輯接到回測引擎，計算勝率、最大回撤、Sharpe ratio、平均持倉時間，寫單元測試（pytest）覆蓋評分邏輯跟回測核心計算

**產出檢查點**：可以在終端機跑 `python -m backtest.run --strategy ema_convergence --symbol BTCUSDT --start 2024-01-01` 印出績效報告

---

## Phase 2：後端 API 層（第 4-6 週）

**目標**：把核心邏輯包裝成 API，建立資料庫。

- **第 4 週**：設計資料庫 schema（見 `02_DATABASE_SCHEMA.md`），用 Alembic 建立 migration，把 Phase 1 的回測結果寫進資料庫
- **第 5 週**：建立 FastAPI 專案骨架，實作 `/api/backtests`、`/api/signals`、`/api/strategies` 等端點（CRUD + 查詢篩選），加上 Pydantic schema 驗證
- **第 6 週**：加上 API 測試（pytest + httpx TestClient），補上 OpenAPI 文件的描述跟範例，Dockerize 後端（Dockerfile + docker-compose 含 PostgreSQL）

**產出檢查點**：`docker-compose up` 後可以打開 `/docs` 看到完整 Swagger UI，並能透過 API 查詢歷史回測結果

---

## Phase 3：前端儀表板（第 7-9 週）

**目標**：視覺化呈現回測績效與歷史訊號。

- **第 7 週**：React + TypeScript + Tailwind 專案初始化，建立基礎頁面路由（Dashboard、回測詳情、策略比較），串接 Phase 2 的 API
- **第 8 週**：實作圖表元件——權益曲線（Recharts）、K 線圖標註進出場點（TradingView Lightweight Charts）、評分雷達圖（5 維度視覺化）
- **第 9 週**：實作策略比較頁（多個策略並排比較勝率/回撤）、響應式設計調整、loading/error 狀態處理

**產出檢查點**：完整可操作的儀表板，能選擇策略、查看回測績效、瀏覽歷史訊號列表

---

## Phase 4：即時模組（第 10-12 週）

**目標**：加上即時資料與即時訊號推送。

- **第 10 週**：實作即時資料訂閱模組（Binance WebSocket），建立背景任務排程（APScheduler）定期跑評分邏輯
- **第 11 週**：FastAPI WebSocket 端點，即時推送新訊號到前端；前端建立 WebSocket hook，即時更新訊號列表
- **第 12 週**：加上通知機制（選用：Discord webhook，沿用你之前做過的邏輯）、即時訊號的去重邏輯、Regime filter 與 funding rate 偵測整合進即時模組

**產出檢查點**：開著儀表板時，新訊號出現會即時跳出，不需要重新整理頁面

---

## Phase 5：打磨與部署（第 13-14 週）

**目標**：讓專案達到「可以放進履歷/接案提案」的完成度。

- **第 13 週**：撰寫完整 README（架構圖、技術選型理由、本地啟動教學、screenshot），錄製 1-2 分鐘 Demo 影片或 GIF
- **第 14 週**：部署上線（後端用 Railway/Render，前端用 Vercel/Netlify，資料庫用 Supabase 或 Railway PostgreSQL），設定環境變數與 CI（GitHub Actions 跑測試）

**產出檢查點**：有一個公開可訪問的 URL，README 完整，GitHub repo 的 commit history 清楚反映開發過程

---

## 彈性建議

如果時間有限，**Phase 1-3 是最小可行版本（MVP）**——回測引擎 + API + 前端儀表板，已經足夠當作求職作品集使用。Phase 4 的即時模組是加分項，能展示更進階的系統設計能力，但不是必要條件。建議先衝到 Phase 3 有東西可以展示，再視時間決定要不要往下做。
