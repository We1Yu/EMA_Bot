# Trade Bot

加密貨幣量化交易平台，含虛擬交易機器人與全端 FastAPI 後端。

| 系統 | 交易所 | 週期 | 策略 | 掃描頻率 |
|------|--------|------|------|----------|
| EMA Scanner（`ema_scanner/`）| BingX | 4H / 1H | EMA 收斂突破 / EMA30 回測反彈 / 結構突破回測 | 每 60 分鐘 |
| Crypto Quant Platform（`backend/`）| Binance Futures | 4H / 1H | 同上（策略 v7）| 每 60 分鐘 |

---

## 目錄結構

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
│   │       ├── backtest/            # engine.py（Regime Filter 對照）
│   │       ├── data_ingestion/      # Binance Futures K 線下載
│   │       └── paper_trader.py
│   ├── scheduler.py                 # 主排程迴圈
│   ├── Dockerfile
│   └── data/                        # 執行期資料（gitignore）
├── ema_scanner/                     # 原版（BingX，歷史參考，不再主動維護）
│   ├── main.py
│   ├── web_app.py                   # Flask 儀表板（port 5001）
│   ├── scanner.py / scorer.py / indicators.py
│   ├── paper_trader.py / backtest_regime.py
│   └── templates/index.html
├── crypto-quant-platform/           # 文件與設定（程式碼已移至根目錄）
│   └── docs/
└── docker-compose.yml
```

---

## Crypto Quant Platform

整合多維度評分邏輯、歷史回測引擎與紙上帳戶管理的 Binance Futures 量化交易輔助平台。

### 技術棧

| 層次 | 技術 |
|------|------|
| 後端 | FastAPI · Uvicorn |
| 資料 | JSON / JSONL / CSV（檔案式，無需資料庫） |
| 部署 | Docker · docker-compose |
| 前端 | 待開發（Phase 3） |

### 本地啟動

```bash
# 方式一：直接啟動（開發用）
cd backend
pip install fastapi uvicorn requests openpyxl
uvicorn app.main:app --reload --port 8000

# 方式二：Docker
docker-compose up -d
```

API 文件：`http://localhost:8000/docs`  
健康檢查：`http://localhost:8000/health`

### API 端點

**帳戶 `/api/account`**

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/account/` | 帳戶統計 + 持倉（含即時現價）+ 最近 100 筆交易 |
| GET | `/api/account/equity` | 完整資產曲線快照（EQUITY_JSONL） |
| GET | `/api/account/records` | 全部逐筆平倉紀錄（最新優先） |
| POST | `/api/account/reset` | 重置紙上帳戶（清倉清紀錄） |

**訊號 `/api/signals`**

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/signals/` | 最近訊號（`limit`、`strategy`、`direction` 可篩選） |
| GET | `/api/signals/history` | 完整歷史訊號（最多 2000 筆，可篩選） |
| GET | `/api/signals/stats` | 各策略 / 方向觸發次數 + 平均評分 |

**掃描 `/api/scan`**

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/scan/` | 觸發全市場掃描（背景執行，含 BTC Regime 過濾） |
| GET | `/api/scan/status` | 查詢掃描任務狀態 |
| GET | `/api/scan/btc-regime` | 查詢目前 BTC 4H Regime 狀態（EMA15 vs EMA60） |

**回測 `/api/backtest`**

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/backtest/` | 觸發回測（`use_all`、`max_symbols` 參數） |
| GET | `/api/backtest/` | 取得上次回測結果 |
| GET | `/api/backtest/status` | 查詢回測任務狀態 |

### 排程器

```bash
cd backend
python scheduler.py
```

- 每 **60 分鐘**掃描一次全市場
- 在 UTC 00 / 04 / 08 / 12 / 16 / 20（4H K 線收盤）額外觸發
- 掃描結束後自動更新持倉、寫入 EQUITY_JSONL
- 程式關閉時自動匯出 Excel 交易報告

### 開發進度

- [x] 專案架構規劃
- [x] 核心策略邏輯（EMA_CONVERGENCE / EMA_PULLBACK / STRUCTURE_BREAKOUT）
- [x] 回測引擎（Regime Filter 對照）
- [x] Binance Futures K 線下載器（含本機快取）
- [x] FastAPI 後端 API（帳戶 / 訊號 / 掃描 / 回測全路由補完）
- [x] 容器化部署（Docker + docker-compose）
- [ ] 前端儀表板（Phase 3）
- [ ] 即時 WebSocket 模組（Phase 4）
- [ ] 生產環境部署（Phase 5）

---

## EMA Scanner

### 掃描排程

- 每 **60 分鐘** 執行一次全量掃描
- 在 4H K 線收盤時刻（UTC 00/04/08/12/16/20）額外立即觸發
- 同一幣種 **4 小時** 內不重複推播

### BTC Regime 濾網

當 BTC 4H EMA15 < EMA60（空頭環境）時，**封鎖所有山寨幣多單**；BTC / ETH 主流幣不受此限制。

### 三種策略

**EMA_CONVERGENCE**（4H 主圖 + 1H 確認）

| 條件 | 說明 |
|------|------|
| EMA 帶寬分位 | 收縮至近 50 根最低 35% 分位以下 |
| 連續收縮根數 | ≥ 3 根 |
| 4H 突破量能 | 主流幣 ≥ 1.3×；山寨幣 ≥ 1.5×（前 20 根均量） |
| 4H RSI | < 75（排除超買追高） |
| EMA200 大方向 | 多單：站上 EMA200；空單：站下 EMA200 |
| 1H 收盤位置 | 在 EMA60 正確側 |
| 1H EMA15/30 穿越 | 近 3 根內完成同向穿越 |
| 1H K棒實體比 | ≥ 45% |

停損：多單 = 收斂區域最低點 − 1.0 ATR；空單 = 最高點 + 1.0 ATR

**EMA_PULLBACK**（1H 主圖）

| 條件 | 說明 |
|------|------|
| 4H EMA200 大方向 | 多頭 / 空頭 |
| 4H EMA60 方向 | 上升做多 / 下降做空 |
| 4H RSI 動能 | 多單：RSI 46–76；空單：RSI 24–54 |
| ADX | > 20（確認趨勢，排除震盪盤） |
| 1H EMA 排列 | 多單：EMA15 > EMA30；空單：EMA15 < EMA30 |
| 1H 收盤位置 | 在 EMA60 正確側 |
| 前根觸碰 EMA30 | 主流幣距離 ≤ 0.7%；山寨幣距離 ≤ 1.2% |
| 當根反彈確認 | 多單：陽線；空單：陰線 |
| 量能 | ≥ 20 根均量 × 1.8 |
| 1H RSI（多單）| ≥ 48（確認動能未死；空單免檢） |

停損：多單 = min(前根低點, EMA30) − 1.0 ATR；空單 = max(前根高點, EMA30) + 1.0 ATR

**STRUCTURE_BREAKOUT**（1H 結構突破回測）

| 條件 | 說明 |
|------|------|
| 4H EMA200 大方向 | 多頭 / 空頭 |
| 4H RSI 動能 | 多單：RSI 46–76；空單：RSI 24–54 |
| 4H ADX | > 20 |
| 結構突破 | 1H 突破近期歷史高低點 |
| 確認根數 | ≥ 2 根 1H K 線收盤確認突破 |
| 回測進場 | 價格回測結構位附近（0.8% 內） |

停損：突破前結構高低點反側 ± 1.0 ATR

### 出場規則

| 層次 | 觸發條件 | 動作 |
|------|----------|------|
| SL | 觸及停損 | 全倉出場 |
| TP1 | entry ± 1.5 × (entry − SL) | 出場 **25%**，停損移至進場價（保本） |
| TP2 | entry ± 2.5 × (entry − SL) | 剩餘 **75%** 全部出場 |

### 評分系統（0–10 分）

達標門檻：**7.5 分**（低於此分不推播、不開倉）

**EMA_CONVERGENCE 評分：**

| 項目 | 條件 | 得分 |
|------|------|------|
| EMA 帶寬 | < 1.0% | +2.0 |
| | 1.0–1.5% | +1.0 |
| | 1.5–2.0% | +0.5 |
| 連續收縮根數 | ≥ 5 根 | +2.0 |
| | ≥ 3 根 | +1.0 |
| 量能倍數 | ≥ 2.0× | +2.0 |
| | ≥ 1.5× | +1.0 |
| 1H K棒實體比 | ≥ 70% | +1.0 |
| | ≥ 60% | +0.5 |
| EMA200 大方向通過 | — | +1.0 |
| 1H EMA 穿越確認 | — | +1.0 |
| 歐美盤加成（TWN 15–22 時）| — | +1.0 |

**EMA_PULLBACK 評分：**

| 項目 | 條件 | 得分 |
|------|------|------|
| 形態有效基礎分 | — | +3.0 |
| 量能倍數 | ≥ 2.0× | +2.0 |
| | ≥ 1.5× | +1.5 |
| | ≥ 1.2× | +0.5 |
| K棒實體比 | ≥ 75% | +2.0 |
| | ≥ 65% | +1.5 |
| | ≥ 55% | +0.5 |
| EMA200 大方向通過 | — | +1.0 |
| 歐美盤加成（TWN 15–22 時）| — | +1.0 |

**STRUCTURE_BREAKOUT 評分：**

| 項目 | 條件 | 得分 |
|------|------|------|
| 結構突破基礎分 | — | +4.0 |
| 量能倍數 | ≥ 2.5× | +2.5 |
| | ≥ 2.0× | +2.0 |
| | ≥ 1.5× | +1.0 |
| K棒實體比 | ≥ 75% | +2.0 |
| | ≥ 65% | +1.5 |
| | ≥ 55% | +0.5 |
| 歐美盤加成（TWN 15–22 時）| — | +1.0 |

### 虛擬帳號參數

| 參數 | 預設值 |
|------|--------|
| 初始本金 | $10,000 |
| 每筆風險 | 2% |
| 最大同時持倉數 | 4 |
| 同向持倉上限 | 2 |

### 回測成果（v7，有 Regime Filter）

回測期間：2025/11/13 – 2026/06/16（215 天），30 個幣種，4H×1500 根

| 指標 | 數值 |
|------|------|
| 訊號觸發 | 44 個 |
| 勝率 | 31.8%（勝 14 / 敗 30） |
| 總損益 | +$1,898（+19.0%） |
| **獲利因子** | **1.08** |
| 最大回撤 | 9.08% |
| 平均獲利 | +$380 |
| 平均虧損 | −$164 |

> 版本演進：v4 首次 PF>0（+0.68）→ v6 回撤降至 8.2%（PF 0.72）→ **v7 出場結構優化（TP1 取 25%/TP2 取 75%），PF 首次突破 1.0**

---

## 網頁儀表板（EMA Scanner）

開啟 `http://localhost:5001`，每 **10 秒**自動刷新。

### 功能

- **帳戶統計**：餘額、總損益、勝率、最大回撤
- **持倉中**：即時未實現損益、進 / 現價、停損停利進度
- **最新掃描訊號**：Top 20 高分訊號
- **成交紀錄**：可按「全部 / 獲利 / 虧損」篩選

---

## 設定

### 環境變數

機密資訊透過環境變數傳入，不寫入原始碼。在 `ema_scanner/` 目錄建立 `.env` 檔案（`.gitignore` 已排除）：

**`ema_scanner/.env`**
```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

> Windows 使用者：透過控制台 → 系統 → 進階系統設定 → 環境變數手動設定，或透過啟動腳本 `set VAR=value` 注入。

---

## 資料檔案

資料目錄：`backend/data/`（Crypto Quant Platform）和 `ema_scanner/`（EMA Scanner）

| 檔案 | 系統 | 內容 |
|------|------|------|
| `backend/data/paper_account.json` | CQP | 紙上帳戶即時狀態（持倉 / 餘額） |
| `backend/data/state.json` | CQP | 最新掃描去重狀態 |
| `backend/data/trade_history.csv` | CQP | 完整成交紀錄（CSV） |
| `backend/data/equity_history.jsonl` | CQP | 資產曲線快照（每次掃描後寫入） |
| `backend/data/signals_history.jsonl` | CQP | 所有達標訊號完整歷史 |
| `backend/data/signals_log.json` | CQP | 最新 300 筆訊號快取（API 用） |
| `backend/data/trade_records/` | CQP | 逐筆平倉紀錄 + 關機 Excel 報告 |
| `ema_scanner/paper_account.json` | EMA | 紙上帳戶即時狀態 |
| `ema_scanner/state.json` | EMA | 最新掃描狀態（供儀表板讀取） |
| `ema_scanner/trade_records/` | EMA | 每次 session 結束後自動歸檔的 Excel |
