"""
Combines technical signals + congressional trade signals into a final
buy/sell recommendation for each portfolio position.
"""

from app.analysis.signals import compute_signals
from app.data_sources.congress_trades import CongressTrade, congress_signal
from app.data_sources.alternative_data import get_alternative_signal
from app.data_sources.market_data import get_price_history
from app.config import settings


def analyze_symbol(symbol: str, congress_trades: list[CongressTrade], lookback_days: int | None = None, risk_tolerance: int | None = None) -> dict:
    days = lookback_days if lookback_days is not None else settings.signal_lookback_days
    risk = risk_tolerance if risk_tolerance is not None else 5
    
    # Adjust thresholds based on risk tolerance (1=very conservative, 10=very aggressive)
    # Conservative (1-3): require higher conviction (higher thresholds)
    # Moderate (4-6): standard thresholds
    # Aggressive (7-10): lower thresholds for more trading
    if risk <= 3:
        strong_buy_threshold = 5.5
        buy_threshold = 3.0
        strong_sell_threshold = -5.5
        sell_threshold = -3.0
    elif risk <= 6:
        strong_buy_threshold = 4.0
        buy_threshold = 2.0
        strong_sell_threshold = -4.0
        sell_threshold = -2.0
    else:  # risk > 6
        strong_buy_threshold = 2.5
        buy_threshold = 1.0
        strong_sell_threshold = -2.5
        sell_threshold = -1.0
    
    history = get_price_history(symbol, days=days)
    tech = compute_signals(symbol, history)
    cong = congress_signal(symbol, congress_trades)
    alt = get_alternative_signal(symbol, lookback_days=30)

    # Combined score: technical + congress contribution + alternative-data contribution.
    congress_contribution = max(-2, min(2, cong["congress_score"] // 2))
    alt_contribution = max(-2, min(2, int(alt.get("alternative_score", 0))))
    combined_score = tech["score"] + congress_contribution + alt_contribution

    if combined_score >= strong_buy_threshold:
        final = "STRONG BUY"
    elif combined_score >= buy_threshold:
        final = "BUY"
    elif combined_score <= strong_sell_threshold:
        final = "STRONG SELL"
    elif combined_score <= sell_threshold:
        final = "SELL"
    else:
        final = "HOLD"

    return {
        "symbol": symbol,
        "final_recommendation": final,
        "combined_score": combined_score,
        "technical": tech,
        "congress": cong,
        "alternative": alt,
        "alternative_contribution": alt_contribution,
        "price_history": history[-30:],  # last 30 days for chart
        "risk_tolerance_used": risk,
    }
