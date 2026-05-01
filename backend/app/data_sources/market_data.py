"""
Market price history fetched from Yahoo Finance (yfinance).
Used for technical analysis when broker data is insufficient.
"""

import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

YF_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def get_price_history(symbol: str, days: int = 90) -> list[dict]:
    """
    Return OHLCV list for *symbol* covering the last *days* calendar days.
    Each item: {date, open, high, low, close, volume}
    """
    end = int(datetime.utcnow().timestamp())
    start = int((datetime.utcnow() - timedelta(days=days)).timestamp())
    params = {
        "period1": start,
        "period2": end,
        "interval": "1d",
        "includeAdjustedClose": "true",
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                YF_CHART_URL.format(symbol=symbol),
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            result = resp.json()["chart"]["result"][0]
            timestamps = result["timestamp"]
            ohlcv = result["indicators"]["quote"][0]
            rows = []
            for i, ts in enumerate(timestamps):
                rows.append(
                    {
                        "date": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"),
                        "open": ohlcv["open"][i],
                        "high": ohlcv["high"][i],
                        "low": ohlcv["low"][i],
                        "close": ohlcv["close"][i],
                        "volume": ohlcv["volume"][i],
                    }
                )
            return rows
    except Exception as exc:
        logger.warning("Price history fetch failed for %s: %s", symbol, exc)
        return []
