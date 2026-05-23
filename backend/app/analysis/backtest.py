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

import yfinance as yf

from app.analysis.signals import compute_signals
from app.data_sources.congress_trades import (
    get_congress_trades,
    congress_signal,
    filter_congress_trades,
)
from app.data_sources.alternative_data import get_alternative_signal
from app.data_sources.market_data import get_price_history

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
    lookback_days: int = 90,
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
    all_congress = get_congress_trades([symbol], days_back=lookback_days)
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

    # --- Fundamentals from yfinance (current, used as approximation) ---
    fund_info = {}
    try:
        fund_info = yf.Ticker(symbol).info
    except Exception:
        pass

    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    # --- Unified combined score (same logic as _compute_buy_sell_signal in company.py) ---
    # Technical (12%): RSI, MACD, Bollinger, SMA50/200
    tech_contribution = _clamp(tech["score"] * 0.24, -1.2, 1.2)

    # Support / Resistance (8%): derived from technical indicators at sim_date
    sr_signal = str((tech.get("indicators", {}) or {}).get("sr_signal", "NEUTRAL"))
    if "bullish" in sr_signal.lower():
        sr_contribution = 0.8
    elif "bearish" in sr_signal.lower():
        sr_contribution = -0.8
    else:
        sr_contribution = 0.0

    # Congressional (10%)
    cong_contribution = _clamp((cong["congress_score"] or 0) * 0.1, -1.0, 1.0)

    # Alternative Data (20%)
    alt_contribution = _clamp(float(alt.get("alternative_score", 0)), -2.0, 2.0)

    # Fundamentals (20%)
    fund_score = 0.0
    fund_factors: dict = {}
    pe = fund_info.get("trailingPE")
    if pe:
        fund_factors["pe_ratio"] = round(float(pe), 2)
        if pe < 15:
            fund_score += 1.5
        elif pe > 30:
            fund_score -= 1.5
    dte = fund_info.get("debtToEquity")
    if dte:
        fund_factors["debt_to_equity"] = round(float(dte), 2)
        if dte < 0.5:
            fund_score += 1.0
        elif dte > 2.0:
            fund_score -= 1.0
    cr = fund_info.get("currentRatio")
    if cr:
        fund_factors["current_ratio"] = round(float(cr), 2)
        if cr > 1.5:
            fund_score += 0.75
        elif cr < 1.0:
            fund_score -= 0.75
    fund_contribution = _clamp(fund_score * 0.625, -2.0, 2.0)

    # Momentum (15%): from price history at sim_date
    mom_score = 0.0
    mom_factors: dict = {}
    if len(pre_history) >= 2:
        last_p = pre_history[-1]["close"] or 0
        prev_p = pre_history[-2]["close"] or last_p
        if prev_p and last_p:
            day_chg = (last_p - prev_p) / prev_p * 100
            mom_factors["day_change_pct"] = round(day_chg, 2)
            if day_chg > 2:
                mom_score += 1.0
            elif day_chg < -2:
                mom_score -= 1.0
        # Approx 52w change from lookback history
        first_p = pre_history[0]["close"] or last_p
        if first_p and last_p:
            yr_chg = (last_p - first_p) / first_p * 100
            mom_factors["52w_change_pct"] = round(yr_chg, 2)
            if yr_chg > 20:
                mom_score += 1.25
            elif yr_chg < -20:
                mom_score -= 1.25
    mom_contribution = _clamp(mom_score * 0.667, -1.5, 1.5)

    # Options chain not available historically — omitted (0 contribution)
    combined_score = round(
        tech_contribution + cong_contribution + alt_contribution
        + fund_contribution + mom_contribution + sr_contribution,
        2,
    )

    if combined_score >= 5:
        final_rec = "STRONG BUY"
    elif combined_score >= 2.5:
        final_rec = "BUY"
    elif combined_score <= -5:
        final_rec = "STRONG SELL"
    elif combined_score <= -2.5:
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
        # Unified factor breakdown (matches company-page signal structure)
        "signal_factors": {
            "technical": {
                "score": tech["score"],
                "recommendation": tech.get("recommendation", "N/A"),
                "contribution": round(tech_contribution, 3),
                "indicators": tech.get("indicators", {}),
                "weight": "12%",
            },
            "support_resistance": {
                "signal": sr_signal,
                "support_near": tech.get("indicators", {}).get("support_near"),
                "resistance_near": tech.get("indicators", {}).get("resistance_near"),
                "support_major": tech.get("indicators", {}).get("support_major"),
                "resistance_major": tech.get("indicators", {}).get("resistance_major"),
                "stop_loss_suggestion": tech.get("indicators", {}).get("stop_loss_suggestion"),
                "take_profit_1": tech.get("indicators", {}).get("take_profit_1"),
                "take_profit_2": tech.get("indicators", {}).get("take_profit_2"),
                "risk_reward_tp1": tech.get("indicators", {}).get("risk_reward_tp1"),
                "contribution": round(sr_contribution, 3),
                "weight": "8%",
            },
            "congressional": {
                "signal": cong.get("congress_signal", "NEUTRAL"),
                "score": cong.get("congress_score", 0),
                "contribution": round(cong_contribution, 3),
                "weight": "10%",
            },
            "alternative_data": {
                "score": alt.get("alternative_score", 0),
                "label": alt.get("alternative_signal", "NEUTRAL"),
                "contribution": round(alt_contribution, 3),
                "weight": "20%",
            },
            "fundamentals": {
                **fund_factors,
                "contribution": round(fund_contribution, 3),
                "weight": "20%",
            },
            "momentum": {
                **mom_factors,
                "contribution": round(mom_contribution, 3),
                "weight": "15%",
            },
            "options_chain": {
                "contribution": 0.0,
                "weight": "0% (not available for historical dates)",
            },
        },
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
