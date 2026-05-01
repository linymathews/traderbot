"""
Alternative data aggregation across multiple providers.

Providers covered:
- Capitol Trades
- OpenInsider
- WhaleWisdom
- Quiver Quantitative
- StockGeist / LunarCrush
- Alpha Vantage (News Sentiment)
- Polygon.io
- Financial Modeling Prep (FMP)
- EODHD
- FRED API
- Tiingo
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.data_sources.congress_trades import get_congress_trades, filter_congress_trades

logger = logging.getLogger(__name__)

OPENINSIDER_URLS = [
    "http://openinsider.com/screener",
    "https://openinsider.com/screener",
    "http://www.openinsider.com/screener",
    "https://www.openinsider.com/screener",
]
WHALEWISDOM_URL = "https://whalewisdom.com/stock/{symbol}"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
POLYGON_TICKER_URL = "https://api.polygon.io/v3/reference/tickers/{symbol}"
POLYGON_NEWS_URL = "https://api.polygon.io/v2/reference/news"
FMP_INCOME_STATEMENT_URL = "https://financialmodelingprep.com/stable/income-statement"
EODHD_EOD_URL = "https://eodhd.com/api/eod/{symbol}"
FRED_SERIES_URL = "https://api.stlouisfed.org/fred/series/observations"
TIINGO_META_URL = "https://api.tiingo.com/tiingo/daily/{symbol}"
LUNARCRUSH_ASSET_URL = "https://lunarcrush.com/api4/public/topic/{symbol}/v1"


def _today(reference_date: Optional[date]) -> date:
    return reference_date or datetime.utcnow().date()


def _safe_date(value: str) -> Optional[date]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).date()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except Exception:
        return None


def _http_get_json(url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None) -> tuple[Optional[dict], Optional[str]]:
    try:
        with httpx.Client(timeout=12, follow_redirects=True) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}"
            return resp.json(), None
    except Exception as exc:
        return None, str(exc)


def _http_get_text(url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None) -> tuple[Optional[str], Optional[str]]:
    try:
        with httpx.Client(timeout=12, follow_redirects=True) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}"
            return resp.text, None
    except Exception as exc:
        return None, str(exc)


def _provider_result(
    name: str,
    *,
    configured: bool = True,
    enabled: bool = True,
    available: bool = False,
    details: Optional[dict] = None,
    error: Optional[str] = None,
    score: float = 0.0,
    weight: float = 0.0,
) -> dict:
    return {
        "name": name,
        "configured": configured,
        "enabled": enabled,
        "available": available,
        "signal_score": score,
        "weight": weight,
        "weighted_score": round(score * max(0.0, weight), 4),
        "details": details or {},
        "error": error,
    }


def _disabled_provider(name: str, reason: str, weight: float) -> dict:
    return _provider_result(
        name,
        configured=True,
        enabled=False,
        available=False,
        error=reason,
        score=0.0,
        weight=weight,
    )


def _capitol_summary(symbol: str, reference_date: Optional[date], lookback_days: int, weight: float) -> dict:
    as_of = _today(reference_date)
    trades = get_congress_trades([symbol], days_back=max(lookback_days, 30))
    trades = filter_congress_trades(
        trades,
        disclosed_days=lookback_days,
        require_ticker=True,
        reference_date=as_of,
    )
    trades = [t for t in trades if t.symbol.upper() == symbol.upper() and _safe_date(t.disclosure_date) and _safe_date(t.disclosure_date) <= as_of]

    buys = sum(1 for t in trades if "buy" in (t.transaction or "").lower() or "purchase" in (t.transaction or "").lower())
    sells = sum(1 for t in trades if "sell" in (t.transaction or "").lower() or "sale" in (t.transaction or "").lower())
    net = buys - sells
    score = 0.0
    if net > 0:
        score = min(1.0, net / 3)
    elif net < 0:
        score = max(-1.0, net / 3)

    return _provider_result(
        "Capitol Trades",
        configured=True,
        enabled=True,
        available=True,
        score=score,
        weight=weight,
        details={
            "trades_count": len(trades),
            "buy_count": buys,
            "sell_count": sells,
            "net_buy_minus_sell": net,
            "window_days": lookback_days,
        },
    )


def _openinsider_summary(symbol: str, reference_date: Optional[date], lookback_days: int, weight: float) -> dict:
    as_of = _today(reference_date)
    params = {
        "s": symbol,
        "fd": str(lookback_days),
        "xp": "1",
    }
    text: Optional[str] = None
    err: Optional[str] = None
    used_url = ""
    for candidate in OPENINSIDER_URLS:
        used_url = candidate
        text, err = _http_get_text(
            candidate,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if text and not err:
            break

    if err or not text:
        return _provider_result("OpenInsider", available=False, error=err, weight=weight)

    soup = BeautifulSoup(text, "lxml")
    table = soup.find("table", class_="tinytable")
    if not table:
        # OpenInsider layout occasionally serves only the screener form markup to bots.
        # Treat this as reachable but with no parseable filing rows instead of a hard error.
        return _provider_result(
            "OpenInsider",
            enabled=True,
            available=True,
            score=0.0,
            weight=weight,
            details={
                "filings_count": 0,
                "buy_count": 0,
                "sell_count": 0,
                "net_buy_minus_sell": 0,
                "window_days": lookback_days,
                "parse_note": "No insider results table found in current response",
                "url": f"{used_url.split('?')[0]}?s={symbol}",
            },
        )

    rows = table.find_all("tr")
    buys = 0
    sells = 0
    count = 0
    for tr in rows[1:]:
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        filed_raw = tds[1].get_text(strip=True)
        filed_date = _safe_date(filed_raw)
        if filed_date and filed_date > as_of:
            continue
        tx_type = tds[6].get_text(strip=True).upper()
        count += 1
        if "P" in tx_type:
            buys += 1
        if "S" in tx_type:
            sells += 1

    net = buys - sells
    score = 0.0
    if net > 0:
        score = min(1.0, net / 5)
    elif net < 0:
        score = max(-1.0, net / 5)

    return _provider_result(
        "OpenInsider",
        enabled=True,
        available=True,
        score=score,
        weight=weight,
        details={
            "filings_count": count,
            "buy_count": buys,
            "sell_count": sells,
            "net_buy_minus_sell": net,
            "window_days": lookback_days,
            "url": f"{used_url.split('?')[0]}?s={symbol}",
        },
    )


def _whalewisdom_summary(symbol: str, weight: float) -> dict:
    url = WHALEWISDOM_URL.format(symbol=symbol.lower())
    text, err = _http_get_text(url, headers={"User-Agent": "Mozilla/5.0"})
    if err or not text:
        return _provider_result("WhaleWisdom", available=False, error=err, details={"url": url}, weight=weight)

    soup = BeautifulSoup(text, "lxml")
    title = (soup.title.get_text(strip=True) if soup.title else "WhaleWisdom")
    return _provider_result(
        "WhaleWisdom",
        enabled=True,
        available=True,
        details={"page_title": title, "url": url},
        score=0.0,
        weight=weight,
    )


def _quiver_summary(symbol: str, reference_date: Optional[date], lookback_days: int, weight: float) -> dict:
    key = settings.quiver_quant_api_key
    if not key:
        return _provider_result("Quiver Quantitative", configured=False, available=False, error="QUIVER_QUANT_API_KEY missing", weight=weight)

    as_of = _today(reference_date)
    url = f"https://api.quiverquant.com/beta/historical/congresstrading/{symbol}"
    data, err = _http_get_json(url, headers={"Authorization": f"Token {key}"})
    if err or data is None:
        return _provider_result("Quiver Quantitative", configured=True, available=False, error=err, weight=weight)

    cutoff = as_of - timedelta(days=lookback_days)
    buys = 0
    sells = 0
    count = 0

    if isinstance(data, list):
        for row in data:
            d = _safe_date(str(row.get("Date", "")))
            if not d or d < cutoff or d > as_of:
                continue
            count += 1
            tx = str(row.get("Transaction", "")).lower()
            if "buy" in tx or "purchase" in tx:
                buys += 1
            if "sell" in tx or "sale" in tx:
                sells += 1

    net = buys - sells
    score = 0.0
    if net > 0:
        score = min(1.0, net / 4)
    elif net < 0:
        score = max(-1.0, net / 4)

    return _provider_result(
        "Quiver Quantitative",
        configured=True,
        enabled=True,
        available=True,
        score=score,
        weight=weight,
        details={
            "trades_count": count,
            "buy_count": buys,
            "sell_count": sells,
            "net_buy_minus_sell": net,
            "window_days": lookback_days,
        },
    )


def _alpha_vantage_summary(symbol: str, reference_date: Optional[date], lookback_days: int, weight: float) -> dict:
    key = settings.alpha_vantage_api_key
    if not key:
        return _provider_result("Alpha Vantage", configured=False, available=False, error="ALPHA_VANTAGE_API_KEY missing", weight=weight)

    as_of = _today(reference_date)
    data, err = _http_get_json(
        ALPHA_VANTAGE_URL,
        params={
            "function": "NEWS_SENTIMENT",
            "tickers": symbol,
            "limit": "50",
            "apikey": key,
        },
    )
    if err or data is None:
        return _provider_result("Alpha Vantage", configured=True, available=False, error=err, weight=weight)

    feed = data.get("feed", []) if isinstance(data, dict) else []
    cutoff = as_of - timedelta(days=lookback_days)
    scores: list[float] = []
    for item in feed:
        dt = _safe_date(str(item.get("time_published", "")))
        if not dt or dt < cutoff or dt > as_of:
            continue
        try:
            scores.append(float(item.get("overall_sentiment_score", 0.0)))
        except Exception:
            continue

    avg = mean(scores) if scores else 0.0
    score = max(-1.0, min(1.0, avg))

    return _provider_result(
        "Alpha Vantage",
        configured=True,
        enabled=True,
        available=True,
        score=score,
        weight=weight,
        details={
            "news_count": len(scores),
            "avg_sentiment": round(avg, 4),
            "window_days": lookback_days,
        },
    )


def _polygon_summary(symbol: str, reference_date: Optional[date], lookback_days: int, weight: float) -> dict:
    key = settings.polygon_api_key
    if not key:
        return _provider_result("Polygon.io", configured=False, available=False, error="POLYGON_API_KEY missing", weight=weight)

    as_of = _today(reference_date)
    ticker_data, ticker_err = _http_get_json(POLYGON_TICKER_URL.format(symbol=symbol), params={"apiKey": key})
    news_data, news_err = _http_get_json(
        POLYGON_NEWS_URL,
        params={"ticker": symbol, "limit": 50, "apiKey": key},
    )

    available = ticker_data is not None or news_data is not None
    if not available:
        return _provider_result("Polygon.io", configured=True, available=False, error=ticker_err or news_err, weight=weight)

    news_results = []
    if isinstance(news_data, dict):
        news_results = news_data.get("results", []) or []
    cutoff = as_of - timedelta(days=lookback_days)
    news_count = 0
    for item in news_results:
        d = _safe_date(str(item.get("published_utc", "")))
        if d and cutoff <= d <= as_of:
            news_count += 1

    positive = 0
    negative = 0
    for item in news_results:
        title = str(item.get("title", "")).lower()
        if any(k in title for k in ("beat", "growth", "upgrade", "record", "profit")):
            positive += 1
        if any(k in title for k in ("miss", "downgrade", "lawsuit", "fraud", "decline")):
            negative += 1

    sentiment_balance = positive - negative
    score = 0.0
    if sentiment_balance > 0:
        score = min(1.0, sentiment_balance / 10)
    elif sentiment_balance < 0:
        score = max(-1.0, sentiment_balance / 10)

    details = {
        "news_count": news_count,
        "positive_headlines": positive,
        "negative_headlines": negative,
        "window_days": lookback_days,
    }
    if isinstance(ticker_data, dict) and ticker_data.get("results"):
        r = ticker_data.get("results", {})
        details["name"] = r.get("name")
        details["market"] = r.get("market")
        details["type"] = r.get("type")

    return _provider_result("Polygon.io", configured=True, enabled=True, available=True, details=details, score=score, weight=weight)


def _fmp_summary(symbol: str, weight: float) -> dict:
    key = settings.fmp_api_key
    if not key:
        return _provider_result("Financial Modeling Prep", configured=False, available=False, error="FMP_API_KEY missing", weight=weight)

    data, err = _http_get_json(FMP_INCOME_STATEMENT_URL, params={"symbol": symbol, "apikey": key})
    if err or data is None:
        return _provider_result("Financial Modeling Prep", configured=True, available=False, error=err, weight=weight)

    row = data[0] if isinstance(data, list) and data else {}
    score = 0.0
    try:
        # Score based on net income trend
        net_income = float(row.get("netIncome", 0)) if row.get("netIncome") is not None else 0
        revenue = float(row.get("revenue", 0)) if row.get("revenue") is not None else 0
        if revenue > 0:
            profit_margin = net_income / revenue
            if profit_margin > 0.2:
                score = 0.15  # Strong profitability
            elif profit_margin < 0.05:
                score = -0.15  # Weak profitability
    except Exception:
        score = 0.0

    return _provider_result(
        "Financial Modeling Prep",
        configured=True,
        enabled=True,
        available=bool(row),
        details={
            "fiscal_year": row.get("fiscalYear"),
            "period": row.get("period"),
            "revenue": row.get("revenue"),
            "net_income": row.get("netIncome"),
            "beta": row.get("beta"),
            "market_cap": row.get("mktCap"),
        },
        score=score,
        weight=weight,
    )


def _eodhd_summary(symbol: str, weight: float) -> dict:
    key = settings.eodhd_api_key
    if not key:
        return _provider_result("EODHD", configured=False, available=False, error="EODHD_API_KEY missing", weight=weight)

    data, err = _http_get_json(
        EODHD_EOD_URL.format(symbol=f"{symbol}.US"),
        params={"api_token": key, "fmt": "json"},
    )
    if err or data is None:
        data, err = _http_get_json(
            EODHD_EOD_URL.format(symbol=symbol),
            params={"api_token": key, "fmt": "json"},
        )

    if err or data is None:
        return _provider_result("EODHD", configured=True, available=False, error=err, weight=weight)

    row = data[0] if isinstance(data, list) and data else {}
    score = 0.0
    try:
        cp = float(row.get("change_p", 0.0) or 0.0)
        score = max(-1.0, min(1.0, cp / 5.0))
    except Exception:
        score = 0.0

    return _provider_result(
        "EODHD",
        configured=True,
        enabled=True,
        available=True,
        details={
            "close": row.get("close"),
            "change": row.get("change"),
            "change_p": row.get("change_p"),
            "volume": row.get("volume"),
        },
        score=score,
        weight=weight,
    )


def _fred_summary(weight: float) -> dict:
    key = settings.fred_api_key
    if not key:
        return _provider_result("FRED", configured=False, available=False, error="FRED_API_KEY missing", weight=weight)

    series = {
        "fed_funds_rate": "DFF",
        "unemployment_rate": "UNRATE",
        "cpi_index": "CPIAUCSL",
    }
    details: dict = {}
    for label, sid in series.items():
        data, err = _http_get_json(
            FRED_SERIES_URL,
            params={
                "series_id": sid,
                "api_key": key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            },
        )
        if err or data is None:
            continue
        obs = (data.get("observations") or [])
        if not obs:
            continue
        details[label] = {
            "value": obs[0].get("value"),
            "date": obs[0].get("date"),
        }

    score = 0.0
    try:
        ff = float(details.get("fed_funds_rate", {}).get("value")) if details.get("fed_funds_rate") else None
        ur = float(details.get("unemployment_rate", {}).get("value")) if details.get("unemployment_rate") else None
        cpi = float(details.get("cpi_index", {}).get("value")) if details.get("cpi_index") else None

        if ff is not None:
            if ff <= 3.0:
                score += 0.2
            elif ff >= 5.0:
                score -= 0.2
        if ur is not None:
            if ur <= 4.2:
                score += 0.2
            elif ur >= 6.0:
                score -= 0.2
        if cpi is not None:
            score += 0.0
    except Exception:
        score = 0.0

    score = max(-1.0, min(1.0, score))

    return _provider_result(
        "FRED",
        configured=True,
        enabled=True,
        available=bool(details),
        details=details,
        score=score,
        weight=weight,
    )


def _tiingo_summary(symbol: str, weight: float) -> dict:
    key = settings.tiingo_api_key
    if not key:
        return _provider_result("Tiingo", configured=False, available=False, error="TIINGO_API_KEY missing", weight=weight)

    data, err = _http_get_json(
        TIINGO_META_URL.format(symbol=symbol),
        headers={"Authorization": f"Token {key}"},
    )
    if err or data is None:
        return _provider_result("Tiingo", configured=True, available=False, error=err, weight=weight)

    return _provider_result(
        "Tiingo",
        configured=True,
        enabled=True,
        available=True,
        details={
            "name": data.get("name") if isinstance(data, dict) else None,
            "exchange": data.get("exchangeCode") if isinstance(data, dict) else None,
            "description": data.get("description") if isinstance(data, dict) else None,
        },
        score=0.0,
        weight=weight,
    )


def _lunarcrush_summary(symbol: str, weight: float) -> dict:
    key = settings.lunarcrush_api_key
    if not key:
        return _provider_result("StockGeist / LunarCrush", configured=False, available=False, error="LUNARCRUSH_API_KEY missing", weight=weight)

    url = LUNARCRUSH_ASSET_URL.format(symbol=symbol)
    try:
        with __import__("httpx").Client(timeout=12, follow_redirects=True) as client:
            resp = client.get(url, headers={"Authorization": f"Token {key}"})
            if resp.status_code == 402:
                return _provider_result("StockGeist / LunarCrush", configured=True, available=False,
                                        error="Subscription plan required (LunarCrush Individual+)", weight=weight)
            if resp.status_code == 429:
                return _provider_result("StockGeist / LunarCrush", configured=True, available=False,
                                        error="Rate limit exceeded — try again later", weight=weight)
            if resp.status_code != 200:
                try:
                    msg = resp.json().get("error") or f"HTTP {resp.status_code}"
                except Exception:
                    msg = f"HTTP {resp.status_code}"
                return _provider_result("StockGeist / LunarCrush", configured=True, available=False, error=msg, weight=weight)
            data = resp.json()
    except Exception as exc:
        return _provider_result("StockGeist / LunarCrush", configured=True, available=False, error=str(exc), weight=weight)

    details = {}
    score = 0.0
    if isinstance(data, dict):
        details["keys"] = sorted(list(data.keys()))[:12]
        sentiment_like = data.get("sentiment") or data.get("market_sentiment")
        try:
            if sentiment_like is not None:
                score = max(-1.0, min(1.0, float(sentiment_like)))
        except Exception:
            score = 0.0

    return _provider_result(
        "StockGeist / LunarCrush",
        configured=True,
        enabled=True,
        available=True,
        details=details,
        score=score,
        weight=weight,
    )


def _normalize_total_score(raw_score: float) -> int:
    if raw_score >= 1.5:
        return 2
    if raw_score >= 0.5:
        return 1
    if raw_score <= -1.5:
        return -2
    if raw_score <= -0.5:
        return -1
    return 0


def get_alternative_signal(symbol: str, *, reference_date: Optional[date] = None, lookback_days: int = 30) -> dict:
    """Aggregate multi-provider alternative data and derive a compact signal score."""
    symbol = symbol.upper()

    provider_specs: list[tuple[str, str, bool, float, callable]] = [
        (
            "capitol_trades",
            "Capitol Trades",
            settings.alt_enable_capitol_trades,
            max(0.0, settings.alt_weight_capitol_trades),
            lambda: _capitol_summary(symbol, reference_date, lookback_days, max(0.0, settings.alt_weight_capitol_trades)),
        ),
        (
            "openinsider",
            "OpenInsider",
            settings.alt_enable_openinsider,
            max(0.0, settings.alt_weight_openinsider),
            lambda: _openinsider_summary(symbol, reference_date, lookback_days, max(0.0, settings.alt_weight_openinsider)),
        ),
        (
            "whalewisdom",
            "WhaleWisdom",
            settings.alt_enable_whalewisdom,
            max(0.0, settings.alt_weight_whalewisdom),
            lambda: _whalewisdom_summary(symbol, max(0.0, settings.alt_weight_whalewisdom)),
        ),
        (
            "quiver_quantitative",
            "Quiver Quantitative",
            settings.alt_enable_quiver_quantitative,
            max(0.0, settings.alt_weight_quiver_quantitative),
            lambda: _quiver_summary(symbol, reference_date, lookback_days, max(0.0, settings.alt_weight_quiver_quantitative)),
        ),
        (
            "alpha_vantage_news_sentiment",
            "Alpha Vantage",
            settings.alt_enable_alpha_vantage,
            max(0.0, settings.alt_weight_alpha_vantage),
            lambda: _alpha_vantage_summary(symbol, reference_date, lookback_days, max(0.0, settings.alt_weight_alpha_vantage)),
        ),
        (
            "polygon",
            "Polygon.io",
            settings.alt_enable_polygon,
            max(0.0, settings.alt_weight_polygon),
            lambda: _polygon_summary(symbol, reference_date, lookback_days, max(0.0, settings.alt_weight_polygon)),
        ),
        (
            "financial_modeling_prep",
            "Financial Modeling Prep",
            settings.alt_enable_fmp,
            max(0.0, settings.alt_weight_fmp),
            lambda: _fmp_summary(symbol, max(0.0, settings.alt_weight_fmp)),
        ),
        (
            "eodhd",
            "EODHD",
            settings.alt_enable_eodhd,
            max(0.0, settings.alt_weight_eodhd),
            lambda: _eodhd_summary(symbol, max(0.0, settings.alt_weight_eodhd)),
        ),
        (
            "fred",
            "FRED",
            settings.alt_enable_fred,
            max(0.0, settings.alt_weight_fred),
            lambda: _fred_summary(max(0.0, settings.alt_weight_fred)),
        ),
        (
            "tiingo",
            "Tiingo",
            settings.alt_enable_tiingo,
            max(0.0, settings.alt_weight_tiingo),
            lambda: _tiingo_summary(symbol, max(0.0, settings.alt_weight_tiingo)),
        ),
        (
            "stockgeist_lunarcrush",
            "StockGeist / LunarCrush",
            settings.alt_enable_lunarcrush,
            max(0.0, settings.alt_weight_lunarcrush),
            lambda: _lunarcrush_summary(symbol, max(0.0, settings.alt_weight_lunarcrush)),
        ),
    ]

    providers: dict[str, dict] = {}
    for key, name, enabled, weight, fn in provider_specs:
        if not enabled:
            providers[key] = _disabled_provider(name, "Disabled by settings", weight)
            continue
        providers[key] = fn()

    raw_score = sum(float(v.get("weighted_score", 0.0) or 0.0) for v in providers.values())
    enabled_weight_sum = sum(float(v.get("weight", 0.0) or 0.0) for v in providers.values() if v.get("enabled"))
    normalized_raw = (raw_score / enabled_weight_sum * 2.0) if enabled_weight_sum > 0 else 0.0
    normalized_raw = max(-2.0, min(2.0, normalized_raw))
    alt_score = _normalize_total_score(normalized_raw)

    if alt_score >= 2:
        label = "BULLISH"
    elif alt_score <= -2:
        label = "BEARISH"
    else:
        label = "NEUTRAL"

    available_count = sum(1 for v in providers.values() if v.get("enabled") and v.get("available"))
    configured_count = sum(1 for v in providers.values() if v.get("enabled") and v.get("configured"))
    enabled_count = sum(1 for v in providers.values() if v.get("enabled"))

    return {
        "symbol": symbol,
        "lookback_days": lookback_days,
        "as_of_date": _today(reference_date).isoformat(),
        "providers": providers,
        "alternative_score": alt_score,
        "alternative_signal": label,
        "raw_score": round(raw_score, 4),
        "normalized_raw_score": round(normalized_raw, 4),
        "enabled_weight_sum": round(enabled_weight_sum, 4),
        "enabled_sources": enabled_count,
        "available_sources": available_count,
        "configured_sources": configured_count,
    }
