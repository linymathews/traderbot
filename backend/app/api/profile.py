"""
Profile/Settings management — read and write .env at runtime.

All secrets returned via GET /api/profile are masked (last 4 chars visible).
PUT /api/profile writes only the fields the client sends.
POST /api/profile/test-connection re-instantiates the chosen broker and checks auth.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)
profile_router = APIRouter(prefix="/api/profile", tags=["profile"])

ENV_PATH = Path(__file__).parent.parent.parent / ".env"

# ── .env helpers ──────────────────────────────────────────────────────────────

def _read_env() -> dict[str, str]:
    """Parse .env into a plain dict (no interpolation)."""
    result: dict[str, str] = {}
    if not ENV_PATH.exists():
        return result
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def _write_env(data: dict[str, str]) -> None:
    """
    Re-write .env preserving comments and key order.
    Existing keys are updated in-place; new keys are appended.
    """
    lines: list[str] = []
    updated: set[str] = set()

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                lines.append(line)
                continue
            if "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in data:
                    lines.append(f"{k}={data[k]}")
                    updated.add(k)
                    continue
            lines.append(line)

    # Append keys that didn't exist yet
    for k, v in data.items():
        if k not in updated:
            lines.append(f"{k}={v}")

    ENV_PATH.write_text("\n".join(lines) + "\n")


def _mask(value: str) -> str:
    """Show only the last 4 characters of a secret."""
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return "•" * (len(value) - 4) + value[-4:]


# ── Models ────────────────────────────────────────────────────────────────────

class ProfileResponse(BaseModel):
    # Active broker
    active_broker: str

    # Alpaca
    alpaca_api_key_masked: str
    alpaca_secret_key_masked: str
    alpaca_paper: bool
    alpaca_configured: bool

    # Robinhood
    robinhood_username: str
    robinhood_password_masked: str
    robinhood_totp_configured: bool
    robinhood_configured: bool

    # E-Trade
    etrade_consumer_key_masked: str
    etrade_consumer_secret_masked: str
    etrade_sandbox: bool
    etrade_configured: bool

    # Data sources
    capitol_trades_enabled: bool
    quiver_quant_api_key_masked: str
    quiver_quant_configured: bool

    # Alternative data controls
    alt_enable_capitol_trades: bool
    alt_enable_openinsider: bool
    alt_enable_whalewisdom: bool
    alt_enable_quiver_quantitative: bool
    alt_enable_alpha_vantage: bool
    alt_enable_polygon: bool
    alt_enable_fmp: bool
    alt_enable_eodhd: bool
    alt_enable_fred: bool
    alt_enable_tiingo: bool
    alt_enable_lunarcrush: bool

    alt_weight_capitol_trades: float
    alt_weight_openinsider: float
    alt_weight_whalewisdom: float
    alt_weight_quiver_quantitative: float
    alt_weight_alpha_vantage: float
    alt_weight_polygon: float
    alt_weight_fmp: float
    alt_weight_eodhd: float
    alt_weight_fred: float
    alt_weight_tiingo: float
    alt_weight_lunarcrush: float

    # App settings
    refresh_interval_minutes: int
    signal_lookback_days: int


class ProfileUpdate(BaseModel):
    # Active broker
    active_broker: Optional[str] = None

    # Alpaca
    alpaca_api_key: Optional[str] = None
    alpaca_secret_key: Optional[str] = None
    alpaca_paper: Optional[bool] = None

    # Robinhood
    robinhood_username: Optional[str] = None
    robinhood_password: Optional[str] = None
    robinhood_totp_secret: Optional[str] = None

    # E-Trade
    etrade_consumer_key: Optional[str] = None
    etrade_consumer_secret: Optional[str] = None
    etrade_sandbox: Optional[bool] = None

    # Data sources
    capitol_trades_enabled: Optional[bool] = None
    quiver_quant_api_key: Optional[str] = None

    # Alternative data controls
    alt_enable_capitol_trades: Optional[bool] = None
    alt_enable_openinsider: Optional[bool] = None
    alt_enable_whalewisdom: Optional[bool] = None
    alt_enable_quiver_quantitative: Optional[bool] = None
    alt_enable_alpha_vantage: Optional[bool] = None
    alt_enable_polygon: Optional[bool] = None
    alt_enable_fmp: Optional[bool] = None
    alt_enable_eodhd: Optional[bool] = None
    alt_enable_fred: Optional[bool] = None
    alt_enable_tiingo: Optional[bool] = None
    alt_enable_lunarcrush: Optional[bool] = None

    alt_weight_capitol_trades: Optional[float] = None
    alt_weight_openinsider: Optional[float] = None
    alt_weight_whalewisdom: Optional[float] = None
    alt_weight_quiver_quantitative: Optional[float] = None
    alt_weight_alpha_vantage: Optional[float] = None
    alt_weight_polygon: Optional[float] = None
    alt_weight_fmp: Optional[float] = None
    alt_weight_eodhd: Optional[float] = None
    alt_weight_fred: Optional[float] = None
    alt_weight_tiingo: Optional[float] = None
    alt_weight_lunarcrush: Optional[float] = None

    # App settings
    refresh_interval_minutes: Optional[int] = None
    signal_lookback_days: Optional[int] = None

    @field_validator("active_broker")
    @classmethod
    def validate_broker(cls, v):
        if v is not None and v not in ("alpaca", "robinhood", "etrade"):
            raise ValueError("active_broker must be alpaca, robinhood, or etrade")
        return v

    @field_validator("refresh_interval_minutes")
    @classmethod
    def validate_refresh(cls, v):
        if v is not None and v < 1:
            raise ValueError("refresh_interval_minutes must be >= 1")
        return v

    @field_validator("signal_lookback_days")
    @classmethod
    def validate_lookback(cls, v):
        if v is not None and (v < 30 or v > 365):
            raise ValueError("signal_lookback_days must be between 30 and 365")
        return v

    @field_validator(
        "alt_weight_capitol_trades",
        "alt_weight_openinsider",
        "alt_weight_whalewisdom",
        "alt_weight_quiver_quantitative",
        "alt_weight_alpha_vantage",
        "alt_weight_polygon",
        "alt_weight_fmp",
        "alt_weight_eodhd",
        "alt_weight_fred",
        "alt_weight_tiingo",
        "alt_weight_lunarcrush",
    )
    @classmethod
    def validate_alt_weights(cls, v):
        if v is not None and (v < 0 or v > 3):
            raise ValueError("alternative weights must be between 0 and 3")
        return v


class TestConnectionRequest(BaseModel):
    broker: str  # alpaca | robinhood | etrade


class TestConnectionResponse(BaseModel):
    broker: str
    success: bool
    message: str
    account_id: Optional[str] = None
    portfolio_value: Optional[float] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@profile_router.get("", response_model=ProfileResponse)
def get_profile():
    """Return current configuration with secrets masked."""
    env = _read_env()

    alpaca_key = env.get("ALPACA_API_KEY", "")
    alpaca_secret = env.get("ALPACA_SECRET_KEY", "")
    rh_pass = env.get("ROBINHOOD_PASSWORD", "")
    rh_totp = env.get("ROBINHOOD_TOTP_SECRET", "")
    et_key = env.get("ETRADE_CONSUMER_KEY", "")
    et_secret = env.get("ETRADE_CONSUMER_SECRET", "")
    qq_key = env.get("QUIVER_QUANT_API_KEY", "")

    return ProfileResponse(
        active_broker=env.get("ACTIVE_BROKER", "alpaca"),
        alpaca_api_key_masked=_mask(alpaca_key),
        alpaca_secret_key_masked=_mask(alpaca_secret),
        alpaca_paper=env.get("ALPACA_PAPER", "true").lower() == "true",
        alpaca_configured=bool(alpaca_key and alpaca_secret),
        robinhood_username=env.get("ROBINHOOD_USERNAME", ""),
        robinhood_password_masked=_mask(rh_pass),
        robinhood_totp_configured=bool(rh_totp),
        robinhood_configured=bool(env.get("ROBINHOOD_USERNAME") and rh_pass),
        etrade_consumer_key_masked=_mask(et_key),
        etrade_consumer_secret_masked=_mask(et_secret),
        etrade_sandbox=env.get("ETRADE_SANDBOX", "true").lower() == "true",
        etrade_configured=bool(et_key and et_secret),
        capitol_trades_enabled=env.get("CAPITOL_TRADES_ENABLED", "true").lower() == "true",
        quiver_quant_api_key_masked=_mask(qq_key),
        quiver_quant_configured=bool(qq_key),

        alt_enable_capitol_trades=env.get("ALT_ENABLE_CAPITOL_TRADES", "true").lower() == "true",
        alt_enable_openinsider=env.get("ALT_ENABLE_OPENINSIDER", "true").lower() == "true",
        alt_enable_whalewisdom=env.get("ALT_ENABLE_WHALEWISDOM", "true").lower() == "true",
        alt_enable_quiver_quantitative=env.get("ALT_ENABLE_QUIVER_QUANTITATIVE", "true").lower() == "true",
        alt_enable_alpha_vantage=env.get("ALT_ENABLE_ALPHA_VANTAGE", "true").lower() == "true",
        alt_enable_polygon=env.get("ALT_ENABLE_POLYGON", "true").lower() == "true",
        alt_enable_fmp=env.get("ALT_ENABLE_FMP", "true").lower() == "true",
        alt_enable_eodhd=env.get("ALT_ENABLE_EODHD", "true").lower() == "true",
        alt_enable_fred=env.get("ALT_ENABLE_FRED", "true").lower() == "true",
        alt_enable_tiingo=env.get("ALT_ENABLE_TIINGO", "true").lower() == "true",
        alt_enable_lunarcrush=env.get("ALT_ENABLE_LUNARCRUSH", "true").lower() == "true",

        alt_weight_capitol_trades=float(env.get("ALT_WEIGHT_CAPITOL_TRADES", "1.0")),
        alt_weight_openinsider=float(env.get("ALT_WEIGHT_OPENINSIDER", "1.0")),
        alt_weight_whalewisdom=float(env.get("ALT_WEIGHT_WHALEWISDOM", "0.35")),
        alt_weight_quiver_quantitative=float(env.get("ALT_WEIGHT_QUIVER_QUANTITATIVE", "0.90")),
        alt_weight_alpha_vantage=float(env.get("ALT_WEIGHT_ALPHA_VANTAGE", "0.85")),
        alt_weight_polygon=float(env.get("ALT_WEIGHT_POLYGON", "0.60")),
        alt_weight_fmp=float(env.get("ALT_WEIGHT_FMP", "0.35")),
        alt_weight_eodhd=float(env.get("ALT_WEIGHT_EODHD", "0.55")),
        alt_weight_fred=float(env.get("ALT_WEIGHT_FRED", "0.45")),
        alt_weight_tiingo=float(env.get("ALT_WEIGHT_TIINGO", "0.25")),
        alt_weight_lunarcrush=float(env.get("ALT_WEIGHT_LUNARCRUSH", "0.50")),
        refresh_interval_minutes=int(env.get("REFRESH_INTERVAL_MINUTES", "15")),
        signal_lookback_days=int(env.get("SIGNAL_LOOKBACK_DAYS", "90")),
    )


@profile_router.put("")
def update_profile(body: ProfileUpdate):
    """
    Update configuration. Only non-None fields in the request body are written.
    Empty string for a secret field means "clear it".
    Placeholder strings containing only bullets (•) are ignored (masked value sent back unchanged).
    """
    env = _read_env()
    updates: dict[str, str] = {}

    def _should_write(val: Optional[str]) -> bool:
        """Ignore None and masked placeholder values."""
        if val is None:
            return False
        if re.match(r'^[•*]+$', val):
            return False
        return True

    if body.active_broker is not None:
        updates["ACTIVE_BROKER"] = body.active_broker
    if _should_write(body.alpaca_api_key):
        updates["ALPACA_API_KEY"] = body.alpaca_api_key
    if _should_write(body.alpaca_secret_key):
        updates["ALPACA_SECRET_KEY"] = body.alpaca_secret_key
    if body.alpaca_paper is not None:
        updates["ALPACA_PAPER"] = "true" if body.alpaca_paper else "false"
    if _should_write(body.robinhood_username):
        updates["ROBINHOOD_USERNAME"] = body.robinhood_username
    if _should_write(body.robinhood_password):
        updates["ROBINHOOD_PASSWORD"] = body.robinhood_password
    if _should_write(body.robinhood_totp_secret):
        updates["ROBINHOOD_TOTP_SECRET"] = body.robinhood_totp_secret
    if _should_write(body.etrade_consumer_key):
        updates["ETRADE_CONSUMER_KEY"] = body.etrade_consumer_key
    if _should_write(body.etrade_consumer_secret):
        updates["ETRADE_CONSUMER_SECRET"] = body.etrade_consumer_secret
    if body.etrade_sandbox is not None:
        updates["ETRADE_SANDBOX"] = "true" if body.etrade_sandbox else "false"
    if body.capitol_trades_enabled is not None:
        updates["CAPITOL_TRADES_ENABLED"] = "true" if body.capitol_trades_enabled else "false"
    if _should_write(body.quiver_quant_api_key):
        updates["QUIVER_QUANT_API_KEY"] = body.quiver_quant_api_key

    bool_updates = {
        "ALT_ENABLE_CAPITOL_TRADES": body.alt_enable_capitol_trades,
        "ALT_ENABLE_OPENINSIDER": body.alt_enable_openinsider,
        "ALT_ENABLE_WHALEWISDOM": body.alt_enable_whalewisdom,
        "ALT_ENABLE_QUIVER_QUANTITATIVE": body.alt_enable_quiver_quantitative,
        "ALT_ENABLE_ALPHA_VANTAGE": body.alt_enable_alpha_vantage,
        "ALT_ENABLE_POLYGON": body.alt_enable_polygon,
        "ALT_ENABLE_FMP": body.alt_enable_fmp,
        "ALT_ENABLE_EODHD": body.alt_enable_eodhd,
        "ALT_ENABLE_FRED": body.alt_enable_fred,
        "ALT_ENABLE_TIINGO": body.alt_enable_tiingo,
        "ALT_ENABLE_LUNARCRUSH": body.alt_enable_lunarcrush,
    }
    for key, value in bool_updates.items():
        if value is not None:
            updates[key] = "true" if value else "false"

    float_updates = {
        "ALT_WEIGHT_CAPITOL_TRADES": body.alt_weight_capitol_trades,
        "ALT_WEIGHT_OPENINSIDER": body.alt_weight_openinsider,
        "ALT_WEIGHT_WHALEWISDOM": body.alt_weight_whalewisdom,
        "ALT_WEIGHT_QUIVER_QUANTITATIVE": body.alt_weight_quiver_quantitative,
        "ALT_WEIGHT_ALPHA_VANTAGE": body.alt_weight_alpha_vantage,
        "ALT_WEIGHT_POLYGON": body.alt_weight_polygon,
        "ALT_WEIGHT_FMP": body.alt_weight_fmp,
        "ALT_WEIGHT_EODHD": body.alt_weight_eodhd,
        "ALT_WEIGHT_FRED": body.alt_weight_fred,
        "ALT_WEIGHT_TIINGO": body.alt_weight_tiingo,
        "ALT_WEIGHT_LUNARCRUSH": body.alt_weight_lunarcrush,
    }
    for key, value in float_updates.items():
        if value is not None:
            updates[key] = f"{value:.4f}".rstrip("0").rstrip(".")
    if body.refresh_interval_minutes is not None:
        updates["REFRESH_INTERVAL_MINUTES"] = str(body.refresh_interval_minutes)
    if body.signal_lookback_days is not None:
        updates["SIGNAL_LOOKBACK_DAYS"] = str(body.signal_lookback_days)

    if not updates:
        return {"message": "Nothing to update"}

    _write_env(updates)

    # Reload settings module so new values are picked up
    from importlib import reload
    import app.config as cfg_module
    reload(cfg_module)
    from app.config import settings as new_settings
    import app.config
    app.config.settings = new_settings

    # Reset broker singleton so next request re-authenticates
    import app.api.routes as routes_module
    routes_module._broker = None
    routes_module._broker_connected = False

    logger.info("Profile updated: %s", list(updates.keys()))
    return {"message": "Settings saved", "updated_keys": list(updates.keys())}


@profile_router.post("/test-connection", response_model=TestConnectionResponse)
def test_connection(body: TestConnectionRequest):
    """Instantiate the configured broker and attempt authentication."""
    broker_name = body.broker.lower()
    if broker_name not in ("alpaca", "robinhood", "etrade"):
        raise HTTPException(400, "broker must be alpaca, robinhood, or etrade")

    try:
        from app.config import settings

        if broker_name == "alpaca":
            from app.brokers.alpaca import AlpacaBroker
            b = AlpacaBroker()
        elif broker_name == "robinhood":
            from app.brokers.robinhood import RobinhoodBroker
            b = RobinhoodBroker()
        else:
            from app.brokers.etrade import ETradeBroker
            b = ETradeBroker()
            return TestConnectionResponse(
                broker=broker_name,
                success=False,
                message="E-Trade requires interactive OAuth. Use the E-Trade OAuth flow from the Portfolio tab.",
            )

        ok = b.connect()
        if not ok:
            return TestConnectionResponse(
                broker=broker_name,
                success=False,
                message="Connection failed. Check your credentials.",
            )

        account = b.get_account()
        return TestConnectionResponse(
            broker=broker_name,
            success=True,
            message=f"Connected successfully as account {account.account_id}",
            account_id=account.account_id,
            portfolio_value=account.portfolio_value,
        )
    except Exception as exc:
        logger.exception("Test connection failed for %s", broker_name)
        return TestConnectionResponse(
            broker=broker_name,
            success=False,
            message=str(exc),
        )
