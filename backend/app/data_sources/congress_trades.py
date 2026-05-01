"""
Capitol Trades & Congressional stock trade monitoring.

Sources:
  1. CapitolTrades.com  – scrapes public JSON API
  2. QuiverQuant API    – if QUIVER_QUANT_API_KEY is configured
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.config import settings

logger = logging.getLogger(__name__)

CAPITOL_TRADES_API = "https://bff.capitoltrades.com/trades"
CAPITOL_TRADES_PAGE = "https://www.capitoltrades.com/trades"
QUIVER_CONGRESS_API = "https://api.quiverquant.com/beta/live/congresstrading"
INVALID_TICKERS = {"N/A", "NA", "NONE", "NULL", "UNKNOWN", "-", ""}
CAPITOL_SCRAPE_MAX_PAGES = 8


@dataclass
class CongressTrade:
    politician: str
    party: str
    chamber: str       # Senate / House
    symbol: str
    traded_issuer: str
    transaction: str   # Purchase / Sale / Sale (Partial)
    amount_range: str  # e.g. "$1,001 - $15,000"
    trade_date: str
    disclosure_date: str
    filed_after_days: Optional[int] = None
    owner: Optional[str] = None
    price: Optional[str] = None
    description: Optional[str] = None


def _fetch_capitol_trades(symbols: list[str], days_back: int = 90) -> list[CongressTrade]:
    """Fetch recent trades from CapitolTrades public BFF API."""
    results: list[CongressTrade] = []
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    api_error = False
    try:
        with httpx.Client(timeout=15) as client:
            params = {
                "pageSize": 500,
                "page": 1,
                "sortBy": "-reportDate",
            }
            if symbols:
                params["ticker"] = ",".join(symbols)

            resp = client.get(CAPITOL_TRADES_API, params=params)
            resp.raise_for_status()
            data = resp.json()
            trades_raw = data.get("data", [])

            for t in trades_raw:
                trade_date = t.get("txDate") or t.get("reportDate", "")
                if trade_date < cutoff:
                    continue
                politician = f"{t.get('politician', {}).get('firstName', '')} {t.get('politician', {}).get('lastName', '')}".strip()
                results.append(
                    CongressTrade(
                        politician=politician,
                        party=t.get("politician", {}).get("party", ""),
                        chamber=t.get("politician", {}).get("chamber", ""),
                        symbol=t.get("asset", {}).get("assetTicker", ""),
                        traded_issuer=t.get("asset", {}).get("assetName", ""),
                        transaction=t.get("type", ""),
                        amount_range=t.get("amount", ""),
                        trade_date=trade_date,
                        disclosure_date=t.get("reportDate", ""),
                        filed_after_days=t.get("reportingGap") or t.get("daysToReport"),
                        owner=(
                            t.get("owner", {}).get("type", "")
                            if isinstance(t.get("owner"), dict)
                            else (t.get("ownerType") or t.get("owner", ""))
                        ),
                        price=str(t.get("price") or t.get("txPrice") or t.get("assetPrice") or ""),
                        description=t.get("asset", {}).get("assetName", ""),
                    )
                )
    except Exception as exc:
        api_error = True
        logger.warning("CapitolTrades fetch error: %s", exc)

    # CapitolTrades BFF endpoint frequently returns 503 from CloudFront.
    # Fallback to scraping the public trades table so the app still has data.
    if api_error or not results:
        fallback = _scrape_capitol_trades_page(symbols, days_back)
        if fallback:
            return fallback

    return results


def _parse_capitol_date(day_text: str, year_text: str) -> str:
    day_text = (day_text or "").strip()
    year_text = (year_text or "").strip()
    if not day_text:
        return ""

    today = datetime.utcnow().date()
    if day_text.lower() == "today":
        return today.strftime("%Y-%m-%d")

    if day_text.lower() == "yesterday":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        parsed = datetime.strptime(f"{day_text} {year_text}", "%d %b %Y")
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _scrape_capitol_trades_page(symbols: list[str], days_back: int = 90) -> list[CongressTrade]:
    results: list[CongressTrade] = []
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    symbol_filter = {s.upper() for s in symbols if s}

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        with httpx.Client(timeout=20, headers=headers, follow_redirects=True) as client:
            tx_window = f"{max(1, int(days_back))}d"

            for page in range(1, CAPITOL_SCRAPE_MAX_PAGES + 1):
                resp = client.get(
                    CAPITOL_TRADES_PAGE,
                    params={
                        "assetType": "stock",
                        "txDate": tx_window,
                        "page": page,
                    },
                )
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "lxml")
                rows = soup.select("table tbody tr")
                if not rows:
                    break

                page_added = 0
                for row in rows:
                    politician = ""
                    pol_tag = row.select_one("h2.politician-name a")
                    if pol_tag:
                        politician = pol_tag.get_text(strip=True)

                    party = ""
                    party_tag = row.select_one("span.party")
                    if party_tag:
                        party = party_tag.get_text(strip=True)

                    chamber = ""
                    chamber_tag = row.select_one("span.chamber")
                    if chamber_tag:
                        chamber = chamber_tag.get_text(strip=True)

                    symbol = ""
                    ticker_tag = row.select_one("span.issuer-ticker")
                    if ticker_tag:
                        ticker = ticker_tag.get_text(strip=True)
                        symbol = ticker.split(":", 1)[0].upper()

                    if symbol_filter and symbol not in symbol_filter:
                        continue

                    tx = ""
                    tx_tag = row.select_one("span.tx-type")
                    if tx_tag:
                        tx = tx_tag.get_text(strip=True).title()

                    amount = ""
                    amount_tag = row.select_one("span.trade-size .mt-1")
                    if amount_tag:
                        amount = amount_tag.get_text(strip=True)

                    filed_after_days: Optional[int] = None
                    owner = ""
                    price = ""

                    date_cells = row.select("td")
                    trade_date = ""
                    disclosure_date = ""
                    if len(date_cells) >= 4:
                        disc_day = date_cells[2].select_one("div.text-size-2")
                        disc_year = date_cells[2].select_one("div.text-size-3")
                        trade_day = date_cells[3].select_one("div.text-size-3")
                        trade_year = date_cells[3].select_one("div.text-size-2")

                        disclosure_date = _parse_capitol_date(
                            disc_day.get_text(strip=True) if disc_day else "",
                            disc_year.get_text(strip=True) if disc_year else "",
                        )
                        trade_date = _parse_capitol_date(
                            trade_day.get_text(strip=True) if trade_day else "",
                            trade_year.get_text(strip=True) if trade_year else "",
                        )

                        gap_val = date_cells[4].select_one(".q-value") if len(date_cells) > 4 else None
                        if gap_val:
                            digits = "".join(ch for ch in gap_val.get_text(strip=True) if ch.isdigit())
                            if digits:
                                filed_after_days = int(digits)

                        owner_label = date_cells[5].select_one(".q-label") if len(date_cells) > 5 else None
                        if owner_label:
                            owner = owner_label.get_text(strip=True)

                        price_tag = date_cells[8].select_one("span") if len(date_cells) > 8 else None
                        if price_tag:
                            price = price_tag.get_text(strip=True)

                    if not trade_date or trade_date < cutoff:
                        continue

                    if not disclosure_date:
                        disclosure_date = trade_date

                    issuer_name = ""
                    issuer_tag = row.select_one("h3.issuer-name a")
                    if issuer_tag:
                        issuer_name = issuer_tag.get_text(strip=True)

                    results.append(
                        CongressTrade(
                            politician=politician,
                            party=party,
                            chamber=chamber,
                            symbol=symbol,
                            traded_issuer=issuer_name,
                            transaction=tx,
                            amount_range=amount,
                            trade_date=trade_date,
                            disclosure_date=disclosure_date,
                            filed_after_days=filed_after_days,
                            owner=owner,
                            price=price,
                            description=issuer_name,
                        )
                    )
                    page_added += 1

                if page_added == 0:
                    break
    except Exception as exc:
        logger.warning("CapitolTrades page scrape error: %s", exc)

    return results


def _fetch_quiver_trades(symbols: list[str], days_back: int = 90) -> list[CongressTrade]:
    """Fetch congress trades from QuiverQuant if API key is configured."""
    if not settings.quiver_quant_api_key:
        return []
    results: list[CongressTrade] = []
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    headers = {"Authorization": f"Token {settings.quiver_quant_api_key}"}
    try:
        with httpx.Client(timeout=15) as client:
            for symbol in symbols:
                url = f"https://api.quiverquant.com/beta/historical/congresstrading/{symbol}"
                resp = client.get(url, headers=headers)
                if resp.status_code != 200:
                    continue
                for t in resp.json():
                    if t.get("Date", "") < cutoff:
                        continue
                    results.append(
                        CongressTrade(
                            politician=t.get("Representative", ""),
                            party=t.get("Party", ""),
                            chamber=t.get("Chamber", ""),
                            symbol=symbol,
                            traded_issuer=t.get("Ticker", symbol),
                            transaction=t.get("Transaction", ""),
                            amount_range=t.get("Range", ""),
                            trade_date=t.get("Date", ""),
                            disclosure_date=t.get("ReportDate", ""),
                            filed_after_days=t.get("DaysUntilReport") or t.get("ReportingGap"),
                            owner=t.get("Owner", ""),
                            price=str(t.get("Price") or ""),
                        )
                    )
    except Exception as exc:
        logger.warning("QuiverQuant fetch error: %s", exc)
    return results


def get_congress_trades(
    symbols: list[str], days_back: int = 90
) -> list[CongressTrade]:
    """Aggregate congress trade data from all enabled sources."""
    trades: list[CongressTrade] = []
    if settings.capitol_trades_enabled:
        trades.extend(_fetch_capitol_trades(symbols, days_back))
    trades.extend(_fetch_quiver_trades(symbols, days_back))

    # Deduplicate loosely by (politician, symbol, trade_date, transaction)
    seen: set[tuple] = set()
    deduped: list[CongressTrade] = []
    for t in trades:
        key = (t.politician, t.symbol, t.trade_date, t.transaction)
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    return sorted(deduped, key=lambda x: x.trade_date, reverse=True)


def filter_congress_trades(
    trades: list[CongressTrade],
    disclosed_days: int = 30,
    require_ticker: bool = True,
    reference_date: Optional[date] = None,
) -> list[CongressTrade]:
    """Filter trades by disclosure recency and ticker validity."""
    ref_date = reference_date or datetime.utcnow().date()
    cutoff = ref_date - timedelta(days=disclosed_days)

    filtered: list[CongressTrade] = []
    for t in trades:
        ticker = (t.symbol or "").strip().upper()
        if require_ticker and ticker in INVALID_TICKERS:
            continue

        try:
            disclosed_on = datetime.strptime(t.disclosure_date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue

        if disclosed_on < cutoff:
            continue
        filtered.append(t)

    return filtered


def congress_signal(symbol: str, trades: list[CongressTrade]) -> dict:
    """
    Derive a simple buy/sell signal from congressional trades for a symbol.

    Scoring:
      +2 per Purchase
      -2 per Sale / Sale (Partial)
    Returns score, net_buys, net_sells, summary string.
    """
    relevant = [t for t in trades if t.symbol.upper() == symbol.upper()]
    score = 0
    buys = 0
    sells = 0
    for t in relevant:
        tx = t.transaction.lower()
        if "purchase" in tx or "buy" in tx:
            score += 2
            buys += 1
        elif "sale" in tx or "sell" in tx:
            score -= 2
            sells += 1

    if score > 2:
        label = "BULLISH"
    elif score < -2:
        label = "BEARISH"
    else:
        label = "NEUTRAL"

    return {
        "symbol": symbol,
        "congress_score": score,
        "congress_buys": buys,
        "congress_sells": sells,
        "congress_signal": label,
        "recent_trades": [
            {
                "politician": t.politician,
                "party": t.party,
                "traded_issuer": t.traded_issuer,
                "transaction": t.transaction,
                "amount_range": t.amount_range,
                "trade_date": t.trade_date,
                "disclosure_date": t.disclosure_date,
                "filed_after_days": t.filed_after_days,
                "owner": t.owner,
                "price": t.price,
            }
            for t in relevant[:10]
        ],
    }
