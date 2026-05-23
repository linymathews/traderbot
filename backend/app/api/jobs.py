import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, time as dtime
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from pymongo import MongoClient
from pymongo.collection import Collection

from app.analysis import analyze_symbol
from app.analysis.signals import compute_signals
from app.brokers import get_broker
from app.config import settings
from app.api.auth import get_authenticated_user
from app.api.profile import _apply_profile_to_runtime_settings, _get_or_create_profile

logger = logging.getLogger(__name__)

jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_MONGO_CLIENT: MongoClient | None = None
_JOB_LOOP_TASK: asyncio.Task | None = None

JOBS_COLLECTION = "trading_jobs"
JOB_SETTINGS_COLLECTION = "trading_job_settings"

CHECK_INTERVAL_SECONDS = 300  # every 5 minutes
LOOP_TICK_SECONDS = 30
MARKET_TZ = ZoneInfo("America/New_York")


class JobSettingsUpdate(BaseModel):
    max_total_loss_pct: float = Field(ge=0, le=100)


VALID_ALGORITHMS = [
    "recommendation",
    "rsi_mean_reversion",
    "macd_cross",
    "bollinger_bands",
    "sma_cross",
    "support_resistance",
    "volume_momentum",
]
AlgorithmType = Literal[
    "recommendation",
    "rsi_mean_reversion",
    "macd_cross",
    "bollinger_bands",
    "sma_cross",
    "support_resistance",
    "volume_momentum",
]


class TradingJobCreate(BaseModel):
    ticker: str
    algorithm: AlgorithmType = "recommendation"
    allocated_amount: float = Field(gt=0)
    max_loss_pct: float = Field(default=2.0, ge=0, le=100)
    quantity: Optional[float] = Field(default=None, gt=0)
    trailing_stop_pct: float = Field(default=3.0, ge=0, le=50)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str):
        s = (v or "").strip().upper()
        if not s:
            raise ValueError("ticker is required")
        return s


class TradingJobUpdate(BaseModel):
    ticker: Optional[str] = None
    algorithm: Optional[AlgorithmType] = None
    allocated_amount: Optional[float] = Field(default=None, gt=0)
    max_loss_pct: Optional[float] = Field(default=None, ge=0, le=100)
    quantity: Optional[float] = Field(default=None, gt=0)
    trailing_stop_pct: Optional[float] = Field(default=None, ge=0, le=50)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: Optional[str]):
        if v is None:
            return None
        s = (v or "").strip().upper()
        if not s:
            raise ValueError("ticker cannot be empty")
        return s


class JobActionResponse(BaseModel):
    ok: bool
    message: str


def _mongo_collection(name: str) -> Collection:
    global _MONGO_CLIENT
    if _MONGO_CLIENT is None:
        _MONGO_CLIENT = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=2000)
        _MONGO_CLIENT.admin.command("ping")
    db = _MONGO_CLIENT[settings.mongodb_db_name]
    col = db[name]
    return col


def _jobs_collection() -> Collection:
    col = _mongo_collection(JOBS_COLLECTION)
    col.create_index("id", unique=True)
    col.create_index([("user_id", 1), ("status", 1)])
    return col


def _job_settings_collection() -> Collection:
    col = _mongo_collection(JOB_SETTINGS_COLLECTION)
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


def _serialize_job(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc.get("id"),
        "ticker": doc.get("ticker"),
        "algorithm": doc.get("algorithm"),
        "allocated_amount": doc.get("allocated_amount"),
        "max_loss_pct": doc.get("max_loss_pct"),
        "quantity": doc.get("quantity"),
        "trailing_stop_pct": doc.get("trailing_stop_pct"),
        "status": doc.get("status"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "last_checked_at": doc.get("last_checked_at"),
        "last_price": doc.get("last_price"),
        "last_decision": doc.get("last_decision"),
        "last_action": doc.get("last_action"),
        "last_error": doc.get("last_error"),
        "high_watermark": doc.get("high_watermark"),
        "stop_loss_price": doc.get("stop_loss_price"),
        "trailing_stop_price": doc.get("trailing_stop_price"),
        "held_qty": doc.get("held_qty"),
        "entry_price": doc.get("entry_price"),
        "cost_basis": doc.get("cost_basis"),
        "market_value": doc.get("market_value"),
        "gain_loss_pct": doc.get("gain_loss_pct"),
    }


def _market_status_now() -> dict[str, Any]:
    now = datetime.now(MARKET_TZ)
    open_dt = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_dt = now.replace(hour=16, minute=0, second=0, microsecond=0)

    is_weekday = now.weekday() < 5
    is_open = bool(is_weekday and open_dt <= now < close_dt)

    if is_open:
        next_open = None
        next_close = close_dt
    else:
        if is_weekday and now < open_dt:
            next_open = open_dt
        else:
            d = now + timedelta(days=1)
            while d.weekday() >= 5:
                d += timedelta(days=1)
            next_open = d.replace(hour=9, minute=30, second=0, microsecond=0)
        next_close = next_open.replace(hour=16, minute=0, second=0, microsecond=0)

    return {
        "is_open": is_open,
        "current_time_et": now.isoformat(),
        "next_open_at": next_open.isoformat() if next_open else None,
        "next_close_at": next_close.isoformat() if next_close else None,
    }


def _get_or_create_job_settings(user_id: str) -> dict[str, Any]:
    col = _job_settings_collection()
    doc = col.find_one({"user_id": user_id})
    if doc:
        return doc
    now = int(time.time())
    new_doc = {
        "user_id": user_id,
        "max_total_loss_pct": 10.0,
        "baseline_portfolio_value": None,
        "updated_at": now,
    }
    col.replace_one({"user_id": user_id}, new_doc, upsert=True)
    return new_doc


def _job_decision(algorithm: str, ticker: str, price_history_days: int = 120) -> str:
    if algorithm == "recommendation":
        analysis = analyze_symbol(ticker, congress_trades=[], lookback_days=price_history_days, risk_tolerance=5)
        rec = (analysis.get("final_recommendation") or "HOLD").upper()
        if "BUY" in rec:
            return "BUY"
        if "SELL" in rec:
            return "SELL"
        return "HOLD"

    tech = compute_signals(ticker, analyze_symbol(ticker, congress_trades=[], lookback_days=price_history_days, risk_tolerance=5).get("price_history", []))
    indicators = tech.get("indicators", {})

    if algorithm == "rsi_mean_reversion":
        rsi_val = float(indicators.get("rsi", 50))
        if rsi_val < 30:
            return "BUY"
        if rsi_val > 70:
            return "SELL"
        return "HOLD"

    if algorithm == "macd_cross":
        hist = indicators.get("macd_histogram")
        macd_val = indicators.get("macd")
        sig_val = indicators.get("macd_signal")
        if hist is None or macd_val is None or sig_val is None:
            return "HOLD"
        if float(macd_val) > float(sig_val) and float(hist) > 0:
            return "BUY"
        if float(macd_val) < float(sig_val) and float(hist) < 0:
            return "SELL"
        return "HOLD"

    if algorithm == "bollinger_bands":
        bb_upper = indicators.get("bb_upper")
        bb_lower = indicators.get("bb_lower")
        if bb_upper is None or bb_lower is None:
            return "HOLD"
        # Need current price: re-derive from analyze_symbol price_history last close
        price_hist = analyze_symbol(
            ticker, congress_trades=[], lookback_days=price_history_days, risk_tolerance=5
        ).get("price_history", [])
        if not price_hist:
            return "HOLD"
        cur = float(price_hist[-1].get("close", 0) or 0)
        if cur <= 0:
            return "HOLD"
        if cur < float(bb_lower):
            return "BUY"
        if cur > float(bb_upper):
            return "SELL"
        return "HOLD"

    if algorithm == "sma_cross":
        sma50 = indicators.get("sma50")
        sma200 = indicators.get("sma200")
        if sma50 is None or sma200 is None:
            return "HOLD"
        if float(sma50) > float(sma200):
            return "BUY"
        return "SELL"

    if algorithm == "support_resistance":
        sr = indicators.get("sr_signal", "")
        if "NEAR SUPPORT" in str(sr).upper():
            return "BUY"
        if "NEAR RESISTANCE" in str(sr).upper():
            return "SELL"
        return "HOLD"

    if algorithm == "volume_momentum":
        vol_sig = str(indicators.get("volume_signal") or "").upper()
        macd_sig = str(indicators.get("macd_cross") or "").upper()
        if "SPIKE" in vol_sig and "BULLISH" in macd_sig:
            return "BUY"
        if "SPIKE" in vol_sig and "BEARISH" in macd_sig:
            return "SELL"
        # Fallback to MACD alone
        hist = indicators.get("macd_histogram")
        if hist is not None:
            return "BUY" if float(hist) > 0 else "SELL"
        return "HOLD"

    return "HOLD"


def _safe_get_price(broker, ticker: str, fallback_positions: list[Any]) -> Optional[float]:
    p = broker.get_current_price(ticker)
    if p is not None:
        return float(p)
    for pos in fallback_positions:
        if (pos.symbol or "").upper() == ticker:
            return float(pos.current_price)
    return None


def _process_job(job: dict[str, Any]) -> None:
    user_id = str(job["user_id"])
    now = int(time.time())

    if str(job.get("status", "active")) != "active":
        return

    last_checked = int(job.get("last_checked_at") or 0)
    if now - last_checked < CHECK_INTERVAL_SECONDS:
        return

    jobs_col = _jobs_collection()

    market = _market_status_now()
    if not market["is_open"]:
        jobs_col.update_one(
            {"id": job["id"]},
            {"$set": {
                "last_checked_at": now,
                "last_action": "SKIPPED_MARKET_CLOSED",
                "last_error": f"Market closed. Next open: {market.get('next_open_at')}",
                "updated_at": now,
            }},
        )
        return

    try:
        profile = _get_or_create_profile(user_id)
        _apply_profile_to_runtime_settings(profile)
        broker = get_broker()
        if not broker.connect():
            raise RuntimeError("Broker is not configured or could not connect")

        account = broker.get_account()
        positions = account.positions or []
        ticker = str(job.get("ticker") or "").upper()
        position = next((p for p in positions if (p.asset_type or "stock") == "stock" and (p.symbol or "").upper() == ticker), None)
        held_qty = float(position.quantity) if position else 0.0
        entry_price = float(position.avg_cost) if position else 0.0

        settings_doc = _get_or_create_job_settings(user_id)
        baseline = settings_doc.get("baseline_portfolio_value")
        if baseline is None and account.portfolio_value > 0:
            _job_settings_collection().update_one(
                {"user_id": user_id},
                {"$set": {"baseline_portfolio_value": float(account.portfolio_value), "updated_at": now}},
                upsert=True,
            )
            baseline = float(account.portfolio_value)

        if baseline and float(baseline) > 0:
            max_loss_pct = float(settings_doc.get("max_total_loss_pct", 10.0))
            drawdown_pct = (float(baseline) - float(account.portfolio_value)) / float(baseline) * 100
            if drawdown_pct >= max_loss_pct:
                jobs_col.update_one(
                    {"id": job["id"]},
                    {"$set": {
                        "last_checked_at": now,
                        "last_error": f"Global max loss reached ({drawdown_pct:.2f}% >= {max_loss_pct:.2f}%). Actions skipped.",
                        "updated_at": now,
                    }},
                )
                return

        price = _safe_get_price(broker, ticker, positions)
        if price is None:
            raise RuntimeError(f"Could not fetch price for {ticker}")

        high_watermark = float(job.get("high_watermark") or 0)
        max_loss_pct = float(job.get("max_loss_pct") or 0)
        trailing_stop_pct = float(job.get("trailing_stop_pct") or 0)
        stop_loss_price = None
        trailing_stop_price = None

        if held_qty > 0:
            high_watermark = max(high_watermark, price)
            if max_loss_pct > 0 and entry_price > 0:
                stop_loss_price = entry_price * (1 - max_loss_pct / 100.0)
            if trailing_stop_pct > 0:
                trailing_stop_price = high_watermark * (1 - trailing_stop_pct / 100.0)

        decision = _job_decision(str(job.get("algorithm") or "recommendation"), ticker)

        action = "NONE"
        protect_thresholds = [v for v in [stop_loss_price, trailing_stop_price] if v is not None]
        if held_qty > 0 and protect_thresholds:
            protect_price = max(protect_thresholds)
            if price <= protect_price:
                decision = "SELL"
                action = "PROTECTIVE_STOP_TRIGGERED"

        qty_cfg = float(job.get("quantity") or 0)
        allocated_amount = float(job.get("allocated_amount") or 0)
        order_info = None

        if decision == "BUY" and held_qty <= 0:
            buy_qty = qty_cfg if qty_cfg > 0 else (allocated_amount / price if allocated_amount > 0 and price > 0 else 0)
            if buy_qty > 0:
                order_info = broker.submit_market_order(symbol=ticker, side="buy", quantity=buy_qty)
                action = f"BUY_PLACED:{order_info.get('id', 'unknown')}"
            else:
                action = "BUY_SKIPPED_ZERO_QTY"
        elif decision == "SELL" and held_qty > 0:
            sell_qty = min(held_qty, qty_cfg if qty_cfg > 0 else held_qty)
            if sell_qty > 0:
                order_info = broker.submit_market_order(symbol=ticker, side="sell", quantity=sell_qty)
                action = f"SELL_PLACED:{order_info.get('id', 'unknown')}"

        gain_loss_pct = None
        cost_basis = None
        market_value = None
        if held_qty > 0:
            if entry_price > 0:
                gain_loss_pct = round((price - entry_price) / entry_price * 100, 2)
                cost_basis = round(held_qty * entry_price, 4)
            market_value = round(held_qty * price, 4)

        jobs_col.update_one(
            {"id": job["id"]},
            {"$set": {
                "last_checked_at": now,
                "last_price": price,
                "last_decision": decision,
                "last_action": action,
                "last_error": None,
                "high_watermark": high_watermark if high_watermark > 0 else None,
                "stop_loss_price": stop_loss_price,
                "trailing_stop_price": trailing_stop_price,
                "held_qty": held_qty,
                "entry_price": entry_price if held_qty > 0 else None,
                "cost_basis": cost_basis,
                "market_value": market_value,
                "gain_loss_pct": gain_loss_pct,
                "updated_at": now,
            }},
        )
    except Exception as exc:
        logger.exception("Automated job failed id=%s", job.get("id"))
        jobs_col.update_one(
            {"id": job["id"]},
            {"$set": {
                "last_checked_at": now,
                "last_error": str(exc),
                "updated_at": now,
            }},
        )


async def _job_loop() -> None:
    logger.info("Automated trading job loop started")
    while True:
        try:
            jobs = list(_jobs_collection().find({"status": "active"}))
            for job in jobs:
                _process_job(job)
        except Exception:
            logger.exception("Automated trading loop tick failed")
        await asyncio.sleep(LOOP_TICK_SECONDS)


def start_job_loop() -> None:
    global _JOB_LOOP_TASK
    if _JOB_LOOP_TASK is None or _JOB_LOOP_TASK.done():
        _JOB_LOOP_TASK = asyncio.create_task(_job_loop())


def stop_job_loop() -> None:
    global _JOB_LOOP_TASK
    if _JOB_LOOP_TASK and not _JOB_LOOP_TASK.done():
        _JOB_LOOP_TASK.cancel()


@jobs_router.get("/settings")
def get_job_settings(request: Request):
    user_id = _require_user_id(request)
    s = _get_or_create_job_settings(user_id)
    return {
        "max_total_loss_pct": float(s.get("max_total_loss_pct", 10.0)),
        "baseline_portfolio_value": s.get("baseline_portfolio_value"),
    }


@jobs_router.get("/market-status")
def get_market_status(request: Request):
    _ = _require_user_id(request)
    market = _market_status_now()
    market["check_interval_seconds"] = CHECK_INTERVAL_SECONDS
    return market


@jobs_router.put("/settings")
def update_job_settings(request: Request, body: JobSettingsUpdate):
    user_id = _require_user_id(request)
    now = int(time.time())
    _job_settings_collection().update_one(
        {"user_id": user_id},
        {"$set": {"max_total_loss_pct": float(body.max_total_loss_pct), "updated_at": now}},
        upsert=True,
    )
    return {"ok": True, "message": "Job settings updated"}


@jobs_router.get("")
def list_jobs(request: Request):
    user_id = _require_user_id(request)
    docs = list(_jobs_collection().find({"user_id": user_id}).sort("created_at", -1))
    return {"jobs": [_serialize_job(d) for d in docs]}


@jobs_router.post("")
def create_job(request: Request, body: TradingJobCreate):
    user_id = _require_user_id(request)
    now = int(time.time())
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "ticker": body.ticker,
        "algorithm": body.algorithm,
        "allocated_amount": float(body.allocated_amount),
        "max_loss_pct": float(body.max_loss_pct),
        "quantity": float(body.quantity) if body.quantity is not None else None,
        "trailing_stop_pct": float(body.trailing_stop_pct),
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "last_checked_at": None,
        "last_price": None,
        "last_decision": None,
        "last_action": None,
        "last_error": None,
        "high_watermark": None,
        "stop_loss_price": None,
        "trailing_stop_price": None,
    }
    _jobs_collection().insert_one(doc)
    return {"ok": True, "job": _serialize_job(doc)}


@jobs_router.put("/{job_id}")
def edit_job(request: Request, job_id: str, body: TradingJobUpdate):
    user_id = _require_user_id(request)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"ok": True, "message": "No changes"}

    updates["updated_at"] = int(time.time())
    if "ticker" in updates:
        updates["ticker"] = str(updates["ticker"]).upper()
        updates["high_watermark"] = None
        updates["stop_loss_price"] = None
        updates["trailing_stop_price"] = None

    res = _jobs_collection().update_one({"id": job_id, "user_id": user_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "Job not found")
    doc = _jobs_collection().find_one({"id": job_id, "user_id": user_id})
    return {"ok": True, "job": _serialize_job(doc)}


@jobs_router.post("/{job_id}/pause", response_model=JobActionResponse)
def pause_job(request: Request, job_id: str):
    user_id = _require_user_id(request)
    res = _jobs_collection().update_one(
        {"id": job_id, "user_id": user_id},
        {"$set": {"status": "paused", "updated_at": int(time.time())}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Job not found")
    return JobActionResponse(ok=True, message="Job paused")


@jobs_router.post("/{job_id}/resume", response_model=JobActionResponse)
def resume_job(request: Request, job_id: str):
    user_id = _require_user_id(request)
    res = _jobs_collection().update_one(
        {"id": job_id, "user_id": user_id},
        {"$set": {"status": "active", "updated_at": int(time.time()), "last_error": None}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Job not found")
    return JobActionResponse(ok=True, message="Job resumed")


@jobs_router.post("/{job_id}/stop", response_model=JobActionResponse)
def stop_job(request: Request, job_id: str):
    user_id = _require_user_id(request)
    res = _jobs_collection().update_one(
        {"id": job_id, "user_id": user_id},
        {"$set": {"status": "stopped", "updated_at": int(time.time())}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Job not found")
    return JobActionResponse(ok=True, message="Job stopped")


@jobs_router.delete("/{job_id}", response_model=JobActionResponse)
def delete_job(request: Request, job_id: str):
    user_id = _require_user_id(request)
    res = _jobs_collection().delete_one({"id": job_id, "user_id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Job not found")
    return JobActionResponse(ok=True, message="Job deleted")
