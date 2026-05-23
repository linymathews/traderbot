"""
Company profile endpoint: fundamentals, supply chain, sector peers.

GET /api/company/{symbol}
"""

import asyncio
import json
import logging
import math
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import httpx
import yfinance as yf
from fastapi import APIRouter, HTTPException
from app.analysis.signals import compute_signals
from app.data_sources.alternative_data import get_alternative_signal
from app.data_sources.congress_trades import congress_signal, filter_congress_trades, get_congress_trades
from app.data_sources.market_data import get_price_history as get_market_price_history
from app.config import settings

logger = logging.getLogger(__name__)
company_router = APIRouter(prefix="/api")
_executor = ThreadPoolExecutor(max_workers=12)


# ─── FMP company enrichment ───────────────────────────────────────────────────

def _fmp_http(url: str, params: dict) -> dict | list | None:
    """Tiny helper: GET a FMP stable endpoint, return parsed JSON or None."""
    try:
        with httpx.Client(timeout=12, follow_redirects=True) as client:
            r = client.get(url, params=params)
            return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _fmp_company_data_sync(symbol: str) -> dict:
    """Fetch rich FMP data for display in the Company tab."""
    key = settings.fmp_api_key
    if not key:
        return {"available": False, "reason": "FMP_API_KEY not configured"}

    base    = {"symbol": symbol, "apikey": key}
    lim4    = {**base, "limit": 4}
    lim8    = {**base, "limit": 8}
    lim20   = {**base, "limit": 20}
    lim10   = {**base, "limit": 10}
    lim8q   = {**base, "limit": 8, "period": "quarter"}

    FMP = "https://financialmodelingprep.com/stable"

    from concurrent.futures import ThreadPoolExecutor as _T
    with _T(max_workers=12) as pool:
        f_profile   = pool.submit(_fmp_http, f"{FMP}/profile",                   base)
        f_metrics   = pool.submit(_fmp_http, f"{FMP}/key-metrics",               lim4)
        f_ratios    = pool.submit(_fmp_http, f"{FMP}/ratios",                    lim4)
        f_dcf       = pool.submit(_fmp_http, f"{FMP}/discounted-cash-flow",      base)
        f_rating    = pool.submit(_fmp_http, f"{FMP}/rating",                    base)
        f_surprises = pool.submit(_fmp_http, f"{FMP}/earnings-surprises",        lim8)
        f_insider   = pool.submit(_fmp_http, f"{FMP}/insider-trading",          lim20)
        f_grades    = pool.submit(_fmp_http, f"{FMP}/grade",                    lim10)
        f_target    = pool.submit(_fmp_http, f"{FMP}/price-target-consensus",    base)
        f_estimates = pool.submit(_fmp_http, f"{FMP}/analyst-estimates",        lim8)
        f_income    = pool.submit(_fmp_http, f"{FMP}/income-statement",         lim8q)
        f_cashflow  = pool.submit(_fmp_http, f"{FMP}/cash-flow-statement",      lim8q)

        profile_data   = f_profile.result()
        metrics_data   = f_metrics.result()
        ratios_data    = f_ratios.result()
        dcf_data       = f_dcf.result()
        rating_data    = f_rating.result()
        surprises_data = f_surprises.result()
        insider_data   = f_insider.result()
        grades_data    = f_grades.result()
        target_data    = f_target.result()
        estimates_data = f_estimates.result()
        income_data    = f_income.result()
        cashflow_data  = f_cashflow.result()

    def _first(d):
        if isinstance(d, list) and d:
            return d[0]
        return d if isinstance(d, dict) else {}

    def _lst(d):
        return d if isinstance(d, list) else []

    profile  = _first(profile_data)
    dcf      = _first(dcf_data)
    rating   = _first(rating_data)
    target   = _first(target_data)
    metrics  = _first(metrics_data)
    ratios   = _first(ratios_data)

    # ── Earnings surprises ────────────────────────────────────────────────────
    surprises: list[dict] = []
    for s in _lst(surprises_data)[:8]:
        try:
            actual    = float(s.get("actualEarningResult") or 0)
            estimated = float(s.get("estimatedEarning")    or 0)
            if abs(estimated) > 0.001:
                beat = actual > estimated
                surprise_pct = (actual - estimated) / abs(estimated) * 100
                surprises.append({
                    "date":         s.get("date"),
                    "actual":       round(actual, 4),
                    "estimated":    round(estimated, 4),
                    "surprise_pct": round(surprise_pct, 2),
                    "beat":         beat,
                })
        except Exception:
            pass

    # ── Insider trades (last 90 days) ─────────────────────────────────────────
    insiders: list[dict] = []
    cutoff_90 = (datetime.utcnow() - timedelta(days=90)).date()
    for t in _lst(insider_data)[:20]:
        raw = t.get("transactionDate") or t.get("filingDate")
        try:
            tx_date = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date() if raw else None
        except Exception:
            tx_date = None
        acq   = str(t.get("acquistionOrDisposition") or "").upper()
        ttype = str(t.get("transactionType")         or "").upper()
        is_buy  = acq == "A" or "P-PURCHASE" in ttype
        is_sell = acq == "D" or "S-SALE"     in ttype
        if not is_buy and not is_sell:
            continue
        try:
            shares = int(float(t.get("securitiesTransacted") or 0))
        except Exception:
            shares = 0
        insiders.append({
            "name":   t.get("reportingName"),
            "title":  t.get("typeOfOwner"),
            "date":   str(tx_date) if tx_date else None,
            "recent": bool(tx_date and tx_date >= cutoff_90),
            "type":   "BUY" if is_buy else "SELL",
            "shares": shares,
            "price":  t.get("price"),
            "form":   t.get("formType"),
        })

    # ── Analyst grade history ─────────────────────────────────────────────────
    grade_list: list[dict] = []
    for g in _lst(grades_data)[:10]:
        grade_list.append({
            "date":    g.get("date"),
            "company": g.get("gradingCompany"),
            "from":    g.get("previousGrade"),
            "to":      g.get("newGrade"),
            "action":  g.get("action"),
        })

    # ── Analyst estimates (forward quarters) ──────────────────────────────────
    estimate_list: list[dict] = []
    for e in sorted(_lst(estimates_data), key=lambda x: x.get("date", ""), reverse=True)[:4]:
        estimate_list.append({
            "date":            e.get("date"),
            "eps_avg":         e.get("estimatedEpsAvg"),
            "eps_high":        e.get("estimatedEpsHigh"),
            "eps_low":         e.get("estimatedEpsLow"),
            "revenue_avg":     e.get("estimatedRevenueAvg"),
            "analysts_eps":    e.get("numberAnalystsEstimatedEps"),
            "analysts_rev":    e.get("numberAnalystEstimatedRevenue"),
        })

    # ── Quarterly income trend ────────────────────────────────────────────────
    income_trend: list[dict] = []
    for row in _lst(income_data)[:8]:
        income_trend.append({
            "date":             row.get("date"),
            "period":           row.get("period"),
            "revenue":          row.get("revenue"),
            "gross_profit":     row.get("grossProfit"),
            "operating_income": row.get("operatingIncome"),
            "net_income":       row.get("netIncome"),
            "eps":              row.get("eps"),
        })

    # ── Quarterly cash flow trend ─────────────────────────────────────────────
    cashflow_trend: list[dict] = []
    for row in _lst(cashflow_data)[:8]:
        cashflow_trend.append({
            "date":          row.get("date"),
            "period":        row.get("period"),
            "operating":     row.get("operatingCashFlow"),
            "capex":         row.get("capitalExpenditure"),
            "free_cashflow": row.get("freeCashFlow"),
        })

    # ── Derived valuation ─────────────────────────────────────────────────────
    current_price = float(dcf.get("Stock Price") or profile.get("price") or 0)
    dcf_value     = float(dcf.get("dcf") or 0)
    dcf_upside    = (
        round((dcf_value - current_price) / current_price * 100, 2)
        if current_price > 0 and dcf_value > 0 else None
    )

    tc = float(target.get("targetConsensus") or 0)
    target_upside = (
        round((tc - current_price) / current_price * 100, 2)
        if current_price > 0 and tc > 0 else None
    )

    return {
        "available": bool(profile or dcf or rating),
        "profile": {
            "symbol":      profile.get("symbol") or symbol,
            "name":        profile.get("companyName") or profile.get("name"),
            "ceo":         profile.get("ceo"),
            "sector":      profile.get("sector"),
            "industry":    profile.get("industry"),
            "exchange":    profile.get("exchange") or profile.get("exchangeShortName"),
            "country":     profile.get("country"),
            "employees":   profile.get("fullTimeEmployees"),
            "website":     profile.get("website"),
            "description": profile.get("description"),
            "beta":        profile.get("beta"),
            "market_cap":  profile.get("mktCap"),
            "ipo_date":    profile.get("ipoDate"),
            "isin":        profile.get("isin"),
        },
        "valuation": {
            "dcf":              round(dcf_value, 2) if dcf_value else None,
            "price":            round(current_price, 2) if current_price else None,
            "dcf_upside_pct":   dcf_upside,
            "target_consensus": target.get("targetConsensus"),
            "target_high":      target.get("targetHigh"),
            "target_low":       target.get("targetLow"),
            "target_median":    target.get("targetMedian"),
            "target_upside_pct": target_upside,
        },
        "rating": {
            "rating":          rating.get("rating"),
            "score":           rating.get("ratingScore"),
            "recommendation":  rating.get("ratingRecommendation"),
            "dcf_score":       rating.get("ratingDetailsDCFScore"),
            "dcf_rec":         rating.get("ratingDetailsDCFRecommendation"),
            "roe_score":       rating.get("ratingDetailsROEScore"),
            "roe_rec":         rating.get("ratingDetailsROERecommendation"),
            "roa_score":       rating.get("ratingDetailsROAScore"),
            "roa_rec":         rating.get("ratingDetailsROARecommendation"),
            "de_score":        rating.get("ratingDetailsDEScore"),
            "de_rec":          rating.get("ratingDetailsDERecommendation"),
            "pe_score":        rating.get("ratingDetailsPEScore"),
            "pe_rec":          rating.get("ratingDetailsPERecommendation"),
            "pb_score":        rating.get("ratingDetailsPBScore"),
            "pb_rec":          rating.get("ratingDetailsPBRecommendation"),
        },
        "key_metrics": {
            "pe_ratio":               metrics.get("peRatio"),
            "pb_ratio":               metrics.get("pbRatio"),
            "ev_to_ebitda":           metrics.get("evToEbitda"),
            "ev_to_sales":            metrics.get("evToSales"),
            "roe":                    metrics.get("roe"),
            "roa":                    metrics.get("roa"),
            "roic":                   metrics.get("roic"),
            "debt_to_equity":         metrics.get("debtToEquity"),
            "current_ratio":          metrics.get("currentRatio"),
            "piotroski_score":        metrics.get("piotroskiScore"),
            "free_cashflow_yield":    metrics.get("freeCashFlowYield"),
            "earnings_yield":         metrics.get("earningsYield"),
            "dividend_yield":         metrics.get("dividendYield"),
            "revenue_per_share":      metrics.get("revenuePerShare"),
            "net_income_per_share":   metrics.get("netIncomePerShare"),
            "price_to_fcf":          ratios.get("priceToFreeCashFlowsRatio"),
            "gross_profit_margin":   ratios.get("grossProfitMargin"),
            "net_profit_margin":     ratios.get("netProfitMargin"),
            "operating_profit_margin": ratios.get("operatingProfitMargin"),
            "return_on_invested_capital": ratios.get("returnOnInvestedCapital") or metrics.get("roic"),
        },
        "earnings_surprises": surprises,
        "insider_trades":     insiders,
        "analyst_grades":     grade_list,
        "analyst_estimates":  estimate_list,
        "income_trend":       income_trend,
        "cashflow_trend":     cashflow_trend,
    }

# Fallback universe for sector/industry peer discovery when Yahoo does not
# return relatedTickers/recommendedSymbols.
FALLBACK_PEER_SYMBOLS: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "QCOM",
    "INTC", "MU", "TXN", "ADBE", "CRM", "ORCL", "IBM", "NFLX", "UBER", "ABNB",
    "JPM", "BAC", "WFC", "C", "GS", "MS", "V", "MA", "PYPL", "AXP",
    "XOM", "CVX", "COP", "SLB", "EOG", "PXD", "BP", "SHEL", "TTE", "ENB",
    "JNJ", "PFE", "MRK", "LLY", "ABBV", "TMO", "DHR", "ISRG", "UNH", "HUM",
    "WMT", "COST", "TGT", "HD", "LOW", "AMZN", "NKE", "SBUX", "MCD", "DIS",
    "CAT", "DE", "BA", "GE", "HON", "LMT", "RTX", "NOC", "ETN", "PH",
    "T", "VZ", "TMUS", "CMCSA", "CHTR", "SPOT", "SNAP", "PINS", "ROKU", "PARA",
    "KO", "PEP", "PG", "CL", "KMB", "MDLZ", "GIS", "KHC", "SYY", "EL",
)

# ─── Supply-chain knowledge base ─────────────────────────────────────────────
# SUPPLY_CHAIN[symbol] = {
#   "suppliers": [{"symbol": ..., "role": ...}, ...],
#   "customers": [{"symbol": ..., "role": ...}, ...],
# }

SUPPLY_CHAIN: dict[str, dict] = {
    "AAPL": {
        "suppliers": [
            {"symbol": "TSM",  "role": "Primary chip fabricator — A-series, M-series, T-series SoCs"},
            {"symbol": "QCOM", "role": "5G modem chips for iPhone and iPad"},
            {"symbol": "AVGO", "role": "Wi-Fi, Bluetooth, and cellular connectivity chips"},
            {"symbol": "TXN",  "role": "Touch controllers and mixed-signal ICs"},
            {"symbol": "SWKS", "role": "RF front-end modules for cellular radios"},
            {"symbol": "QRVO", "role": "RF filters and power amplifiers"},
            {"symbol": "CRUS", "role": "Audio DSP chips for iPhone and AirPods"},
            {"symbol": "MU",   "role": "LPDDR5 RAM and NAND flash storage for devices"},
            {"symbol": "AMAT", "role": "Semiconductor fab equipment (indirect via TSMC)"},
            {"symbol": "LRCX", "role": "Etch/deposition equipment (indirect via TSMC)"},
        ],
        "customers": [
            {"symbol": "T",    "role": "AT&T — iPhone carrier distribution and subsidies"},
            {"symbol": "VZ",   "role": "Verizon — iPhone carrier distribution"},
            {"symbol": "TMUS", "role": "T-Mobile — iPhone carrier distribution"},
            {"symbol": "AMZN", "role": "Amazon — resells Apple devices; competes with services"},
            {"symbol": "WMT",  "role": "Walmart — retail channel for Apple products"},
        ],
    },
    "MSFT": {
        "suppliers": [
            {"symbol": "NVDA", "role": "H100/B200 GPUs for Azure AI supercomputers"},
            {"symbol": "AMD",  "role": "EPYC server CPUs and Instinct GPUs for Azure"},
            {"symbol": "INTC", "role": "Xeon server CPUs for Azure data centers"},
            {"symbol": "TSM",  "role": "Custom Azure Maia AI chip and Cobalt CPU fabrication"},
            {"symbol": "AVGO", "role": "Networking ASICs for Azure backbone"},
            {"symbol": "SNPS", "role": "EDA tools for custom silicon design"},
            {"symbol": "CDNS", "role": "Cadence EDA tools for chip verification"},
            {"symbol": "DELL", "role": "Server hardware for enterprise channel sales"},
            {"symbol": "HPE",  "role": "ProLiant servers for data centers"},
        ],
        "customers": [
            {"symbol": "ORCL", "role": "Oracle products on Azure; Oracle 365 integration"},
            {"symbol": "SAP",  "role": "SAP workloads run on Azure (SAP on Azure deep partnership)"},
            {"symbol": "ADBE", "role": "Adobe integrates with Microsoft 365; Azure customer"},
            {"symbol": "CRM",  "role": "Salesforce Einstein AI partnership with Azure OpenAI"},
            {"symbol": "AMZN", "role": "Enterprise customers use both AWS and Azure"},
        ],
    },
    "NVDA": {
        "suppliers": [
            {"symbol": "TSM",  "role": "Sole fabricator for H100, B200, RTX, A100 at 4nm/3nm"},
            {"symbol": "AMAT", "role": "CVD, ALD, ion implant equipment at TSMC fabs"},
            {"symbol": "LRCX", "role": "Plasma etch and CVD deposition equipment"},
            {"symbol": "KLAC", "role": "Process control, metrology, and inspection systems"},
            {"symbol": "ASML", "role": "EUV lithography systems for 5nm and 3nm nodes"},
            {"symbol": "SNPS", "role": "Synopsys EDA tools for GPU and accelerator design"},
            {"symbol": "CDNS", "role": "Cadence EDA tools for timing closure and signoff"},
            {"symbol": "MU",   "role": "HBM3/HBM3e memory stacks on H100/H200 GPUs"},
        ],
        "customers": [
            {"symbol": "MSFT", "role": "Azure AI infrastructure — largest H100 cluster (~$15B+)"},
            {"symbol": "GOOGL","role": "Google Cloud AI training and inference (H100/B200)"},
            {"symbol": "AMZN", "role": "AWS AI compute clusters (P5 instances with H100)"},
            {"symbol": "META", "role": "~600,000 H100 GPUs for Llama AI training"},
            {"symbol": "ORCL", "role": "Oracle Cloud 131,000+ H100 cluster"},
            {"symbol": "TSLA", "role": "Dojo v1 supercomputer and FSD training workloads"},
            {"symbol": "NFLX", "role": "GPU clusters for content recommendation AI models"},
        ],
    },
    "AMZN": {
        "suppliers": [
            {"symbol": "NVDA", "role": "H100 GPUs for AWS P5 instances and AI training"},
            {"symbol": "INTC", "role": "Xeon CPUs for legacy AWS EC2 instances"},
            {"symbol": "TSM",  "role": "Fabricates AWS Graviton, Trainium, Inferentia chips"},
            {"symbol": "AVGO", "role": "Custom networking ASICs for AWS backbone"},
            {"symbol": "UPS",  "role": "Package delivery for Amazon fulfillment network"},
            {"symbol": "FDX",  "role": "FedEx last-mile delivery for Amazon orders"},
        ],
        "customers": [
            {"symbol": "NFLX", "role": "Netflix — one of the largest AWS customers by spend"},
            {"symbol": "AAPL", "role": "Apple iCloud uses AWS infrastructure"},
            {"symbol": "SNAP", "role": "Snapchat — major AWS cloud customer"},
            {"symbol": "UBER", "role": "Uber — heavy AWS user for maps and ride matching"},
            {"symbol": "ABNB", "role": "Airbnb — runs on AWS infrastructure"},
        ],
    },
    "GOOGL": {
        "suppliers": [
            {"symbol": "NVDA", "role": "H100/B200 GPUs along with TPUs for Google Cloud AI"},
            {"symbol": "TSM",  "role": "Fabricates Google TPU v4/v5 custom AI chips"},
            {"symbol": "ASML", "role": "EUV equipment at TSMC for Google custom silicon"},
            {"symbol": "INTC", "role": "Server CPUs for non-TPU Google workloads"},
            {"symbol": "CDNS", "role": "Cadence EDA tools for TPU chip design"},
            {"symbol": "SNPS", "role": "Synopsys tools for chip design verification"},
        ],
        "customers": [
            {"symbol": "AAPL", "role": "Apple pays Google ~$18–20B/yr for default search on Safari"},
            {"symbol": "META", "role": "Meta advertises on Google Search and YouTube"},
            {"symbol": "AMZN", "role": "Amazon is one of the largest Google Search advertisers"},
            {"symbol": "WMT",  "role": "Walmart Google Cloud customer and Google Shopping partner"},
            {"symbol": "NFLX", "role": "Netflix uses Google Cloud CDN and infrastructure"},
        ],
    },
    "META": {
        "suppliers": [
            {"symbol": "NVDA", "role": "~600,000 H100 GPUs deployed for Llama and AI research"},
            {"symbol": "AVGO", "role": "Co-developed MTIA custom AI inference chip"},
            {"symbol": "TSM",  "role": "Fabricates Meta's MTIA custom AI silicon"},
            {"symbol": "QCOM", "role": "Snapdragon XR chips for Quest VR/AR headsets"},
            {"symbol": "AMZN", "role": "AWS for edge computing (minor; Meta runs own DCs)"},
        ],
        "customers": [
            {"symbol": "T",    "role": "AT&T — large advertiser on Facebook and Instagram"},
            {"symbol": "AMZN", "role": "Amazon — single largest advertiser on Meta platforms"},
            {"symbol": "GOOGL","role": "Google competes/partners; iOS privacy impacts both"},
            {"symbol": "AAPL", "role": "App Store dependency; Apple ATT impacts ad revenue"},
        ],
    },
    "TSLA": {
        "suppliers": [
            {"symbol": "ON",   "role": "Power MOSFETs and SiC inverter modules"},
            {"symbol": "STM",  "role": "ST Micro SiC MOSFETs for drivetrain inverters"},
            {"symbol": "MU",   "role": "DRAM and NAND for infotainment and FSD systems"},
            {"symbol": "QCOM", "role": "Snapdragon chips for infotainment (legacy models)"},
            {"symbol": "NVDA", "role": "H100 GPUs for Dojo supercomputer (v1 build)"},
            {"symbol": "ALB",  "role": "Albemarle — lithium supply for battery cathodes"},
            {"symbol": "TSM",  "role": "Fabricates Tesla's custom FSD chip at 7nm"},
        ],
        "customers": [
            {"symbol": "NEE",  "role": "NextEra Energy — utility-scale Megapack storage"},
            {"symbol": "DUK",  "role": "Duke Energy — utility Megapack projects"},
            {"symbol": "TMUS", "role": "T-Mobile — Tesla fleet management and Starlink deals"},
        ],
    },
    "INTC": {
        "suppliers": [
            {"symbol": "ASML", "role": "EUV lithography for Intel 18A and future process nodes"},
            {"symbol": "AMAT", "role": "CVD, ALD, implant equipment for Intel Foundry"},
            {"symbol": "LRCX", "role": "Etch equipment for Intel Foundry advanced nodes"},
            {"symbol": "KLAC", "role": "Metrology equipment for Intel process control"},
            {"symbol": "SNPS", "role": "EDA tools for Core, Xeon, and Arc chip design"},
            {"symbol": "CDNS", "role": "Cadence tools for design verification"},
        ],
        "customers": [
            {"symbol": "MSFT", "role": "Azure Xeon CPU data center platform"},
            {"symbol": "AMZN", "role": "AWS EC2 Intel-based instances"},
            {"symbol": "DELL", "role": "PowerEdge servers with Intel Xeon processors"},
            {"symbol": "HPE",  "role": "ProLiant servers powered by Intel Xeon"},
            {"symbol": "LENOVO","role": "Lenovo Think servers and PCs (largest Intel OEM)"},
        ],
    },
    "AMD": {
        "suppliers": [
            {"symbol": "TSM",  "role": "Sole fab partner — all Zen CPUs and CDNA/RDNA GPUs"},
            {"symbol": "SNPS", "role": "Synopsys EDA tools for Zen and RDNA chip design"},
            {"symbol": "CDNS", "role": "Cadence EDA for timing and physical verification"},
            {"symbol": "AMAT", "role": "Process equipment at TSMC (indirect dependency)"},
            {"symbol": "ASML", "role": "EUV lithography at TSMC (indirect dependency)"},
        ],
        "customers": [
            {"symbol": "MSFT", "role": "Xbox Series X APU + Azure EPYC CPU instances"},
            {"symbol": "AMZN", "role": "AWS Graviton and AMD EPYC EC2 instances"},
            {"symbol": "GOOGL","role": "Google Cloud N2D instances use AMD EPYC"},
            {"symbol": "SONY", "role": "PlayStation 5 — custom AMD Zen2 + RDNA2 APU"},
            {"symbol": "MSFT", "role": "Azure Instinct GPU for AI (CDNA competition with NVDA)"},
        ],
    },
    "TSM": {
        "suppliers": [
            {"symbol": "ASML", "role": "EUV/DUV lithography — sole EUV supplier, ~35% of TSMC capex"},
            {"symbol": "AMAT", "role": "CVD, ALD, PVD, implant equipment for all process nodes"},
            {"symbol": "LRCX", "role": "Plasma etch and CVD deposition systems"},
            {"symbol": "KLAC", "role": "Process control, inspection, and metrology"},
            {"symbol": "ADI",  "role": "Analog semiconductor content for fab control systems"},
        ],
        "customers": [
            {"symbol": "AAPL", "role": "Largest customer ~25% revenue — A-series, M-series SoCs"},
            {"symbol": "NVDA", "role": "~11% revenue — H100, B200, RTX, Jetson chips"},
            {"symbol": "AMD",  "role": "Zen CPUs and RDNA/CDNA GPUs at advanced nodes"},
            {"symbol": "QCOM", "role": "Snapdragon SoCs for smartphones and IoT"},
            {"symbol": "INTC", "role": "Intel outsources 18A and some Tile chiplets to TSMC"},
            {"symbol": "GOOGL","role": "TPU v4/v5 custom AI accelerator fabrication"},
            {"symbol": "AVGO", "role": "Custom ASICs for hyperscalers (Google, Meta, Apple)"},
        ],
    },
    "QCOM": {
        "suppliers": [
            {"symbol": "TSM",  "role": "Primary fab for Snapdragon and IoT chips at 4nm/3nm"},
            {"symbol": "SNPS", "role": "Synopsys EDA for Snapdragon design"},
            {"symbol": "CDNS", "role": "Cadence EDA tools for chip verification"},
            {"symbol": "AMAT", "role": "Process equipment through TSMC (indirect)"},
        ],
        "customers": [
            {"symbol": "AAPL", "role": "5G modem chips for iPhone 12–16 series"},
            {"symbol": "MSFT", "role": "Snapdragon X Elite for Copilot+ Windows PCs"},
            {"symbol": "META", "role": "Snapdragon XR chips for Quest 3 headsets"},
            {"symbol": "GOOGL","role": "Snapdragon modems for Pixel phones"},
            {"symbol": "SSNLF","role": "Samsung Galaxy flagship smartphones"},
        ],
    },
    "AVGO": {
        "suppliers": [
            {"symbol": "TSM",  "role": "Primary fab for custom ASICs, RF chips, and networking"},
            {"symbol": "AMAT", "role": "Process equipment through TSMC (indirect)"},
            {"symbol": "SNPS", "role": "EDA tools for custom ASIC design and verification"},
        ],
        "customers": [
            {"symbol": "AAPL", "role": "Wi-Fi 6E/7 and Bluetooth chips for iPhone, iPad, Mac"},
            {"symbol": "GOOGL","role": "Custom TPU networking ASICs (co-developed partnership)"},
            {"symbol": "META", "role": "Custom MTIA AI inference chip co-development"},
            {"symbol": "MSFT", "role": "Azure custom silicon and network ASICs"},
            {"symbol": "AMZN", "role": "AWS custom Trainium/Inferentia ASIC collaboration"},
        ],
    },
    "AMAT": {
        "suppliers": [
            {"symbol": "EMR",  "role": "Emerson — industrial automation and process control"},
            {"symbol": "ITW",  "role": "Illinois Tool Works — precision components"},
        ],
        "customers": [
            {"symbol": "TSM",  "role": "TSMC — consistently >15% of AMAT revenue"},
            {"symbol": "INTC", "role": "Intel Foundry CVD, ALD, and implant tools"},
            {"symbol": "MU",   "role": "Micron DRAM and 3D NAND fabs"},
            {"symbol": "LRCX", "role": "Lam Research — competitor in some segments; complementary"},
            {"symbol": "WDC",  "role": "Western Digital 3D NAND fabs"},
        ],
    },
    "LRCX": {
        "suppliers": [
            {"symbol": "EMR",  "role": "Industrial automation components"},
            {"symbol": "AMAT", "role": "Some complementary tool collaboration"},
        ],
        "customers": [
            {"symbol": "TSM",  "role": "TSMC — etch tools across all advanced nodes"},
            {"symbol": "INTC", "role": "Intel Foundry etch systems"},
            {"symbol": "MU",   "role": "Micron DRAM/NAND etch processes"},
            {"symbol": "WDC",  "role": "Western Digital 3D NAND etch tools"},
            {"symbol": "KLAC", "role": "KLAC uses Lam equipment in process development"},
        ],
    },
    "KLAC": {
        "suppliers": [
            {"symbol": "AMAT", "role": "Some complementary process equipment"},
        ],
        "customers": [
            {"symbol": "TSM",  "role": "TSMC process control and defect inspection"},
            {"symbol": "INTC", "role": "Intel Foundry metrology systems"},
            {"symbol": "MU",   "role": "Micron memory yield management"},
            {"symbol": "ASML", "role": "KLA overlay metrology for ASML litho feedback"},
        ],
    },
    "ASML": {
        "suppliers": [
            {"symbol": "ZEISS","role": "Carl Zeiss — precision optics and mirrors for EUV (sole supplier)"},
            {"symbol": "CYMB", "role": "Cymer (ASML subsidiary) — DUV laser light sources"},
        ],
        "customers": [
            {"symbol": "TSM",  "role": "TSMC — ~35% of ASML revenue; all EUV machines"},
            {"symbol": "INTC", "role": "Intel Foundry — major EUV buyer for 18A node"},
            {"symbol": "MU",   "role": "Micron — DUV lithography for DRAM"},
            {"symbol": "LRCX", "role": "Indirect: downstream fabs use both ASML+LRCX"},
        ],
    },
    "MU": {
        "suppliers": [
            {"symbol": "AMAT", "role": "CVD, ALD, PVD equipment for DRAM and 3D NAND"},
            {"symbol": "LRCX", "role": "Etch and deposition equipment for memory fabs"},
            {"symbol": "KLAC", "role": "Process control and yield management"},
            {"symbol": "ASML", "role": "DUV lithography for DRAM cell patterning"},
            {"symbol": "SNPS", "role": "EDA tools for memory controller design"},
        ],
        "customers": [
            {"symbol": "AAPL", "role": "iPhone LPDDR5X RAM and NAND storage modules"},
            {"symbol": "NVDA", "role": "HBM3/HBM3e memory stacks on H100/H200/B200 dies"},
            {"symbol": "INTC", "role": "Server DDR5 DIMM memory for Intel platforms"},
            {"symbol": "AMZN", "role": "AWS server DRAM modules"},
            {"symbol": "MSFT", "role": "Azure server memory infrastructure"},
        ],
    },
    "SNPS": {
        "suppliers": [
            {"symbol": "MSFT", "role": "Azure cloud for SaaS offerings and internal tools"},
            {"symbol": "AMZN", "role": "AWS cloud infrastructure"},
        ],
        "customers": [
            {"symbol": "NVDA", "role": "EDA tools for H100/B200 GPU design and signoff"},
            {"symbol": "AMD",  "role": "Zen CPU and RDNA/CDNA GPU design verification"},
            {"symbol": "QCOM", "role": "Snapdragon SoC design and timing closure"},
            {"symbol": "TSM",  "role": "TSMC process design kits and design enablement"},
            {"symbol": "INTC", "role": "Intel CPU/GPU design EDA flows"},
            {"symbol": "AVGO", "role": "Custom ASIC design verification"},
        ],
    },
    "CDNS": {
        "suppliers": [
            {"symbol": "MSFT", "role": "Azure cloud for Cadence Clarity cloud simulation"},
            {"symbol": "AMZN", "role": "AWS cloud simulation workloads"},
        ],
        "customers": [
            {"symbol": "NVDA", "role": "GPU/accelerator physical design and verification"},
            {"symbol": "AMD",  "role": "CPU/GPU chip timing, place-and-route"},
            {"symbol": "TSM",  "role": "TSMC process libraries and design kits"},
            {"symbol": "QCOM", "role": "Snapdragon SoC signoff"},
            {"symbol": "AVGO", "role": "Networking and custom ASIC design"},
        ],
    },
    "JPM": {
        "suppliers": [
            {"symbol": "MSFT", "role": "Azure cloud and Microsoft 365 platform"},
            {"symbol": "ORCL", "role": "Oracle Financials and database infrastructure"},
            {"symbol": "IBM",  "role": "IBM mainframes for core banking transaction processing"},
            {"symbol": "FIS",  "role": "Core banking software and payment processing"},
            {"symbol": "FISV", "role": "Fiserv payment network and merchant services"},
        ],
        "customers": [
            {"symbol": "V",    "role": "Visa — JPMorgan is a leading Visa card issuer"},
            {"symbol": "MA",   "role": "Mastercard — JPMorgan issues Mastercard products"},
            {"symbol": "GS",   "role": "Goldman Sachs — interbank lending and clearing"},
            {"symbol": "BAC",  "role": "Bank of America — correspondent banking"},
        ],
    },
    "V": {
        "suppliers": [
            {"symbol": "MSFT", "role": "Azure cloud for Visa Direct and cybersecurity services"},
            {"symbol": "AMZN", "role": "AWS for some Visa token and analytics services"},
            {"symbol": "VRSN", "role": "Verisign — DNS infrastructure and internet security"},
        ],
        "customers": [
            {"symbol": "JPM",  "role": "JPMorgan Chase — leading Visa card issuer"},
            {"symbol": "BAC",  "role": "Bank of America — major Visa issuer"},
            {"symbol": "WFC",  "role": "Wells Fargo — Visa card portfolio"},
            {"symbol": "WMT",  "role": "Walmart — largest merchant by transaction volume"},
            {"symbol": "AMZN", "role": "Amazon — major e-commerce merchant accepting Visa"},
            {"symbol": "TGT",  "role": "Target — major retailer; Visa acceptance"},
        ],
    },
    "MA": {
        "suppliers": [
            {"symbol": "MSFT", "role": "Azure cloud for Mastercard analytics platform"},
            {"symbol": "AMZN", "role": "AWS for cloud workloads"},
        ],
        "customers": [
            {"symbol": "JPM",  "role": "JPMorgan — World Elite Mastercard issuer"},
            {"symbol": "C",    "role": "Citigroup — major Mastercard issuer globally"},
            {"symbol": "WMT",  "role": "Walmart — large merchant acceptance"},
            {"symbol": "AMZN", "role": "Amazon — e-commerce acceptance"},
            {"symbol": "GOOGL","role": "Google Pay integration with Mastercard network"},
        ],
    },
    "WMT": {
        "suppliers": [
            {"symbol": "PG",   "role": "Procter & Gamble — single largest CPG supplier (~5% of WMT buys)"},
            {"symbol": "KO",   "role": "Coca-Cola — beverages; Walmart is KO's largest retailer"},
            {"symbol": "PEP",  "role": "PepsiCo — beverages and Frito-Lay snacks"},
            {"symbol": "UL",   "role": "Unilever — household, personal care, and food brands"},
            {"symbol": "MSFT", "role": "Microsoft — Azure cloud (Walmart's primary cloud partner)"},
            {"symbol": "ORCL", "role": "Oracle supply chain and inventory management"},
        ],
        "customers": [
            {"symbol": "V",    "role": "Visa — payment acceptance at all Walmart stores"},
            {"symbol": "MA",   "role": "Mastercard — payment acceptance"},
            {"symbol": "AMZN", "role": "Amazon Fresh competes with Walmart Grocery"},
        ],
    },
    "NFLX": {
        "suppliers": [
            {"symbol": "AMZN", "role": "AWS — Netflix's primary and almost exclusive cloud provider"},
            {"symbol": "MSFT", "role": "Azure supplementary; Xbox Game Pass competitor"},
            {"symbol": "NVDA", "role": "GPU clusters for ML-based content recommendation"},
            {"symbol": "GOOGL","role": "Google CDN for content delivery in some regions"},
        ],
        "customers": [
            {"symbol": "AAPL", "role": "Apple TV app — Netflix on Apple devices"},
            {"symbol": "AMZN", "role": "Fire TV — Netflix integrated on Alexa ecosystem"},
            {"symbol": "GOOGL","role": "Google TV / Android TV — Netflix app preinstalled"},
            {"symbol": "SONY", "role": "PlayStation 5 — Netflix dedicated app experience"},
        ],
    },
    "ORCL": {
        "suppliers": [
            {"symbol": "NVDA", "role": "131,000+ H100 GPUs powering Oracle Cloud AI cluster"},
            {"symbol": "AMD",  "role": "EPYC processors for Oracle Cloud compute"},
            {"symbol": "INTC", "role": "Xeon CPUs for Oracle legacy database appliances"},
            {"symbol": "AMZN", "role": "AWS partnership for Oracle Database@AWS"},
        ],
        "customers": [
            {"symbol": "MSFT", "role": "Microsoft and Oracle co-sell Azure + OCI interconnect"},
            {"symbol": "AMZN", "role": "Oracle Database runs on AWS (Oracle Database@AWS)"},
            {"symbol": "JPM",  "role": "JPMorgan — Oracle Financials for banking systems"},
            {"symbol": "WMT",  "role": "Walmart uses Oracle supply chain management"},
        ],
    },
    "CRM": {
        "suppliers": [
            {"symbol": "AMZN", "role": "AWS — Salesforce's primary cloud infrastructure"},
            {"symbol": "GOOGL","role": "Google Cloud — Salesforce partnership and workloads"},
            {"symbol": "MSFT", "role": "Azure AI (OpenAI) integration with Salesforce Einstein"},
            {"symbol": "MDB",  "role": "MongoDB used in Salesforce Data Cloud"},
        ],
        "customers": [
            {"symbol": "WMT",  "role": "Walmart uses Salesforce for retail cloud CRM"},
            {"symbol": "AMZN", "role": "Amazon uses Salesforce externally for seller CRM"},
            {"symbol": "T",    "role": "AT&T — major Salesforce enterprise customer"},
        ],
    },
    "ADBE": {
        "suppliers": [
            {"symbol": "AMZN", "role": "AWS — Adobe Experience Cloud primary infrastructure"},
            {"symbol": "MSFT", "role": "Azure — Adobe Firefly and Teams integrations"},
            {"symbol": "NVDA", "role": "GPUs for Adobe Firefly generative AI models"},
        ],
        "customers": [
            {"symbol": "WMT",  "role": "Walmart uses Adobe Experience Manager for digital commerce"},
            {"symbol": "AMZN", "role": "Amazon seller tools integrate with Adobe Commerce"},
            {"symbol": "NFLX", "role": "Netflix uses Adobe analytics and marketing cloud"},
        ],
    },
    "GS": {
        "suppliers": [
            {"symbol": "MSFT", "role": "Microsoft 365 and Azure for GS internal systems"},
            {"symbol": "IBM",  "role": "IBM mainframes for core trading and settlement"},
            {"symbol": "ORCL", "role": "Oracle database for trading systems"},
            {"symbol": "MSCI", "role": "MSCI risk analytics, factor models, and ESG data"},
        ],
        "customers": [
            {"symbol": "JPM",  "role": "JPMorgan — prime brokerage and interbank clearing"},
            {"symbol": "BAC",  "role": "Bank of America — repo and derivatives counterparty"},
            {"symbol": "C",    "role": "Citigroup — interbank FX and derivatives"},
        ],
    },
}


def _safe(v, default=None):
    """Return v if it is a real number, else default."""
    if v is None:
        return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_str(v, default=None):
    """Return v as string if non-empty, else default."""
    if v is None or (isinstance(v, float) and (v != v)):
        return default
    s = str(v).strip()
    return s if s and s.lower() not in ('nan', 'none', '') else default


def _fetch_ticker_sync(symbol: str):
    """Blocking call — run in executor.

    This function must never raise: upstream routes call it inside
    asyncio.gather(), where a single exception can fail the whole request.
    """
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        if isinstance(info, dict) and info:
            return info
    except Exception as exc:
        logger.warning("Ticker info fetch failed for %s: %s", symbol, exc)

    # Fallback to fast_info when full info is rate-limited/unavailable.
    try:
        t = yf.Ticker(symbol)
        fi = t.fast_info
        return {
            "symbol": symbol,
            "shortName": symbol,
            "longName": symbol,
            "currentPrice": _safe(getattr(fi, "last_price", None)),
            "regularMarketPrice": _safe(getattr(fi, "last_price", None)),
            "previousClose": _safe(getattr(fi, "previous_close", None)),
            "regularMarketPreviousClose": _safe(getattr(fi, "previous_close", None)),
            "open": _safe(getattr(fi, "open", None)),
            "dayHigh": _safe(getattr(fi, "day_high", None)),
            "dayLow": _safe(getattr(fi, "day_low", None)),
            "volume": _safe(getattr(fi, "last_volume", None)),
            "averageVolume": _safe(getattr(fi, "ten_day_average_volume", None)),
            "marketCap": _safe(getattr(fi, "market_cap", None)),
            "exchange": _safe_str(getattr(fi, "exchange", None)),
            "currency": _safe_str(getattr(fi, "currency", None), default="USD"),
            "quoteType": "EQUITY",
        }
    except Exception as exc:
        logger.warning("Ticker fast_info fallback failed for %s: %s", symbol, exc)
        return {
            "symbol": symbol,
            "shortName": symbol,
            "longName": symbol,
            "currency": "USD",
            "quoteType": "EQUITY",
        }


def _fetch_news_and_research_sync(symbol: str, max_news: int = 20, max_research: int = 12) -> dict:
    """Fetch and categorize company-related news and analyst research links."""
    try:
        raw_items = yf.Ticker(symbol).news or []
    except Exception as exc:
        logger.warning("News fetch failed for %s: %s", symbol, exc)
        return {
            "related_news": [],
            "analyst_research": [],
            "updated_at": datetime.utcnow().isoformat(),
            "reason": str(exc),
        }

    def _content_of(item: dict) -> dict:
        if not isinstance(item, dict):
            return {}
        return item.get("content") if isinstance(item.get("content"), dict) else item

    def _pick(item: dict, *keys):
        for k in keys:
            v = item.get(k)
            if v is not None:
                return v
        return None

    def _news_row(item: dict) -> dict | None:
        c = _content_of(item)
        title = _safe_str(_pick(c, "title", "headline"))
        link = _safe_str(_pick(c, "link", "url"))
        if not link:
            canon = c.get("canonicalUrl")
            if isinstance(canon, dict):
                link = _safe_str(canon.get("url"))
        if not title or not link:
            return None
        provider = _safe_str(_pick(c, "provider", "publisher"), default="Source")
        pub_ts = _pick(c, "pubDate", "providerPublishTime", "publishTime", "published_at")
        related = c.get("relatedTickers") if isinstance(c.get("relatedTickers"), list) else []
        related = [str(x).upper() for x in related if x]
        return {
            "title": title,
            "link": link,
            "publisher": provider,
            "published_at": _safe_str(pub_ts),
            "related_tickers": related,
        }

    impact_keywords = (
        "earnings", "guidance", "forecast", "outlook", "acquisition", "merger", "lawsuit",
        "investigation", "fda", "approval", "downgrade", "upgrade", "target", "buyback",
        "dividend", "ceo", "cfo", "layoff", "restructuring", "sec", "antitrust",
    )
    analyst_keywords = (
        "analyst", "price target", "initiates", "coverage", "downgrade", "upgrade", "overweight",
        "underweight", "outperform", "underperform", "research note", "rating",
    )

    all_rows: list[dict] = []
    seen_links: set[str] = set()
    for raw in raw_items:
        row = _news_row(raw)
        if not row:
            continue
        key = row["link"].strip()
        if key in seen_links:
            continue
        seen_links.add(key)
        all_rows.append(row)

    related_news: list[dict] = []
    analyst_research: list[dict] = []
    sym_upper = symbol.upper()
    for row in all_rows:
        title_l = row["title"].lower()
        has_symbol_context = sym_upper in row.get("related_tickers", []) or sym_upper in row["title"].upper()
        if has_symbol_context or any(k in title_l for k in impact_keywords):
            related_news.append(row)
        if any(k in title_l for k in analyst_keywords):
            analyst_research.append(row)

    # Add broker research actions from Yahoo analyst-grade history.
    # These are legally accessible summary actions (upgrade/downgrade/maintain),
    # and we link to public analysis pages for further context.
    try:
        actions = yf.Ticker(symbol).get_upgrades_downgrades()
        if actions is not None and not actions.empty:
            base_analysis_url = f"https://finance.yahoo.com/quote/{symbol}/analysis"
            for idx, row in actions.sort_index(ascending=False).head(25).iterrows():
                firm = _safe_str(row.get("Firm"), default="Broker")
                to_grade = _safe_str(row.get("ToGrade"), default="N/A")
                from_grade = _safe_str(row.get("FromGrade"), default="N/A")
                action = _safe_str(row.get("Action"), default="Update")

                dt_str = None
                try:
                    dt_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else _safe_str(idx)
                except Exception:
                    dt_str = _safe_str(idx)

                title = f"{firm}: {action} {from_grade} → {to_grade}" if from_grade != "N/A" else f"{firm}: {action} to {to_grade}"
                analyst_research.append(
                    {
                        "title": title,
                        "link": base_analysis_url,
                        "publisher": firm,
                        "published_at": dt_str,
                        "related_tickers": [symbol.upper()],
                    }
                )
    except Exception as exc:
        logger.warning("Analyst action fetch failed for %s: %s", symbol, exc)

    # De-duplicate analyst research by (title, date) while preserving order.
    dedup_research = []
    seen_research = set()
    for item in analyst_research:
        key = f"{item.get('title','')}|{item.get('published_at','')}"
        if key in seen_research:
            continue
        seen_research.add(key)
        dedup_research.append(item)

    return {
        "related_news": related_news[:max_news],
        "analyst_research": dedup_research[:max_research],
        "updated_at": datetime.utcnow().isoformat(),
    }


def _parse_news_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            ts = float(value)
            if ts > 1e12:
                ts = ts / 1000.0
            return datetime.utcfromtimestamp(ts)
        except Exception:
            return None

    s = _safe_str(value)
    if not s:
        return None

    # Numeric-as-string Unix timestamp support.
    if s.isdigit():
        try:
            ts = float(s)
            if ts > 1e12:
                ts = ts / 1000.0
            return datetime.utcfromtimestamp(ts)
        except Exception:
            pass

    # ISO / RFC-ish strings.
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except Exception:
            continue

    return None


def _compute_news_research_factor(news_bundle: dict | None) -> dict:
    if not news_bundle:
        return {
            "signal": "HOLD",
            "score": 0.0,
            "contribution": 0.0,
            "weight": "10%",
            "bullish_mentions": 0,
            "bearish_mentions": 0,
            "scored_items": 0,
            "considered_items": 0,
        }

    bullish_words = {
        "upgrade", "upgraded", "outperform", "overweight", "buy", "strong buy",
        "beat", "beats", "surge", "rally", "bullish", "raised", "raise", "reiterated buy",
        "price target raised", "initiated buy", "accumulate",
    }
    bearish_words = {
        "downgrade", "downgraded", "underperform", "underweight", "sell", "strong sell",
        "miss", "misses", "drop", "plunge", "bearish", "cut", "lowered", "slashed",
        "price target cut", "initiated sell", "lawsuit", "probe", "investigation",
    }

    def _sentiment_score(title: str) -> tuple[float, int, int]:
        t = (title or "").lower()
        bull_hits = sum(1 for w in bullish_words if w in t)
        bear_hits = sum(1 for w in bearish_words if w in t)
        if bull_hits == 0 and bear_hits == 0:
            return 0.0, 0, 0
        # Net sentiment in [-1, 1], damped to avoid one headline dominating.
        raw = (bull_hits - bear_hits) / max(1, bull_hits + bear_hits)
        return _clamp(raw, -1.0, 1.0), bull_hits, bear_hits

    now = datetime.utcnow()
    related_news = news_bundle.get("related_news") or []
    analyst_research = news_bundle.get("analyst_research") or []

    weighted_sum = 0.0
    weight_total = 0.0
    bullish_mentions = 0
    bearish_mentions = 0
    scored_items = 0

    def _consume(items: list[dict], source_weight: float):
        nonlocal weighted_sum, weight_total, bullish_mentions, bearish_mentions, scored_items
        for item in items:
            title = _safe_str(item.get("title"), default="")
            score, bull_hits, bear_hits = _sentiment_score(title)
            bullish_mentions += bull_hits
            bearish_mentions += bear_hits
            if score == 0.0:
                continue

            published = _parse_news_ts(item.get("published_at"))
            if published:
                age_days = max(0.0, (now - published).total_seconds() / 86400.0)
            else:
                age_days = 10.0

            # Recency decay: 0d~1.0, 7d~0.5, 21d~0.25.
            recency_weight = 1.0 / (1.0 + (age_days / 7.0))
            w = source_weight * recency_weight
            weighted_sum += score * w
            weight_total += w
            scored_items += 1

    _consume(related_news, source_weight=1.0)
    _consume(analyst_research, source_weight=1.25)

    if weight_total <= 0:
        signal = "HOLD"
        normalized = 0.0
    else:
        normalized = _clamp(weighted_sum / weight_total, -1.0, 1.0)
        if normalized >= 0.7:
            signal = "STRONG_BUY"
        elif normalized >= 0.3:
            signal = "BUY"
        elif normalized <= -0.7:
            signal = "STRONG_SELL"
        elif normalized <= -0.3:
            signal = "SELL"
        else:
            signal = "HOLD"

    contribution = _clamp(normalized * 1.0, -1.0, 1.0)
    return {
        "signal": signal,
        "score": round(normalized, 3),
        "contribution": round(contribution, 3),
        "weight": "10%",
        "bullish_mentions": bullish_mentions,
        "bearish_mentions": bearish_mentions,
        "scored_items": scored_items,
        "considered_items": len(related_news) + len(analyst_research),
    }


def _fetch_batch_info_sync(symbols: list[str]) -> dict[str, dict]:
    """Fetch basic info for multiple symbols in one shot with yfinance."""
    result = {}
    if not symbols:
        return result
    try:
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                info = tickers.tickers[sym].info or {}
                result[sym] = {
                    "symbol": sym,
                    "name": info.get("longName") or info.get("shortName", sym),
                    "price": _safe(info.get("currentPrice") or info.get("regularMarketPrice")),
                    "market_cap": _safe(info.get("marketCap")),
                    "sector": _safe_str(info.get("sector")),
                    "industry": _safe_str(info.get("industry")),
                }
            except Exception:
                result[sym] = {"symbol": sym, "name": sym, "price": None,
                               "market_cap": None, "sector": None, "industry": None}
    except Exception as exc:
        logger.warning("Batch info failed: %s", exc)
    return result


def _fetch_options_chain_sync(symbol: str, max_contracts: int = 12) -> dict:
    """Fetch nearest-expiry options chain and summary metrics for a symbol."""
    try:
        t = yf.Ticker(symbol)
        expirations = list(t.options or [])
        if not expirations:
            return {
                "available": False,
                "reason": "No listed options expirations for this symbol",
                "expirations": [],
            }

        selected_expiration = expirations[0]
        chain = t.option_chain(selected_expiration)
        calls = chain.calls
        puts = chain.puts

        def _contracts(df):
            if df is None or df.empty:
                return []
            data = df.copy()
            if "openInterest" in data.columns:
                data["openInterest"] = data["openInterest"].fillna(0)
            if "volume" in data.columns:
                data["volume"] = data["volume"].fillna(0)

            sort_cols = [c for c in ["openInterest", "volume"] if c in data.columns]
            if sort_cols:
                data = data.sort_values(sort_cols, ascending=False)

            out = []
            for _, row in data.head(max_contracts).iterrows():
                out.append(
                    {
                        "contract_symbol": _safe_str(row.get("contractSymbol")),
                        "strike": _safe(row.get("strike")),
                        "last_price": _safe(row.get("lastPrice")),
                        "bid": _safe(row.get("bid")),
                        "ask": _safe(row.get("ask")),
                        "change": _safe(row.get("change")),
                        "percent_change": _safe(row.get("percentChange")),
                        "volume": int(_safe(row.get("volume"), 0) or 0),
                        "open_interest": int(_safe(row.get("openInterest"), 0) or 0),
                        "implied_volatility": _safe(row.get("impliedVolatility")),
                        "in_the_money": bool(row.get("inTheMoney")) if row.get("inTheMoney") is not None else False,
                    }
                )
            return out

        total_call_oi = int(calls["openInterest"].fillna(0).sum()) if calls is not None and not calls.empty and "openInterest" in calls.columns else 0
        total_put_oi = int(puts["openInterest"].fillna(0).sum()) if puts is not None and not puts.empty and "openInterest" in puts.columns else 0
        total_call_vol = int(calls["volume"].fillna(0).sum()) if calls is not None and not calls.empty and "volume" in calls.columns else 0
        total_put_vol = int(puts["volume"].fillna(0).sum()) if puts is not None and not puts.empty and "volume" in puts.columns else 0

        put_call_oi_ratio = round(total_put_oi / total_call_oi, 4) if total_call_oi > 0 else None
        put_call_vol_ratio = round(total_put_vol / total_call_vol, 4) if total_call_vol > 0 else None

        bucket_defs = [
            ("7d", 0, 7),
            ("30d", 8, 30),
            ("60d", 31, 60),
            ("90d", 61, 90),
            ("180d", 91, 180),
            ("365d", 181, 365),
        ]

        def _bucket_for_dte(days_to_expiry: int) -> str | None:
            for label, min_d, max_d in bucket_defs:
                if min_d <= days_to_expiry <= max_d:
                    return label
            return None

        today = date.today()
        grouped: dict[str, dict] = {
            label: {
                "label": label,
                "expiration_count": 0,
                "dates": [],
                "total_call_open_interest": 0,
                "total_put_open_interest": 0,
                "total_call_volume": 0,
                "total_put_volume": 0,
            }
            for (label, _, _) in bucket_defs
        }

        # Aggregate options pressure by expiry horizon to estimate future demand.
        for exp in expirations:
            try:
                exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            except Exception:
                continue

            dte = (exp_date - today).days
            bucket = _bucket_for_dte(dte)
            if bucket is None:
                continue

            try:
                per_chain = t.option_chain(exp)
                per_calls = per_chain.calls
                per_puts = per_chain.puts
            except Exception:
                continue

            call_oi = int(per_calls["openInterest"].fillna(0).sum()) if per_calls is not None and not per_calls.empty and "openInterest" in per_calls.columns else 0
            put_oi = int(per_puts["openInterest"].fillna(0).sum()) if per_puts is not None and not per_puts.empty and "openInterest" in per_puts.columns else 0
            call_vol = int(per_calls["volume"].fillna(0).sum()) if per_calls is not None and not per_calls.empty and "volume" in per_calls.columns else 0
            put_vol = int(per_puts["volume"].fillna(0).sum()) if per_puts is not None and not per_puts.empty and "volume" in per_puts.columns else 0

            g = grouped[bucket]
            g["expiration_count"] += 1
            if len(g["dates"]) < 4:
                g["dates"].append(exp)
            g["total_call_open_interest"] += call_oi
            g["total_put_open_interest"] += put_oi
            g["total_call_volume"] += call_vol
            g["total_put_volume"] += put_vol

        expiry_groups = []
        for (label, _, _) in bucket_defs:
            g = grouped[label]
            call_oi_g = g["total_call_open_interest"]
            put_oi_g = g["total_put_open_interest"]
            call_vol_g = g["total_call_volume"]
            put_vol_g = g["total_put_volume"]

            ratio_oi = round(put_oi_g / call_oi_g, 4) if call_oi_g > 0 else None
            ratio_vol = round(put_vol_g / call_vol_g, 4) if call_vol_g > 0 else None

            oi_den = call_oi_g + put_oi_g
            vol_den = call_vol_g + put_vol_g
            oi_bias = ((call_oi_g - put_oi_g) / oi_den) if oi_den > 0 else 0.0
            vol_bias = ((call_vol_g - put_vol_g) / vol_den) if vol_den > 0 else 0.0
            demand_score = round((0.7 * oi_bias) + (0.3 * vol_bias), 4)

            if demand_score >= 0.15:
                signal = "BULLISH"
            elif demand_score <= -0.15:
                signal = "BEARISH"
            else:
                signal = "NEUTRAL"

            expiry_groups.append(
                {
                    **g,
                    "put_call_oi_ratio": ratio_oi,
                    "put_call_volume_ratio": ratio_vol,
                    "future_demand_score": demand_score,
                    "future_demand_signal": signal,
                }
            )

        return {
            "available": True,
            "expirations": expirations,
            "selected_expiration": selected_expiration,
            "summary": {
                "total_call_open_interest": total_call_oi,
                "total_put_open_interest": total_put_oi,
                "total_call_volume": total_call_vol,
                "total_put_volume": total_put_vol,
                "put_call_oi_ratio": put_call_oi_ratio,
                "put_call_volume_ratio": put_call_vol_ratio,
            },
            "expiry_groups": expiry_groups,
            "calls": _contracts(calls),
            "puts": _contracts(puts),
        }
    except Exception as exc:
        logger.warning("Options chain fetch failed for %s: %s", symbol, exc)
        return {
            "available": False,
            "reason": str(exc),
            "expirations": [],
        }


def _fmt_supply_chain_entry(entry: dict, quote: dict | None) -> dict:
    q = quote or {}
    return {
        "symbol": entry["symbol"],
        "name": q.get("name", entry["symbol"]),
        "role": entry["role"],
        "price": q.get("price"),
        "market_cap": q.get("market_cap"),
        "sector": q.get("sector"),
        "industry": q.get("industry"),
    }


def _compute_buy_sell_signal(
    info: dict,
    alternative_data: dict,
    options_chain: dict,
    technical_signal: dict | None = None,
    congress_activity: dict | None = None,
    news_bundle: dict | None = None,
    risk_tolerance: int = 5,
) -> dict:
    """
    Unified buy/sell signal combining all available data sources.

        Scoring components (max about ±10.5 total):
      Alternative Data     ±2.0  (20%)
      Options Chain P/C    ±2.0  (20%)
      Fundamentals         ±2.0  (20%)
      Momentum             ±1.5  (15%)
            Technical Indicators ±1.2  (12%) — RSI, MACD, Bollinger, SMA50/200
            Support/Resistance   ±0.8  (8%)  — level proximity and risk/reward
      Congressional Trades ±1.0  (10%) — recent disclosures

    Final classification:
      score >= 5   → STRONG_BUY
      score >= 2.5 → BUY
      score <= -5  → STRONG_SELL
      score <= -2.5 → SELL
      else         → HOLD
    """
    score = 0.0
    factors = {}

    # ── Alternative Data (20%) — capped at ±2.0 ──
    alt_score = alternative_data.get("alternative_score", 0)  # -2 to 2
    alt_contribution = _clamp(float(alt_score), -2.0, 2.0)
    score += alt_contribution
    factors["alternative_data"] = {
        "score": alt_score,
        "label": alternative_data.get("alternative_signal", "NEUTRAL"),
        "contribution": round(alt_contribution, 3),
        "weight": "20%",
    }

    # ── Options Chain (20%) ──
    opt_contribution = 0.0
    put_call_ratio = None
    if options_chain and options_chain.get("summary"):
        summary = options_chain["summary"]
        pc_ratio = summary.get("put_call_oi_ratio", 1.0) or 1.0
        put_call_ratio = pc_ratio
        if pc_ratio < 0.6:
            opt_contribution = 2.0    # Strong bullish
        elif pc_ratio < 0.8:
            opt_contribution = 1.2    # Moderate bullish
        elif pc_ratio > 1.5:
            opt_contribution = -2.0   # Strong bearish
        elif pc_ratio > 1.3:
            opt_contribution = -1.2   # Moderate bearish
    score += opt_contribution
    factors["options_chain"] = {
        "put_call_ratio": put_call_ratio,
        "contribution": round(opt_contribution, 3),
        "weight": "20%",
    }

    # ── Fundamentals (20%) ──
    fund_score = 0.0
    fund_details: dict = {}
    pe_ratio = _safe(info.get("trailingPE"))
    if pe_ratio:
        fund_details["pe_ratio"] = pe_ratio
        if pe_ratio < 15:
            fund_score += 1.5   # Undervalued
        elif pe_ratio > 30:
            fund_score -= 1.5   # Potentially overvalued
    debt_to_equity = _safe(info.get("debtToEquity"))
    if debt_to_equity:
        fund_details["debt_to_equity"] = debt_to_equity
        if debt_to_equity < 0.5:
            fund_score += 1.0   # Strong balance sheet
        elif debt_to_equity > 2.0:
            fund_score -= 1.0   # High debt burden
    current_ratio = _safe(info.get("currentRatio"))
    if current_ratio:
        fund_details["current_ratio"] = current_ratio
        if current_ratio > 1.5:
            fund_score += 0.75  # Good liquidity
        elif current_ratio < 1.0:
            fund_score -= 0.75  # Tight liquidity
    fund_contribution = _clamp(fund_score * 0.625, -2.0, 2.0)
    score += fund_contribution
    factors["fundamentals"] = {
        **fund_details,
        "contribution": round(fund_contribution, 3),
        "weight": "20%",
    }

    # ── Price Momentum (15%) ──
    mom_score = 0.0
    mom_data: dict = {}
    price_change_pct = _safe(info.get("regularMarketChangePercent") or info.get("priceChangePercent"))
    if price_change_pct:
        mom_data["day_change_pct"] = price_change_pct
        if price_change_pct > 2:
            mom_score += 1.0
        elif price_change_pct < -2:
            mom_score -= 1.0
    week_52_change_pct = _safe(info.get("fiftyTwoWeekChangePercent"))
    if week_52_change_pct:
        mom_data["52w_change_pct"] = week_52_change_pct
        if week_52_change_pct > 20:
            mom_score += 1.25
        elif week_52_change_pct < -20:
            mom_score -= 1.25
    mom_contribution = _clamp(mom_score * 0.667, -1.5, 1.5)
    score += mom_contribution
    factors["momentum"] = {
        **mom_data,
        "contribution": round(mom_contribution, 3),
        "weight": "15%",
    }

    # ── Technical Indicators (12%) — RSI, MACD, Bollinger Bands, SMA50/200 ──
    tech_contribution = 0.0
    if technical_signal and technical_signal.get("recommendation") not in (None, "INSUFFICIENT_DATA"):
        tech_score_raw = int(technical_signal.get("score", 0))
        tech_contribution = _clamp(tech_score_raw * 0.24, -1.2, 1.2)
    score += tech_contribution
    factors["technical"] = {
        "score": technical_signal.get("score", 0) if technical_signal else 0,
        "recommendation": technical_signal.get("recommendation", "N/A") if technical_signal else "N/A",
        "contribution": round(tech_contribution, 3),
        "indicators": technical_signal.get("indicators", {}) if technical_signal else {},
        "weight": "12%",
    }

    # ── Support / Resistance (8%) ──
    sr_contribution = 0.0
    sr_ind = (technical_signal or {}).get("indicators", {}) if technical_signal else {}
    sr_signal = str(sr_ind.get("sr_signal", "NEUTRAL"))
    if "bullish" in sr_signal.lower():
        sr_contribution = 0.8
    elif "bearish" in sr_signal.lower():
        sr_contribution = -0.8
    score += sr_contribution
    factors["support_resistance"] = {
        "signal": sr_signal,
        "support_near": sr_ind.get("support_near"),
        "resistance_near": sr_ind.get("resistance_near"),
        "support_major": sr_ind.get("support_major"),
        "resistance_major": sr_ind.get("resistance_major"),
        "stop_loss_suggestion": sr_ind.get("stop_loss_suggestion"),
        "take_profit_1": sr_ind.get("take_profit_1"),
        "take_profit_2": sr_ind.get("take_profit_2"),
        "risk_reward_tp1": sr_ind.get("risk_reward_tp1"),
        "contribution": round(sr_contribution, 3),
        "weight": "8%",
    }

    # ── Congressional Trades (10%) ──
    cong_contribution = 0.0
    if congress_activity:
        cong_raw = congress_activity.get("signal_score", 0) or 0
        cong_contribution = _clamp(cong_raw * 0.1, -1.0, 1.0)
    score += cong_contribution
    factors["congressional"] = {
        "signal": congress_activity.get("signal_label", "NEUTRAL") if congress_activity else "N/A",
        "score": congress_activity.get("signal_score", 0) if congress_activity else 0,
        "contribution": round(cong_contribution, 3),
        "weight": "10%",
    }

    # ── News & Research (10%) ──
    news_factor = _compute_news_research_factor(news_bundle)
    news_contribution = float(news_factor.get("contribution", 0.0) or 0.0)
    score += news_contribution
    factors["news_research"] = news_factor

    # ── Final Signal Classification (thresholds adjusted by risk tolerance) ──
    # Conservative (1-3): require higher conviction
    # Moderate (4-6): standard thresholds
    # Aggressive (7-10): lower thresholds for more trading signals
    risk = max(1, min(10, int(risk_tolerance)))
    if risk <= 3:
        strong_buy_t, buy_t = 6.0, 3.5
        strong_sell_t, sell_t = -6.0, -3.5
    elif risk <= 6:
        strong_buy_t, buy_t = 5.0, 2.5
        strong_sell_t, sell_t = -5.0, -2.5
    else:
        strong_buy_t, buy_t = 3.5, 1.5
        strong_sell_t, sell_t = -3.5, -1.5

    if score >= strong_buy_t:
        signal = "STRONG_BUY"
    elif score >= buy_t:
        signal = "BUY"
    elif score <= strong_sell_t:
        signal = "STRONG_SELL"
    elif score <= sell_t:
        signal = "SELL"
    else:
        signal = "HOLD"

    return {
        "signal": signal,
        "score": round(score, 2),
        "factors": factors,
        "risk_tolerance_used": risk,
    }


def _compute_technical_signal_sync(symbol: str) -> dict:
    """Fetch price history and run all technical indicators (RSI, MACD, Bollinger, SMA)."""
    try:
        history = get_market_price_history(symbol, days=settings.signal_lookback_days)
        # Fallback for intermittent upstream chart API failures/rate limits.
        if len(history) < 30:
            try:
                hist = yf.Ticker(symbol).history(period="6mo", interval="1d", auto_adjust=False)
                if hist is not None and not hist.empty:
                    history = [
                        {
                            "date": idx.strftime("%Y-%m-%d"),
                            "open": float(row.get("Open")) if row.get("Open") is not None else None,
                            "high": float(row.get("High")) if row.get("High") is not None else None,
                            "low": float(row.get("Low")) if row.get("Low") is not None else None,
                            "close": float(row.get("Close")) if row.get("Close") is not None else None,
                            "volume": float(row.get("Volume")) if row.get("Volume") is not None else None,
                        }
                        for idx, row in hist.iterrows()
                    ]
            except Exception as fallback_exc:
                logger.warning("Technical fallback history fetch failed for %s: %s", symbol, fallback_exc)
        return compute_signals(symbol, history)
    except Exception as exc:
        logger.warning("Technical signal fetch failed for %s: %s", symbol, exc)
        return {
            "recommendation": "INSUFFICIENT_DATA",
            "score": 0,
            "indicators": {},
            "reason": str(exc),
        }


def _compute_congress_activity(symbol: str) -> dict:
    history_window_days = 90
    signal_window_days = 30
    symbol = symbol.upper()

    try:
        trades_90d = [
            trade for trade in get_congress_trades([symbol], days_back=history_window_days)
            if (trade.symbol or "").strip().upper() == symbol
        ]
        signal_trades = filter_congress_trades(
            trades_90d,
            disclosed_days=signal_window_days,
            require_ticker=True,
            reference_date=datetime.utcnow().date(),
        )
        signal_summary = congress_signal(symbol, signal_trades)
    except Exception as exc:
        logger.warning("Congress activity fetch failed for %s: %s", symbol, exc)
        return {
            "symbol": symbol,
            "history_window_days": history_window_days,
            "signal_window_days": signal_window_days,
            "signal": "HOLD",
            "signal_label": "UNAVAILABLE",
            "signal_score": 0,
            "trades_90d_count": 0,
            "purchases_90d": 0,
            "sales_90d": 0,
            "net_90d": 0,
            "signal_trade_count": 0,
            "latest_trade_date": None,
            "latest_disclosure_date": None,
            "recent_trades": [],
            "unavailable_reason": str(exc),
        }

    purchases_90d = sum(
        1 for trade in trades_90d
        if "purchase" in (trade.transaction or "").lower() or "buy" in (trade.transaction or "").lower()
    )
    sales_90d = sum(
        1 for trade in trades_90d
        if "sale" in (trade.transaction or "").lower() or "sell" in (trade.transaction or "").lower()
    )

    signal_score = int(signal_summary.get("congress_score", 0) or 0)
    if signal_score > 0:
        signal = "BUY"
    elif signal_score < 0:
        signal = "SELL"
    else:
        signal = "HOLD"

    latest_trade_date = max((trade.trade_date for trade in trades_90d if trade.trade_date), default=None)
    latest_disclosure_date = max((trade.disclosure_date for trade in trades_90d if trade.disclosure_date), default=None)

    return {
        "symbol": symbol,
        "history_window_days": history_window_days,
        "signal_window_days": signal_window_days,
        "signal": signal,
        "signal_label": signal_summary.get("congress_signal", "NEUTRAL"),
        "signal_score": signal_score,
        "trades_90d_count": len(trades_90d),
        "purchases_90d": purchases_90d,
        "sales_90d": sales_90d,
        "net_90d": purchases_90d - sales_90d,
        "signal_trade_count": len(signal_trades),
        "latest_trade_date": latest_trade_date,
        "latest_disclosure_date": latest_disclosure_date,
        "recent_trades": [
            {
                "politician": trade.politician,
                "party": trade.party,
                "transaction": trade.transaction,
                "amount_range": trade.amount_range,
                "trade_date": trade.trade_date,
                "disclosure_date": trade.disclosure_date,
            }
            for trade in trades_90d[:6]
        ],
    }


# ─── Sector ETF map ──────────────────────────────────────────────────────────
_SECTOR_ETF = {
    "Technology": "XLK", "Financials": "XLF", "Health Care": "XLV",
    "Consumer Discretionary": "XLY", "Consumer Staples": "XLP",
    "Energy": "XLE", "Industrials": "XLI", "Materials": "XLB",
    "Real Estate": "XLRE", "Utilities": "XLU", "Communication Services": "XLC",
}


def _search_companies_sync(query: str, limit: int = 8) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []

    safe_limit = max(1, min(int(limit or 8), 25))
    url = (
        "https://query1.finance.yahoo.com/v1/finance/search"
        f"?q={quote_plus(q)}&quotesCount={safe_limit}&newsCount=0"
    )

    try:
        req = Request(url, headers={"User-Agent": "traderbot/1.0"})
        with urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Company search failed for query '%s': %s", q, exc)
        return []

    quotes = payload.get("quotes") if isinstance(payload, dict) else []
    if not isinstance(quotes, list):
        return []

    allowed_types = {"EQUITY", "ETF", "MUTUALFUND", "INDEX"}
    seen: set[str] = set()
    out: list[dict] = []
    for item in quotes:
        if not isinstance(item, dict):
            continue
        symbol = _safe_str(item.get("symbol"), default="").upper()
        if not symbol or symbol in seen:
            continue

        qtype = _safe_str(item.get("quoteType") or item.get("typeDisp"), default="").upper()
        if qtype and qtype not in allowed_types:
            continue

        name = _safe_str(
            item.get("shortname")
            or item.get("longname")
            or item.get("name"),
            default=symbol,
        )
        exchange = _safe_str(item.get("exchange") or item.get("exchDisp") or item.get("exchangeDisp"), default="")
        seen.add(symbol)
        out.append(
            {
                "symbol": symbol,
                "name": name,
                "exchange": exchange,
                "type": qtype or "UNKNOWN",
            }
        )
        if len(out) >= safe_limit:
            break

    return out


@company_router.get("/company-search", tags=["company"])
async def company_search(q: str, limit: int = 8):
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(_executor, _search_companies_sync, q, limit)
    return {
        "query": q,
        "results": results,
    }

def _fetch_price_history_sync(symbol: str, period: str, interval: str, sector: str | None):
    """Fetch OHLCV history for symbol, SPY, and sector ETF. Returns normalised series."""
    comparisons = {"SPY": "S&P 500"}
    etf = _SECTOR_ETF.get(sector or "")
    if etf:
        comparisons[etf] = f"{sector} Sector"

    tickers_to_fetch = [symbol] + list(comparisons.keys())
    raw = yf.download(tickers_to_fetch, period=period, interval=interval,
                      auto_adjust=True, progress=False, threads=True)

    def _extract(sym):
        try:
            if len(tickers_to_fetch) == 1:
                closes = raw["Close"]
            else:
                closes = raw["Close"][sym]
            closes = closes.dropna()
            if closes.empty:
                return []
            # Normalise to 100 at first point for comparison
            base = float(closes.iloc[0])
            return [
                {"t": str(idx.date() if hasattr(idx, "date") else idx)[:10],
                 "v": round(float(v), 4),
                 "n": round(float(v) / base * 100, 4)}
                for idx, v in closes.items()
            ]
        except Exception:
            return []

    result = {"symbol": symbol, "series": _extract(symbol), "comparisons": {}}
    for ticker, label in comparisons.items():
        pts = _extract(ticker)
        if pts:
            result["comparisons"][label] = pts
    return result


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _fetch_future_projection_sync(symbol: str) -> dict:
    """Build min/avg/max price targets from combined indicators and historical volatility."""
    info = _fetch_ticker_sync(symbol)
    current_price = _safe(info.get("currentPrice") or info.get("regularMarketPrice"))
    if current_price is None:
        raise ValueError("Current price unavailable")

    alternative_data = get_alternative_signal(symbol)
    options_chain = _fetch_options_chain_sync(symbol)
    buy_sell_signal = _compute_buy_sell_signal(info, alternative_data, options_chain)

    # Realized volatility baseline (2-year daily history)
    hist = yf.Ticker(symbol).history(period="2y", interval="1d", auto_adjust=True)
    try:
        daily_ret = hist["Close"].pct_change().dropna()
        annual_vol = float(daily_ret.std()) * math.sqrt(252)
    except Exception:
        annual_vol = 0.3
    annual_vol = _clamp(annual_vol if annual_vol > 0 else 0.3, 0.12, 1.0)

    # Signal strengths in [-1, 1]
    signal_strength = _clamp(float(buy_sell_signal.get("score", 0.0)) / 10.0, -1.0, 1.0)
    alt_strength = _clamp(float(alternative_data.get("normalized_raw_score", 0.0)) / 2.0, -1.0, 1.0)

    option_groups = options_chain.get("expiry_groups") or []
    valid_groups = [g for g in option_groups if int(g.get("expiration_count") or 0) > 0]
    if valid_groups:
        option_strength = sum(float(g.get("future_demand_score") or 0.0) for g in valid_groups) / len(valid_groups)
    else:
        option_strength = 0.0
    option_strength = _clamp(option_strength, -1.0, 1.0)

    factors = buy_sell_signal.get("factors", {})
    fund_strength = _clamp(float(factors.get("fundamentals", {}).get("contribution", 0.0)) / 2.5, -1.0, 1.0)
    mom_strength = _clamp(float(factors.get("momentum", {}).get("contribution", 0.0)) / 2.5, -1.0, 1.0)

    # Composite forward view from all indicators
    composite = (
        0.40 * signal_strength
        + 0.20 * alt_strength
        + 0.20 * option_strength
        + 0.10 * fund_strength
        + 0.10 * mom_strength
    )

    # Drift range roughly -18% to +30% annualized
    annual_drift = 0.06 + (0.24 * composite)

    horizons = [
        ("1w", "1 Week", 5),
        ("1mo", "1 Month", 21),
        ("3mo", "3 Months", 63),
        ("6mo", "6 Months", 126),
        ("1y", "1 Year", 252),
    ]

    targets = []
    for key, label, trading_days in horizons:
        t = trading_days / 252.0
        avg_price = float(current_price) * math.exp(annual_drift * t)
        band = annual_vol * math.sqrt(t)
        min_price = max(0.01, avg_price * math.exp(-1.15 * band))
        max_price = avg_price * math.exp(1.15 * band)
        targets.append({
            "key": key,
            "label": label,
            "trading_days": trading_days,
            "min": round(min_price, 2),
            "avg": round(avg_price, 2),
            "max": round(max_price, 2),
        })

    return {
        "symbol": symbol,
        "current_price": round(float(current_price), 2),
        "targets": targets,
        "model_inputs": {
            "annual_drift": round(annual_drift, 4),
            "annual_volatility": round(annual_vol, 4),
            "composite_signal": round(composite, 4),
            "signals": {
                "buy_sell": round(signal_strength, 4),
                "alternative_data": round(alt_strength, 4),
                "options": round(option_strength, 4),
                "fundamentals": round(fund_strength, 4),
                "momentum": round(mom_strength, 4),
            },
        },
    }


@company_router.get("/price-history/{symbol}", tags=["company"])
async def get_price_history(symbol: str, range: str = "1y"):
    symbol = symbol.upper()
    # Map UI range → yfinance period + interval
    range_map = {
        "1d":  ("1d",  "5m"),
        "1w":  ("5d",  "30m"),
        "1mo": ("1mo", "1d"),
        "3mo": ("3mo", "1d"),
        "6mo": ("6mo", "1d"),
        "1y":  ("1y",  "1d"),
        "3y":  ("3y",  "1wk"),
        "5y":  ("5y",  "1wk"),
    }
    if range not in range_map:
        raise HTTPException(status_code=400, detail=f"Invalid range. Choose from: {', '.join(range_map)}")
    period, interval = range_map[range]

    # Get sector from a quick yf info call
    try:
        info = yf.Ticker(symbol).fast_info
        sector = getattr(info, "sector", None)
    except Exception:
        sector = None

    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(_executor, _fetch_price_history_sync, symbol, period, interval, sector)
    return data


@company_router.get("/future-projection/{symbol}", tags=["company"])
async def get_future_projection(symbol: str):
    symbol = symbol.upper()
    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(_executor, _fetch_future_projection_sync, symbol)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return data


@company_router.get("/company/{symbol}", tags=["company"])
async def get_company_profile(symbol: str):
    """Fast core endpoint: ticker fundamentals only, no slow external calls."""
    symbol = symbol.upper()
    loop = asyncio.get_event_loop()

    # ── Fetch ticker info ─────────────────────────────────────────────────────
    info = await loop.run_in_executor(_executor, _fetch_ticker_sync, symbol)

    if not info or (not info.get("symbol") and not info.get("shortName") and not info.get("longName")):
        raise HTTPException(404, f"No data found for symbol '{symbol}'")

    # Build peer symbols from available Yahoo fields.
    peer_syms: list[str] = []
    for key in ("relatedTickers", "recommendedSymbols", "peerSymbols"):
        raw = info.get(key)
        if not raw:
            continue
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    s = item.strip().upper()
                    if s != symbol and s not in peer_syms:
                        peer_syms.append(s)
                elif isinstance(item, dict):
                    s = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
                    if s and s != symbol and s not in peer_syms:
                        peer_syms.append(s)
        elif isinstance(raw, str):
            for item in raw.split(","):
                s = item.strip().upper()
                if s and s != symbol and s not in peer_syms:
                    peer_syms.append(s)

    # ── Core price / identity ─────────────────────────────────────────────────
    current_price  = _safe(info.get("currentPrice") or info.get("regularMarketPrice"))
    prev_close     = _safe(info.get("previousClose") or info.get("regularMarketPreviousClose"))
    price_change   = round(current_price - prev_close, 4) if current_price and prev_close else None
    price_change_p = round((price_change / prev_close) * 100, 4) if price_change and prev_close else None

    return {
        "symbol":       symbol,
        "name":         info.get("longName") or info.get("shortName", symbol),
        "exchange":     _safe_str(info.get("exchange") or info.get("fullExchangeName")),
        "currency":     _safe_str(info.get("currency"), default="USD"),
        "quote_type":   _safe_str(info.get("quoteType")),
        "_peer_syms":   peer_syms,

        # Price
        "price":             current_price,
        "prev_close":        prev_close,
        "price_change":      price_change,
        "price_change_pct":  price_change_p,
        "market_open":       _safe(info.get("open") or info.get("regularMarketOpen")),
        "day_high":          _safe(info.get("dayHigh") or info.get("regularMarketDayHigh")),
        "day_low":           _safe(info.get("dayLow")  or info.get("regularMarketDayLow")),
        "volume":            _safe(info.get("volume")  or info.get("regularMarketVolume")),
        "avg_volume":        _safe(info.get("averageVolume") or info.get("averageDailyVolume10Day")),

        # Valuation
        "market_cap":            _safe(info.get("marketCap")),
        "enterprise_value":      _safe(info.get("enterpriseValue")),
        "pe_ratio":              _safe(info.get("trailingPE")),
        "forward_pe":            _safe(info.get("forwardPE")),
        "peg_ratio":             _safe(info.get("pegRatio")),
        "price_to_sales":        _safe(info.get("priceToSalesTrailing12Months")),
        "price_to_book":         _safe(info.get("priceToBook")),
        "enterprise_to_revenue": _safe(info.get("enterpriseToRevenue")),
        "enterprise_to_ebitda":  _safe(info.get("enterpriseToEbitda")),

        # EPS & dividends
        "eps":              _safe(info.get("trailingEps")),
        "eps_forward":      _safe(info.get("forwardEps")),
        "dividend_rate":    _safe(info.get("dividendRate")),
        "dividend_yield":   _safe(info.get("dividendYield")),
        "ex_dividend_date": _safe_str(info.get("exDividendDate")),
        "payout_ratio":     _safe(info.get("payoutRatio")),

        # Risk & volatility
        "beta":                  _safe(info.get("beta")),
        "fifty_two_week_high":   _safe(info.get("fiftyTwoWeekHigh")),
        "fifty_two_week_low":    _safe(info.get("fiftyTwoWeekLow")),
        "fifty_day_avg":         _safe(info.get("fiftyDayAverage")),
        "two_hundred_day_avg":   _safe(info.get("twoHundredDayAverage")),
        "short_ratio":           _safe(info.get("shortRatio")),
        "short_percent_float":   _safe(info.get("shortPercentOfFloat")),

        # Shares
        "shares_outstanding": _safe(info.get("sharesOutstanding")),
        "float_shares":       _safe(info.get("floatShares")),
        "book_value":         _safe(info.get("bookValue")),

        # Financials (TTM)
        "revenue_ttm":        _safe(info.get("totalRevenue")),
        "gross_margins":      _safe(info.get("grossMargins")),
        "operating_margins":  _safe(info.get("operatingMargins")),
        "profit_margins":     _safe(info.get("profitMargins")),
        "return_on_equity":   _safe(info.get("returnOnEquity")),
        "return_on_assets":   _safe(info.get("returnOnAssets")),
        "revenue_growth":     _safe(info.get("revenueGrowth")),
        "earnings_growth":    _safe(info.get("earningsGrowth")),

        # Balance sheet
        "total_cash":         _safe(info.get("totalCash")),
        "total_debt":         _safe(info.get("totalDebt")),
        "debt_to_equity":     _safe(info.get("debtToEquity")),
        "current_ratio":      _safe(info.get("currentRatio")),
        "quick_ratio":        _safe(info.get("quickRatio")),

        # Cash flow
        "operating_cashflow": _safe(info.get("operatingCashflow")),
        "free_cashflow":      _safe(info.get("freeCashflow")),

        # Analyst
        "target_mean_price":  _safe(info.get("targetMeanPrice")),
        "target_high_price":  _safe(info.get("targetHighPrice")),
        "target_low_price":   _safe(info.get("targetLowPrice")),
        "recommendation_key": _safe_str(info.get("recommendationKey")),
        "analyst_count":      _safe(info.get("numberOfAnalystOpinions")),

        # Company identity
        "sector":      _safe_str(info.get("sector")),
        "industry":    _safe_str(info.get("industry")),
        "country":     _safe_str(info.get("country")),
        "city":        _safe_str(info.get("city")),
        "state":       _safe_str(info.get("state")),
        "employees":   info.get("fullTimeEmployees"),
        "website":     _safe_str(info.get("website")),
        "description": _safe_str(info.get("longBusinessSummary")),
    }


@company_router.get("/company/{symbol}/sections", tags=["company"])
async def get_company_sections(symbol: str, peer_syms: str = "", risk_tolerance: int = 5):
    """
    Slow sections loaded in parallel: supply chain quotes, options chain,
    alternative data, and buy/sell signal.

    'peer_syms' is an optional comma-separated list returned by the core endpoint.
    """
    symbol = symbol.upper()
    loop = asyncio.get_event_loop()

    # ── Need ticker info for buy/sell signal computation ─────────────────────
    peer_list = [p for p in peer_syms.split(",") if p] if peer_syms else []
    fallback_candidates: list[str] = []

    sc_data       = SUPPLY_CHAIN.get(symbol, {})
    suppliers_raw = sc_data.get("suppliers", [])
    customers_raw = sc_data.get("customers", [])

    if not peer_list:
        fallback_set: set[str] = set(FALLBACK_PEER_SYMBOLS)
        fallback_set.update(SUPPLY_CHAIN.keys())
        for chain in SUPPLY_CHAIN.values():
            for edge in chain.get("suppliers", []):
                s = _safe_str(edge.get("symbol"))
                if s:
                    fallback_set.add(s.upper())
            for edge in chain.get("customers", []):
                s = _safe_str(edge.get("symbol"))
                if s:
                    fallback_set.add(s.upper())
        fallback_set.discard(symbol)
        fallback_candidates = sorted(fallback_set)

    all_chain_syms = list({
        e["symbol"]
        for e in suppliers_raw + customers_raw + [{"symbol": s} for s in (peer_list + fallback_candidates)]
    })

    # ── All slow fetches in parallel ─────────────────────────────────────────
    ticker_task   = loop.run_in_executor(_executor, _fetch_ticker_sync, symbol)
    quotes_task   = loop.run_in_executor(_executor, _fetch_batch_info_sync, all_chain_syms)
    alt_task      = loop.run_in_executor(_executor, get_alternative_signal, symbol)
    options_task  = loop.run_in_executor(_executor, _fetch_options_chain_sync, symbol)
    congress_task = loop.run_in_executor(_executor, _compute_congress_activity, symbol)
    tech_task     = loop.run_in_executor(_executor, _compute_technical_signal_sync, symbol)
    news_task     = loop.run_in_executor(_executor, _fetch_news_and_research_sync, symbol)
    fmp_task      = loop.run_in_executor(_executor, _fmp_company_data_sync, symbol)

    results = await asyncio.gather(
        ticker_task,
        quotes_task,
        alt_task,
        options_task,
        congress_task,
        tech_task,
        news_task,
        fmp_task,
        return_exceptions=True,
    )

    info, quotes, alternative_data, options_chain, congress_activity, technical_signal, news_bundle, fmp_data = results

    if isinstance(info, Exception):
        logger.warning("Company sections ticker fetch failed for %s: %s", symbol, info)
        info = {}
    if isinstance(quotes, Exception):
        logger.warning("Company sections quotes fetch failed for %s: %s", symbol, quotes)
        quotes = {}
    if isinstance(alternative_data, Exception):
        logger.warning("Company sections alternative data fetch failed for %s: %s", symbol, alternative_data)
        alternative_data = {
            "symbol": symbol,
            "alternative_score": 0.0,
            "alternative_signal": "NEUTRAL",
            "available_sources": 0,
            "providers": {},
            "as_of_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "lookback_days": int(settings.signal_lookback_days),
            "normalized_raw_score": 0.0,
        }
    if isinstance(options_chain, Exception):
        logger.warning("Company sections options fetch failed for %s: %s", symbol, options_chain)
        options_chain = {"symbol": symbol, "expiry_groups": []}
    if isinstance(congress_activity, Exception):
        logger.warning("Company sections congress activity fetch failed for %s: %s", symbol, congress_activity)
        congress_activity = {
            "symbol": symbol,
            "history_window_days": 90,
            "signal_window_days": 30,
            "signal": "HOLD",
            "signal_label": "UNAVAILABLE",
            "signal_score": 0,
            "trades_90d_count": 0,
            "purchases_90d": 0,
            "sales_90d": 0,
            "net_90d": 0,
            "signal_trade_count": 0,
            "latest_trade_date": None,
            "latest_disclosure_date": None,
            "recent_trades": [],
        }
    if isinstance(technical_signal, Exception):
        logger.warning("Company sections technical signal fetch failed for %s: %s", symbol, technical_signal)
        technical_signal = {
            "recommendation": "INSUFFICIENT_DATA",
            "score": 0,
            "indicators": {},
        }
    if isinstance(news_bundle, Exception):
        logger.warning("Company sections news fetch failed for %s: %s", symbol, news_bundle)
        news_bundle = {
            "related_news": [],
            "analyst_research": [],
            "updated_at": datetime.utcnow().isoformat(),
        }
    if isinstance(fmp_data, Exception):
        logger.warning("Company sections FMP fetch failed for %s: %s", symbol, fmp_data)
        fmp_data = {"available": False, "reason": "FMP fetch error"}

    if not info:
        info = {}

    # If no peers were provided by the core endpoint, infer peers by matching
    # sector/industry within fallback candidates and rank by market cap.
    if not peer_list and fallback_candidates:
        target_sector = (_safe_str(info.get("sector")) or "").lower()
        target_industry = (_safe_str(info.get("industry")) or "").lower()

        ranked: list[tuple[int, float, str]] = []
        for cand in fallback_candidates:
            q = quotes.get(cand, {})
            sec = (_safe_str(q.get("sector")) or "").lower()
            ind = (_safe_str(q.get("industry")) or "").lower()

            score = 0
            if target_industry and ind and ind == target_industry:
                score = 3
            elif target_sector and sec and sec == target_sector:
                score = 2

            if score <= 0:
                continue

            ranked.append((score, float(q.get("market_cap") or 0), cand))

        ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
        peer_list = [cand for _, _, cand in ranked[:30]]

        # Final fallback: if sector/industry are unavailable, return top names by market cap.
        if not peer_list:
            by_cap: list[tuple[float, str]] = []
            for cand in fallback_candidates:
                q = quotes.get(cand, {})
                by_cap.append((float(q.get("market_cap") or 0), cand))
            by_cap.sort(reverse=True)
            peer_list = [cand for _, cand in by_cap[:20] if cand != symbol]

    # ── Assemble supply chain ─────────────────────────────────────────────────
    suppliers = [_fmt_supply_chain_entry(e, quotes.get(e["symbol"])) for e in suppliers_raw]
    customers = [_fmt_supply_chain_entry(e, quotes.get(e["symbol"])) for e in customers_raw]

    peers = []
    for ps in peer_list:
        if ps == symbol:
            continue
        q = quotes.get(ps, {})
        peers.append({
            "symbol": ps,
            "name":   q.get("name", ps),
            "price":  q.get("price"),
            "market_cap": q.get("market_cap"),
            "sector":     q.get("sector"),
            "industry":   q.get("industry"),
            "relationship": "peer",
        })

    buy_sell_signal = _compute_buy_sell_signal(
        info, alternative_data, options_chain, technical_signal, congress_activity, news_bundle,
        risk_tolerance=risk_tolerance,
    )

    return {
        "suppliers":           suppliers,
        "customers":           customers,
        "peers":               peers,
        "has_supply_chain_data": bool(sc_data),
        "alternative_data":    alternative_data,
        "options_chain":       options_chain,
        "congress_activity":   congress_activity,
        "technical_signal":    technical_signal,
        "buy_sell_signal":     buy_sell_signal,
        "related_news":        news_bundle.get("related_news", []),
        "analyst_research":    news_bundle.get("analyst_research", []),
        "news_updated_at":     news_bundle.get("updated_at"),
        "fmp_data":            fmp_data,
    }
