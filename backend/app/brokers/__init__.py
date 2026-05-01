from app.config import settings
from app.brokers.base import BaseBroker


def get_broker() -> BaseBroker:
    broker_name = settings.active_broker.lower()
    if broker_name == "alpaca":
        from app.brokers.alpaca import AlpacaBroker
        return AlpacaBroker()
    elif broker_name == "robinhood":
        from app.brokers.robinhood import RobinhoodBroker
        return RobinhoodBroker()
    elif broker_name == "etrade":
        from app.brokers.etrade import ETradeBroker
        return ETradeBroker()
    else:
        raise ValueError(f"Unknown broker: {broker_name!r}")
