"""Binance Futures async data source — mirrors bingx_source interface."""

import logging
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

BINANCE_BASE = "https://fapi.binance.com"


async def _get(session: aiohttp.ClientSession, url: str, params: dict) -> Optional[any]:
    try:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except Exception as e:
        log.debug("Binance fetch error %s: %s", url, e)
        return None


async def fetch_symbols(session: aiohttp.ClientSession) -> list[str]:
    """Return all active USDT-M perpetual symbols."""
    data = await _get(session, f"{BINANCE_BASE}/fapi/v1/exchangeInfo", {})
    if not data:
        return []
    return [
        s["symbol"]
        for s in data.get("symbols", [])
        if s.get("contractType") == "PERPETUAL"
        and s.get("quoteAsset") == "USDT"
        and s.get("status") == "TRADING"
    ]


async def fetch_klines(
    session: aiohttp.ClientSession, symbol: str, interval: str, limit: int
) -> Optional[list]:
    """Returns raw list-of-lists from Binance klines endpoint."""
    return await _get(
        session,
        f"{BINANCE_BASE}/fapi/v1/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )


async def fetch_funding(session: aiohttp.ClientSession, symbol: str) -> float:
    data = await _get(session, f"{BINANCE_BASE}/fapi/v1/premiumIndex", {"symbol": symbol})
    if data and isinstance(data, dict):
        try:
            return float(data.get("lastFundingRate", 0))
        except Exception:
            pass
    return 0.0


async def fetch_ticker_24h(session: aiohttp.ClientSession, symbol: str) -> float:
    data = await _get(session, f"{BINANCE_BASE}/fapi/v1/ticker/24hr", {"symbol": symbol})
    if data and isinstance(data, dict):
        try:
            return float(data.get("priceChangePercent", 0))
        except Exception:
            pass
    return 0.0
