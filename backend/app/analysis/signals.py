"""
Technical analysis signal engine.

Indicators used:
  - RSI(14)          — momentum
  - MACD(12,26,9)    — trend / momentum
  - Bollinger Bands  — volatility / mean reversion
  - SMA 50 / SMA 200 — trend (golden/death cross)
    - Support/Resistance levels — proximity to local range boundaries
  - Volume spike     — confirmation

Scoring:
  Each indicator contributes +1 (bullish), -1 (bearish), or 0 (neutral).
    Final recommendation:
        >= +4  → STRONG BUY
        >= +2  → BUY
        <= -4  → STRONG SELL
        <= -2  → SELL
    else   → HOLD
"""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _to_df(price_history: list[dict]) -> Optional[pd.DataFrame]:
    if len(price_history) < 30:
        return None
    df = pd.DataFrame(price_history)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df.dropna(subset=["close"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger(close: pd.Series, period: int = 20):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    return upper, sma, lower


def compute_signals(symbol: str, price_history: list[dict]) -> dict:
    """
    Run all technical indicators and return a structured signal dict.
    """
    df = _to_df(price_history)
    if df is None:
        return {
            "symbol": symbol,
            "recommendation": "INSUFFICIENT_DATA",
            "score": 0,
            "indicators": {},
            "reason": "Not enough price history",
        }

    close = df["close"]
    volume = df["volume"]

    score = 0
    indicators: dict = {}

    # --- RSI ---
    rsi_series = _rsi(close)
    rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0
    indicators["rsi"] = round(rsi_val, 2)
    if rsi_val < 30:
        score += 1
        indicators["rsi_signal"] = "OVERSOLD (bullish)"
    elif rsi_val > 70:
        score -= 1
        indicators["rsi_signal"] = "OVERBOUGHT (bearish)"
    else:
        indicators["rsi_signal"] = "NEUTRAL"

    # --- MACD ---
    macd_line, signal_line, histogram = _macd(close)
    macd_val = float(macd_line.iloc[-1])
    sig_val = float(signal_line.iloc[-1])
    hist_val = float(histogram.iloc[-1])
    prev_hist = float(histogram.iloc[-2]) if len(histogram) > 1 else 0.0
    indicators["macd"] = round(macd_val, 4)
    indicators["macd_signal"] = round(sig_val, 4)
    indicators["macd_histogram"] = round(hist_val, 4)
    if hist_val > 0 and prev_hist <= 0:
        score += 1
        indicators["macd_cross"] = "BULLISH crossover"
    elif hist_val < 0 and prev_hist >= 0:
        score -= 1
        indicators["macd_cross"] = "BEARISH crossover"
    elif hist_val > 0:
        score += 1
        indicators["macd_cross"] = "BULLISH momentum"
    elif hist_val < 0:
        score -= 1
        indicators["macd_cross"] = "BEARISH momentum"
    else:
        indicators["macd_cross"] = "NEUTRAL"

    # --- Bollinger Bands ---
    bb_upper, bb_mid, bb_lower = _bollinger(close)
    current_price = float(close.iloc[-1])
    u = float(bb_upper.iloc[-1]) if not bb_upper.empty else current_price
    l = float(bb_lower.iloc[-1]) if not bb_lower.empty else current_price
    indicators["bb_upper"] = round(u, 2)
    indicators["bb_lower"] = round(l, 2)
    if current_price < l:
        score += 1
        indicators["bb_signal"] = "BELOW lower band (bullish)"
    elif current_price > u:
        score -= 1
        indicators["bb_signal"] = "ABOVE upper band (bearish)"
    else:
        indicators["bb_signal"] = "WITHIN bands (neutral)"

    # --- SMA 50 / SMA 200 ---
    sma50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None
    sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None
    if sma50 is not None:
        indicators["sma50"] = round(float(sma50), 2)
        if current_price > float(sma50):
            score += 1
            indicators["sma50_signal"] = "PRICE ABOVE SMA50 (bullish)"
        else:
            score -= 1
            indicators["sma50_signal"] = "PRICE BELOW SMA50 (bearish)"
    if sma200 is not None:
        indicators["sma200"] = round(float(sma200), 2)
        if sma50 is not None and float(sma50) > float(sma200):
            score += 1
            indicators["sma_cross"] = "GOLDEN CROSS SMA50>SMA200 (bullish)"
        elif sma50 is not None:
            score -= 1
            indicators["sma_cross"] = "DEATH CROSS SMA50<SMA200 (bearish)"

    # --- Support / Resistance levels ---
    lookback_near = min(len(close), 20)
    lookback_major = min(len(close), 50)
    near_window = close.tail(lookback_near)
    major_window = close.tail(lookback_major)

    support_near = float(near_window.min()) if not near_window.empty else current_price
    resistance_near = float(near_window.max()) if not near_window.empty else current_price
    support_major = float(major_window.min()) if not major_window.empty else support_near
    resistance_major = float(major_window.max()) if not major_window.empty else resistance_near

    indicators["support_near"] = round(support_near, 2)
    indicators["resistance_near"] = round(resistance_near, 2)
    indicators["support_major"] = round(support_major, 2)
    indicators["resistance_major"] = round(resistance_major, 2)

    if current_price <= support_near * 1.02:
        score += 1
        indicators["sr_signal"] = "NEAR SUPPORT (bullish)"
    elif current_price >= resistance_near * 0.98:
        score -= 1
        indicators["sr_signal"] = "NEAR RESISTANCE (bearish)"
    else:
        indicators["sr_signal"] = "RANGE MIDPOINT (neutral)"

    stop_loss = support_near * 0.985
    tp1 = resistance_near
    tp2 = resistance_major
    indicators["stop_loss_suggestion"] = round(stop_loss, 2)
    indicators["take_profit_1"] = round(tp1, 2)
    indicators["take_profit_2"] = round(tp2, 2)

    if current_price > 0:
        indicators["distance_to_support_pct"] = round((current_price - support_near) / current_price * 100, 2)
        indicators["distance_to_resistance_pct"] = round((resistance_near - current_price) / current_price * 100, 2)

    risk = current_price - stop_loss
    reward = tp1 - current_price
    if risk > 0:
        indicators["risk_reward_tp1"] = round(reward / risk, 2)

    # --- Volume spike ---
    avg_vol = float(volume.rolling(20).mean().iloc[-1]) if len(volume) >= 20 else 0
    last_vol = float(volume.iloc[-1])
    indicators["volume"] = int(last_vol)
    indicators["avg_volume_20d"] = int(avg_vol)
    if avg_vol > 0 and last_vol > 1.5 * avg_vol:
        indicators["volume_signal"] = "ABOVE-AVERAGE volume (confirmation)"
        # Not scored alone; just informational
    else:
        indicators["volume_signal"] = "NORMAL volume"

    # --- Final recommendation ---
    if score >= 4:
        recommendation = "STRONG BUY"
    elif score >= 2:
        recommendation = "BUY"
    elif score <= -4:
        recommendation = "STRONG SELL"
    elif score <= -2:
        recommendation = "SELL"
    else:
        recommendation = "HOLD"

    return {
        "symbol": symbol,
        "current_price": round(current_price, 2),
        "recommendation": recommendation,
        "score": score,
        "indicators": indicators,
    }
