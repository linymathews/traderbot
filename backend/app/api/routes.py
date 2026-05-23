"""
FastAPI routes.
"""

import asyncio
import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.brokers import get_broker
from app.brokers.base import BaseBroker
from app.data_sources.congress_trades import get_congress_trades, filter_congress_trades
from app.analysis import analyze_symbol
from app.config import settings
from app.api.profile import apply_user_profile_to_runtime_for_request

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Per-user broker cache ─────────────────────────────────────────────────────
_brokers: dict[str, BaseBroker] = {}
_broker_connected: dict[str, bool] = {}
_broker_name: dict[str, str] = {}
_broker_profile_updated_at: dict[str, int] = {}


def _get_broker_for_user(request: Request) -> tuple[str, dict[str, Any], BaseBroker]:
    user_id, profile = apply_user_profile_to_runtime_for_request(request)
    active_broker = str(profile.get("active_broker") or settings.active_broker).lower()
    profile_updated_at = int(profile.get("updated_at") or 0)

    broker = _brokers.get(user_id)
    cache_outdated = _broker_profile_updated_at.get(user_id, 0) != profile_updated_at
    if broker is None or _broker_name.get(user_id) != active_broker or cache_outdated:
        broker = get_broker()
        _brokers[user_id] = broker
        _broker_connected[user_id] = False
        _broker_name[user_id] = active_broker
        _broker_profile_updated_at[user_id] = profile_updated_at

    if not _broker_connected.get(user_id, False):
        _broker_connected[user_id] = broker.connect()

    return user_id, profile, broker


def _require_connected_broker_for_user(request: Request) -> tuple[str, dict[str, Any], BaseBroker]:
    user_id, profile, broker = _get_broker_for_user(request)
    if not _broker_connected.get(user_id, False):
        raise HTTPException(503, "Broker is not configured or could not connect")
    return user_id, profile, broker


# ── E-Trade OAuth helpers ─────────────────────────────────────────────────────
@router.get("/broker/etrade/auth", tags=["broker"])
def etrade_auth_start(request: Request):
    from app.brokers.etrade import ETradeBroker

    user_id, _profile = apply_user_profile_to_runtime_for_request(request)
    broker = ETradeBroker()
    _brokers[user_id] = broker
    _broker_connected[user_id] = False
    _broker_name[user_id] = "etrade"
    url = broker.get_oauth_url()
    return {"message": "Open this URL in a browser to authorize", "oauth_url": url}


class ETradeVerifier(BaseModel):
    verifier: str


class TradeOrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    instrument_type: str = "stock"  # stock | option
    order_type: str = "market"      # market | limit
    time_in_force: str = "day"      # day | gtc | ioc | fok
    limit_price: Optional[float] = None
    account_id: Optional[str] = None


@router.post("/broker/etrade/auth", tags=["broker"])
def etrade_auth_complete(request: Request, body: ETradeVerifier):
    from app.brokers.etrade import ETradeBroker

    user_id, _profile = apply_user_profile_to_runtime_for_request(request)
    broker = _brokers.get(user_id)
    if not isinstance(broker, ETradeBroker):
        raise HTTPException(400, "E-Trade OAuth not started. Call GET /broker/etrade/auth first.")
    ok = broker.complete_oauth(body.verifier)
    _broker_connected[user_id] = ok
    if not ok:
        raise HTTPException(400, "OAuth verification failed")
    return {"message": "E-Trade connected successfully"}


# ── Broker status ─────────────────────────────────────────────────────────────
@router.get("/broker/status", tags=["broker"])
def broker_status(request: Request):
    user_id, profile, _broker = _get_broker_for_user(request)
    active_broker = str(profile.get("active_broker") or settings.active_broker)
    alpaca_paper = bool(profile.get("alpaca_paper", settings.alpaca_paper))
    return {
        "active_broker": active_broker,
        "connected": bool(_broker_connected.get(user_id, False)),
        "paper_mode": alpaca_paper if active_broker == "alpaca" else None,
    }


# ── Account & portfolio ───────────────────────────────────────────────────────
@router.get("/account", tags=["account"])
def get_account(request: Request):
    try:
        _user_id, _profile, broker = _get_broker_for_user(request)
        account = broker.get_account()
        return {
            "broker": account.broker,
            "account_id": account.account_id,
            "cash": account.cash,
            "portfolio_value": account.portfolio_value,
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_cost": p.avg_cost,
                    "current_price": p.current_price,
                    "market_value": p.market_value,
                    "unrealized_pl": p.unrealized_pl,
                    "unrealized_pl_pct": p.unrealized_pl_pct,
                    "asset_type": p.asset_type,
                    "underlying_symbol": p.underlying_symbol,
                    "option_type": p.option_type,
                    "strike": p.strike,
                    "expiration": p.expiration,
                }
                for p in account.positions
            ],
        }
    except Exception as exc:
        logger.exception("Failed to fetch account")
        raise HTTPException(500, str(exc))


# ── Analysis ──────────────────────────────────────────────────────────────────
@router.get("/analysis", tags=["analysis"])
async def get_analysis(request: Request):
    """Analyze all portfolio positions and return buy/sell suggestions."""
    try:
        _user_id, profile, broker = _get_broker_for_user(request)
        lookback_days = int(profile.get("signal_lookback_days", settings.signal_lookback_days))
        account = broker.get_account()
        pending_orders = broker.get_pending_orders()
        symbols = [p.symbol for p in account.positions if (p.asset_type or "stock") == "stock"]
        if not symbols:
            total_positions = len(account.positions)
            message = "No positions in portfolio"
            if total_positions > 0:
                message = "No stock positions found for analysis (positions may be options or unsupported types)"
            return {
                "account_summary": {
                    "broker": account.broker,
                    "portfolio_value": account.portfolio_value,
                    "cash": account.cash,
                    "positions_count": total_positions,
                    "pending_orders_count": len(pending_orders),
                },
                "analyses": [],
                "pending_orders": pending_orders,
                "message": message,
            }

        # Fetch congress trades once for all symbols
        loop = asyncio.get_event_loop()
        congress_trades = await loop.run_in_executor(
            None, get_congress_trades, symbols, lookback_days
        )
        congress_trades = filter_congress_trades(
            congress_trades,
            disclosed_days=30,
            require_ticker=True,
        )

        # Analyze each symbol concurrently
        risk_tolerance = int(profile.get("risk_tolerance", 5))
        async def _analyze(sym: str) -> dict:
            return await loop.run_in_executor(None, analyze_symbol, sym, congress_trades, lookback_days, risk_tolerance)

        analyses = await asyncio.gather(*[_analyze(s) for s in symbols])

        # Attach position data
        pos_map = {p.symbol: p for p in account.positions}
        results = []
        for a in analyses:
            sym = a["symbol"]
            pos = pos_map.get(sym)
            results.append(
                {
                    **a,
                    "position": {
                        "quantity": pos.quantity if pos else 0,
                        "avg_cost": pos.avg_cost if pos else 0,
                        "current_price": pos.current_price if pos else 0,
                        "market_value": pos.market_value if pos else 0,
                        "unrealized_pl": pos.unrealized_pl if pos else 0,
                        "unrealized_pl_pct": pos.unrealized_pl_pct if pos else 0,
                    },
                }
            )

        results.sort(key=lambda x: x["combined_score"], reverse=True)
        return {
            "account_summary": {
                "broker": account.broker,
                "portfolio_value": account.portfolio_value,
                "cash": account.cash,
                "positions_count": len(account.positions),
                "pending_orders_count": len(pending_orders),
            },
            "analyses": results,
            "pending_orders": pending_orders,
        }
    except Exception as exc:
        logger.exception("Analysis failed")
        raise HTTPException(500, str(exc))


# ── Trading helpers ──────────────────────────────────────────────────────────
@router.get("/trade/summary/{symbol}", tags=["trade"])
def get_trade_summary(request: Request, symbol: str):
    symbol = symbol.upper()
    try:
        _user_id, _profile, broker = _require_connected_broker_for_user(request)
        account = broker.get_account()

        stock_shares = 0.0
        option_positions: list[dict[str, Any]] = []
        for p in account.positions:
            asset_type = p.asset_type or "stock"
            if asset_type == "stock" and p.symbol == symbol:
                stock_shares += float(p.quantity or 0)
            elif asset_type == "option":
                under = (p.underlying_symbol or "").upper()
                if under == symbol:
                    option_positions.append(
                        {
                            "symbol": p.symbol,
                            "quantity": p.quantity,
                            "option_type": p.option_type,
                            "strike": p.strike,
                            "expiration": p.expiration,
                            "market_value": p.market_value,
                            "unrealized_pl": p.unrealized_pl,
                            "unrealized_pl_pct": p.unrealized_pl_pct,
                        }
                    )

        return {
            "symbol": symbol,
            "broker": account.broker,
            "selected_account": account.account_id,
            "accounts": [
                {
                    "account_id": account.account_id,
                    "label": f"{account.broker.upper()} {account.account_id}",
                }
            ],
            "stock_shares": round(stock_shares, 4),
            "option_contracts": round(sum(float(op.get("quantity", 0) or 0) for op in option_positions), 4),
            "option_positions": option_positions,
        }
    except Exception as exc:
        logger.exception("Trade summary fetch failed")
        raise HTTPException(500, str(exc))


@router.post("/trade/order", tags=["trade"])
def place_trade_order(request: Request, body: TradeOrderRequest):
    try:
        _user_id, _profile, broker = _require_connected_broker_for_user(request)
        account = broker.get_account()

        if body.account_id and body.account_id != account.account_id:
            raise HTTPException(400, f"Unknown account_id '{body.account_id}' for active broker")

        symbol = body.symbol.strip().upper()
        if not symbol:
            raise HTTPException(400, "symbol is required")

        side = body.side.strip().lower()
        if side not in {"buy", "sell"}:
            raise HTTPException(400, "side must be 'buy' or 'sell'")

        instrument_type = body.instrument_type.strip().lower()
        if instrument_type not in {"stock", "option"}:
            raise HTTPException(400, "instrument_type must be 'stock' or 'option'")

        if body.quantity <= 0:
            raise HTTPException(400, "quantity must be > 0")

        order_type = body.order_type.strip().lower()
        if order_type not in {"market", "limit"}:
            raise HTTPException(400, "order_type must be 'market' or 'limit'")

        time_in_force = body.time_in_force.strip().lower()
        if time_in_force not in {"day", "gtc", "ioc", "fok"}:
            raise HTTPException(400, "time_in_force must be one of day|gtc|ioc|fok")

        limit_price = body.limit_price
        if order_type == "limit":
            if limit_price is None or float(limit_price) <= 0:
                raise HTTPException(400, "limit_price must be > 0 for limit orders")
        else:
            limit_price = None

        try:
            order = broker.submit_market_order(
                symbol=symbol,
                side=side,
                quantity=float(body.quantity),
                instrument_type=instrument_type,
                order_type=order_type,
                time_in_force=time_in_force,
                limit_price=float(limit_price) if limit_price is not None else None,
            )
        except NotImplementedError as exc:
            raise HTTPException(501, str(exc)) from exc

        return {
            "ok": True,
            "message": f"{side.upper()} {body.quantity} {instrument_type} {order_type} order submitted for {symbol}",
            "order": order,
            "account_id": account.account_id,
            "broker": account.broker,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Order placement failed")
        raise HTTPException(500, str(exc))


@router.get("/analysis/{symbol}", tags=["analysis"])
async def get_symbol_analysis(request: Request, symbol: str):
    """Analyze a single symbol (does not need to be in portfolio)."""
    symbol = symbol.upper()
    try:
        _user_id, profile = apply_user_profile_to_runtime_for_request(request)
        lookback_days = int(profile.get("signal_lookback_days", settings.signal_lookback_days))
        risk_tolerance = int(profile.get("risk_tolerance", 5))
        loop = asyncio.get_event_loop()
        congress_trades = await loop.run_in_executor(
            None, get_congress_trades, [symbol], lookback_days
        )
        congress_trades = filter_congress_trades(
            congress_trades,
            disclosed_days=30,
            require_ticker=True,
        )
        result = await loop.run_in_executor(None, analyze_symbol, symbol, congress_trades, lookback_days, risk_tolerance)
        return result
    except Exception as exc:
        logger.exception("Analysis failed for %s", symbol)
        raise HTTPException(500, str(exc))


# ── Congress trades ───────────────────────────────────────────────────────────
@router.get("/congress-trades", tags=["data"])
async def get_congress_trades_endpoint(request: Request, symbols: str = ""):
    """
    Return raw congressional trade data.
    ?symbols=AAPL,MSFT,NVDA  (optional filter; if blank uses portfolio)
    """
    try:
        _user_id, profile = apply_user_profile_to_runtime_for_request(request)
        lookback_days = int(profile.get("signal_lookback_days", settings.signal_lookback_days))
        sym_list: list[str] = []
        if symbols:
            sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        else:
            try:
                _uid, _prof, broker = _get_broker_for_user(request)
                sym_list = broker.get_portfolio_symbols()
            except Exception as exc:
                # Broker is optional for congress feed. If unavailable/misconfigured,
                # continue with empty symbols to fetch the global recent trade stream.
                logger.warning("Broker unavailable for congress symbol filter; falling back to global feed: %s", exc)
                sym_list = []

        loop = asyncio.get_event_loop()
        trades = await loop.run_in_executor(
            None, get_congress_trades, sym_list, lookback_days
        )
        filtered_trades = filter_congress_trades(
            trades,
            disclosed_days=30,
            require_ticker=True,
        )

        return {
            "count": len(filtered_trades),
            "trades": [
                {
                    "politician": t.politician,
                    "party": t.party,
                    "chamber": t.chamber,
                    "symbol": t.symbol,
                    "traded_issuer": t.traded_issuer,
                    "published": t.disclosure_date,
                    "traded": t.trade_date,
                    "filed_after_days": t.filed_after_days,
                    "owner": t.owner,
                    "type": t.transaction,
                    "size": t.amount_range,
                    "price": t.price,
                    "transaction": t.transaction,
                    "amount_range": t.amount_range,
                    "trade_date": t.trade_date,
                    "disclosure_date": t.disclosure_date,
                }
                for t in filtered_trades
            ],
        }
    except Exception as exc:
        logger.exception("Congress trades fetch failed")
        raise HTTPException(500, str(exc))


# ── Settings ──────────────────────────────────────────────────────────────────
@router.get("/settings", tags=["config"])
def get_settings(request: Request):
    _user_id, profile = apply_user_profile_to_runtime_for_request(request)
    return {
        "active_broker": profile.get("active_broker", settings.active_broker),
        "alpaca_paper": bool(profile.get("alpaca_paper", settings.alpaca_paper)),
        "etrade_sandbox": bool(profile.get("etrade_sandbox", settings.etrade_sandbox)),
        "capitol_trades_enabled": bool(profile.get("capitol_trades_enabled", settings.capitol_trades_enabled)),
        "quiver_quant_configured": bool(profile.get("quiver_quant_api_key", "")),
        "refresh_interval_minutes": int(profile.get("refresh_interval_minutes", settings.refresh_interval_minutes)),
        "signal_lookback_days": int(profile.get("signal_lookback_days", settings.signal_lookback_days)),
    }


# ── Backtest ──────────────────────────────────────────────────────────────────
@router.get("/backtest/{symbol}", tags=["backtest"])
async def backtest(
    request: Request,
    symbol: str,
    sim_date: date = Query(..., description="Date to evaluate signal (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(default=None, description="End date for P&L measurement (defaults to today)"),
    capital: float = Query(default=10_000.0, ge=100, description="Hypothetical capital in USD"),
):
    """
    Simulate what would have happened if the trader followed the TraderBot signal
    on *sim_date* and held until *end_date*.
    """
    from app.analysis.backtest import run_backtest

    symbol = symbol.upper()
    if end_date is None:
        end_date = date.today()

    try:
        _user_id, profile = apply_user_profile_to_runtime_for_request(request)
        lookback_days = int(profile.get("signal_lookback_days", settings.signal_lookback_days))
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, run_backtest, symbol, sim_date, end_date, capital, lookback_days
        )
        if "error" in result:
            raise HTTPException(422, result["error"])
        return result
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as exc:
        logger.exception("Backtest failed for %s", symbol)
        raise HTTPException(500, str(exc))

