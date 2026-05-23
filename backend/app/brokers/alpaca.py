import logging
import re
from typing import Optional

import httpx

from app.brokers.base import BaseBroker, AccountInfo, Position
from app.config import settings

logger = logging.getLogger(__name__)


class AlpacaBroker(BaseBroker):
    def __init__(self):
        self._trading_client = None
        self._data_client = None

    def connect(self) -> bool:
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.data.historical import StockHistoricalDataClient

            self._trading_client = TradingClient(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
                paper=settings.alpaca_paper,
            )
            self._data_client = StockHistoricalDataClient(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
            )
            # Validate credentials
            self._trading_client.get_account()
            logger.info("Alpaca connected successfully (paper=%s)", settings.alpaca_paper)
            return True
        except Exception as exc:
            logger.error("Alpaca connection failed: %s", exc)
            return False

    def get_account(self) -> AccountInfo:
        account = self._trading_client.get_account()
        positions_raw = self._trading_client.get_all_positions()

        positions = []
        for p in positions_raw:
            symbol = p.symbol
            asset_class = str(getattr(p, "asset_class", "stock") or "stock").lower()
            asset_type = "option" if "option" in asset_class else "stock"
            option_type = None
            strike = None
            expiration = None
            underlying_symbol = getattr(p, "underlying_symbol", None)
            if asset_type == "option":
                m = re.match(r"^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$", symbol)
                if m:
                    underlying_symbol = underlying_symbol or m.group(1)
                    yy, mm, dd = m.group(2), m.group(3), m.group(4)
                    option_type = "call" if m.group(5) == "C" else "put"
                    strike = int(m.group(6)) / 1000.0
                    expiration = f"20{yy}-{mm}-{dd}"

            qty = float(p.qty)
            avg_cost = float(p.avg_entry_price)
            current = float(p.current_price)
            market_val = float(p.market_value)
            upl = float(p.unrealized_pl)
            upl_pct = (upl / (avg_cost * qty) * 100) if avg_cost and qty else 0.0
            positions.append(
                Position(
                    symbol=symbol,
                    quantity=qty,
                    avg_cost=avg_cost,
                    current_price=current,
                    market_value=market_val,
                    unrealized_pl=upl,
                    unrealized_pl_pct=round(upl_pct, 2),
                    asset_type=asset_type,
                    underlying_symbol=underlying_symbol,
                    option_type=option_type,
                    strike=strike,
                    expiration=expiration,
                )
            )

        return AccountInfo(
            broker="alpaca",
            account_id=str(account.id),
            cash=float(account.cash),
            portfolio_value=float(account.portfolio_value),
            positions=positions,
        )

    def get_current_price(self, symbol: str) -> Optional[float]:
        try:
            from alpaca.data.requests import StockLatestQuoteRequest

            req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = self._data_client.get_stock_latest_quote(req)
            q = quotes.get(symbol)
            if q:
                return float((q.ask_price + q.bid_price) / 2)
        except Exception as exc:
            logger.warning("Could not fetch price for %s: %s", symbol, exc)
        return None

    def submit_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        instrument_type: str = "stock",
        order_type: str = "market",
        time_in_force: str = "day",
        limit_price: Optional[float] = None,
    ) -> dict:
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        if instrument_type not in {"stock", "option"}:
            raise ValueError("instrument_type must be 'stock' or 'option'")
        if order_type not in {"market", "limit"}:
            raise ValueError("order_type must be 'market' or 'limit'")
        if time_in_force not in {"day", "gtc", "ioc", "fok"}:
            raise ValueError("time_in_force must be one of day|gtc|ioc|fok")
        if order_type == "limit" and (limit_price is None or float(limit_price) <= 0):
            raise ValueError("limit_price must be > 0 for limit orders")

        base_url = "https://paper-api.alpaca.markets" if settings.alpaca_paper else "https://api.alpaca.markets"
        headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
            "Content-Type": "application/json",
        }
        payload = {
            "symbol": symbol,
            "qty": str(quantity),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if order_type == "limit":
            payload["limit_price"] = str(limit_price)
        if instrument_type == "option":
            payload["asset_class"] = "option"

        try:
            with httpx.Client(timeout=20) as client:
                resp = client.post(f"{base_url}/v2/orders", headers=headers, json=payload)
            if resp.status_code >= 400:
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                raise RuntimeError(f"Alpaca order rejected ({resp.status_code}): {detail}")

            data = resp.json()
            return {
                "id": data.get("id"),
                "status": data.get("status"),
                "symbol": data.get("symbol", symbol),
                "side": data.get("side", side),
                "qty": data.get("qty", str(quantity)),
                "asset_class": data.get("asset_class", instrument_type),
                "type": data.get("type", order_type),
                "time_in_force": data.get("time_in_force", time_in_force),
                "limit_price": data.get("limit_price"),
                "submitted_at": data.get("submitted_at"),
            }
        except Exception as exc:
            logger.exception("Alpaca order submit failed")
            raise RuntimeError(str(exc)) from exc

    def get_pending_orders(self) -> list[dict]:
        base_url = "https://paper-api.alpaca.markets" if settings.alpaca_paper else "https://api.alpaca.markets"
        headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.get(f"{base_url}/v2/orders", headers=headers, params={"status": "open", "direction": "desc"})
            resp.raise_for_status()
            orders = resp.json() if isinstance(resp.json(), list) else []
            out = []
            for o in orders:
                out.append(
                    {
                        "id": o.get("id"),
                        "symbol": o.get("symbol"),
                        "side": o.get("side"),
                        "qty": o.get("qty"),
                        "type": o.get("type"),
                        "time_in_force": o.get("time_in_force"),
                        "status": o.get("status"),
                        "submitted_at": o.get("submitted_at"),
                        "limit_price": o.get("limit_price"),
                    }
                )
            return out
        except Exception as exc:
            logger.warning("Could not fetch Alpaca pending orders: %s", exc)
            return []
