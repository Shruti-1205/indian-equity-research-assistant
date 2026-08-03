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
#   2. Cerebras Llama 3.3 70B (free, 10x Groq quota)       — if CEREBRAS_API_KEY set
#   3. Groq Llama 3.3 70B   (free, small quota)             — always available if GROQ_API_KEY set
SYNTHESIS_PRIMARY_MODEL     = "claude-haiku-4-5-20251001"
# Cerebras free-tier accessible model (2026-Q2): Alibaba's Qwen 3 235B MoE
# (22B active params). Claude-tier quality, supports JSON mode, occasional
# queue_exceeded under load — handled by retry in llm_client._call_cerebras.
SYNTHESIS_CEREBRAS_MODEL    = "qwen-3-235b-a22b-instruct-2507"
SYNTHESIS_GROQ_MODEL        = "llama-3.3-70b-versatile"
# Back-compat alias used by older code paths.
SYNTHESIS_FALLBACK_MODEL    = SYNTHESIS_GROQ_MODEL

# Orchestrator + verifier: free Groq 8B — cheap, fast, and we already route
# via this model so we stay under free-tier quotas.
GROQ_MODEL      = "llama-3.3-70b-versatile"   # kept for backward compat
GROQ_FAST_MODEL = "llama-3.1-8b-instant"

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
