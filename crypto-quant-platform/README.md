# Crypto Quant Signal Platform

一個整合多維度評分邏輯、歷史回測引擎、即時訊號儀表板的加密貨幣量化交易輔助平台。

> 本專案目前處於 **Phase 1（核心邏輯重構）** 開發階段，詳見 [docs/01_ROADMAP.md](docs/01_ROADMAP.md)。

## 專案文件

- [專案總覽與技術選型](docs/00_PROJECT_OVERVIEW.md)
- [開發路線圖](docs/01_ROADMAP.md)
- [資料庫 Schema](docs/02_DATABASE_SCHEMA.md)
- [目錄結構說明](docs/03_DIRECTORY_STRUCTURE.md)

## 技術棚架

**後端**：FastAPI · PostgreSQL · SQLAlchemy 2.0 (async) · WebSocket
**前端**：React · TypeScript · TailwindCSS · Recharts
**部署**：Docker · docker-compose

## 本地啟動（開發中，待 Phase 2 完善）

```bash
# 後端 + 資料庫
docker-compose up -d

# 確認後端運行
curl http://localhost:8000/health
```

API 文件啟動後可在 `http://localhost:8000/docs` 查看。

## 開發進度

- [x] 專案架構與資料庫 schema 規劃
- [ ] Phase 1：核心評分邏輯重構與回測引擎
- [ ] Phase 2：後端 API 層
- [ ] Phase 3：前端儀表板
- [ ] Phase 4：即時模組
- [ ] Phase 5：部署上線
