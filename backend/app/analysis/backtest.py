"""
Back-test simulation engine.

Given a symbol and a simulation date, re-computes what the combined
signal would have been on that date (using only data available up to
and including that date), then tracks what actually happened to the
price from that date to a chosen end date.

Returns per-day equity curve so the UI can plot it.
"""

import logging
from datetime import date, datetime, timedelta

from app.analysis.signals import compute_signals
from app.data_sources.congress_trades import (
    get_congress_trades,
    congress_signal,
    filter_congress_trades,
)
from app.data_sources.alternative_data import get_alternative_signal
from app.data_sources.market_data import get_price_history
from app.config import settings

logger = logging.getLogger(__name__)

_ACTION_LABEL = {
    "STRONG BUY": "BUY",
    "BUY": "BUY",
    "HOLD": "HOLD",
    "SELL": "SELL",
    "STRONG SELL": "SELL",
    "INSUFFICIENT_DATA": "HOLD",
}


def run_backtest(
    symbol: str,
    sim_date: date,
    end_date: date,
    initial_capital: float = 10_000.0,
) -> dict:
    """
    Simulate what would have happened if a trader followed the signal on
    *sim_date* and held until *end_date*.

    Parameters
    ----------
    symbol          : ticker symbol
    sim_date        : the date on which the signal is evaluated
    end_date        : the date to measure P&L against  (defaults to today)
    initial_capital : hypothetical USD amount invested

    Returns a dict with:
      - signal_date, end_date
      - technical_signal, congress_signal, final_recommendation, combined_score
      - action  : BUY | SELL | HOLD
      - entry_price, exit_price
      - gain_loss_usd, gain_loss_pct
      - shares         : how many shares with initial_capital at entry_price
      - indicators     : snapshot of each indicator as of sim_date
      - equity_curve   : [{date, price, equity}] from sim_date to end_date
      - pre_equity_curve: [{date, price}] 90 days before sim_date (for context chart)
      - congress_recent_trades: list of trades visible on sim_date
    """
    today = date.today()
    if sim_date > today:
        raise ValueError("sim_date cannot be in the future")
    if end_date > today:
        end_date = today
    if end_date <= sim_date:
        raise ValueError("end_date must be after sim_date")

    # Fetch enough history: 200 trading days before sim_date (for SMA200) + forward to end_date
    lookback_start = sim_date - timedelta(days=365)  # ~200 trading days
    # days must be measured from TODAY back to lookback_start so Yahoo returns the full range
    total_days = (date.today() - lookback_start).days + 10
    all_history = get_price_history(symbol, days=total_days)

    # Split history at sim_date
    pre_history = [r for r in all_history if r["date"] <= sim_date.isoformat()]
    post_history = [r for r in all_history if r["date"] >= sim_date.isoformat()]

    # Need at least 30 candles before sim_date
    if len(pre_history) < 30:
        return {
            "error": f"Insufficient price history before {sim_date} for {symbol}",
            "symbol": symbol,
            "sim_date": sim_date.isoformat(),
        }

    # --- Technical signals as of sim_date ---
    tech = compute_signals(symbol, pre_history)

    # --- Congressional signals visible on sim_date ---
    days_back_congress = (sim_date - lookback_start).days
    all_congress = get_congress_trades([symbol], days_back=settings.signal_lookback_days)
    all_congress = filter_congress_trades(
        all_congress,
        disclosed_days=30,
        require_ticker=True,
        reference_date=sim_date,
    )
    # Filter to only trades disclosed on or before sim_date
    congress_trades_then = [
        t for t in all_congress
        if t.disclosure_date and t.disclosure_date <= sim_date.isoformat()
    ]
    cong = congress_signal(symbol, congress_trades_then)
    alt = get_alternative_signal(symbol, reference_date=sim_date, lookback_days=30)

    # --- Combined score (same logic as analysis/__init__.py) ---
    congress_contribution = max(-2, min(2, cong["congress_score"] // 2))
    alt_contribution = max(-2, min(2, int(alt.get("alternative_score", 0))))
    combined_score = tech["score"] + congress_contribution + alt_contribution

    if combined_score >= 4:
        final_rec = "STRONG BUY"
    elif combined_score >= 2:
        final_rec = "BUY"
    elif combined_score <= -4:
        final_rec = "STRONG SELL"
    elif combined_score <= -2:
        final_rec = "SELL"
    else:
        final_rec = "HOLD"

    action = _ACTION_LABEL.get(final_rec, "HOLD")

    # --- Entry / exit prices ---
    # Entry = closing price on sim_date (or nearest available)
    entry_row = pre_history[-1]
    entry_price = entry_row["close"] or 0.0

    exit_row = post_history[-1] if post_history else entry_row
    exit_price = exit_row["close"] or entry_price

    shares = (initial_capital / entry_price) if entry_price else 0.0

    if action == "BUY":
        gain_loss_usd = (exit_price - entry_price) * shares
    elif action == "SELL":
        # Short: profit if price fell
        gain_loss_usd = (entry_price - exit_price) * shares
    else:  # HOLD — no position, no P&L
        gain_loss_usd = 0.0
        shares = 0.0

    gain_loss_pct = (gain_loss_usd / initial_capital * 100) if initial_capital else 0.0

    # --- Equity curve for the forward period ---
    equity_curve = []
    for row in post_history:
        price = row["close"] or entry_price
        if action == "BUY":
            eq = initial_capital + (price - entry_price) * shares
        elif action == "SELL":
            eq = initial_capital + (entry_price - price) * shares
        else:
            eq = initial_capital
        equity_curve.append({"date": row["date"], "price": price, "equity": round(eq, 2)})

    # --- Pre-sim context (90 days before sim_date) ---
    pre_context_start = (sim_date - timedelta(days=90)).isoformat()
    pre_equity_curve = [
        {"date": r["date"], "price": r["close"]}
        for r in pre_history
        if r["date"] >= pre_context_start
    ]

    return {
        "symbol": symbol,
        "sim_date": sim_date.isoformat(),
        "end_date": end_date.isoformat(),
        "initial_capital": initial_capital,
        "action": action,
        "final_recommendation": final_rec,
        "combined_score": combined_score,
        "technical_score": tech["score"],
        "congress_score": cong["congress_score"],
        "congress_signal_label": cong["congress_signal"],
        "alternative_score": alt.get("alternative_score", 0),
        "alternative_signal_label": alt.get("alternative_signal", "NEUTRAL"),
        "alternative_contribution": alt_contribution,
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "shares": round(shares, 6),
        "gain_loss_usd": round(gain_loss_usd, 2),
        "gain_loss_pct": round(gain_loss_pct, 4),
        "final_equity": round(initial_capital + gain_loss_usd, 2),
        "indicators": tech.get("indicators", {}),
        "equity_curve": equity_curve,
        "pre_equity_curve": pre_equity_curve,
        "alternative_data": alt,
        "congress_trades_at_sim_date": [
            {
                "politician": t.politician,
                "party": t.party,
                "transaction": t.transaction,
                "amount_range": t.amount_range,
                "trade_date": t.trade_date,
                "disclosure_date": t.disclosure_date,
            }
            for t in congress_trades_then[:10]
        ],
    }
