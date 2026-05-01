"""
FastAPI routes.
"""

import asyncio
import logging
from datetime import date
from functools import lru_cache
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.brokers import get_broker
from app.brokers.base import BaseBroker
from app.data_sources.congress_trades import get_congress_trades, filter_congress_trades
from app.analysis import analyze_symbol
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Broker singleton ──────────────────────────────────────────────────────────
_broker: BaseBroker | None = None
_broker_connected: bool = False


def _get_broker() -> BaseBroker:
    global _broker, _broker_connected
    if _broker is None:
        _broker = get_broker()
    if not _broker_connected:
        _broker_connected = _broker.connect()
    return _broker


# ── E-Trade OAuth helpers ─────────────────────────────────────────────────────
@router.get("/broker/etrade/auth", tags=["broker"])
def etrade_auth_start():
    from app.brokers.etrade import ETradeBroker

    global _broker, _broker_connected
    _broker = ETradeBroker()
    url = _broker.get_oauth_url()
    return {"message": "Open this URL in a browser to authorize", "oauth_url": url}


class ETradeVerifier(BaseModel):
    verifier: str


@router.post("/broker/etrade/auth", tags=["broker"])
def etrade_auth_complete(body: ETradeVerifier):
    global _broker_connected
    from app.brokers.etrade import ETradeBroker

    if not isinstance(_broker, ETradeBroker):
        raise HTTPException(400, "E-Trade OAuth not started. Call GET /broker/etrade/auth first.")
    ok = _broker.complete_oauth(body.verifier)
    _broker_connected = ok
    if not ok:
        raise HTTPException(400, "OAuth verification failed")
    return {"message": "E-Trade connected successfully"}


# ── Broker status ─────────────────────────────────────────────────────────────
@router.get("/broker/status", tags=["broker"])
def broker_status():
    return {
        "active_broker": settings.active_broker,
        "connected": _broker_connected,
        "paper_mode": settings.alpaca_paper if settings.active_broker == "alpaca" else None,
    }


# ── Account & portfolio ───────────────────────────────────────────────────────
@router.get("/account", tags=["account"])
def get_account():
    try:
        broker = _get_broker()
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
                }
                for p in account.positions
            ],
        }
    except Exception as exc:
        logger.exception("Failed to fetch account")
        raise HTTPException(500, str(exc))


# ── Analysis ──────────────────────────────────────────────────────────────────
@router.get("/analysis", tags=["analysis"])
async def get_analysis():
    """Analyze all portfolio positions and return buy/sell suggestions."""
    try:
        broker = _get_broker()
        account = broker.get_account()
        symbols = [p.symbol for p in account.positions]
        if not symbols:
            return {"analyses": [], "message": "No positions in portfolio"}

        # Fetch congress trades once for all symbols
        loop = asyncio.get_event_loop()
        congress_trades = await loop.run_in_executor(
            None, get_congress_trades, symbols, settings.signal_lookback_days
        )
        congress_trades = filter_congress_trades(
            congress_trades,
            disclosed_days=30,
            require_ticker=True,
        )

        # Analyze each symbol concurrently
        async def _analyze(sym: str) -> dict:
            return await loop.run_in_executor(None, analyze_symbol, sym, congress_trades)

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
            },
            "analyses": results,
        }
    except Exception as exc:
        logger.exception("Analysis failed")
        raise HTTPException(500, str(exc))


@router.get("/analysis/{symbol}", tags=["analysis"])
async def get_symbol_analysis(symbol: str):
    """Analyze a single symbol (does not need to be in portfolio)."""
    symbol = symbol.upper()
    try:
        loop = asyncio.get_event_loop()
        congress_trades = await loop.run_in_executor(
            None, get_congress_trades, [symbol], settings.signal_lookback_days
        )
        congress_trades = filter_congress_trades(
            congress_trades,
            disclosed_days=30,
            require_ticker=True,
        )
        result = await loop.run_in_executor(None, analyze_symbol, symbol, congress_trades)
        return result
    except Exception as exc:
        logger.exception("Analysis failed for %s", symbol)
        raise HTTPException(500, str(exc))


# ── Congress trades ───────────────────────────────────────────────────────────
@router.get("/congress-trades", tags=["data"])
async def get_congress_trades_endpoint(symbols: str = ""):
    """
    Return raw congressional trade data.
    ?symbols=AAPL,MSFT,NVDA  (optional filter; if blank uses portfolio)
    """
    try:
        sym_list: list[str] = []
        if symbols:
            sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        else:
            broker = _get_broker()
            sym_list = broker.get_portfolio_symbols()

        loop = asyncio.get_event_loop()
        trades = await loop.run_in_executor(
            None, get_congress_trades, sym_list, settings.signal_lookback_days
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
def get_settings():
    return {
        "active_broker": settings.active_broker,
        "alpaca_paper": settings.alpaca_paper,
        "etrade_sandbox": settings.etrade_sandbox,
        "capitol_trades_enabled": settings.capitol_trades_enabled,
        "quiver_quant_configured": bool(settings.quiver_quant_api_key),
        "refresh_interval_minutes": settings.refresh_interval_minutes,
        "signal_lookback_days": settings.signal_lookback_days,
    }


# ── Backtest ──────────────────────────────────────────────────────────────────
@router.get("/backtest/{symbol}", tags=["backtest"])
async def backtest(
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
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, run_backtest, symbol, sim_date, end_date, capital
        )
        if "error" in result:
            raise HTTPException(422, result["error"])
        return result
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as exc:
        logger.exception("Backtest failed for %s", symbol)
        raise HTTPException(500, str(exc))

