"""
BingX async data source for crypto_screener.
Mirrors the Binance fetch interface so scanner.py can swap between them.
"""

import logging
import time
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

BINGX_BASE = "https://open-api.bingx.com"

STABLECOIN_KEYWORDS = {
    "USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USDD",
    "FRAX", "USDP", "GUSD", "SUSD",
}

_rate_limit_until: float = 0.0  # 速率限制解除時間（Unix 秒）


async def _get(session: aiohttp.ClientSession, url: str, params: dict) -> Optional[dict]:
    global _rate_limit_until
    now = time.time()
    if now < _rate_limit_until:
        remaining = int(_rate_limit_until - now)
        log.warning("BingX rate-limited, skipping request, %d seconds remaining", remaining)
        return None

    try:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            data = await resp.json(content_type=None)
            if isinstance(data, dict) and data.get("code") == 0:
                return data
            if isinstance(data, dict) and data.get("code") == 109415:
                return None   # contract suspended — silent skip
            if isinstance(data, dict) and data.get("code") == 100410:
                msg = data.get("msg", "")
                try:
                    unblock_ms = int(msg.split("after ")[-1].strip())
                    _rate_limit_until = unblock_ms / 1000.0
                except (ValueError, IndexError):
                    _rate_limit_until = time.time() + 3600
                wait_sec = max(0, int(_rate_limit_until - time.time()))
                log.warning("BingX API rate ban! Will unblock in %d seconds (code=100410)", wait_sec)
                return None
            log.debug("BingX non-zero code: %s", data)
            return None
    except Exception as e:
        log.debug("BingX fetch error %s: %s", url, e)
        return None


# ── Public interface (same signatures as scanner.py Binance helpers) ──

async def fetch_symbols(session: aiohttp.ClientSession) -> list[str]:
    """Return all active USDT perpetual symbols in BTC-USDT format."""
    data = await _get(session, f"{BINGX_BASE}/openApi/swap/v2/quote/contracts", {})
    if not data:
        return []
    symbols = []
    for c in data.get("data", []):
        sym: str = c.get("symbol", "")
        if not sym.endswith("-USDT"):
            continue
        base = sym.replace("-USDT", "").upper()
        if base in STABLECOIN_KEYWORDS:
            continue
        symbols.append(sym)
    return symbols


async def fetch_klines(
    session: aiohttp.ClientSession, symbol: str, interval: str, limit: int
) -> Optional[list]:
    """
    Fetch klines from BingX.
    interval: "4h" / "1h" / "1w"  (lowercase, BingX style)
    Returns list of raw bar dicts: [{open, high, low, close, volume, time}, ...]
    sorted oldest → newest.
    """
    data = await _get(
        session,
        f"{BINGX_BASE}/openApi/swap/v3/quote/klines",
        {"symbol": symbol, "interval": interval.lower(), "limit": limit},
    )
    if not data:
        return None
    raw = data.get("data", [])
    if not raw:
        return None

    candles = []
    for bar in raw:
        try:
            candles.append({
                "open":   float(bar["open"]),
                "high":   float(bar["high"]),
                "low":    float(bar["low"]),
                "close":  float(bar["close"]),
                "volume": float(bar["volume"]),
                "time":   int(bar["time"]),
            })
        except (KeyError, TypeError, ValueError):
            continue

    candles.sort(key=lambda x: x["time"])
    return candles if candles else None


async def fetch_funding(session: aiohttp.ClientSession, symbol: str) -> float:
    """Return latest funding rate as a decimal (e.g. 0.0001)."""
    data = await _get(
        session,
        f"{BINGX_BASE}/openApi/swap/v2/quote/premiumIndex",
        {"symbol": symbol},
    )
    if not data:
        return 0.0
    item = data.get("data")
    if isinstance(item, list) and item:
        item = item[0]
    if isinstance(item, dict):
        for key in ("lastFundingRate", "fundingRate"):
            try:
                v = float(item.get(key) or 0)
                return v
            except (TypeError, ValueError):
                pass
    return 0.0


async def fetch_price(session: aiohttp.ClientSession, symbol: str) -> Optional[float]:
    """Return current last/mark price for symbol (used for fast position checks)."""
    data = await _get(
        session,
        f"{BINGX_BASE}/openApi/swap/v2/quote/ticker",
        {"symbol": symbol},
    )
    if not data:
        return None
    items = data.get("data", [])
    if isinstance(items, dict):
        items = [items]
    for it in items:
        for key in ("lastPrice", "price"):
            try:
                v = it.get(key)
                if v is not None:
                    return float(v)
            except (TypeError, ValueError):
                pass
    return None


async def fetch_ticker_24h(session: aiohttp.ClientSession, symbol: str) -> float:
    """Return 24h price change percent (e.g. 3.5 means +3.5%)."""
    data = await _get(
        session,
        f"{BINGX_BASE}/openApi/swap/v2/quote/ticker",
        {"symbol": symbol},
    )
    if not data:
        return 0.0
    items = data.get("data", [])
    if isinstance(items, dict):
        items = [items]
    for it in items:
        for key in ("priceChangePercent", "priceChange24h"):
            try:
                return float(it.get(key) or 0)
            except (TypeError, ValueError):
                pass
    return 0.0


async def fetch_open_interest(session: aiohttp.ClientSession, symbol: str) -> float:
    """Return current open interest (contract units). Returns 0.0 on failure."""
    data = await _get(
        session,
        f"{BINGX_BASE}/openApi/swap/v2/quote/openInterest",
        {"symbol": symbol},
    )
    if not data:
        return 0.0
    item = data.get("data", {})
    if isinstance(item, dict):
        try:
            return float(item.get("openInterest") or 0)
        except (TypeError, ValueError):
            pass
    return 0.0


async def fetch_trade_flow(
    session: aiohttp.ClientSession, symbol: str, limit: int = 100
) -> dict:
    """
    Aggregate last `limit` trades into directional flow metrics.
    Returns:
      flow_ratio  : (buy_vol − sell_vol) / total_vol  ∈ [−1, +1]
      large_trade : True if any single trade exceeds 3× average trade size
    isBuyerMaker=True → sell-side aggressor; False → buy-side aggressor.
    """
    data = await _get(
        session,
        f"{BINGX_BASE}/openApi/swap/v2/quote/trades",
        {"symbol": symbol, "limit": limit},
    )
    _empty = {"flow_ratio": 0.0, "large_trade": False}
    if not data:
        return _empty

    trades = data.get("data", [])
    if not isinstance(trades, list) or not trades:
        return _empty

    buy_vol = sell_vol = 0.0
    vols: list[float] = []
    for t in trades:
        try:
            qty = float(t.get("qty") or 0)
            buyer_maker = t.get("isBuyerMaker", t.get("buyerMaker", True))
            vols.append(qty)
            if not buyer_maker:
                buy_vol += qty
            else:
                sell_vol += qty
        except (TypeError, ValueError):
            continue

    total = buy_vol + sell_vol
    if total == 0 or not vols:
        return _empty

    flow_ratio  = (buy_vol - sell_vol) / total
    avg_vol     = sum(vols) / len(vols)
    large_trade = any(v > 3.0 * avg_vol for v in vols) if avg_vol > 0 else False

    return {"flow_ratio": round(flow_ratio, 3), "large_trade": large_trade}
