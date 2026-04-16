"""FastAPI wrapper around the multi-agent pipeline.

Run with:
  uvicorn src.api.main:app --reload --port 8000

Endpoints:
  GET  /health                      — liveness + data freshness
  POST /query                       — natural-language question → full pipeline
  POST /explain                     — structured symbol/date → full pipeline
  GET  /movers?date=YYYY-MM-DD      — biggest movers for a given date
  GET  /events/{symbol}?days=30     — recent BSE announcements for a stock
  GET  /macro/latest                — latest FRED values + 20d VIX avg
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Optional

os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import NIFTY50
from src.agents.graph import run as run_pipeline
from src.agents.orchestrator import orchestrate
from src.data.db import get_conn
from src.rag.chroma_store import query_events, stats as chroma_stats
from src.data.pdf_fetcher import cache_stats as pdf_stats

app = FastAPI(
    title="NSE Research Intelligence",
    description="Multi-agent AI for Indian equity research. Every claim sourced to "
                "primary data (NSE prices, BSE filings, FII/DII, FRED macro).",
    version="0.1.0",
)


# ─────────────────── Schemas ───────────────────

class QueryIn(BaseModel):
    text: str = Field(..., description="Free-form natural-language query.")


class ExplainIn(BaseModel):
    symbol: str
    query_date: str = Field(..., description="YYYY-MM-DD")
    user_query: str = ""


class ExplainOut(BaseModel):
    symbol: str
    query_date: str
    explanation: str
    primary_driver: str
    confidence: str
    citations: list[str]
    validation_ok: Optional[bool] = None
    unverified_claims: list[str] = []
    changes_made: bool = False
    evidence: dict[str, Any]


# ─────────────────── Health ───────────────────

@app.get("/health")
def health():
    con = get_conn()
    stats = {}
    for tbl in ("prices", "features", "fii_dii", "macro", "pdf_cache"):
        stats[tbl] = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    latest_price = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    con.close()
    return {
        "status": "ok",
        "latest_price_date": str(latest_price) if latest_price else None,
        "duckdb_rows": stats,
        "chroma_announcements": chroma_stats().get("count", 0),
        "pdf_cache": pdf_stats(),
    }


# ─────────────────── Query endpoints ───────────────────

def _state_to_out(state: dict) -> dict:
    return {
        "symbol": state.get("symbol"),
        "query_date": state.get("query_date"),
        "explanation": state.get("explanation", ""),
        "primary_driver": state.get("primary_driver", "unclear"),
        "confidence": state.get("confidence", "low"),
        "citations": state.get("citations", []),
        "validation_ok": state.get("validation_ok"),
        "unverified_claims": state.get("unverified_claims", []),
        "changes_made": bool(state.get("changes_made")),
        "evidence": {
            "price": state.get("price"),
            "events": (state.get("events") or {}).get("events", []),
            "flow": state.get("flow"),
            "macro": state.get("macro"),
        },
    }


@app.post("/query", response_model=ExplainOut)
def query(q: QueryIn):
    plan = orchestrate(q.text)
    if plan["intent"] != "explain_move" or not plan["symbol"]:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse into a stock query. Parsed plan: {plan}",
        )
    state = run_pipeline(plan["symbol"], plan["query_date"], plan["user_hint"])
    return _state_to_out(state)


@app.post("/explain", response_model=ExplainOut)
def explain(q: ExplainIn):
    if q.symbol not in NIFTY50:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol: {q.symbol}")
    state = run_pipeline(q.symbol, q.query_date, q.user_query)
    return _state_to_out(state)


# ─────────────────── Data endpoints ───────────────────

@app.get("/movers")
def movers(date: Optional[str] = None, n: int = 15):
    con = get_conn()
    if not date:
        date = str(con.execute("SELECT MAX(date) FROM features").fetchone()[0])
    df = con.execute("""
        SELECT f.symbol,
               ROUND(f.pct_change_1d, 2)     AS pct_1d,
               ROUND(f.pct_from_52w_high, 1) AS pct_52w_high,
               ROUND(f.vol_vs_20d_avg, 2)    AS vol_mult
        FROM features f
        WHERE f.date = CAST(? AS DATE) AND f.symbol NOT LIKE '^%'
        ORDER BY ABS(f.pct_change_1d) DESC
        LIMIT ?
    """, [date, n]).df()
    con.close()
    return {"date": date, "rows": df.to_dict(orient="records")}


@app.get("/events/{symbol}")
def events(symbol: str, days: int = 30, k: int = 10):
    rows = query_events(symbol=symbol, query="", days_back=days, k=k)
    return {"symbol": symbol, "days_back": days, "count": len(rows), "events": rows}


@app.get("/macro/latest")
def macro_latest():
    con = get_conn()
    df = con.execute("""
        WITH r AS (SELECT series, MAX(date) AS d FROM macro GROUP BY series)
        SELECT m.series, m.date, m.value
        FROM macro m JOIN r ON m.series = r.series AND m.date = r.d
        ORDER BY m.series
    """).df()
    con.close()
    return {"rows": df.to_dict(orient="records")}
