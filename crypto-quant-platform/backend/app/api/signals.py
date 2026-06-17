"""訊號歷史 API"""

import json

from fastapi import APIRouter

from app.core.config import SIGNALS_LOG

router = APIRouter()


def _load_signals() -> list[dict]:
    if SIGNALS_LOG.exists():
        try:
            return json.loads(SIGNALS_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


@router.get("/")
async def get_signals(limit: int = 50):
    """最近 N 筆達標訊號（最新優先）"""
    signals = _load_signals()
    return list(reversed(signals[-limit:]))
