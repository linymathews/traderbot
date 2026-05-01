import logging
from typing import Optional

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
            qty = float(p.qty)
            avg_cost = float(p.avg_entry_price)
            current = float(p.current_price)
            market_val = float(p.market_value)
            upl = float(p.unrealized_pl)
            upl_pct = (upl / (avg_cost * qty) * 100) if avg_cost and qty else 0.0
            positions.append(
                Position(
                    symbol=p.symbol,
                    quantity=qty,
                    avg_cost=avg_cost,
                    current_price=current,
                    market_value=market_val,
                    unrealized_pl=upl,
                    unrealized_pl_pct=round(upl_pct, 2),
                )
            )

        return AccountInfo(
            broker="alpaca",
            account_id=account.id,
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
