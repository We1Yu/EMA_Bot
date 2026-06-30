# 安裝與啟動

## 步驟 1 — 安裝 Python

前往 [python.org/downloads](https://www.python.org/downloads/) 下載 **Python 3.11 以上版本**。

安裝時勾選 **「Add Python to PATH」**，否則後續指令需輸入完整路徑。

安裝完成後確認：

```
python --version
```

應顯示 `Python 3.11.x` 或更高版本。

---

## 步驟 2 — 下載專案

**方式 A：用 Git clone（推薦）**

安裝 [Git for Windows](https://git-scm.com/download/win)，然後執行：

```
git clone https://github.com/We1Yu/EMA_Bot.git
cd EMA_Bot
```

**方式 B：直接下載 ZIP**

GitHub 頁面右上角 → `Code` → `Download ZIP`，解壓縮到任意資料夾。

---

## 步驟 3 — 安裝依賴套件

```
pip install -r crypto_screener/requirements.txt
```

如果同時要使用 EMA Scanner：

```
pip install -r legacy/ema_scanner/requirements.txt
```

---

## 步驟 4 — 設定 Discord Webhook（選填）

不需要 Discord 通知可跳過此步驟。

1. 在 Discord 頻道設定中建立 Webhook，複製 Webhook URL
2. 開啟 `crypto_screener/config.py`，找到最後一行並貼上 URL：

```python
SCALP_DISCORD_WEBHOOK = "https://discord.com/api/webhooks/你的webhook網址"
```

留空字串則不發送通知。

---

## 步驟 5 — 啟動

**方式 A：雙擊 `start.bat`（最簡單）**

> 注意：`start.bat` 內的 Python 路徑預設為 `C:\Users\User\AppData\Local\Python\bin\python.exe`，如果你的 Python 安裝路徑不同，請用文字編輯器打開 `start.bat`，將第 2 行改為你的路徑，或直接改為：
> ```
> set PY=python
> ```

**方式 B：手動啟動（任何電腦都適用）**

開啟兩個終端機視窗，分別執行：

```
# 視窗 1 — 高頻機器人
cd crypto_screener
python main_scalp.py
```

```
# 視窗 2 — 網頁儀表板
cd crypto_screener
python web_app.py
```

---

## 步驟 6 — 開啟儀表板

瀏覽器輸入：

```
http://localhost:5000
```

看到儀表板載入即代表安裝成功。機器人會自動開始掃描並顯示訊號與持倉。

---

## EMA Scanner（獨立啟動，選填）

```
cd ema_scanner
python main.py
```

啟動後儀表板的「EMA Scanner」分頁也會同步顯示資料。

---

## 手機遠端觀看

**同一個 Wi-Fi**：查詢電腦的區網 IP（`ipconfig`），手機瀏覽器輸入 `http://192.168.x.x:5000`。

**不在同一個 Wi-Fi**：安裝 [Tailscale](https://tailscale.com/download)，電腦與手機登入同一帳號，用 Tailscale 提供的 IP（`100.x.x.x`）即可隨時連線。
