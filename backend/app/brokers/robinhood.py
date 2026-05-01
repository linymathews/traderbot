import logging
import pyotp
from typing import Optional

from app.brokers.base import BaseBroker, AccountInfo, Position
from app.config import settings

logger = logging.getLogger(__name__)


class RobinhoodBroker(BaseBroker):
    def __init__(self):
        self._rh = None

    def connect(self) -> bool:
        try:
            import robin_stocks.robinhood as rh

            self._rh = rh
            mfa_code = None
            if settings.robinhood_totp_secret:
                totp = pyotp.TOTP(settings.robinhood_totp_secret)
                mfa_code = totp.now()

            login = rh.login(
                username=settings.robinhood_username,
                password=settings.robinhood_password,
                mfa_code=mfa_code,
                store_session=False,
            )
            if login and login.get("access_token"):
                logger.info("Robinhood connected successfully")
                return True
            logger.error("Robinhood login returned unexpected response: %s", login)
            return False
        except Exception as exc:
            logger.error("Robinhood connection failed: %s", exc)
            return False

    def get_account(self) -> AccountInfo:
        profile = self._rh.profiles.load_account_profile()
        portfolio = self._rh.profiles.load_portfolio_profile()
        positions_raw = self._rh.account.get_open_stock_positions()

        positions = []
        for p in positions_raw:
            instrument_url = p["instrument"]
            instrument = self._rh.stocks.get_instrument_by_url(instrument_url)
            symbol = instrument["symbol"]
            qty = float(p["quantity"])
            avg_cost = float(p["average_buy_price"])
            current = self._rh.stocks.get_latest_price(symbol)
            current = float(current[0]) if current else avg_cost
            market_val = qty * current
            upl = (current - avg_cost) * qty
            upl_pct = ((current - avg_cost) / avg_cost * 100) if avg_cost else 0.0
            positions.append(
                Position(
                    symbol=symbol,
                    quantity=qty,
                    avg_cost=avg_cost,
                    current_price=current,
                    market_value=round(market_val, 2),
                    unrealized_pl=round(upl, 2),
                    unrealized_pl_pct=round(upl_pct, 2),
                )
            )

        return AccountInfo(
            broker="robinhood",
            account_id=profile.get("account_number", "unknown"),
            cash=float(portfolio.get("withdrawable_amount", 0)),
            portfolio_value=float(portfolio.get("market_value", 0)),
            positions=positions,
        )

    def get_current_price(self, symbol: str) -> Optional[float]:
        try:
            prices = self._rh.stocks.get_latest_price(symbol)
            return float(prices[0]) if prices else None
        except Exception as exc:
            logger.warning("Could not fetch price for %s: %s", symbol, exc)
            return None
