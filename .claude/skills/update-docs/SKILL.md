---
name: update-docs
description: 自動根據最新 git commit 更新 CHANGELOG.md 和 README.md
---

# update-docs skill

## 觸發時機

用戶輸入 `/update-docs` 時執行。也可傳入版本號：`/update-docs 1.5.0`

## 執行步驟

### 1. 蒐集資訊

執行以下指令取得所需資料：

```bash
# 最新 CHANGELOG 版本號與日期
head -20 CHANGELOG.md

# 上次版本 tag 之後的所有 commit（若無 tag，取最近 20 筆）
git log --oneline -20

# 目前實際檔案結構（排除 git/pycache/data 檔）
find . -not -path "./.git/*" -not -path "./__pycache__/*" \
       -not -path "*/__pycache__/*" -not -path "./.claude/*" \
       -not -name "*.jsonl" -not -name "*.json" -not -name "*.csv" \
       -not -name "*.xlsx" | sort

# 目前日期（台灣時間）
date +%Y-%m-%d
```

### 2. 決定版本號

- 若用戶有傳入版本號（例如 `/update-docs 1.5.0`）直接使用
- 否則根據 commit 內容自動判斷：
  - `feat:` / 新增功能 → minor bump（1.3.x → 1.4.0）
  - `fix:` / `refactor:` / 小修正 → patch bump（1.3.0 → 1.3.1）
  - breaking change → major bump（1.x.x → 2.0.0）

### 3. 更新 CHANGELOG.md

在現有最新版本**上方**插入新版本區塊，格式如下：

```markdown
## [X.Y.Z] - YYYY-MM-DD

### 新增
- ...

### 修正
- ...

### 調整
- ...

### 移除
- ...
```

規則：
- 只列**有內容**的小節，沒有就省略
- 以 commit message 為主要素材，但要翻譯成繁體中文、寫成人讀得懂的句子
- `feat:` commit → 新增；`fix:` → 修正；`refactor:` / `chore:` → 調整；`delete` / `remove` → 移除
- 若 commit message 已是中文直接使用，只整理格式

### 4. 更新 README.md

只更新**會因程式碼變動而過時**的部分：

1. **目錄結構** — 對照實際檔案結構，更新 ```` ```  ```` code block
2. **系統說明表格**（若策略或週期有變）
3. **功能描述段落**（若有新增或移除的功能）

**不要動**的部分：安裝說明、使用說明、環境變數設定等說明性文字（除非 commit 明確涉及這些）。

### 5. 輸出與確認

- 直接修改檔案（用 Edit 工具）
- 修改完後印出摘要：新版本號、CHANGELOG 新增了哪些條目、README 改了哪些部分
- **不要自動 commit**，讓用戶決定

## 注意事項

- 日期用台灣時間（UTC+8）
- 文字用**繁體中文**
- CHANGELOG 格式與現有風格保持一致（參考 CHANGELOG.md 現有條目）
- 若 git log 裡有 `Co-Authored-By: Claude` 的 commit，說明是 AI 輔助的改動，摘要時不需特別提及
