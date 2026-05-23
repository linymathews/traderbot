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
- Yahoo Ownership Signals
- Yahoo Short Interest Pressure
- Yahoo Analyst Consensus / Target Spread
- Finnhub Analyst Recommendation Trends
- Finviz Analyst Snapshot (scraped)
- SEC EDGAR Filings Activity
- Yahoo Options Flow Pressure
- Yahoo Earnings Revision Proxy
- Yahoo Credit Stress Proxy
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
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
FMP_PROFILE_URL           = "https://financialmodelingprep.com/stable/profile"
FMP_KEY_METRICS_URL       = "https://financialmodelingprep.com/stable/key-metrics"
FMP_ANALYST_ESTIMATES_URL = "https://financialmodelingprep.com/stable/analyst-estimates"
FMP_PRICE_TARGET_URL      = "https://financialmodelingprep.com/stable/price-target-consensus"
FMP_DCF_URL               = "https://financialmodelingprep.com/stable/discounted-cash-flow"
FMP_RATING_URL            = "https://financialmodelingprep.com/stable/rating"
FMP_EARNINGS_SURPRISES_URL= "https://financialmodelingprep.com/stable/earnings-surprises"
FMP_INSIDER_TRADING_URL   = "https://financialmodelingprep.com/stable/insider-trading"
FMP_GRADE_URL             = "https://financialmodelingprep.com/stable/grade"
EODHD_EOD_URL = "https://eodhd.com/api/eod/{symbol}"
FRED_SERIES_URL = "https://api.stlouisfed.org/fred/series/observations"
TIINGO_META_URL = "https://api.tiingo.com/tiingo/daily/{symbol}"
LUNARCRUSH_ASSET_URL = "https://lunarcrush.com/api4/public/topic/{symbol}/v1"
FINNHUB_RECOMMENDATION_URL = "https://finnhub.io/api/v1/stock/recommendation"
FINVIZ_QUOTE_URL = "https://finviz.com/quote.ashx"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"


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


def _fmp_summary(symbol: str, weight: float) -> dict:  # noqa: PLR0912,PLR0915
    key = settings.fmp_api_key
    if not key:
        return _provider_result(
            "Financial Modeling Prep", configured=False, available=False,
            error="FMP_API_KEY missing", weight=weight,
        )

    base_params  = {"symbol": symbol, "apikey": key}
    limit_params = {**base_params, "limit": 8}

    # ── Fetch all endpoints in parallel ──────────────────────────────────────
    def _fetch(url: str, p: dict) -> tuple:
        return _http_get_json(url, params=p)

    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
        f_profile   = pool.submit(_fetch, FMP_PROFILE_URL,           base_params)
        f_metrics   = pool.submit(_fetch, FMP_KEY_METRICS_URL,       limit_params)
        f_estimates = pool.submit(_fetch, FMP_ANALYST_ESTIMATES_URL, limit_params)
        f_target    = pool.submit(_fetch, FMP_PRICE_TARGET_URL,      base_params)
        f_dcf       = pool.submit(_fetch, FMP_DCF_URL,               base_params)
        f_rating    = pool.submit(_fetch, FMP_RATING_URL,            base_params)
        f_surprises = pool.submit(_fetch, FMP_EARNINGS_SURPRISES_URL, limit_params)
        f_insider   = pool.submit(_fetch, FMP_INSIDER_TRADING_URL,   {**base_params, "limit": 20})
        f_grade     = pool.submit(_fetch, FMP_GRADE_URL,             {**base_params, "limit": 10})

        profile_data,   _  = f_profile.result()
        metrics_data,   _  = f_metrics.result()
        estimates_data, _  = f_estimates.result()
        target_data,    _  = f_target.result()
        dcf_data,       _  = f_dcf.result()
        rating_data,    _  = f_rating.result()
        surprises_data, _  = f_surprises.result()
        insider_data,   _  = f_insider.result()
        grade_data,     _  = f_grade.result()

    def _first(d):
        if isinstance(d, list) and d:
            return d[0]
        return d if isinstance(d, dict) else {}

    profile  = _first(profile_data)
    metrics  = _first(metrics_data)
    dcf      = _first(dcf_data)
    rating   = _first(rating_data)
    target   = _first(target_data)

    estimates_list = estimates_data if isinstance(estimates_data, list) else []
    estimates_list = sorted(estimates_list, key=lambda x: x.get("date", ""), reverse=True)
    fwd_estimate   = estimates_list[0] if estimates_list else {}

    surprises  = surprises_data  if isinstance(surprises_data,  list) else []
    insiders   = insider_data    if isinstance(insider_data,     list) else []
    grades     = grade_data      if isinstance(grade_data,       list) else []

    score    = 0.0
    details: dict = {}

    # ── 1. DCF vs price ───────────────────────────────────────────────────────
    dcf_value     = None
    current_price = None
    dcf_upside    = None
    try:
        dcf_value     = float(dcf.get("dcf") or 0)
        current_price = float(dcf.get("Stock Price") or profile.get("price") or 0)
        if dcf_value > 0 and current_price > 0:
            dcf_upside = (dcf_value - current_price) / current_price
            if   dcf_upside >=  0.25: score += 0.30
            elif dcf_upside >=  0.10: score += 0.15
            elif dcf_upside <= -0.25: score -= 0.30
            elif dcf_upside <= -0.10: score -= 0.15
    except Exception:
        pass
    details["dcf_value"]      = round(dcf_value, 2)       if dcf_value       else None
    details["dcf_price"]      = round(current_price, 2)   if current_price   else None
    details["dcf_upside_pct"] = round(dcf_upside * 100, 2) if dcf_upside is not None else None

    # ── 2. FMP composite rating (1–5 scale) ───────────────────────────────────
    fmp_rating_score = None
    try:
        rs = int(rating.get("ratingScore") or 0)
        if rs:
            fmp_rating_score = rs
            if   rs == 5: score += 0.25
            elif rs == 4: score += 0.15
            elif rs == 2: score -= 0.15
            elif rs == 1: score -= 0.25
    except Exception:
        pass
    details["fmp_rating"]             = rating.get("rating")
    details["fmp_rating_score"]       = fmp_rating_score
    details["fmp_rating_rec"]         = rating.get("ratingRecommendation")
    details["fmp_rating_dcf_score"]   = rating.get("ratingDetailsDCFScore")
    details["fmp_rating_roe_score"]   = rating.get("ratingDetailsROEScore")
    details["fmp_rating_roa_score"]   = rating.get("ratingDetailsROAScore")

    # ── 3. Analyst price target upside ────────────────────────────────────────
    target_consensus = None
    target_upside    = None
    try:
        tc = float(target.get("targetConsensus") or 0)
        if tc > 0 and current_price and current_price > 0:
            target_consensus = tc
            target_upside = (tc - current_price) / current_price
            if   target_upside >=  0.25: score += 0.25
            elif target_upside >=  0.10: score += 0.15
            elif target_upside <= -0.20: score -= 0.25
            elif target_upside <= -0.10: score -= 0.15
    except Exception:
        pass
    details["analyst_target_consensus"]  = round(target_consensus, 2) if target_consensus else None
    details["analyst_target_high"]       = target.get("targetHigh")
    details["analyst_target_low"]        = target.get("targetLow")
    details["analyst_target_median"]     = target.get("targetMedian")
    details["analyst_target_upside_pct"] = round(target_upside * 100, 2) if target_upside is not None else None

    # ── 4. Earnings surprise streak ───────────────────────────────────────────
    beats = 0
    misses = 0
    surprise_list: list[dict] = []
    for s in surprises[:4]:
        try:
            actual    = float(s.get("actualEarningResult")  or 0)
            estimated = float(s.get("estimatedEarning")     or 0)
            if abs(estimated) > 0.001:
                beat = actual > estimated
                beats  += 1 if beat else 0
                misses += 0 if beat else 1
                surprise_pct = (actual - estimated) / abs(estimated) * 100
                surprise_list.append({
                    "date":         s.get("date"),
                    "actual":       round(actual, 4),
                    "estimated":    round(estimated, 4),
                    "surprise_pct": round(surprise_pct, 2),
                    "beat":         beat,
                })
        except Exception:
            pass
    if beats + misses >= 2:
        if   beats == 4:  score += 0.20
        elif beats == 3:  score += 0.10
        elif misses == 4: score -= 0.20
        elif misses == 3: score -= 0.10
    details["earnings_surprises"] = surprise_list
    details["earnings_beats"]     = beats
    details["earnings_misses"]    = misses

    # ── 5. Piotroski F-Score ──────────────────────────────────────────────────
    piotroski = None
    try:
        ps = int(metrics.get("piotroskiScore") or 0)
        if ps:
            piotroski = ps
            if   ps >= 7: score += 0.15
            elif ps <= 3: score -= 0.15
    except Exception:
        pass
    details["piotroski_score"] = piotroski

    # ── 6. Insider net activity (last 90 days) ────────────────────────────────
    purchases_90d = 0
    sales_90d     = 0
    insider_list: list[dict] = []
    cutoff = _today(None) - timedelta(days=90)
    for tr in insiders[:20]:
        raw_date = tr.get("transactionDate") or tr.get("filingDate")
        tx_date  = _safe_date(str(raw_date)) if raw_date else None
        if not tx_date or tx_date < cutoff:
            continue
        acq = str(tr.get("acquistionOrDisposition") or "").upper()
        ttype = str(tr.get("transactionType") or "").upper()
        is_buy  = acq == "A" or "P-PURCHASE" in ttype
        is_sell = acq == "D" or "S-SALE" in ttype
        if not is_buy and not is_sell:
            continue
        purchases_90d += 1 if is_buy  else 0
        sales_90d     += 1 if is_sell else 0
        try:
            shares = int(float(tr.get("securitiesTransacted") or 0))
        except Exception:
            shares = 0
        insider_list.append({
            "name":   tr.get("reportingName"),
            "date":   str(tx_date),
            "type":   "BUY" if is_buy else "SELL",
            "shares": shares,
            "price":  tr.get("price"),
        })
    if purchases_90d + sales_90d >= 2:
        net = purchases_90d - sales_90d
        if   net >=  2: score += 0.15
        elif net <= -2: score -= 0.15
    details["insider_purchases_90d"] = purchases_90d
    details["insider_sales_90d"]     = sales_90d
    details["insider_trades"]        = insider_list[:6]

    # ── 7. Forward EPS growth ─────────────────────────────────────────────────
    try:
        trailing_eps = float(profile.get("eps") or 0)
        forward_eps  = float(fwd_estimate.get("estimatedEpsAvg") or 0)
        if abs(trailing_eps) > 0.01 and forward_eps:
            eps_growth = (forward_eps - trailing_eps) / abs(trailing_eps)
            if   eps_growth >=  0.15: score += 0.15
            elif eps_growth >=  0.05: score += 0.08
            elif eps_growth <= -0.10: score -= 0.15
            elif eps_growth <= -0.03: score -= 0.08
            details["eps_growth_forecast_pct"] = round(eps_growth * 100, 2)
    except Exception:
        pass

    # ── 8. Recent analyst grade momentum ─────────────────────────────────────
    upgrades   = 0
    downgrades = 0
    grade_cutoff = _today(None) - timedelta(days=90)
    for g in grades[:10]:
        gd = _safe_date(str(g.get("date") or ""))
        if not gd or gd < grade_cutoff:
            continue
        action = str(g.get("action") or "").lower()
        if "upgrade" in action:
            upgrades   += 1
        elif "downgrade" in action:
            downgrades += 1
    if upgrades + downgrades >= 2:
        if upgrades > downgrades:   score += 0.10
        elif downgrades > upgrades: score -= 0.10
    details["analyst_upgrades_90d"]   = upgrades
    details["analyst_downgrades_90d"] = downgrades

    # ── Profile meta ─────────────────────────────────────────────────────────
    details["company_name"] = profile.get("companyName") or profile.get("name")
    details["ceo"]          = profile.get("ceo")
    details["sector"]       = profile.get("sector")
    details["industry"]     = profile.get("industry")
    details["beta"]         = profile.get("beta")
    details["market_cap"]   = profile.get("mktCap")
    details["employees"]    = profile.get("fullTimeEmployees")
    details["exchange"]     = profile.get("exchange") or profile.get("exchangeShortName")
    details["roe"]          = metrics.get("roe")
    details["roa"]          = metrics.get("roa")
    details["pe_ratio"]     = metrics.get("peRatio")
    details["pb_ratio"]     = metrics.get("pbRatio")
    details["ev_to_ebitda"] = metrics.get("evToEbitda")
    details["debt_to_equity"]       = metrics.get("debtToEquity")
    details["current_ratio"]        = metrics.get("currentRatio")
    details["free_cashflow_yield"]  = metrics.get("freeCashFlowYield")
    details["earnings_yield"]       = metrics.get("earningsYield")
    details["dividend_yield"]       = metrics.get("dividendYield")
    details["analyst_estimate_eps"] = fwd_estimate.get("estimatedEpsAvg")
    details["analyst_estimate_rev"] = fwd_estimate.get("estimatedRevenueAvg")
    details["analyst_estimate_date"]= fwd_estimate.get("date")

    score = max(-1.0, min(1.0, score))
    available = bool(profile or dcf or rating)

    return _provider_result(
        "Financial Modeling Prep",
        configured=True,
        enabled=True,
        available=available,
        details=details,
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


def _yahoo_ownership_summary(symbol: str, weight: float) -> dict:
    try:
        yf_mod = __import__("yfinance")
        info = yf_mod.Ticker(symbol).info or {}
    except Exception as exc:
        return _provider_result("Yahoo Ownership", configured=True, available=False, error=str(exc), weight=weight)

    inst = info.get("heldPercentInstitutions")
    insider = info.get("heldPercentInsiders")

    inst_v = float(inst) if inst is not None else None
    insider_v = float(insider) if insider is not None else None

    score = 0.0
    if inst_v is not None:
        if inst_v >= 0.65:
            score += 0.25
        elif inst_v <= 0.35:
            score -= 0.2
    if insider_v is not None:
        if insider_v >= 0.08:
            score += 0.25
        elif insider_v <= 0.01:
            score -= 0.15

    score = max(-1.0, min(1.0, score))
    available = inst_v is not None or insider_v is not None

    return _provider_result(
        "Yahoo Ownership",
        configured=True,
        enabled=True,
        available=available,
        details={
            "held_percent_institutions": round(inst_v, 4) if inst_v is not None else None,
            "held_percent_insiders": round(insider_v, 4) if insider_v is not None else None,
        },
        score=score,
        weight=weight,
    )


def _yahoo_short_interest_summary(symbol: str, weight: float) -> dict:
    try:
        yf_mod = __import__("yfinance")
        info = yf_mod.Ticker(symbol).info or {}
    except Exception as exc:
        return _provider_result("Yahoo Short Interest", configured=True, available=False, error=str(exc), weight=weight)

    spf = info.get("shortPercentOfFloat")
    sr = info.get("shortRatio")

    spf_v = float(spf) if spf is not None else None
    sr_v = float(sr) if sr is not None else None

    score = 0.0
    if spf_v is not None:
        if spf_v >= 0.20:
            score -= 0.7
        elif spf_v >= 0.12:
            score -= 0.35
        elif spf_v <= 0.05:
            score += 0.25
    if sr_v is not None:
        if sr_v >= 8:
            score -= 0.45
        elif sr_v >= 5:
            score -= 0.2
        elif sr_v <= 2.5:
            score += 0.2

    score = max(-1.0, min(1.0, score))
    available = spf_v is not None or sr_v is not None

    return _provider_result(
        "Yahoo Short Interest",
        configured=True,
        enabled=True,
        available=available,
        details={
            "short_percent_float": round(spf_v, 4) if spf_v is not None else None,
            "short_ratio": round(sr_v, 4) if sr_v is not None else None,
        },
        score=score,
        weight=weight,
    )


def _yahoo_analyst_summary(symbol: str, weight: float) -> dict:
    try:
        yf_mod = __import__("yfinance")
        info = yf_mod.Ticker(symbol).info or {}
    except Exception as exc:
        return _provider_result("Yahoo Analyst Consensus", configured=True, available=False, error=str(exc), weight=weight)

    rec_mean = info.get("recommendationMean")
    analyst_count = info.get("numberOfAnalystOpinions")
    target = info.get("targetMeanPrice")
    current = info.get("currentPrice") or info.get("regularMarketPrice")

    rec_v = float(rec_mean) if rec_mean is not None else None
    analysts_v = int(analyst_count) if analyst_count is not None else 0
    target_v = float(target) if target is not None else None
    current_v = float(current) if current is not None else None

    score = 0.0
    if rec_v is not None:
        if rec_v <= 2.2:
            score += 0.45
        elif rec_v <= 2.8:
            score += 0.2
        elif rec_v >= 3.4:
            score -= 0.45
        elif rec_v >= 3.0:
            score -= 0.2

    upside = None
    if target_v is not None and current_v is not None and current_v > 0:
        upside = (target_v - current_v) / current_v
        if upside >= 0.15:
            score += 0.45
        elif upside >= 0.06:
            score += 0.2
        elif upside <= -0.10:
            score -= 0.45
        elif upside <= -0.03:
            score -= 0.2

    # lower confidence when analyst coverage is thin
    if analysts_v and analysts_v < 5:
        score *= 0.7

    score = max(-1.0, min(1.0, score))
    available = rec_v is not None or upside is not None

    return _provider_result(
        "Yahoo Analyst Consensus",
        configured=True,
        enabled=True,
        available=available,
        details={
            "recommendation_mean": round(rec_v, 3) if rec_v is not None else None,
            "analyst_count": analysts_v,
            "target_mean_price": round(target_v, 4) if target_v is not None else None,
            "current_price": round(current_v, 4) if current_v is not None else None,
            "upside_pct": round(upside * 100, 2) if upside is not None else None,
        },
        score=score,
        weight=weight,
    )


def _finnhub_recommendation_summary(symbol: str, reference_date: Optional[date], lookback_days: int, weight: float) -> dict:
    key = settings.finnhub_api_key
    if not key:
        return _provider_result("Finnhub Analyst Trends", configured=False, available=False, error="FINNHUB_API_KEY missing", weight=weight)

    data, err = _http_get_json(
        FINNHUB_RECOMMENDATION_URL,
        params={"symbol": symbol, "token": key},
    )
    if err or data is None:
        return _provider_result("Finnhub Analyst Trends", configured=True, available=False, error=err, weight=weight)

    rows = data if isinstance(data, list) else []
    as_of = _today(reference_date)
    cutoff = as_of - timedelta(days=max(lookback_days, 30))
    recent = []
    for r in rows:
        d = _safe_date(str(r.get("period", "")))
        if d and cutoff <= d <= as_of:
            recent.append(r)
    if not recent and rows:
        recent = [rows[0]]
    if not recent:
        return _provider_result("Finnhub Analyst Trends", configured=True, available=False, error="No recommendation history", weight=weight)

    latest = recent[0]
    sb = int(latest.get("strongBuy", 0) or 0)
    b = int(latest.get("buy", 0) or 0)
    h = int(latest.get("hold", 0) or 0)
    s = int(latest.get("sell", 0) or 0)
    ss = int(latest.get("strongSell", 0) or 0)
    total = sb + b + h + s + ss
    net = (sb + b) - (s + ss)
    score = max(-1.0, min(1.0, (net / total) if total > 0 else 0.0))

    return _provider_result(
        "Finnhub Analyst Trends",
        configured=True,
        enabled=True,
        available=True,
        score=score,
        weight=weight,
        details={
            "period": latest.get("period"),
            "strong_buy": sb,
            "buy": b,
            "hold": h,
            "sell": s,
            "strong_sell": ss,
            "analyst_total": total,
            "window_days": lookback_days,
        },
    )


def _finviz_snapshot_summary(symbol: str, weight: float) -> dict:
    text, err = _http_get_text(
        FINVIZ_QUOTE_URL,
        params={"t": symbol},
        headers={"User-Agent": "Mozilla/5.0"},
    )
    if err or not text:
        return _provider_result("Finviz Analyst Snapshot", configured=True, available=False, error=err, weight=weight)

    soup = BeautifulSoup(text, "lxml")
    snapshot = soup.find("table", class_="snapshot-table2")
    if not snapshot:
        return _provider_result("Finviz Analyst Snapshot", configured=True, available=False, error="Snapshot table not found", weight=weight)

    cells = [td.get_text(" ", strip=True) for td in snapshot.find_all("td")]
    kv: dict[str, str] = {}
    for i in range(0, len(cells) - 1, 2):
        k = cells[i]
        v = cells[i + 1]
        if k:
            kv[k] = v

    def _num(v: str | None) -> float | None:
        if not v:
            return None
        txt = str(v).replace(",", "")
        m = re.search(r"-?\d+(?:\.\d+)?", txt)
        if not m:
            return None
        try:
            return float(m.group(0))
        except Exception:
            return None

    recom = _num(kv.get("Recom"))
    target = _num(kv.get("Target Price"))
    price = _num(kv.get("Price"))
    perf_month = _num(kv.get("Perf Month"))

    score = 0.0
    if recom is not None:
        if recom <= 2.0:
            score += 0.45
        elif recom <= 2.6:
            score += 0.2
        elif recom >= 3.4:
            score -= 0.45
        elif recom >= 3.0:
            score -= 0.2

    if target is not None and price is not None and price > 0:
        upside = (target - price) / price
        if upside >= 0.15:
            score += 0.4
        elif upside >= 0.06:
            score += 0.2
        elif upside <= -0.1:
            score -= 0.4
        elif upside <= -0.03:
            score -= 0.2

    if perf_month is not None:
        if perf_month >= 10:
            score += 0.1
        elif perf_month <= -10:
            score -= 0.1

    score = max(-1.0, min(1.0, score))

    return _provider_result(
        "Finviz Analyst Snapshot",
        configured=True,
        enabled=True,
        available=bool(kv),
        score=score,
        weight=weight,
        details={
            "recom": recom,
            "target_price": target,
            "price": price,
            "perf_month_pct": perf_month,
            "url": f"{FINVIZ_QUOTE_URL}?t={symbol}",
        },
    )


def _sec_edgar_filings_summary(symbol: str, reference_date: Optional[date], lookback_days: int, weight: float) -> dict:
    try:
        yf_mod = __import__("yfinance")
        info = yf_mod.Ticker(symbol).info or {}
    except Exception as exc:
        return _provider_result("SEC EDGAR Filings", configured=True, available=False, error=str(exc), weight=weight)

    cik_raw = info.get("cik")
    cik: Optional[str] = None
    if cik_raw is not None:
        cik = str(int(cik_raw)).zfill(10)
    else:
        # Fallback to SEC official ticker mapping when Yahoo omits CIK.
        mapping, map_err = _http_get_json(
            SEC_TICKER_MAP_URL,
            headers={"User-Agent": "traderbot/1.0 (research@example.com)", "Accept": "application/json"},
        )
        if map_err or mapping is None:
            return _provider_result("SEC EDGAR Filings", configured=True, available=False, error="CIK unavailable", weight=weight)

        try:
            for _, row in (mapping.items() if isinstance(mapping, dict) else []):
                t = str(row.get("ticker", "")).upper().strip()
                if t == symbol:
                    cik = str(int(row.get("cik_str"))).zfill(10)
                    break
        except Exception:
            cik = None

        if not cik:
            return _provider_result("SEC EDGAR Filings", configured=True, available=False, error="CIK unavailable", weight=weight)
    data, err = _http_get_json(
        SEC_SUBMISSIONS_URL.format(cik=cik),
        headers={"User-Agent": "traderbot/1.0 (research@example.com)", "Accept": "application/json"},
    )
    if err or data is None:
        return _provider_result("SEC EDGAR Filings", configured=True, available=False, error=err, weight=weight)

    recent = (data.get("filings", {}) or {}).get("recent", {}) or {}
    forms = recent.get("form", []) or []
    dates = recent.get("filingDate", []) or []
    if not forms or not dates:
        return _provider_result("SEC EDGAR Filings", configured=True, available=False, error="No filing history", weight=weight)

    as_of = _today(reference_date)
    cutoff = as_of - timedelta(days=max(lookback_days, 30))

    form_counts: dict[str, int] = {"8-K": 0, "10-Q": 0, "10-K": 0, "4": 0, "13D": 0, "13G": 0}
    latest_periodic: Optional[date] = None

    for f, d_raw in zip(forms, dates):
        d = _safe_date(str(d_raw))
        if not d:
            continue
        if f in ("10-Q", "10-K") and (latest_periodic is None or d > latest_periodic):
            latest_periodic = d
        if d < cutoff or d > as_of:
            continue
        if f in form_counts:
            form_counts[f] += 1

    score = 0.0
    if latest_periodic is not None:
        age_days = (as_of - latest_periodic).days
        if age_days <= 120:
            score += 0.25
        elif age_days >= 220:
            score -= 0.35
    else:
        score -= 0.2

    if form_counts["8-K"] >= 6:
        score -= 0.2
    if (form_counts["4"] + form_counts["13D"] + form_counts["13G"]) >= 2:
        score += 0.15

    score = max(-1.0, min(1.0, score))

    return _provider_result(
        "SEC EDGAR Filings",
        configured=True,
        enabled=True,
        available=True,
        score=score,
        weight=weight,
        details={
            "cik": cik,
            "latest_periodic_filing": latest_periodic.isoformat() if latest_periodic else None,
            "counts_window": form_counts,
            "window_days": lookback_days,
        },
    )


def _yahoo_options_flow_summary(symbol: str, weight: float) -> dict:
    try:
        yf_mod = __import__("yfinance")
        t = yf_mod.Ticker(symbol)
        expirations = list(t.options or [])
        if not expirations:
            return _provider_result("Yahoo Options Flow", configured=True, available=False, error="No options expirations", weight=weight)
        chain = t.option_chain(expirations[0])
        calls = chain.calls
        puts = chain.puts
    except Exception as exc:
        return _provider_result("Yahoo Options Flow", configured=True, available=False, error=str(exc), weight=weight)

    total_call_oi = int(calls["openInterest"].fillna(0).sum()) if calls is not None and not calls.empty and "openInterest" in calls.columns else 0
    total_put_oi = int(puts["openInterest"].fillna(0).sum()) if puts is not None and not puts.empty and "openInterest" in puts.columns else 0
    total_call_vol = int(calls["volume"].fillna(0).sum()) if calls is not None and not calls.empty and "volume" in calls.columns else 0
    total_put_vol = int(puts["volume"].fillna(0).sum()) if puts is not None and not puts.empty and "volume" in puts.columns else 0

    oi_ratio = (total_put_oi / total_call_oi) if total_call_oi > 0 else None
    vol_ratio = (total_put_vol / total_call_vol) if total_call_vol > 0 else None

    score = 0.0
    for ratio in (oi_ratio, vol_ratio):
        if ratio is None:
            continue
        if ratio <= 0.75:
            score += 0.45
        elif ratio <= 0.95:
            score += 0.2
        elif ratio >= 1.35:
            score -= 0.45
        elif ratio >= 1.1:
            score -= 0.2
    score = max(-1.0, min(1.0, score))

    return _provider_result(
        "Yahoo Options Flow",
        configured=True,
        enabled=True,
        available=True,
        score=score,
        weight=weight,
        details={
            "nearest_expiration": expirations[0],
            "put_call_oi_ratio": round(oi_ratio, 4) if oi_ratio is not None else None,
            "put_call_volume_ratio": round(vol_ratio, 4) if vol_ratio is not None else None,
            "total_call_open_interest": total_call_oi,
            "total_put_open_interest": total_put_oi,
            "total_call_volume": total_call_vol,
            "total_put_volume": total_put_vol,
        },
    )


def _yahoo_earnings_revision_summary(symbol: str, weight: float) -> dict:
    try:
        yf_mod = __import__("yfinance")
        info = yf_mod.Ticker(symbol).info or {}
    except Exception as exc:
        return _provider_result("Yahoo Earnings Revision", configured=True, available=False, error=str(exc), weight=weight)

    trailing_eps = info.get("trailingEps")
    forward_eps = info.get("forwardEps")
    earnings_growth = info.get("earningsGrowth")
    revenue_growth = info.get("revenueGrowth")

    t_eps = float(trailing_eps) if trailing_eps is not None else None
    f_eps = float(forward_eps) if forward_eps is not None else None
    e_growth = float(earnings_growth) if earnings_growth is not None else None
    r_growth = float(revenue_growth) if revenue_growth is not None else None

    score = 0.0
    revision = None
    if t_eps is not None and f_eps is not None and abs(t_eps) > 1e-9:
        revision = (f_eps - t_eps) / abs(t_eps)
        if revision >= 0.12:
            score += 0.55
        elif revision >= 0.04:
            score += 0.25
        elif revision <= -0.10:
            score -= 0.55
        elif revision <= -0.03:
            score -= 0.25

    if e_growth is not None:
        if e_growth >= 0.12:
            score += 0.2
        elif e_growth <= -0.1:
            score -= 0.2
    if r_growth is not None:
        if r_growth >= 0.08:
            score += 0.1
        elif r_growth <= -0.06:
            score -= 0.1

    score = max(-1.0, min(1.0, score))

    return _provider_result(
        "Yahoo Earnings Revision",
        configured=True,
        enabled=True,
        available=(revision is not None or e_growth is not None or r_growth is not None),
        score=score,
        weight=weight,
        details={
            "trailing_eps": round(t_eps, 4) if t_eps is not None else None,
            "forward_eps": round(f_eps, 4) if f_eps is not None else None,
            "eps_revision_pct": round(revision * 100, 2) if revision is not None else None,
            "earnings_growth": round(e_growth, 4) if e_growth is not None else None,
            "revenue_growth": round(r_growth, 4) if r_growth is not None else None,
        },
    )


def _yahoo_credit_stress_summary(symbol: str, weight: float) -> dict:
    try:
        yf_mod = __import__("yfinance")
        info = yf_mod.Ticker(symbol).info or {}
    except Exception as exc:
        return _provider_result("Yahoo Credit Stress", configured=True, available=False, error=str(exc), weight=weight)

    debt_to_equity = info.get("debtToEquity")
    current_ratio = info.get("currentRatio")
    quick_ratio = info.get("quickRatio")
    interest_cov = info.get("interestCoverage")

    dte = float(debt_to_equity) if debt_to_equity is not None else None
    cr = float(current_ratio) if current_ratio is not None else None
    qr = float(quick_ratio) if quick_ratio is not None else None
    ic = float(interest_cov) if interest_cov is not None else None

    score = 0.0
    if dte is not None:
        if dte <= 80:
            score += 0.35
        elif dte <= 140:
            score += 0.1
        elif dte >= 260:
            score -= 0.5
        elif dte >= 180:
            score -= 0.25
    if cr is not None:
        if cr >= 1.4:
            score += 0.2
        elif cr < 1.0:
            score -= 0.25
    if qr is not None:
        if qr >= 1.0:
            score += 0.1
        elif qr < 0.7:
            score -= 0.15
    if ic is not None:
        if ic >= 5:
            score += 0.15
        elif ic < 2:
            score -= 0.2

    score = max(-1.0, min(1.0, score))

    return _provider_result(
        "Yahoo Credit Stress",
        configured=True,
        enabled=True,
        available=(dte is not None or cr is not None or qr is not None or ic is not None),
        score=score,
        weight=weight,
        details={
            "debt_to_equity": round(dte, 3) if dte is not None else None,
            "current_ratio": round(cr, 3) if cr is not None else None,
            "quick_ratio": round(qr, 3) if qr is not None else None,
            "interest_coverage": round(ic, 3) if ic is not None else None,
        },
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
        (
            "yahoo_ownership",
            "Yahoo Ownership",
            getattr(settings, "alt_enable_yahoo_ownership", True),
            max(0.0, float(getattr(settings, "alt_weight_yahoo_ownership", 0.55))),
            lambda: _yahoo_ownership_summary(symbol, max(0.0, float(getattr(settings, "alt_weight_yahoo_ownership", 0.55)))),
        ),
        (
            "yahoo_short_interest",
            "Yahoo Short Interest",
            getattr(settings, "alt_enable_yahoo_short_interest", True),
            max(0.0, float(getattr(settings, "alt_weight_yahoo_short_interest", 0.65))),
            lambda: _yahoo_short_interest_summary(symbol, max(0.0, float(getattr(settings, "alt_weight_yahoo_short_interest", 0.65)))),
        ),
        (
            "yahoo_analyst_consensus",
            "Yahoo Analyst Consensus",
            getattr(settings, "alt_enable_yahoo_analyst_consensus", True),
            max(0.0, float(getattr(settings, "alt_weight_yahoo_analyst_consensus", 0.70))),
            lambda: _yahoo_analyst_summary(symbol, max(0.0, float(getattr(settings, "alt_weight_yahoo_analyst_consensus", 0.70)))),
        ),
        (
            "finnhub_analyst_trends",
            "Finnhub Analyst Trends",
            getattr(settings, "alt_enable_finnhub_analyst_trends", True),
            max(0.0, float(getattr(settings, "alt_weight_finnhub_analyst_trends", 0.75))),
            lambda: _finnhub_recommendation_summary(symbol, reference_date, lookback_days, max(0.0, float(getattr(settings, "alt_weight_finnhub_analyst_trends", 0.75)))),
        ),
        (
            "finviz_analyst_snapshot",
            "Finviz Analyst Snapshot",
            getattr(settings, "alt_enable_finviz_analyst_snapshot", True),
            max(0.0, float(getattr(settings, "alt_weight_finviz_analyst_snapshot", 0.60))),
            lambda: _finviz_snapshot_summary(symbol, max(0.0, float(getattr(settings, "alt_weight_finviz_analyst_snapshot", 0.60)))),
        ),
        (
            "sec_edgar_filings",
            "SEC EDGAR Filings",
            getattr(settings, "alt_enable_sec_edgar_filings", True),
            max(0.0, float(getattr(settings, "alt_weight_sec_edgar_filings", 0.50))),
            lambda: _sec_edgar_filings_summary(symbol, reference_date, lookback_days, max(0.0, float(getattr(settings, "alt_weight_sec_edgar_filings", 0.50)))),
        ),
        (
            "yahoo_options_flow",
            "Yahoo Options Flow",
            getattr(settings, "alt_enable_yahoo_options_flow", True),
            max(0.0, float(getattr(settings, "alt_weight_yahoo_options_flow", 0.70))),
            lambda: _yahoo_options_flow_summary(symbol, max(0.0, float(getattr(settings, "alt_weight_yahoo_options_flow", 0.70)))),
        ),
        (
            "yahoo_earnings_revision",
            "Yahoo Earnings Revision",
            getattr(settings, "alt_enable_yahoo_earnings_revision", True),
            max(0.0, float(getattr(settings, "alt_weight_yahoo_earnings_revision", 0.75))),
            lambda: _yahoo_earnings_revision_summary(symbol, max(0.0, float(getattr(settings, "alt_weight_yahoo_earnings_revision", 0.75)))),
        ),
        (
            "yahoo_credit_stress",
            "Yahoo Credit Stress",
            getattr(settings, "alt_enable_yahoo_credit_stress", True),
            max(0.0, float(getattr(settings, "alt_weight_yahoo_credit_stress", 0.60))),
            lambda: _yahoo_credit_stress_summary(symbol, max(0.0, float(getattr(settings, "alt_weight_yahoo_credit_stress", 0.60)))),
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
