"""Event agent: hybrid RAG over BSE announcements for the target stock.

Strategy:
  1. Pull ALL announcements for the symbol in [query_date - 14d, query_date].
     A price move is most often caused by something filed in the past 2 weeks.
  2. If the user query has semantic content (e.g. "sales" for an auto stock),
     additionally run a semantic search over the last 60 days.
  3. Enrich top-K hits with full PDF text.
  4. Mark `has_material = True` if any event looks materially relevant
     (earnings result, guidance, buyback, divestment, M&A, downgrade, etc).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.agents.state import AgentState, EventContext
from src.data.pdf_fetcher import enrich_with_pdf_text
from src.rag.chroma_store import query_events

# Keywords that suggest an announcement is *probably* price-relevant.
MATERIAL_KEYWORDS = [
    "result", "earnings", "quarterly", "dividend", "buyback", "bonus",
    "acquisition", "merger", "demerger", "divestment", "stake sale",
    "guidance", "revise", "rating", "downgrade", "upgrade",
    "fund raising", "qip", "preferential", "board meeting",
    "bulk deal", "block deal", "resignation", "ceo", "cfo", "md ",
    "litigation", "penalty", "order", "notice", "raid",
    "sales volume", "dispatch", "production",
]


def _looks_material(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in MATERIAL_KEYWORDS)


def event_agent(state: AgentState) -> dict:
    symbol = state["symbol"]
    query_date = state.get("query_date") or datetime.now().strftime("%Y-%m-%d")
    user_query = state.get("user_query", "") or ""

    # Window: 14 days ending at query_date.
    end = datetime.fromisoformat(query_date).date()
    window_days = (datetime.now().date() - end).days + 14
    window_days = max(window_days, 14)

    # 1) Recent window (no semantic filter) — catches everything filed lately.
    recent = query_events(symbol=symbol, query="", days_back=window_days, k=8)

    # 2) Semantic (if user provided a query with real content).
    semantic: list[dict] = []
    if user_query.strip() and len(user_query.split()) >= 2:
        semantic = query_events(symbol=symbol, query=user_query, days_back=60, k=5)

    # Dedupe + keep only events on/before query_date.
    seen = set()
    merged: list[dict] = []
    for ev in recent + semantic:
        eid = ev.get("id")
        if not eid or eid in seen:
            continue
        d = ev.get("date", "")
        if d and d > query_date:
            continue
        seen.add(eid)
        merged.append(ev)

    merged.sort(key=lambda r: r.get("date", ""), reverse=True)
    top = merged[:5]

    # 3) Enrich with PDF text on-demand (cached in DuckDB).
    enrich_with_pdf_text(top, symbol_hint=symbol)

    # 4) Materiality flag.
    has_material = False
    for ev in top:
        combined = (ev.get("text", "") or "") + " " + (ev.get("full_text", "") or "")
        if _looks_material(combined):
            ev["material"] = True
            has_material = True
        else:
            ev["material"] = False

    return {"events": EventContext(
        events=top,
        event_count=len(top),
        has_material=has_material,
        note="" if top else "no announcements in the last 14 trading days",
    )}


if __name__ == "__main__":
    out = event_agent({"symbol": "EICHERMOT.NS", "query_date": "2026-04-13", "user_query": ""})
    ev = out["events"]
    print(f"Found {ev['event_count']} events (material={ev['has_material']}):")
    for e in ev["events"]:
        mark = "*" if e.get("material") else " "
        print(f" {mark} {e.get('date')} [{e.get('category','?')[:22]:22s}] {e.get('text','')[:80]}")
        if e.get("full_text"):
            print(f"      pdf: {e.get('pdf_status')} ({e.get('page_count')}p); first 200: {e['full_text'][:200].replace(chr(10),' ')}")
