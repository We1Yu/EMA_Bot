# 專案目錄結構說明

```
crypto-quant-platform/
├── docs/                          # 規劃與架構文件（給自己跟面試官/客戶看）
│   ├── 00_PROJECT_OVERVIEW.md     # 專案總覽、技術選型理由
│   ├── 01_ROADMAP.md              # 週次任務拆解
│   ├── 02_DATABASE_SCHEMA.md      # 資料庫 schema 草稿
│   └── 03_DIRECTORY_STRUCTURE.md  # 本檔案
│
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI 進入點
│   │   ├── api/                   # API 路由層（只負責 request/response，不寫商業邏輯）
│   │   │   ├── backtests.py
│   │   │   ├── signals.py
│   │   │   └── strategies.py
│   │   ├── core/                  # 設定、資料庫連線、共用工具
│   │   │   ├── config.py
│   │   │   └── database.py
│   │   ├── models/                # SQLAlchemy ORM models（對應資料庫表）
│   │   │   ├── strategy.py
│   │   │   ├── signal.py
│   │   │   └── backtest.py
│   │   ├── schemas/                # Pydantic schemas（API 的輸入輸出格式驗證）
│   │   │   ├── strategy.py
│   │   │   ├── signal.py
│   │   │   └── backtest.py
│   │   └── services/               # 商業邏輯層（核心，從你現有腳本重構而來）
│   │       ├── scoring/            # 5維度評分系統
│   │       ├── strategies/         # EMA收斂、MA coil breakout、Wyckoff分析
│   │       ├── backtest/           # 回測引擎、績效計算
│   │       └── data_ingestion/     # 歷史/即時資料抓取（Binance API）
│   ├── tests/                      # pytest 測試
│   ├── alembic/                    # 資料庫 migration（Phase 2 建立）
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── components/             # 可重用 UI 元件（圖表、評分卡、訊號列表項）
│   │   ├── pages/                  # 頁面層（Dashboard、回測詳情、策略比較）
│   │   ├── hooks/                  # 自訂 React hooks（如 useWebSocket、useBacktest）
│   │   ├── services/               # API 呼叫封裝（axios 或 fetch wrapper）
│   │   └── types/                  # TypeScript 型別定義（對應後端 Pydantic schemas）
│   ├── package.json
│   └── .env.example
│
├── scripts/                        # 輔助腳本（資料匯入、批次回測執行等）
├── docker-compose.yml              # 一鍵啟動後端+前端+資料庫
└── README.md                       # 專案入口文件（面試官/客戶第一眼看到的）
```

## 分層原則（面試常被問到的「為什麼這樣設計」）

**後端三層架構**：API 層（routes）→ Service 層（商業邏輯）→ Model 層（資料庫存取）。好處是商業邏輯（你的評分演算法、回測邏輯）完全不依賴 FastAPI，未來如果要換框架，或者要寫獨立的批次腳本呼叫同一套評分邏輯，都不需要改動核心程式碼，只需要呼叫 `services/` 裡的函式。

**前端依職責切資料夾**而不是依頁面切，因為圖表元件、評分卡這類 UI 元件很可能在多個頁面被重複使用（Dashboard 跟策略比較頁都需要顯示評分雷達圖），依職責切可以避免重複程式碼。
