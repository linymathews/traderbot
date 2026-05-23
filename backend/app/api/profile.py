"""User profile/settings management in MongoDB."""

import logging
import re
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
from pymongo import MongoClient
from pymongo.collection import Collection

from app.api.auth import get_authenticated_user
from app.config import settings

logger = logging.getLogger(__name__)
profile_router = APIRouter(prefix="/api/profile", tags=["profile"])

_PROFILE_COLLECTION = "user_profiles"
_MONGO_CLIENT: MongoClient | None = None


def _mongo_profiles_collection() -> Collection:
    global _MONGO_CLIENT
    if _MONGO_CLIENT is None:
        try:
            _MONGO_CLIENT = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=2000)
            _MONGO_CLIENT.admin.command("ping")
        except Exception as exc:
            raise HTTPException(503, f"MongoDB unavailable: {exc}") from exc

    db = _MONGO_CLIENT[settings.mongodb_db_name]
    col = db[_PROFILE_COLLECTION]
    col.create_index("user_id", unique=True)
    return col


def _require_user_id(request: Request) -> str:
    user = get_authenticated_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")
    user_id = user.get("sub") or user.get("email")
    if not user_id:
        raise HTTPException(401, "Authenticated user has no stable id")
    return str(user_id)


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return "•" * (len(value) - 4) + value[-4:]


def _default_profile() -> dict[str, Any]:
    return {
        "active_broker": settings.active_broker,
        # Never copy server-side broker/API secrets into a new user profile.
        "alpaca_api_key": "",
        "alpaca_secret_key": "",
        "alpaca_paper": settings.alpaca_paper,
        "robinhood_username": "",
        "robinhood_password": "",
        "robinhood_totp_secret": "",
        "etrade_consumer_key": "",
        "etrade_consumer_secret": "",
        "etrade_sandbox": settings.etrade_sandbox,
        "capitol_trades_enabled": settings.capitol_trades_enabled,
        "quiver_quant_api_key": "",
        "alt_enable_capitol_trades": settings.alt_enable_capitol_trades,
        "alt_enable_openinsider": settings.alt_enable_openinsider,
        "alt_enable_whalewisdom": settings.alt_enable_whalewisdom,
        "alt_enable_quiver_quantitative": settings.alt_enable_quiver_quantitative,
        "alt_enable_alpha_vantage": settings.alt_enable_alpha_vantage,
        "alt_enable_polygon": settings.alt_enable_polygon,
        "alt_enable_fmp": settings.alt_enable_fmp,
        "alt_enable_eodhd": settings.alt_enable_eodhd,
        "alt_enable_fred": settings.alt_enable_fred,
        "alt_enable_tiingo": settings.alt_enable_tiingo,
        "alt_enable_lunarcrush": settings.alt_enable_lunarcrush,
        "alt_weight_capitol_trades": settings.alt_weight_capitol_trades,
        "alt_weight_openinsider": settings.alt_weight_openinsider,
        "alt_weight_whalewisdom": settings.alt_weight_whalewisdom,
        "alt_weight_quiver_quantitative": settings.alt_weight_quiver_quantitative,
        "alt_weight_alpha_vantage": settings.alt_weight_alpha_vantage,
        "alt_weight_polygon": settings.alt_weight_polygon,
        "alt_weight_fmp": settings.alt_weight_fmp,
        "alt_weight_eodhd": settings.alt_weight_eodhd,
        "alt_weight_fred": settings.alt_weight_fred,
        "alt_weight_tiingo": settings.alt_weight_tiingo,
        "alt_weight_lunarcrush": settings.alt_weight_lunarcrush,
        "refresh_interval_minutes": settings.refresh_interval_minutes,
        "signal_lookback_days": settings.signal_lookback_days,
        "risk_tolerance": 5,  # 1 (very conservative) to 10 (very aggressive)
    }


def _get_or_create_profile(user_id: str) -> dict[str, Any]:
    col = _mongo_profiles_collection()
    doc = col.find_one({"user_id": user_id})
    if doc:
        return doc
    now = int(time.time())
    profile = {"user_id": user_id, "created_at": now, "updated_at": now, **_default_profile()}
    col.replace_one({"user_id": user_id}, profile, upsert=True)
    return profile


def _persist_profile(user_id: str, updates: dict[str, Any]) -> None:
    col = _mongo_profiles_collection()
    updates["updated_at"] = int(time.time())
    col.update_one({"user_id": user_id}, {"$set": updates}, upsert=True)


def _apply_profile_to_runtime_settings(profile: dict[str, Any]) -> None:
    settings.active_broker = str(profile.get("active_broker") or settings.active_broker)
    settings.alpaca_api_key = str(profile.get("alpaca_api_key") or "")
    settings.alpaca_secret_key = str(profile.get("alpaca_secret_key") or "")
    settings.alpaca_paper = bool(profile.get("alpaca_paper", settings.alpaca_paper))
    settings.robinhood_username = str(profile.get("robinhood_username") or "")
    settings.robinhood_password = str(profile.get("robinhood_password") or "")
    settings.robinhood_totp_secret = str(profile.get("robinhood_totp_secret") or "")
    settings.etrade_consumer_key = str(profile.get("etrade_consumer_key") or "")
    settings.etrade_consumer_secret = str(profile.get("etrade_consumer_secret") or "")
    settings.etrade_sandbox = bool(profile.get("etrade_sandbox", settings.etrade_sandbox))


def get_user_profile_for_request(request: Request) -> tuple[str, dict[str, Any]]:
    user_id = _require_user_id(request)
    return user_id, _get_or_create_profile(user_id)


def apply_user_profile_to_runtime_for_request(request: Request) -> tuple[str, dict[str, Any]]:
    user_id, profile = get_user_profile_for_request(request)
    _apply_profile_to_runtime_settings(profile)
    return user_id, profile


class ProfileResponse(BaseModel):
    active_broker: str
    alpaca_api_key_masked: str
    alpaca_secret_key_masked: str
    alpaca_paper: bool
    alpaca_configured: bool
    robinhood_username: str
    robinhood_password_masked: str
    robinhood_totp_configured: bool
    robinhood_configured: bool
    etrade_consumer_key_masked: str
    etrade_consumer_secret_masked: str
    etrade_sandbox: bool
    etrade_configured: bool
    capitol_trades_enabled: bool
    quiver_quant_api_key_masked: str
    quiver_quant_configured: bool
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
    refresh_interval_minutes: int
    signal_lookback_days: int
    risk_tolerance: int


class ProfileUpdate(BaseModel):
    active_broker: Optional[str] = None
    alpaca_api_key: Optional[str] = None
    alpaca_secret_key: Optional[str] = None
    alpaca_paper: Optional[bool] = None
    robinhood_username: Optional[str] = None
    robinhood_password: Optional[str] = None
    robinhood_totp_secret: Optional[str] = None
    etrade_consumer_key: Optional[str] = None
    etrade_consumer_secret: Optional[str] = None
    etrade_sandbox: Optional[bool] = None
    capitol_trades_enabled: Optional[bool] = None
    quiver_quant_api_key: Optional[str] = None
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
    refresh_interval_minutes: Optional[int] = None
    signal_lookback_days: Optional[int] = None
    risk_tolerance: Optional[int] = None

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

    @field_validator("risk_tolerance")
    @classmethod
    def validate_risk_tolerance(cls, v):
        if v is not None and (v < 1 or v > 10):
            raise ValueError("risk_tolerance must be between 1 and 10")
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
    broker: str
    alpaca_api_key: Optional[str] = None
    alpaca_secret_key: Optional[str] = None
    alpaca_paper: Optional[bool] = None
    robinhood_username: Optional[str] = None
    robinhood_password: Optional[str] = None
    robinhood_totp_secret: Optional[str] = None
    etrade_consumer_key: Optional[str] = None
    etrade_consumer_secret: Optional[str] = None
    etrade_sandbox: Optional[bool] = None


class TestConnectionResponse(BaseModel):
    broker: str
    success: bool
    message: str
    account_id: Optional[str] = None
    portfolio_value: Optional[float] = None


def _profile_to_response(profile: dict[str, Any]) -> ProfileResponse:
    alpaca_key = str(profile.get("alpaca_api_key") or "")
    alpaca_secret = str(profile.get("alpaca_secret_key") or "")
    rh_user = str(profile.get("robinhood_username") or "")
    rh_pass = str(profile.get("robinhood_password") or "")
    rh_totp = str(profile.get("robinhood_totp_secret") or "")
    et_key = str(profile.get("etrade_consumer_key") or "")
    et_secret = str(profile.get("etrade_consumer_secret") or "")
    qq_key = str(profile.get("quiver_quant_api_key") or "")
    return ProfileResponse(
        active_broker=str(profile.get("active_broker") or "alpaca"),
        alpaca_api_key_masked=_mask(alpaca_key),
        alpaca_secret_key_masked=_mask(alpaca_secret),
        alpaca_paper=bool(profile.get("alpaca_paper", True)),
        alpaca_configured=bool(alpaca_key and alpaca_secret),
        robinhood_username=rh_user,
        robinhood_password_masked=_mask(rh_pass),
        robinhood_totp_configured=bool(rh_totp),
        robinhood_configured=bool(rh_user and rh_pass),
        etrade_consumer_key_masked=_mask(et_key),
        etrade_consumer_secret_masked=_mask(et_secret),
        etrade_sandbox=bool(profile.get("etrade_sandbox", True)),
        etrade_configured=bool(et_key and et_secret),
        capitol_trades_enabled=bool(profile.get("capitol_trades_enabled", True)),
        quiver_quant_api_key_masked=_mask(qq_key),
        quiver_quant_configured=bool(qq_key),
        alt_enable_capitol_trades=bool(profile.get("alt_enable_capitol_trades", True)),
        alt_enable_openinsider=bool(profile.get("alt_enable_openinsider", True)),
        alt_enable_whalewisdom=bool(profile.get("alt_enable_whalewisdom", True)),
        alt_enable_quiver_quantitative=bool(profile.get("alt_enable_quiver_quantitative", True)),
        alt_enable_alpha_vantage=bool(profile.get("alt_enable_alpha_vantage", True)),
        alt_enable_polygon=bool(profile.get("alt_enable_polygon", True)),
        alt_enable_fmp=bool(profile.get("alt_enable_fmp", True)),
        alt_enable_eodhd=bool(profile.get("alt_enable_eodhd", True)),
        alt_enable_fred=bool(profile.get("alt_enable_fred", True)),
        alt_enable_tiingo=bool(profile.get("alt_enable_tiingo", True)),
        alt_enable_lunarcrush=bool(profile.get("alt_enable_lunarcrush", True)),
        alt_weight_capitol_trades=float(profile.get("alt_weight_capitol_trades", 1.0)),
        alt_weight_openinsider=float(profile.get("alt_weight_openinsider", 1.0)),
        alt_weight_whalewisdom=float(profile.get("alt_weight_whalewisdom", 0.35)),
        alt_weight_quiver_quantitative=float(profile.get("alt_weight_quiver_quantitative", 0.9)),
        alt_weight_alpha_vantage=float(profile.get("alt_weight_alpha_vantage", 0.85)),
        alt_weight_polygon=float(profile.get("alt_weight_polygon", 0.6)),
        alt_weight_fmp=float(profile.get("alt_weight_fmp", 0.35)),
        alt_weight_eodhd=float(profile.get("alt_weight_eodhd", 0.55)),
        alt_weight_fred=float(profile.get("alt_weight_fred", 0.45)),
        alt_weight_tiingo=float(profile.get("alt_weight_tiingo", 0.25)),
        alt_weight_lunarcrush=float(profile.get("alt_weight_lunarcrush", 0.5)),
        refresh_interval_minutes=int(profile.get("refresh_interval_minutes", 15)),
        signal_lookback_days=int(profile.get("signal_lookback_days", 90)),
        risk_tolerance=int(profile.get("risk_tolerance", 5)),
    )


@profile_router.get("", response_model=ProfileResponse)
def get_profile(request: Request):
    user_id = _require_user_id(request)
    profile = _get_or_create_profile(user_id)
    return _profile_to_response(profile)


@profile_router.put("")
def update_profile(request: Request, body: ProfileUpdate):
    user_id = _require_user_id(request)
    _get_or_create_profile(user_id)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"message": "Nothing to update"}

    secret_fields = {
        "alpaca_api_key",
        "alpaca_secret_key",
        "robinhood_password",
        "robinhood_totp_secret",
        "etrade_consumer_key",
        "etrade_consumer_secret",
        "quiver_quant_api_key",
    }

    cleaned: dict[str, Any] = {}
    for key, value in updates.items():
        if key in secret_fields and isinstance(value, str) and re.match(r"^[•*]+$", value):
            continue
        cleaned[key] = value

    if not cleaned:
        return {"message": "Nothing to update"}

    _persist_profile(user_id, cleaned)
    logger.info("Profile updated for user %s: %s", user_id, list(cleaned.keys()))
    return {"message": "Settings saved", "updated_keys": list(cleaned.keys())}


@profile_router.post("/test-connection", response_model=TestConnectionResponse)
def test_connection(request: Request, body: TestConnectionRequest):
    user_id = _require_user_id(request)
    profile = _get_or_create_profile(user_id)
    test_profile = dict(profile)

    broker_name = body.broker.lower()
    if broker_name not in ("alpaca", "robinhood", "etrade"):
        raise HTTPException(400, "broker must be alpaca, robinhood, or etrade")

    # Allow test-connection to use unsaved form values without persisting them.
    if broker_name == "alpaca":
        if body.alpaca_api_key is not None:
            test_profile["alpaca_api_key"] = body.alpaca_api_key.strip()
        if body.alpaca_secret_key is not None:
            test_profile["alpaca_secret_key"] = body.alpaca_secret_key.strip()
        if body.alpaca_paper is not None:
            test_profile["alpaca_paper"] = bool(body.alpaca_paper)
    elif broker_name == "robinhood":
        if body.robinhood_username is not None:
            test_profile["robinhood_username"] = body.robinhood_username.strip()
        if body.robinhood_password is not None:
            test_profile["robinhood_password"] = body.robinhood_password.strip()
        if body.robinhood_totp_secret is not None:
            test_profile["robinhood_totp_secret"] = body.robinhood_totp_secret.strip()
    elif broker_name == "etrade":
        if body.etrade_consumer_key is not None:
            test_profile["etrade_consumer_key"] = body.etrade_consumer_key.strip()
        if body.etrade_consumer_secret is not None:
            test_profile["etrade_consumer_secret"] = body.etrade_consumer_secret.strip()
        if body.etrade_sandbox is not None:
            test_profile["etrade_sandbox"] = bool(body.etrade_sandbox)

    try:
        _apply_profile_to_runtime_settings(test_profile)

        if broker_name == "alpaca":
            from app.brokers.alpaca import AlpacaBroker
            broker = AlpacaBroker()
        elif broker_name == "robinhood":
            from app.brokers.robinhood import RobinhoodBroker
            broker = RobinhoodBroker()
        else:
            return TestConnectionResponse(
                broker=broker_name,
                success=False,
                message="E-Trade requires interactive OAuth. Use the E-Trade OAuth flow from the Portfolio tab.",
            )

        ok = broker.connect()
        if not ok:
            return TestConnectionResponse(
                broker=broker_name,
                success=False,
                message="Connection failed. Check your credentials.",
            )

        # Persist the broker settings that were just verified so Portfolio uses
        # the same working configuration immediately after a successful test.
        successful_updates: dict[str, Any] = {"active_broker": broker_name}
        if broker_name == "alpaca":
            if body.alpaca_api_key is not None:
                successful_updates["alpaca_api_key"] = test_profile.get("alpaca_api_key", "")
            if body.alpaca_secret_key is not None:
                successful_updates["alpaca_secret_key"] = test_profile.get("alpaca_secret_key", "")
            if body.alpaca_paper is not None:
                successful_updates["alpaca_paper"] = bool(test_profile.get("alpaca_paper", settings.alpaca_paper))
        elif broker_name == "robinhood":
            if body.robinhood_username is not None:
                successful_updates["robinhood_username"] = test_profile.get("robinhood_username", "")
            if body.robinhood_password is not None:
                successful_updates["robinhood_password"] = test_profile.get("robinhood_password", "")
            if body.robinhood_totp_secret is not None:
                successful_updates["robinhood_totp_secret"] = test_profile.get("robinhood_totp_secret", "")
        elif broker_name == "etrade":
            if body.etrade_consumer_key is not None:
                successful_updates["etrade_consumer_key"] = test_profile.get("etrade_consumer_key", "")
            if body.etrade_consumer_secret is not None:
                successful_updates["etrade_consumer_secret"] = test_profile.get("etrade_consumer_secret", "")
            if body.etrade_sandbox is not None:
                successful_updates["etrade_sandbox"] = bool(test_profile.get("etrade_sandbox", settings.etrade_sandbox))

        _persist_profile(user_id, successful_updates)

        account = broker.get_account()
        return TestConnectionResponse(
            broker=broker_name,
            success=True,
            message=f"Connected successfully as account {account.account_id}",
            account_id=str(account.account_id),
            portfolio_value=account.portfolio_value,
        )
    except Exception as exc:
        logger.exception("Test connection failed for %s user=%s", broker_name, user_id)
        return TestConnectionResponse(
            broker=broker_name,
            success=False,
            message=str(exc),
        )
