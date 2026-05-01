"""
Combines technical signals + congressional trade signals into a final
buy/sell recommendation for each portfolio position.
"""

from app.analysis.signals import compute_signals
from app.data_sources.congress_trades import CongressTrade, congress_signal
from app.data_sources.alternative_data import get_alternative_signal
from app.data_sources.market_data import get_price_history
from app.config import settings


def analyze_symbol(symbol: str, congress_trades: list[CongressTrade]) -> dict:
    history = get_price_history(symbol, days=settings.signal_lookback_days)
    tech = compute_signals(symbol, history)
    cong = congress_signal(symbol, congress_trades)
    alt = get_alternative_signal(symbol, lookback_days=30)

    # Combined score: technical + congress contribution + alternative-data contribution.
    congress_contribution = max(-2, min(2, cong["congress_score"] // 2))
    alt_contribution = max(-2, min(2, int(alt.get("alternative_score", 0))))
    combined_score = tech["score"] + congress_contribution + alt_contribution

    if combined_score >= 4:
        final = "STRONG BUY"
    elif combined_score >= 2:
        final = "BUY"
    elif combined_score <= -4:
        final = "STRONG SELL"
    elif combined_score <= -2:
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
    }
