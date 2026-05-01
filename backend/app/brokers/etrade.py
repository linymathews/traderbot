import logging
from typing import Optional

from app.brokers.base import BaseBroker, AccountInfo, Position
from app.config import settings

logger = logging.getLogger(__name__)


class ETradeBroker(BaseBroker):
    """
    E-Trade integration via pyetrade OAuth1 flow.

    First-time use: call get_oauth_url() in the browser, authorize, then
    pass the verifier code to complete_oauth(verifier).
    The access tokens are stored in memory for the session.
    """

    def __init__(self):
        self._accounts_api = None
        self._market_api = None
        self._oauth = None
        self._access_token: Optional[str] = None
        self._access_token_secret: Optional[str] = None

    def get_oauth_url(self) -> str:
        import pyetrade

        self._oauth = pyetrade.ETradeOAuth(
            settings.etrade_consumer_key,
            settings.etrade_consumer_secret,
        )
        return self._oauth.get_request_token()

    def complete_oauth(self, verifier: str) -> bool:
        try:
            tokens = self._oauth.get_access_token(verifier)
            self._access_token = tokens["oauth_token"]
            self._access_token_secret = tokens["oauth_token_secret"]
            self._init_clients()
            return True
        except Exception as exc:
            logger.error("E-Trade OAuth completion failed: %s", exc)
            return False

    def connect(self) -> bool:
        """For E-Trade the OAuth URL must be obtained separately via get_oauth_url()."""
        if self._accounts_api:
            return True
        logger.warning(
            "E-Trade requires interactive OAuth. "
            "Call GET /broker/etrade/auth to start the flow."
        )
        return False

    def _init_clients(self):
        import pyetrade

        sandbox = settings.etrade_sandbox
        self._accounts_api = pyetrade.ETradeAccounts(
            settings.etrade_consumer_key,
            settings.etrade_consumer_secret,
            self._access_token,
            self._access_token_secret,
            dev=sandbox,
        )
        self._market_api = pyetrade.ETradeMarket(
            settings.etrade_consumer_key,
            settings.etrade_consumer_secret,
            self._access_token,
            self._access_token_secret,
            dev=sandbox,
        )

    def get_account(self) -> AccountInfo:
        accounts = self._accounts_api.list_accounts(resp_format="json")
        account_list = accounts["AccountListResponse"]["Accounts"]["Account"]
        # Use first account
        acct = account_list[0]
        key = acct["accountIdKey"]
        balance = self._accounts_api.get_account_balance(key, resp_format="json")
        bal_data = balance["BalanceResponse"]

        portfolio_resp = self._accounts_api.get_account_portfolio(key, resp_format="json")
        positions = []

        try:
            port_data = portfolio_resp["PortfolioResponse"]["AccountPortfolio"]
            for ap in port_data:
                for pos in ap.get("Position", []):
                    symbol = pos["Product"]["symbol"]
                    qty = float(pos["quantity"])
                    avg_cost = float(pos["costPerShare"])
                    current = float(pos["Quick"]["lastTrade"])
                    market_val = float(pos["marketValue"])
                    upl = float(pos["totalGain"])
                    upl_pct = float(pos["totalGainPct"])
                    positions.append(
                        Position(
                            symbol=symbol,
                            quantity=qty,
                            avg_cost=avg_cost,
                            current_price=current,
                            market_value=market_val,
                            unrealized_pl=upl,
                            unrealized_pl_pct=round(upl_pct, 2),
                        )
                    )
        except (KeyError, TypeError):
            pass

        return AccountInfo(
            broker="etrade",
            account_id=str(acct.get("accountId", key)),
            cash=float(bal_data.get("Computed", {}).get("cashAvailableForInvestment", 0)),
            portfolio_value=float(bal_data.get("Computed", {}).get("RealTimeValues", {}).get("totalAccountValue", 0)),
            positions=positions,
        )

    def get_current_price(self, symbol: str) -> Optional[float]:
        try:
            quote = self._market_api.get_quote([symbol], resp_format="json")
            data = quote["QuoteResponse"]["QuoteData"]
            if data:
                return float(data[0]["All"]["lastTrade"])
        except Exception as exc:
            logger.warning("Could not fetch price for %s: %s", symbol, exc)
        return None
