"""
Crypto Quant Signal Platform — FastAPI 進入點
啟動：uvicorn app.main:app --reload（從 backend/ 目錄執行）
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api import account, signals, scan, backtest
from app.core.logging_config import setup_logging

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield


app = FastAPI(
    title="Crypto Quant Signal Platform API",
    description="整合 EMA 收斂/回測/結構突破策略、5 維度評分、紙上帳戶的 Binance 量化交易輔助平台",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(account.router,  prefix="/api/account",  tags=["account"])
app.include_router(signals.router,  prefix="/api/signals",  tags=["signals"])
app.include_router(scan.router,     prefix="/api/scan",     tags=["scan"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"status": "ok", "message": "Crypto Quant Signal Platform API is running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
