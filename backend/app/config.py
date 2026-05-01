from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Broker
    active_broker: Literal["alpaca", "robinhood", "etrade"] = Field(
        default="alpaca", alias="ACTIVE_BROKER"
    )

    # Alpaca
    alpaca_api_key: str = Field(default="", alias="ALPACA_API_KEY")
    alpaca_secret_key: str = Field(default="", alias="ALPACA_SECRET_KEY")
    alpaca_paper: bool = Field(default=True, alias="ALPACA_PAPER")

    # Robinhood
    robinhood_username: str = Field(default="", alias="ROBINHOOD_USERNAME")
    robinhood_password: str = Field(default="", alias="ROBINHOOD_PASSWORD")
    robinhood_totp_secret: str = Field(default="", alias="ROBINHOOD_TOTP_SECRET")

    # E-Trade
    etrade_consumer_key: str = Field(default="", alias="ETRADE_CONSUMER_KEY")
    etrade_consumer_secret: str = Field(default="", alias="ETRADE_CONSUMER_SECRET")
    etrade_sandbox: bool = Field(default=True, alias="ETRADE_SANDBOX")

    # Data sources
    capitol_trades_enabled: bool = Field(default=True, alias="CAPITOL_TRADES_ENABLED")
    quiver_quant_api_key: str = Field(default="", alias="QUIVER_QUANT_API_KEY")
    alpha_vantage_api_key: str = Field(default="", alias="ALPHA_VANTAGE_API_KEY")
    polygon_api_key: str = Field(default="", alias="POLYGON_API_KEY")
    fmp_api_key: str = Field(default="", alias="FMP_API_KEY")
    eodhd_api_key: str = Field(default="", alias="EODHD_API_KEY")
    fred_api_key: str = Field(default="", alias="FRED_API_KEY")
    tiingo_api_key: str = Field(default="", alias="TIINGO_API_KEY")
    lunarcrush_api_key: str = Field(default="", alias="LUNARCRUSH_API_KEY")

    # Alternative data provider toggles
    alt_enable_capitol_trades: bool = Field(default=True, alias="ALT_ENABLE_CAPITOL_TRADES")
    alt_enable_openinsider: bool = Field(default=True, alias="ALT_ENABLE_OPENINSIDER")
    alt_enable_whalewisdom: bool = Field(default=True, alias="ALT_ENABLE_WHALEWISDOM")
    alt_enable_quiver_quantitative: bool = Field(default=True, alias="ALT_ENABLE_QUIVER_QUANTITATIVE")
    alt_enable_alpha_vantage: bool = Field(default=True, alias="ALT_ENABLE_ALPHA_VANTAGE")
    alt_enable_polygon: bool = Field(default=True, alias="ALT_ENABLE_POLYGON")
    alt_enable_fmp: bool = Field(default=True, alias="ALT_ENABLE_FMP")
    alt_enable_eodhd: bool = Field(default=True, alias="ALT_ENABLE_EODHD")
    alt_enable_fred: bool = Field(default=True, alias="ALT_ENABLE_FRED")
    alt_enable_tiingo: bool = Field(default=True, alias="ALT_ENABLE_TIINGO")
    alt_enable_lunarcrush: bool = Field(default=True, alias="ALT_ENABLE_LUNARCRUSH")

    # Alternative data provider weights
    alt_weight_capitol_trades: float = Field(default=1.00, alias="ALT_WEIGHT_CAPITOL_TRADES")
    alt_weight_openinsider: float = Field(default=1.00, alias="ALT_WEIGHT_OPENINSIDER")
    alt_weight_whalewisdom: float = Field(default=0.35, alias="ALT_WEIGHT_WHALEWISDOM")
    alt_weight_quiver_quantitative: float = Field(default=0.90, alias="ALT_WEIGHT_QUIVER_QUANTITATIVE")
    alt_weight_alpha_vantage: float = Field(default=0.85, alias="ALT_WEIGHT_ALPHA_VANTAGE")
    alt_weight_polygon: float = Field(default=0.60, alias="ALT_WEIGHT_POLYGON")
    alt_weight_fmp: float = Field(default=0.35, alias="ALT_WEIGHT_FMP")
    alt_weight_eodhd: float = Field(default=0.55, alias="ALT_WEIGHT_EODHD")
    alt_weight_fred: float = Field(default=0.45, alias="ALT_WEIGHT_FRED")
    alt_weight_tiingo: float = Field(default=0.25, alias="ALT_WEIGHT_TIINGO")
    alt_weight_lunarcrush: float = Field(default=0.50, alias="ALT_WEIGHT_LUNARCRUSH")

    # App
    refresh_interval_minutes: int = Field(
        default=15, alias="REFRESH_INTERVAL_MINUTES"
    )
    signal_lookback_days: int = Field(default=90, alias="SIGNAL_LOOKBACK_DAYS")


settings = Settings()
