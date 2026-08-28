"""Central config: paths, watchlist, sector indices."""
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
CHROMA_DIR = ROOT / "chroma_db"
DATA_DIR.mkdir(exist_ok=True)
CHROMA_DIR.mkdir(exist_ok=True)

DUCKDB_PATH = DATA_DIR / "market.duckdb"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")

# Hard daily spend cap for paid APIs (USD). Enforced in src/agents/llm_client.py.
# Set to 0.0 to disable paid calls entirely (forces free Groq fallback).
try:
    DAILY_USD_BUDGET = float(os.getenv("DAILY_USD_BUDGET", "1.00"))
except ValueError:
    DAILY_USD_BUDGET = 1.00

# --- Model routing ---
# Synthesis routing order (first available wins):
#   1. Claude Haiku 4.5     (Anthropic, paid, best quality) — if ANTHROPIC_API_KEY set AND budget ok
#   2. Cerebras Qwen 3 235B (free, 10x Groq quota)         — if CEREBRAS_API_KEY set
#   3. Groq gpt-oss-120b    (free, small quota)             — always available if GROQ_API_KEY set
SYNTHESIS_PRIMARY_MODEL     = "claude-haiku-4-5-20251001"
# Cerebras free-tier accessible model (2026-Q2): Alibaba's Qwen 3 235B MoE
# (22B active params). Claude-tier quality, supports JSON mode, occasional
# queue_exceeded under load — handled by retry in llm_client._call_cerebras.
SYNTHESIS_CEREBRAS_MODEL    = "qwen-3-235b-a22b-instruct-2507"
SYNTHESIS_GROQ_MODEL        = "openai/gpt-oss-120b"
# Back-compat alias used by older code paths.
SYNTHESIS_FALLBACK_MODEL    = SYNTHESIS_GROQ_MODEL

# Orchestrator + verifier: the small free Groq model — cheap, fast, and we
# already route via this model so we stay under free-tier quotas.
#
# Both support JSON mode, which the orchestrator and verifier depend on.
# Check `client.models.list()` before changing these — providers retire model
# ids, and a stale one fails at call time rather than at import.
GROQ_MODEL      = "openai/gpt-oss-120b"   # kept for backward compat
GROQ_FAST_MODEL = "openai/gpt-oss-20b"

# Watchlist covers Nifty 100 (Nifty 50 plus Nifty Next 50).
# yfinance uses the .NS suffix for NSE symbols.
#
# Two symbols changed under us and started 404ing on Yahoo:
#   LTIM -> LTM      LTIMindtree rebranded to LTM Ltd, symbol changed 2026-02-27.
#   TATAMOTORS       demerged. The original entity was renamed Tata Motors
#                    Passenger Vehicles (TMPV, keeps BSE 500570 and the full
#                    price history); the carved-out CV business listed
#                    2025-11-12 as TMCV (BSE 544569) and took the Tata Motors
#                    Ltd name. Both are tracked, so the old TATAMOTORS exposure
#                    stays covered across the split.
NIFTY50 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "TITAN.NS", "BAJFINANCE.NS", "NESTLEIND.NS", "HCLTECH.NS", "WIPRO.NS",
    "ULTRACEMCO.NS", "ADANIENT.NS", "POWERGRID.NS", "NTPC.NS", "M&M.NS",
    "TMPV.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "COALINDIA.NS", "ONGC.NS",
    "TECHM.NS", "BAJAJFINSV.NS", "DRREDDY.NS", "CIPLA.NS", "GRASIM.NS",
    "HDFCLIFE.NS", "SBILIFE.NS", "BPCL.NS", "HEROMOTOCO.NS", "BAJAJ-AUTO.NS",
    "EICHERMOT.NS", "BRITANNIA.NS", "DIVISLAB.NS", "INDUSINDBK.NS", "APOLLOHOSP.NS",
    "HINDALCO.NS", "ADANIPORTS.NS", "TATACONSUM.NS", "UPL.NS", "LTM.NS",
]

NIFTY_NEXT_50 = [
    "ADANIGREEN.NS", "ADANIPOWER.NS", "AMBUJACEM.NS", "BANKBARODA.NS", "BERGEPAINT.NS",
    "BEL.NS", "BOSCHLTD.NS", "CANBK.NS", "CHOLAFIN.NS", "COLPAL.NS",
    "DABUR.NS", "DMART.NS", "DLF.NS", "DIXON.NS", "GAIL.NS",
    "GODREJCP.NS", "HAL.NS", "HAVELLS.NS", "HDFCAMC.NS", "ICICIGI.NS",
    "IOC.NS", "INDHOTEL.NS", "INDUSTOWER.NS", "IRCTC.NS", "IRFC.NS",
    "JINDALSTEL.NS", "JSWENERGY.NS", "LICI.NS", "MARICO.NS", "NAUKRI.NS",
    "NMDC.NS", "PIDILITIND.NS", "PNB.NS", "PFC.NS", "RECLTD.NS",
    "SBICARD.NS", "SHREECEM.NS", "SIEMENS.NS", "SRF.NS", "TORNTPHARM.NS",
    "TRENT.NS", "TVSMOTOR.NS", "UNITDSPR.NS", "VEDL.NS", "VBL.NS",
    "ETERNAL.NS", "ZYDUSLIFE.NS", "LODHA.NS", "TATAPOWER.NS", "TMCV.NS",
]

NIFTY100 = NIFTY50 + NIFTY_NEXT_50

# Primary watchlist used throughout the codebase.
WATCHLIST = NIFTY100

SECTOR_INDICES = {
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "IT": "^CNXIT",
    "AUTO": "^CNXAUTO",
    "PHARMA": "^CNXPHARMA",
    "FMCG": "^CNXFMCG",
    "METAL": "^CNXMETAL",
    "ENERGY": "^CNXENERGY",
    "REALTY": "^CNXREALTY",
    "FINSRV": "^CNXFIN",
}

STOCK_TO_SECTOR = {
    # Energy and Utilities
    "RELIANCE.NS": "ENERGY", "ONGC.NS": "ENERGY", "BPCL.NS": "ENERGY",
    "COALINDIA.NS": "ENERGY", "NTPC.NS": "ENERGY", "POWERGRID.NS": "ENERGY",
    "IOC.NS": "ENERGY", "GAIL.NS": "ENERGY", "TATAPOWER.NS": "ENERGY",
    "ADANIPOWER.NS": "ENERGY", "ADANIGREEN.NS": "ENERGY", "JSWENERGY.NS": "ENERGY",
    # IT
    "TCS.NS": "IT", "INFY.NS": "IT", "HCLTECH.NS": "IT",
    "WIPRO.NS": "IT", "TECHM.NS": "IT", "LTM.NS": "IT",
    # Banks
    "HDFCBANK.NS": "BANKNIFTY", "ICICIBANK.NS": "BANKNIFTY", "SBIN.NS": "BANKNIFTY",
    "KOTAKBANK.NS": "BANKNIFTY", "AXISBANK.NS": "BANKNIFTY", "INDUSINDBK.NS": "BANKNIFTY",
    "BANKBARODA.NS": "BANKNIFTY", "PNB.NS": "BANKNIFTY", "CANBK.NS": "BANKNIFTY",
    # Financial Services (non-bank)
    "BAJFINANCE.NS": "FINSRV", "BAJAJFINSV.NS": "FINSRV", "HDFCLIFE.NS": "FINSRV",
    "SBILIFE.NS": "FINSRV", "CHOLAFIN.NS": "FINSRV", "HDFCAMC.NS": "FINSRV",
    "ICICIGI.NS": "FINSRV", "ICICIPRULI.NS": "FINSRV", "LICI.NS": "FINSRV",
    "SBICARD.NS": "FINSRV", "PFC.NS": "FINSRV", "RECLTD.NS": "FINSRV",
    "IRFC.NS": "FINSRV",
    # Auto
    "MARUTI.NS": "AUTO", "TMPV.NS": "AUTO", "TMCV.NS": "AUTO", "M&M.NS": "AUTO",
    "HEROMOTOCO.NS": "AUTO", "BAJAJ-AUTO.NS": "AUTO", "EICHERMOT.NS": "AUTO",
    "TVSMOTOR.NS": "AUTO", "BOSCHLTD.NS": "AUTO",
    # Pharma
    "SUNPHARMA.NS": "PHARMA", "DRREDDY.NS": "PHARMA", "CIPLA.NS": "PHARMA",
    "DIVISLAB.NS": "PHARMA", "APOLLOHOSP.NS": "PHARMA", "TORNTPHARM.NS": "PHARMA",
    "ZYDUSLIFE.NS": "PHARMA",
    # FMCG
    "HINDUNILVR.NS": "FMCG", "ITC.NS": "FMCG", "NESTLEIND.NS": "FMCG",
    "BRITANNIA.NS": "FMCG", "TATACONSUM.NS": "FMCG", "DABUR.NS": "FMCG",
    "MARICO.NS": "FMCG", "COLPAL.NS": "FMCG", "GODREJCP.NS": "FMCG",
    "UNITDSPR.NS": "FMCG", "VBL.NS": "FMCG",
    # Metals
    "TATASTEEL.NS": "METAL", "JSWSTEEL.NS": "METAL", "HINDALCO.NS": "METAL",
    "JINDALSTEL.NS": "METAL", "NMDC.NS": "METAL", "VEDL.NS": "METAL",
    # Realty
    "DLF.NS": "REALTY", "LODHA.NS": "REALTY",
    # Broad Nifty (catch-all for large-caps without a clean sector index)
    "BHARTIARTL.NS": "NIFTY50", "LT.NS": "NIFTY50", "ASIANPAINT.NS": "NIFTY50",
    "TITAN.NS": "NIFTY50", "ULTRACEMCO.NS": "NIFTY50", "GRASIM.NS": "NIFTY50",
    "ADANIENT.NS": "NIFTY50", "ADANIPORTS.NS": "NIFTY50", "UPL.NS": "NIFTY50",
    "AMBUJACEM.NS": "NIFTY50", "BERGEPAINT.NS": "NIFTY50", "BEL.NS": "NIFTY50",
    "DMART.NS": "NIFTY50", "DIXON.NS": "NIFTY50", "HAL.NS": "NIFTY50",
    "HAVELLS.NS": "NIFTY50", "INDHOTEL.NS": "NIFTY50", "INDUSTOWER.NS": "NIFTY50",
    "IRCTC.NS": "NIFTY50", "NAUKRI.NS": "NIFTY50", "PIDILITIND.NS": "NIFTY50",
    "SHREECEM.NS": "NIFTY50", "SIEMENS.NS": "NIFTY50", "SRF.NS": "NIFTY50",
    "TRENT.NS": "NIFTY50", "ETERNAL.NS": "NIFTY50",
}


# --- Display names -----------------------------------------------------------
# The UI shows company names rather than tickers. Sourced from BSE's SLONGNAME
# (already carried on every announcement), with the " Ltd"/" Limited" suffix
# trimmed so they fit chart axes.
COMPANY_NAMES = {
    "RELIANCE.NS":   "Reliance Industries",
    "TCS.NS":        "Tata Consultancy Services",
    "HDFCBANK.NS":   "HDFC Bank",
    "INFY.NS":       "Infosys",
    "ICICIBANK.NS":  "ICICI Bank",
    "HINDUNILVR.NS": "Hindustan Unilever",
    "SBIN.NS":       "State Bank of India",
    "BHARTIARTL.NS": "Bharti Airtel",
    "ITC.NS":        "ITC",
    "KOTAKBANK.NS":  "Kotak Mahindra Bank",
    "LT.NS":         "Larsen & Toubro",
    "AXISBANK.NS":   "AXIS Bank",
    "ASIANPAINT.NS": "Asian Paints",
    "MARUTI.NS":     "Maruti Suzuki India",
    "SUNPHARMA.NS":  "Sun Pharmaceutical Industries",
    "TITAN.NS":      "Titan Company",
    "BAJFINANCE.NS": "Bajaj Finance",
    "NESTLEIND.NS":  "Nestle India",
    "HCLTECH.NS":    "HCL Technologies",
    "WIPRO.NS":      "Wipro",
    "ULTRACEMCO.NS": "UltraTech Cement",
    "ADANIENT.NS":   "Adani Enterprises",
    "POWERGRID.NS":  "Power Grid Corporation of India",
    "NTPC.NS":       "NTPC",
    "M&M.NS":        "Mahindra & Mahindra",
    "TMPV.NS":       "Tata Motors Passenger Vehicles",
    "TATASTEEL.NS":  "Tata Steel",
    "JSWSTEEL.NS":   "JSW Steel",
    "COALINDIA.NS":  "Coal India",
    "ONGC.NS":       "Oil and Natural Gas Corporation",
    "TECHM.NS":      "Tech Mahindra",
    "BAJAJFINSV.NS": "Bajaj Finserv",
    "DRREDDY.NS":    "Dr Reddys Laboratories",
    "CIPLA.NS":      "Cipla",
    "GRASIM.NS":     "Grasim Industries",
    "HDFCLIFE.NS":   "HDFC Life Insurance Company",
    "SBILIFE.NS":    "SBI Life Insurance Company",
    "BPCL.NS":       "Bharat Petroleum Corporation",
    "HEROMOTOCO.NS": "Hero MotoCorp",
    "BAJAJ-AUTO.NS": "Bajaj Auto",
    "EICHERMOT.NS":  "Eicher Motors",
    "BRITANNIA.NS":  "Britannia Industries",
    "DIVISLAB.NS":   "Divis Laboratories",
    "INDUSINDBK.NS": "Indusind Bank",
    "APOLLOHOSP.NS": "Apollo Hospitals Enterprise",
    "HINDALCO.NS":   "Hindalco Industries",
    "ADANIPORTS.NS": "Adani Ports and Special Economic Zone",
    "TATACONSUM.NS": "Tata Consumer Products",
    "UPL.NS":        "UPL",
    "LTM.NS":        "LTM",
    "ADANIGREEN.NS": "Adani Green Energy",
    "ADANIPOWER.NS": "Adani Power",
    "AMBUJACEM.NS":  "Ambuja Cements",
    "BANKBARODA.NS": "Bank of Baroda",
    "BERGEPAINT.NS": "Berger Paints India",
    "BEL.NS":        "Bharat Electronics",
    "BOSCHLTD.NS":   "Bosch",
    "CANBK.NS":      "Canara Bank",
    "CHOLAFIN.NS":   "Cholamandalam Investment and Finance Company",
    "COLPAL.NS":     "Colgate Palmolive (India)",
    "DABUR.NS":      "Dabur India",
    "DMART.NS":      "Avenue Supermarts",
    "DLF.NS":        "DLF",
    "DIXON.NS":      "Dixon Technologies (India)",
    "GAIL.NS":       "Gail (India)",
    "GODREJCP.NS":   "Godrej Consumer Products",
    "HAL.NS":        "Hindustan Aeronautics",
    "HAVELLS.NS":    "Havells India",
    "HDFCAMC.NS":    "HDFC Asset Management Company",
    "ICICIGI.NS":    "ICICI Lombard General Insurance",
    "IOC.NS":        "Indian Oil Corporation",
    "INDHOTEL.NS":   "Indian Hotels Company",
    "INDUSTOWER.NS": "Indus Towers",
    "IRCTC.NS":      "Indian Railway Catering and Tourism Corporation",
    "IRFC.NS":       "Indian Railway Finance Corporation",
    "JINDALSTEL.NS": "Jindal Steel",
    "JSWENERGY.NS":  "JSW Energy",
    "LICI.NS":       "Life Insurance Corporation of India",
    "MARICO.NS":     "Marico",
    "NAUKRI.NS":     "Info Edge (India)",
    "NMDC.NS":       "NMDC",
    "PIDILITIND.NS": "Pidilite Industries",
    "PNB.NS":        "Punjab National Bank",
    "PFC.NS":        "Power Finance Corporation",
    "RECLTD.NS":     "REC",
    "SBICARD.NS":    "SBI Cards and Payment Services",
    "SHREECEM.NS":   "Shree Cement",
    "SIEMENS.NS":    "Siemens",
    "SRF.NS":        "SRF",
    "TORNTPHARM.NS": "Torrent Pharmaceuticals",
    "TRENT.NS":      "Trent",
    "TVSMOTOR.NS":   "TVS Motor Company",
    "UNITDSPR.NS":   "United Spirits",
    "VEDL.NS":       "Vedanta",
    "VBL.NS":        "Varun Beverages",
    "ETERNAL.NS":    "Eternal",
    "ZYDUSLIFE.NS":  "Zydus Lifesciences",
    "LODHA.NS":      "Lodha Developers",
    "TATAPOWER.NS":  "Tata Power Company",
    "TMCV.NS":       "Tata Motors",
}

INDEX_NAMES = {
    "^NSEI":       "Nifty 50",
    "^NSEBANK":    "Bank Nifty",
    "^CNXIT":      "Nifty IT",
    "^CNXAUTO":    "Nifty Auto",
    "^CNXPHARMA":  "Nifty Pharma",
    "^CNXFMCG":    "Nifty FMCG",
    "^CNXMETAL":   "Nifty Metal",
    "^CNXENERGY":  "Nifty Energy",
    "^CNXREALTY":  "Nifty Realty",
    "^CNXFIN":     "Nifty Financial Services",
}

# Readable labels for the sector keys used in STOCK_TO_SECTOR / SECTOR_INDICES.
SECTOR_LABELS = {
    "NIFTY50":   "Nifty 50",
    "BANKNIFTY": "Banks",
    "IT":        "IT",
    "AUTO":      "Auto",
    "PHARMA":    "Pharma",
    "FMCG":      "FMCG",
    "METAL":     "Metals",
    "ENERGY":    "Energy",
    "REALTY":    "Realty",
    "FINSRV":    "Financial Services",
}


def display_name(symbol: str) -> str:
    """Company or index name for `symbol`, falling back to the bare ticker.

    Falling back rather than raising matters: a symbol can enter the database
    before it is added here (a new listing, or a ticker renamed mid-quarter),
    and a missing label should degrade to the ticker instead of breaking the
    page that renders it.
    """
    if symbol in COMPANY_NAMES:
        return COMPANY_NAMES[symbol]
    if symbol in INDEX_NAMES:
        return INDEX_NAMES[symbol]
    return symbol.replace(".NS", "")


def sector_label(key: str) -> str:
    """Readable label for a sector key, falling back to the key itself."""
    return SECTOR_LABELS.get(key, key)


def short_name(symbol: str, limit: int = 26) -> str:
    """`display_name` clipped for chart axes, where a long label steals plot width.

    Some constituents have genuinely long legal names ("Indian Railway Catering
    and Tourism Corporation" is 47 characters), enough to squeeze a horizontal
    bar chart. Clips on a word boundary so the result still reads as a name.
    Tables and headings should use `display_name` instead.
    """
    name = display_name(symbol)
    if len(name) <= limit:
        return name
    cut = name[:limit].rsplit(" ", 1)[0]
    # A single long word leaves nothing to cut back to; clip it directly.
    if not cut:
        cut = name[:limit]
    return cut + "…"
