"""
Binance Futures real-order execution module.
Leverage is always set to 1x (no leverage).
Position sizing: risk_pct of available USDT balance per trade.
"""

import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com"


class LiveTrader:
    def __init__(self, api_key: str, api_secret: str, risk_pct: float = 0.02):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.risk_pct   = risk_pct

    # ── Signing ───────────────────────────────────────────────

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(params)
        sig   = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = sig
        return params

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self.api_key}

    # ── Raw requests ─────────────────────────────────────────

    async def _get(self, session: aiohttp.ClientSession, path: str, params: dict) -> Optional[dict]:
        try:
            async with session.get(
                f"{FAPI}{path}",
                params=self._sign(params),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    log.error("GET %s => %d %s", path, resp.status, data)
                    return None
                return data
        except Exception as e:
            log.error("GET %s error: %s", path, e)
            return None

    async def _post(self, session: aiohttp.ClientSession, path: str, params: dict) -> Optional[dict]:
        try:
            async with session.post(
                f"{FAPI}{path}",
                params=self._sign(params),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if resp.status not in (200, 201):
                    log.error("POST %s => %d %s", path, resp.status, data)
                    return None
                return data
        except Exception as e:
            log.error("POST %s error: %s", path, e)
            return None

    async def _delete(self, session: aiohttp.ClientSession, path: str, params: dict) -> Optional[dict]:
        try:
            async with session.delete(
                f"{FAPI}{path}",
                params=self._sign(params),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    log.error("DELETE %s => %d %s", path, resp.status, data)
                    return None
                return data
        except Exception as e:
            log.error("DELETE %s error: %s", path, e)
            return None

    # ── Account info ─────────────────────────────────────────

    async def get_balance(self, session: aiohttp.ClientSession) -> float:
        """Return available USDT balance in futures wallet."""
        data = await self._get(session, "/fapi/v2/balance", {})
        if not data:
            return 0.0
        for asset in data:
            if asset.get("asset") == "USDT":
                return float(asset.get("availableBalance", 0))
        return 0.0

    async def get_open_positions(self, session: aiohttp.ClientSession) -> list[dict]:
        """Return all positions with non-zero size."""
        data = await self._get(session, "/fapi/v2/positionRisk", {})
        if not data:
            return []
        return [p for p in data if float(p.get("positionAmt", 0)) != 0]

    async def get_open_orders(self, session: aiohttp.ClientSession, symbol: str) -> list[dict]:
        data = await self._get(session, "/fapi/v1/openOrders", {"symbol": symbol})
        return data or []

    # ── Symbol info (precision) ───────────────────────────────

    async def get_symbol_info(self, session: aiohttp.ClientSession, symbol: str) -> Optional[dict]:
        data = await self._get(session, "/fapi/v1/exchangeInfo", {})
        if not data:
            return None
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                return s
        return None

    def _qty_precision(self, sym_info: dict) -> int:
        for f in sym_info.get("filters", []):
            if f["filterType"] == "LOT_SIZE":
                step = f["stepSize"].rstrip("0")
                return len(step.split(".")[-1]) if "." in step else 0
        return 3

    def _price_precision(self, sym_info: dict) -> int:
        return sym_info.get("pricePrecision", 4)

    # ── Set leverage to 1x ───────────────────────────────────

    async def set_leverage_1x(self, session: aiohttp.ClientSession, symbol: str) -> bool:
        data = await self._post(
            session, "/fapi/v1/leverage",
            {"symbol": symbol, "leverage": 1},
        )
        if data:
            log.info("%s leverage set to 1x", symbol)
            return True
        return False

    # ── Calculate quantity ───────────────────────────────────

    def _calc_qty(
        self,
        balance: float,
        entry: float,
        stop_loss: float,
        qty_prec: int,
    ) -> float:
        """
        Risk-based sizing: risk_pct of balance divided by per-unit risk.
        Rounded to qty_prec decimal places.
        """
        risk_dist = abs(entry - stop_loss)
        if risk_dist == 0:
            return 0.0
        raw_qty = (balance * self.risk_pct) / risk_dist
        factor  = 10 ** qty_prec
        return int(raw_qty * factor) / factor   # floor to precision

    # ── Place orders ─────────────────────────────────────────

    async def place_market(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        side: str,     # "BUY" or "SELL"
        qty: float,
        qty_prec: int,
    ) -> Optional[dict]:
        return await self._post(session, "/fapi/v1/order", {
            "symbol":   symbol,
            "side":     side,
            "type":     "MARKET",
            "quantity": f"{qty:.{qty_prec}f}",
        })

    async def place_stop_market(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        side: str,
        qty: float,
        stop_price: float,
        qty_prec: int,
        price_prec: int,
    ) -> Optional[dict]:
        return await self._post(session, "/fapi/v1/order", {
            "symbol":           symbol,
            "side":             side,
            "type":             "STOP_MARKET",
            "quantity":         f"{qty:.{qty_prec}f}",
            "stopPrice":        f"{stop_price:.{price_prec}f}",
            "closePosition":    "false",
            "workingType":      "MARK_PRICE",
            "priceProtect":     "TRUE",
            "reduceOnly":       "true",
        })

    async def place_take_profit_market(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        side: str,
        qty: float,
        stop_price: float,
        qty_prec: int,
        price_prec: int,
    ) -> Optional[dict]:
        return await self._post(session, "/fapi/v1/order", {
            "symbol":       symbol,
            "side":         side,
            "type":         "TAKE_PROFIT_MARKET",
            "quantity":     f"{qty:.{qty_prec}f}",
            "stopPrice":    f"{stop_price:.{price_prec}f}",
            "workingType":  "MARK_PRICE",
            "priceProtect": "TRUE",
            "reduceOnly":   "true",
        })

    # ── Cancel all open orders for symbol ────────────────────

    async def cancel_all_orders(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> bool:
        data = await self._delete(session, "/fapi/v1/allOpenOrders", {"symbol": symbol})
        return data is not None

    # ── Full entry flow ───────────────────────────────────────

    async def open_trade(
        self, session: aiohttp.ClientSession, signal: dict
    ) -> bool:
        """
        Full entry sequence for a LONG signal:
          1. Set leverage to 1x
          2. Get balance
          3. Get symbol precision info
          4. Place MARKET BUY
          5. Place STOP_MARKET (stop loss)
          6. Place 3x TAKE_PROFIT_MARKET (TP1=30%, TP2=40%, TP3=30%)
        Returns True if entry + stop were placed successfully.
        """
        symbol = signal["symbol"]
        entry  = signal["entry"]
        sl     = signal["stop_loss"]
        t1     = signal["target_1"]
        t2     = signal["target_2"]
        t3     = signal["target_3"]

        # Step 1
        if not await self.set_leverage_1x(session, symbol):
            log.warning("%s: could not set leverage", symbol)
            return False

        # Step 2
        balance = await self.get_balance(session)
        if balance <= 0:
            log.error("No USDT balance available")
            return False

        # Step 3
        sym_info  = await self.get_symbol_info(session, symbol)
        if not sym_info:
            log.error("%s: could not get symbol info", symbol)
            return False
        qty_prec   = self._qty_precision(sym_info)
        price_prec = self._price_precision(sym_info)

        total_qty = self._calc_qty(balance, entry, sl, qty_prec)
        if total_qty <= 0:
            log.error("%s: calculated qty=0 (balance=%.2f)", symbol, balance)
            return False

        # Allocate qty per take-profit tier
        q1 = round(total_qty * 0.3, qty_prec)
        q2 = round(total_qty * 0.4, qty_prec)
        q3 = total_qty - q1 - q2   # remaining ~30%
        q3 = round(max(q3, 10 ** -qty_prec), qty_prec)

        # Step 4: market entry
        entry_order = await self.place_market(session, symbol, "BUY", total_qty, qty_prec)
        if not entry_order:
            log.error("%s: market entry failed", symbol)
            return False
        actual_entry = float(entry_order.get("avgPrice") or entry_order.get("price") or entry)
        log.info("%s: ENTRY filled qty=%s @ %s", symbol,
                 f"{total_qty:.{qty_prec}f}", f"{actual_entry:.{price_prec}f}")

        # Step 5: stop loss (full qty, reduce-only)
        sl_order = await self.place_stop_market(
            session, symbol, "SELL", total_qty, sl, qty_prec, price_prec
        )
        if not sl_order:
            log.warning("%s: stop loss order failed — POSITION IS UNPROTECTED", symbol)

        # Step 6a: TP1
        await self.place_take_profit_market(session, symbol, "SELL", q1, t1, qty_prec, price_prec)
        # Step 6b: TP2
        await self.place_take_profit_market(session, symbol, "SELL", q2, t2, qty_prec, price_prec)
        # Step 6c: TP3
        await self.place_take_profit_market(session, symbol, "SELL", q3, t3, qty_prec, price_prec)

        log.info(
            "%s: all orders placed | qty=%s | SL=%s | TP1=%s(%s) | TP2=%s(%s) | TP3=%s(%s)",
            symbol,
            f"{total_qty:.{qty_prec}f}",
            f"{sl:.{price_prec}f}",
            f"{t1:.{price_prec}f}", f"{q1:.{qty_prec}f}",
            f"{t2:.{price_prec}f}", f"{q2:.{qty_prec}f}",
            f"{t3:.{price_prec}f}", f"{q3:.{qty_prec}f}",
        )
        return True

    # ── Check if already in position ─────────────────────────

    async def has_position(self, session: aiohttp.ClientSession, symbol: str) -> bool:
        positions = await self.get_open_positions(session)
        return any(p["symbol"] == symbol for p in positions)
