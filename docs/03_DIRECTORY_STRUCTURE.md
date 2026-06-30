# 專案目錄結構說明

```
Trade_Bot/
├── backend/                         # Crypto Quant Platform 後端（主動維護）
│   ├── app/
│   │   ├── main.py                  # FastAPI 進入點
│   │   ├── api/
│   │   │   ├── account.py           # 帳戶 / 持倉 / 資金曲線 / 重置
│   │   │   ├── signals.py           # 訊號歷史 / 統計 / 篩選
│   │   │   ├── scan.py              # 即時掃描觸發 / BTC Regime 狀態
│   │   │   └── backtest.py          # 回測觸發 / 結果查詢
│   │   ├── core/config.py           # 路徑常數統一管理
│   │   └── services/
│   │       ├── strategies/          # scanner.py + indicators.py
│   │       ├── scoring/             # scorer.py（門檻 7.5）
│   │       ├── backtest/            # engine.py（逐 4H Bar 模擬）
│   │       ├── data_ingestion/      # Binance Futures K 線下載
│   │       └── paper_trader.py
│   ├── scheduler.py                 # 主排程迴圈（每 60 分鐘）
│   ├── Dockerfile
│   ├── requirements.txt
│   └── data/                        # 執行期資料（gitignore）
│       ├── paper_account.json
│       ├── signals_history.jsonl
│       ├── signals_log.json
│       ├── equity_history.jsonl
│       ├── trade_history.csv
│       └── trade_records/
│
├── legacy/
│   └── ema_scanner/                 # 原版（BingX，歷史封存，不再主動維護）
│       ├── main.py
│       ├── web_app.py               # Flask 儀表板（port 5001）
│       ├── scanner.py / scorer.py / indicators.py
│       ├── paper_trader.py / backtest_regime.py
│       └── templates/index.html
│
├── docs/                            # 規劃與架構文件
│   ├── 00_PROJECT_OVERVIEW.md
│   ├── 01_ROADMAP.md
│   ├── 02_DATABASE_SCHEMA.md
│   └── 03_DIRECTORY_STRUCTURE.md   # 本檔案
│
├── docker-compose.yml               # 後端一鍵啟動
├── README.md                        # 主文件
├── CHANGELOG.md                     # 版本歷程
└── INSTALL.md                       # 安裝說明
```

## 分層原則

**後端三層架構**：API 層（routes）→ Service 層（商業邏輯）→ 資料層（JSON/JSONL/CSV）。  
評分演算法與回測邏輯封裝在 `services/` 中，完全不依賴 FastAPI 框架，可獨立呼叫或寫批次腳本。

**資料儲存**：採檔案式儲存（JSON / JSONL / CSV），無需資料庫，降低部署複雜度。  
執行期資料全數放在 `backend/data/` 並加入 `.gitignore`。
