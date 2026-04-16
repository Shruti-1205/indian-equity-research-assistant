"""Lightweight handlers for non explain_move intents.

Each handler is a pure Python function. It reads from DuckDB and optionally
ChromaDB, assembles compact evidence, asks the LLM for a short natural
language summary, and returns a dict suitable for display. No PDF fetching
and no agent fan-out, which keeps token use low.

Routing is done in scripts/ask.py based on the intent produced by
orchestrator.orchestrate().
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.agents.llm_client import call_llm
from src.data.db import get_conn
from src.rag.chroma_store import query_events
from src.utils.dates import effective_date, is_verbose
from config import STOCK_TO_SECTOR, SECTOR_INDICES


def _log(msg: str):
    if is_verbose():
        print(f"[handlers] {msg}")


# ────────────────────────────────────────────────────────────────────────
# market_overview
# ────────────────────────────────────────────────────────────────────────

MARKET_OVERVIEW_PROMPT = """You summarise one trading day in Indian equities
for a portfolio manager. You receive three evidence blocks: Nifty return,
top five movers on both sides, and sector performance. Write a tight four
to five sentence briefing. Every figure in your summary must appear in
the evidence. Cite with [price] for return and volume, [flow] for FII/DII.
No speculation. No em dashes. Do not repeat the same information across
sentences. Do not add a closing sentence that restates what was already said.
"""


def _nifty_ret(con, d: str) -> float | None:
    row = con.execute(
        """
        WITH prior AS (
          SELECT close FROM prices WHERE symbol = '^NSEI' AND date < CAST(? AS DATE)
          ORDER BY date DESC LIMIT 1
        )
        SELECT p.close, (SELECT close FROM prior)
        FROM prices p WHERE p.symbol = '^NSEI' AND p.date = CAST(? AS DATE)
        """, [d, d]).fetchone()
    if not row or row[0] is None or row[1] is None or row[1] == 0:
        return None
    return round((row[0] / row[1] - 1) * 100, 2)


def _sector_breakdown(con, d: str) -> list[dict]:
    df = con.execute(
        """
        SELECT symbol, pct_change_1d FROM features
        WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
        """, [d]).df()
    if df.empty:
        return []
    df["sector"] = df["symbol"].map(STOCK_TO_SECTOR).fillna("Other")
    g = df.groupby("sector")["pct_change_1d"].mean().reset_index()
    g.columns = ["sector", "avg_return"]
    g["avg_return"] = g["avg_return"].round(2)
    return g.sort_values("avg_return", ascending=False).to_dict(orient="records")


def market_overview(query_date: str, sector_hint: str = "") -> dict:
    query_date = effective_date(query_date)
    _log(f"market_overview resolved to {query_date}")
    con = get_conn()
    movers = con.execute(
        """
        SELECT symbol, ROUND(pct_change_1d, 2) AS pct_1d,
               ROUND(vol_vs_20d_avg, 2) AS vol_mult
        FROM features
        WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
        ORDER BY pct_change_1d DESC
        """, [query_date]).df()

    if movers.empty:
        con.close()
        return {"intent": "market_overview", "date": query_date,
                "error": "No data yet. Run scripts/bootstrap first."}

    top_up = movers.head(5).to_dict(orient="records")
    top_down = movers.tail(5).to_dict(orient="records")[::-1]
    nifty_ret = _nifty_ret(con, query_date)
    sectors = _sector_breakdown(con, query_date)

    flow = con.execute(
        "SELECT fii_net, dii_net FROM fii_dii WHERE date = CAST(? AS DATE)",
        [query_date]).fetchone()
    con.close()

    # Compact evidence block
    ev = [f"Date: {query_date}", f"Nifty 50 return: {nifty_ret}%"]
    ev.append("Top gainers: " + "; ".join(
        f"{r['symbol'].replace('.NS','')} +{r['pct_1d']}%" for r in top_up))
    ev.append("Top losers: " + "; ".join(
        f"{r['symbol'].replace('.NS','')} {r['pct_1d']}%" for r in top_down))
    ev.append("Sector averages: " + "; ".join(
        f"{s['sector']} {s['avg_return']:+.2f}%" for s in sectors))
    if flow:
        ev.append(f"FII net: Rs {flow[0]:+,.0f} cr | DII net: Rs {flow[1]:+,.0f} cr")

    r = call_llm(
        system=MARKET_OVERVIEW_PROMPT,
        user="\n".join(ev),
        agent="synthesis",
        json_mode=False,
        max_tokens=400,
        temperature=0.2,
    )

    return {
        "intent": "market_overview",
        "date": query_date,
        "summary": r.text.strip(),
        "nifty_return_pct": nifty_ret,
        "top_gainers": top_up,
        "top_losers": top_down,
        "sector_breakdown": sectors,
        "flow": {"fii_net_cr": flow[0] if flow else None,
                 "dii_net_cr": flow[1] if flow else None},
    }


# ────────────────────────────────────────────────────────────────────────
# stock_screen
# ────────────────────────────────────────────────────────────────────────

def stock_screen(query_date: str, filter_hint: str = "") -> dict:
    """Return a filtered table of stocks based on a simple criterion hint.

    Supported hints:
      near_52w_high   : stocks within 3pp of their 52-week high
      near_52w_low    : stocks within 3pp of their 52-week low
      volume_spike    : volume >= 2x 20 day average
      biggest_movers  : top 10 by absolute return
      below_50dma     : stocks at least 5 percent below 50 day moving average
      above_50dma     : stocks at least 5 percent above 50 day moving average
    (Default falls back to biggest_movers.)
    """
    h = (filter_hint or "").lower().strip()
    query_date = effective_date(query_date)
    _log(f"stock_screen resolved to {query_date}, filter='{h}'")
    con = get_conn()

    if "52w_high" in h or "52-week high" in h:
        label = "Within 3 percent of 52 week high"
        df = con.execute(
            """
            SELECT symbol, ROUND(pct_change_1d, 2) AS pct_1d,
                   ROUND(pct_from_52w_high, 1) AS from_52w_high,
                   ROUND(vol_vs_20d_avg, 2) AS vol_mult
            FROM features
            WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
              AND pct_from_52w_high >= -3
            ORDER BY pct_from_52w_high DESC LIMIT 15
            """, [query_date]).df()
    elif "52w_low" in h or "52-week low" in h:
        label = "Within 3 percent of 52 week low"
        df = con.execute(
            """
            SELECT symbol, ROUND(pct_change_1d, 2) AS pct_1d,
                   ROUND(pct_from_52w_low, 1) AS from_52w_low,
                   ROUND(vol_vs_20d_avg, 2) AS vol_mult
            FROM features
            WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
              AND pct_from_52w_low <= 3 LIMIT 15
            """, [query_date]).df()
    elif "volume" in h:
        label = "Volume above 2x 20 day average"
        df = con.execute(
            """
            SELECT symbol, ROUND(pct_change_1d, 2) AS pct_1d,
                   ROUND(vol_vs_20d_avg, 2) AS vol_mult,
                   ROUND(pct_from_52w_high, 1) AS from_52w_high
            FROM features
            WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
              AND vol_vs_20d_avg >= 2
            ORDER BY vol_vs_20d_avg DESC LIMIT 15
            """, [query_date]).df()
    elif "below" in h and "dma" in h:
        label = "At least 5 percent below 50 day moving average"
        df = con.execute(
            """
            SELECT symbol, ROUND(pct_change_1d, 2) AS pct_1d,
                   ROUND(dist_50dma_pct, 1) AS dist_50dma,
                   ROUND(vol_vs_20d_avg, 2) AS vol_mult
            FROM features
            WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
              AND dist_50dma_pct <= -5
            ORDER BY dist_50dma_pct LIMIT 15
            """, [query_date]).df()
    elif "above" in h and "dma" in h:
        label = "At least 5 percent above 50 day moving average"
        df = con.execute(
            """
            SELECT symbol, ROUND(pct_change_1d, 2) AS pct_1d,
                   ROUND(dist_50dma_pct, 1) AS dist_50dma,
                   ROUND(vol_vs_20d_avg, 2) AS vol_mult
            FROM features
            WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
              AND dist_50dma_pct >= 5
            ORDER BY dist_50dma_pct DESC LIMIT 15
            """, [query_date]).df()
    else:
        label = "Biggest movers today"
        df = con.execute(
            """
            SELECT symbol, ROUND(pct_change_1d, 2) AS pct_1d,
                   ROUND(vol_vs_20d_avg, 2) AS vol_mult,
                   ROUND(pct_from_52w_high, 1) AS from_52w_high
            FROM features
            WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
            ORDER BY ABS(pct_change_1d) DESC LIMIT 15
            """, [query_date]).df()

    con.close()

    result: dict[str, Any] = {
        "intent": "stock_screen",
        "filter_label": label,
        "date": query_date,
        "rows": df.to_dict(orient="records"),
    }
    if df.empty:
        result["summary"] = f"No stocks matched the criterion '{label}' on {query_date}."
        return result

    # Short LLM narrative on the filtered set (single cheap call).
    ev = f"Criterion: {label}\nDate: {query_date}\nMatches:\n" + df.to_string(index=False)
    r = call_llm(
        system=("You write a two sentence summary of a stock screen result for "
                "a portfolio manager. State the number of matches and the most "
                "notable one with its metric. Cite only figures present in the "
                "evidence. No em dashes."),
        user=ev,
        agent="synthesis",
        max_tokens=180,
        temperature=0.2,
    )
    result["summary"] = r.text.strip()
    return result


# ────────────────────────────────────────────────────────────────────────
# search_filings
# ────────────────────────────────────────────────────────────────────────

def search_filings(topic: str, symbol: str | None = None,
                   days_back: int = 30, k: int = 8) -> dict:
    """Semantic search across the BSE filings corpus.

    If a specific symbol is given, the search is restricted to that stock.
    Otherwise it scans all stocks in the watchlist.
    """
    topic = (topic or "").strip() or "material announcement"

    if symbol:
        hits = query_events(symbol=symbol, query=topic,
                            days_back=days_back, k=k)
    else:
        # Cross-symbol search. Use col.get to pull recent docs and their
        # stored embeddings, score with pure numpy. Avoids HNSW ef_search
        # limit entirely and is fast because Chroma caches the vectors.
        from datetime import datetime as _dt
        from src.rag.chroma_store import get_collection, _encode_query
        import numpy as np

        col = get_collection()
        cutoff = _dt.fromordinal(
            _dt.now().date().toordinal() - days_back
        ).strftime("%Y-%m-%d")
        watchlist = list(STOCK_TO_SECTOR.keys())
        got = col.get(
            where={"symbol": {"$in": watchlist}},
            limit=20000,
            include=["metadatas", "documents", "embeddings"],
        )

        q_vec = _encode_query(topic)
        candidates = []
        for i, _id in enumerate(got["ids"]):
            meta = got["metadatas"][i]
            if meta.get("date", "") < cutoff:
                continue
            emb = got["embeddings"][i]
            v = np.asarray(emb, dtype=np.float32)
            v = v / (np.linalg.norm(v) + 1e-9)
            candidates.append({
                "id": _id,
                "text": got["documents"][i],
                "distance": float(1 - np.dot(v, q_vec)),
                **meta,
            })
        candidates.sort(key=lambda r: r["distance"])
        hits = candidates[:k]

    if not hits:
        return {
            "intent": "search_filings",
            "topic": topic,
            "symbol": symbol,
            "hits": [],
            "summary": f"No filings matched the topic '{topic}' in the last {days_back} days.",
        }

    # Narrative summary
    ev_lines = []
    for h in hits:
        ev_lines.append(
            f"{h.get('date','')}  {h.get('symbol','')}  "
            f"[{h.get('category','')}]  {h.get('text','')[:160]}"
        )
    evidence = "Matches (date | stock | category | headline):\n" + "\n".join(ev_lines)

    r = call_llm(
        system=("You summarise a list of corporate filings for a research desk. "
                "Write three to five short lines grouping the filings by theme. "
                "Mention specific stock tickers. No em dashes. No speculation."),
        user=f"Topic: {topic}\nScope: {symbol or 'all watchlist'}\n\n{evidence}",
        agent="synthesis",
        max_tokens=320,
        temperature=0.2,
    )

    return {
        "intent": "search_filings",
        "topic": topic,
        "symbol": symbol,
        "hits": hits,
        "summary": r.text.strip(),
    }
