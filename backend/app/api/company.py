"""
Company profile endpoint: fundamentals, supply chain, sector peers.

GET /api/company/{symbol}
"""

import asyncio
import logging
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf
from fastapi import APIRouter, HTTPException
from app.data_sources.alternative_data import get_alternative_signal

logger = logging.getLogger(__name__)
company_router = APIRouter(prefix="/api")
_executor = ThreadPoolExecutor(max_workers=4)

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
        import math
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
    """Blocking call — run in executor."""
    t = yf.Ticker(symbol)
    info = t.info or {}
    return info


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


def _compute_buy_sell_signal(info: dict, alternative_data: dict, options_chain: dict) -> dict:
    """
    Compute a buy/sell indicator considering:
    - Alternative data sentiment score
    - Options chain put/call ratios
    - Fundamental metrics (P/E, debt ratios)
    - Price momentum
    
    Returns a signal with:
    - signal: "STRONG_BUY" | "BUY" | "HOLD" | "SELL" | "STRONG_SELL"
    - score: -10 to +10
    - factors: breakdown of contributing factors
    """
    score = 0.0
    factors = {}
    
    # ── Alternative Data Score (weight: 30%) ──
    alt_score = alternative_data.get("alternative_score", 0)  # -2 to 2
    alt_contribution = (alt_score / 2.0) * 3  # Scale to -3 to +3
    score += alt_contribution
    factors["alternative_data"] = {
        "score": alt_score,
        "contribution": alt_contribution,
        "weight": "30%"
    }
    
    # ── Options Chain Analysis (weight: 25%) ──
    opt_score = 0.0
    if options_chain and options_chain.get("summary"):
        summary = options_chain["summary"]
        put_call_oi_ratio = summary.get("put_call_oi_ratio", 1.0)
        put_call_vol_ratio = summary.get("put_call_volume_ratio", 1.0)
        
        # Low put/call ratio = bullish (more calls bought)
        # High put/call ratio = bearish (more puts bought)
        if put_call_oi_ratio < 0.8:
            opt_score += 1.5  # Moderate bullish
        elif put_call_oi_ratio < 0.6:
            opt_score += 2.5  # Strong bullish
        elif put_call_oi_ratio > 1.3:
            opt_score -= 1.5  # Moderate bearish
        elif put_call_oi_ratio > 1.5:
            opt_score -= 2.5  # Strong bearish
    
    opt_contribution = opt_score * 0.625  # Scale to -2.5 to +2.5
    score += opt_contribution
    factors["options_chain"] = {
        "put_call_ratio": options_chain.get("summary", {}).get("put_call_oi_ratio"),
        "contribution": opt_contribution,
        "weight": "25%"
    }
    
    # ── Fundamental Metrics (weight: 25%) ──
    fund_score = 0.0
    factors["fundamentals"] = {}
    
    pe_ratio = _safe(info.get("trailingPE"))
    if pe_ratio:
        factors["fundamentals"]["pe_ratio"] = pe_ratio
        if pe_ratio < 15:
            fund_score += 1.5  # Undervalued
        elif pe_ratio > 30:
            fund_score -= 1.5  # Potentially overvalued
    
    debt_to_equity = _safe(info.get("debtToEquity"))
    if debt_to_equity:
        factors["fundamentals"]["debt_to_equity"] = debt_to_equity
        if debt_to_equity < 0.5:
            fund_score += 1.0  # Strong balance sheet
        elif debt_to_equity > 2.0:
            fund_score -= 1.0  # High debt burden
    
    current_ratio = _safe(info.get("currentRatio"))
    if current_ratio:
        factors["fundamentals"]["current_ratio"] = current_ratio
        if current_ratio > 1.5:
            fund_score += 0.75  # Good liquidity
        elif current_ratio < 1.0:
            fund_score -= 0.75  # Tight liquidity
    
    fund_contribution = fund_score * 0.625  # Scale to -2.5 to +2.5
    score += fund_contribution
    factors["fundamentals"]["contribution"] = fund_contribution
    factors["fundamentals"]["weight"] = "25%"
    
    # ── Price Momentum (weight: 20%) ──
    mom_score = 0.0
    mom_data = {}
    
    price_change_pct = _safe(info.get("regularMarketChangePercent") or info.get("priceChangePercent"))
    if price_change_pct:
        mom_data["day_change_pct"] = price_change_pct
        if price_change_pct > 2:
            mom_score += 1.0  # Positive momentum
        elif price_change_pct < -2:
            mom_score -= 1.0  # Negative momentum
    
    week_52_change_pct = _safe(info.get("fiftyTwoWeekChangePercent"))
    if week_52_change_pct:
        mom_data["52w_change_pct"] = week_52_change_pct
        if week_52_change_pct > 20:
            mom_score += 1.25  # Strong uptrend
        elif week_52_change_pct < -20:
            mom_score -= 1.25  # Strong downtrend
    
    mom_contribution = mom_score * 0.5  # Scale to -2.5 to +2.5
    score += mom_contribution
    factors["momentum"] = {
        **mom_data,
        "contribution": mom_contribution,
        "weight": "20%"
    }
    
    # ── Final Signal Classification ──
    if score >= 5:
        signal = "STRONG_BUY"
    elif score >= 2.5:
        signal = "BUY"
    elif score <= -5:
        signal = "STRONG_SELL"
    elif score <= -2.5:
        signal = "SELL"
    else:
        signal = "HOLD"
    
    return {
        "signal": signal,
        "score": round(score, 2),
        "factors": factors,
    }


@company_router.get("/company/{symbol}", tags=["company"])
async def get_company_profile(symbol: str):
    symbol = symbol.upper()
    loop = asyncio.get_event_loop()

    # Fetch main ticker info in thread (yfinance is synchronous)
    info: dict = await loop.run_in_executor(_executor, _fetch_ticker_sync, symbol)

    if not info or not info.get("symbol") and not info.get("shortName") and not info.get("longName"):
        raise HTTPException(404, f"No data found for symbol '{symbol}'")

    # ── Core price / identity ─────────────────────────────────────────────────
    current_price = _safe(info.get("currentPrice") or info.get("regularMarketPrice"))
    prev_close    = _safe(info.get("previousClose") or info.get("regularMarketPreviousClose"))
    price_change  = round(current_price - prev_close, 4) if current_price and prev_close else None
    price_change_p = round((price_change / prev_close) * 100, 4) if price_change and prev_close else None

    # Peers from yfinance recommendations (stored in info as 'recommendedSymbols' sometimes, but use
    # a separate Ticker call via the same executor for simplicity)
    def _peers_sync():
        try:
            t = yf.Ticker(symbol)
            rec = t.recommendations
            if rec is not None and not rec.empty:
                # recommendations df has 'To Grade' + 'Firm' columns
                return []
            # Fall back: use info.get relatedTickers if available
        except Exception:
            pass
        return []

    peer_syms: list[str] = await loop.run_in_executor(_executor, _peers_sync)

    # ── Build response ────────────────────────────────────────────────────────
    company_info = {
        "symbol":       symbol,
        "name":         info.get("longName") or info.get("shortName", symbol),
        "exchange":     _safe_str(info.get("exchange") or info.get("fullExchangeName")),
        "currency":     _safe_str(info.get("currency"), default="USD"),
        "quote_type":   _safe_str(info.get("quoteType")),

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

    # ── Supply chain enrichment ───────────────────────────────────────────────
    sc_data       = SUPPLY_CHAIN.get(symbol, {})
    suppliers_raw = sc_data.get("suppliers", [])
    customers_raw = sc_data.get("customers", [])

    all_chain_syms = list({e["symbol"] for e in suppliers_raw + customers_raw + [{"symbol": s} for s in peer_syms]})

    quotes: dict[str, dict] = await loop.run_in_executor(
        _executor, _fetch_batch_info_sync, all_chain_syms
    )

    suppliers = [_fmt_supply_chain_entry(e, quotes.get(e["symbol"])) for e in suppliers_raw]
    customers = [_fmt_supply_chain_entry(e, quotes.get(e["symbol"])) for e in customers_raw]

    peers = []
    for ps in peer_syms:
        if ps == symbol:
            continue
        q = quotes.get(ps, {})
        peers.append({
            "symbol": ps,
            "name": q.get("name", ps),
            "price": q.get("price"),
            "market_cap": q.get("market_cap"),
            "sector": q.get("sector"),
            "industry": q.get("industry"),
            "relationship": "peer",
        })

    alternative_data = await loop.run_in_executor(
        _executor,
        get_alternative_signal,
        symbol,
    )

    options_chain = await loop.run_in_executor(
        _executor,
        _fetch_options_chain_sync,
        symbol,
    )

    # Compute buy/sell signal
    buy_sell_signal = _compute_buy_sell_signal(info, alternative_data, options_chain)

    return {
        **company_info,
        "suppliers": suppliers,
        "customers": customers,
        "peers": peers,
        "has_supply_chain_data": bool(sc_data),
        "alternative_data": alternative_data,
        "options_chain": options_chain,
        "buy_sell_signal": buy_sell_signal,
    }
