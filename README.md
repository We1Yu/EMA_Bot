# Trade Bot

BingX USDT-M 永續合約虛擬交易機器人，包含兩套獨立系統：

| 系統 | 週期 | 策略 | 掃描頻率 |
|------|------|------|----------|
| 高頻機器人 | 5 分鐘 | MA 群聚突破 / RSI 反彈 / EMA 交叉 / 量能爆發 | 每 60 秒 |
| EMA Scanner | 4 小時 | EMA 群收斂突破 / EMA30 回測反彈 | 每 60 分鐘 |

兩套系統共用同一個網頁儀表板，帳號與持倉完全獨立。

安裝與啟動說明請見 [INSTALL.md](INSTALL.md)。

---

## 目錄結構

```
Trade_Bot/
├── start.bat                    # 一鍵啟動高頻機器人 + 儀表板
├── crypto_screener/             # 高頻機器人
│   ├── main_scalp.py            # 主程式（掃描 + 持倉管理）
│   ├── web_app.py               # Flask 儀表板後端
│   ├── scanner.py               # 掃描邏輯（多策略）
│   ├── scoring.py               # 訊號評分系統（0–150 基礎分 + 加成）
│   ├── paper_account.py         # 虛擬帳號（持倉 / 停損停利 / 歷史）
│   ├── filters.py               # 進場過濾條件
│   ├── indicators.py            # 技術指標（RSI / ADX / BBW / ATR）
│   ├── bingx_source.py          # BingX REST API 封裝
│   ├── config.py                # 所有可調參數
│   ├── discord_alert.py         # Discord Webhook 通知
│   └── templates/index.html     # 前端儀表板 UI
└── ema_scanner/                 # EMA Scanner（獨立系統）
    ├── main.py                  # 主程式
    ├── scanner.py               # EMA_CONVERGENCE / EMA_PULLBACK 邏輯
    ├── scorer.py                # 訊號評分
    ├── paper_trader.py          # 虛擬帳號
    ├── indicators.py            # 技術指標
    ├── bingx.py                 # BingX API 封裝
    └── discord_bot.py           # Discord 通知
```

---

## 高頻機器人

### 運作流程

```
每 60 秒  ──▶  掃描 ~700 種 BingX 永續合約
                │
                ▼
            計算 5m K 線指標 → 評分 → 取高分訊號
                │
                ▼
            開啟虛擬倉位（每筆風險 1% 資金）
                │
每 12 秒  ──▶  抓取最新成交價 → 檢查停損 / 停利
```

同一幣種出場後 **5 分鐘** 冷卻，不重複進場。

### 四種進場策略

#### 1. MA_BREAKOUT — MA 群聚突破
- MA15 / MA30 / MA45 / MA60 緊密群聚（價差 < 1.5%）
- 價格放量向上突破（量能 ≥ 5 根均量 × 1.5）
- K 棒實體 ≥ 60%，RSI 45–75，ADX ≥ 20
- 週線站上 20 週均線（趨勢確認）

SHORT 版本為完全對稱的跌破邏輯。

#### 2. RSI_BOUNCE — RSI 超賣 / 超買反彈
- LONG：RSI ≤ 33 超賣反彈
- SHORT：RSI ≥ 67 超買回落

#### 3. EMA_CROSS — 快慢線交叉
- 快線 EMA9 / 慢線 EMA21
- LONG：EMA9 上穿 EMA21；SHORT：EMA9 下穿 EMA21

#### 4. VOL_SPIKE — 量能爆發
- 成交量 ≥ 均量 × 3.5
- 配合 K 棒方向判斷多空

### 出場規則（ATR 基準）

| 層次 | 觸發條件 | 動作 |
|------|----------|------|
| SL | 進場價 ± 1.5 × ATR | 全倉出場 |
| TP1 | 進場價 ± 2.0 × ATR | 出場 30%，停損移至進場價 |
| TP2 | 進場價 ± 3.0 × ATR | 出場 40%，停損移至 TP1 |
| TP3 | 進場價 ± 4.0 × ATR | 剩餘 30% 全部出場 |
| SHUTDOWN | 程式關閉（Ctrl+C） | 所有持倉以現價強制平倉 |

> 強制平倉的交易在儀表板以橘色 `SHUTDOWN ⚠️` badge 標註，在 Discord 報告以 🔴 圖示與 `⚠️ 強制平倉` 後綴區分。

### 訊號評分（0–150 基礎分 + 加成）

| 分類 | 項目 | 滿分 |
|------|------|------|
| 核心突破品質 | MA 群聚緊密度 | 25 |
| | 量能倍數 | 20 |
| | K 棒實體比 | 10 |
| 假突破過濾 | RSI 區間 | 15 |
| | BBW 布林帶壓縮 | 10 |
| | 收盤位置 | 10 |
| 趨勢確認 | MA200 位置 | 15 |
| | MA200 斜率 | 10 |
| | ADX 強度 | 10 |
| 市場背景 | 資金費率 | 10 |
| | 24H 動能 | 10 |
| | 週線趨勢 | 5 |
| 加成項 | 雙時間框架共振 | +8 |
| | Tier B 轉折 | +5 |
| | RSI 穿越 50 | +3 |
| | ADX 上升 | +3 |
| | 負資金費率（多單） | +2 |

**Tier A**：價格在 MA200 同側（趨勢延續）；**Tier B**：剛穿越 MA200（轉折訊號）。

### 虛擬帳號參數

| 參數 | 預設值 |
|------|--------|
| 初始本金 | $10,000 |
| 每筆風險 | 1% |
| 最大同時持倉 | 無硬性上限（資金耗盡自動停止） |

---

## EMA Scanner

### 兩種策略

**EMA_CONVERGENCE**（4H 主圖 + 1H 確認）
- EMA 帶寬收縮至近 50 根最低 25% 分位
- 連續 4 根以上持續收縮
- 放量突破，1H EMA15/30 同向交叉確認

**EMA_PULLBACK**（1H 主圖）
- 判斷 4H EMA200 大方向
- 等待 1H 價格回踩 EMA30（距離 < 1.2%）
- 反彈後實體 K 棒確認，RSI ≥ 40

### 出場規則

| 層次 | 動作 |
|------|------|
| SL | 全倉出場 |
| TP1 | 出場 50%，停損移至進場價 |
| TP2 | 剩餘 50% 全部出場 |

---

## 網頁儀表板

開啟 `http://localhost:5000`，每 **10 秒**自動刷新。

### 功能

- **啟動時間**：顯示機器人本次啟動的時間點
- **帳戶統計**：餘額、總損益、勝率、最大回撤
- **持倉中**：即時未實現損益、進 / 現價、停損停利進度
- **最新掃描訊號**：Top 20 高分訊號
- **成交紀錄**：可按「全部 / 獲利 / 虧損」篩選；強制平倉以橘色 `SHUTDOWN ⚠️` 標註

---

## 設定

所有參數集中在 `crypto_screener/config.py`：

```python
SCALP_SCAN_INTERVAL_SECS  = 60     # 掃描間隔（秒）
SCALP_CHECK_INTERVAL_SECS = 12     # 持倉檢查間隔（秒）
SCALP_COOLDOWN_SECS       = 300    # 同幣種冷卻時間（秒）
SCALP_PAPER_INITIAL_BALANCE = 10_000.0
SCALP_PAPER_RISK_PCT        = 0.01  # 每筆風險比例
SCALP_DASHBOARD_PORT        = 5000

# Discord Webhook（留空則不發送）
SCALP_DISCORD_WEBHOOK = ""
```

---

## 資料檔案

| 檔案 | 內容 |
|------|------|
| `paper_account_scalp.json` | 虛擬帳號即時狀態（持倉 / 餘額） |
| `scalp_state.json` | 最新掃描狀態（供儀表板讀取） |
| `trades_scalp.jsonl` | 每筆出場紀錄（JSONL，永久累積） |
| `trade_history_scalp.csv` | 完整成交紀錄（CSV，供分析用） |
| `equity_history_scalp.jsonl` | 資產曲線快照 |
| `signals_history_scalp.jsonl` | 所有掃描訊號歷史 |
