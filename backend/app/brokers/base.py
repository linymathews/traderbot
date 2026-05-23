from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_pl_pct: float
    asset_type: str = "stock"
    underlying_symbol: Optional[str] = None
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiration: Optional[str] = None


@dataclass
class AccountInfo:
    broker: str
    account_id: str
    cash: float
    portfolio_value: float
    positions: list[Position] = field(default_factory=list)


class BaseBroker(ABC):
    """Abstract base class for all broker integrations."""

    @abstractmethod
    def connect(self) -> bool:
        """Authenticate and connect to the broker. Returns True on success."""

    @abstractmethod
    def get_account(self) -> AccountInfo:
        """Return account summary and all open positions."""

    @abstractmethod
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Return the latest price for a symbol."""

    def get_portfolio_symbols(self) -> list[str]:
        account = self.get_account()
        return [p.symbol for p in account.positions if (p.asset_type or "stock") == "stock"]

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
        raise NotImplementedError("Order placement is not implemented for this broker")

    def get_pending_orders(self) -> list[dict]:
        """Return open/pending orders if supported by the broker."""
        return []
