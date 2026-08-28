"""End-to-end system diagnostic.

Runs a sequence of independent checks against each subsystem and reports
pass/fail with specific error details. Use this before demos to confirm
everything works.

  python -m scripts.diagnose
  python -m scripts.diagnose --verbose   (sets DEBUG=1)
"""
from __future__ import annotations

import argparse
import os
import traceback


def _header(title: str):
    print()
    print(title)
    print("-" * len(title))


def _check(name: str, fn) -> bool:
    try:
        msg = fn()
        print(f"  [OK]  {name:42s}  {msg}")
        return True
    except Exception as e:
        print(f"  [FAIL] {name:42s}  {type(e).__name__}: {e}")
        if os.getenv("DEBUG"):
            traceback.print_exc()
        return False


def check_env():
    from config import (
        GROQ_API_KEY, FRED_API_KEY, ANTHROPIC_API_KEY,
        CEREBRAS_API_KEY, DAILY_USD_BUDGET,
    )
    lines = []
    lines.append(f"groq={'set' if GROQ_API_KEY else 'missing'}")
    lines.append(f"fred={'set' if FRED_API_KEY else 'missing'}")
    lines.append(f"anthropic={'set' if ANTHROPIC_API_KEY else 'missing'}")
    lines.append(f"cerebras={'set' if CEREBRAS_API_KEY else 'missing'}")
    lines.append(f"budget=${DAILY_USD_BUDGET}")
    return ", ".join(lines)


def check_duckdb():
    from src.data.db import get_conn
    con = get_conn()
    counts = {}
    for tbl in ("prices", "features", "fii_dii", "macro", "pdf_cache"):
        counts[tbl] = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    con.close()
    if counts["prices"] == 0:
        raise RuntimeError("prices table empty, run scripts.bootstrap")
    return f"prices={counts['prices']:,} features={counts['features']:,} pdf_cache={counts['pdf_cache']}"


def check_latest_date():
    from src.utils.dates import latest_trading_date
    d = latest_trading_date()
    return f"latest trading date in db = {d}"


def check_chroma():
    from src.rag.chroma_store import stats
    n = stats().get("count", 0)
    if n == 0:
        raise RuntimeError("chroma empty, run scripts.build_rag")
    return f"{n:,} announcements indexed"


def check_price_agent():
    from src.agents.price_agent import price_agent
    from src.utils.dates import latest_trading_date
    out = price_agent({"symbol": "RELIANCE.NS", "query_date": latest_trading_date()})
    p = out.get("price") or {}
    if p.get("pct_change_1d") is None:
        raise RuntimeError("no pct_change_1d returned")
    return f"RELIANCE moved {p['pct_change_1d']:+.2f}% (sector={p.get('sector_return_pct')})"


def check_event_agent():
    from src.agents.event_agent import event_agent
    from src.utils.dates import latest_trading_date
    out = event_agent({"symbol": "RELIANCE.NS", "query_date": latest_trading_date()})
    ev = out.get("events") or {}
    return f"{ev.get('event_count', 0)} events retrieved, has_material={ev.get('has_material')}"


def check_flow_agent():
    from src.agents.flow_agent import flow_agent
    from src.utils.dates import latest_trading_date
    out = flow_agent({"symbol": "RELIANCE.NS", "query_date": latest_trading_date()})
    fl = out.get("flow") or {}
    return f"fii_net={fl.get('fii_net_cr')} dii_net={fl.get('dii_net_cr')} days={fl.get('days_available')}"


def check_macro_agent():
    from src.agents.macro_agent import macro_agent
    from src.utils.dates import latest_trading_date
    out = macro_agent({"symbol": "RELIANCE.NS", "query_date": latest_trading_date()})
    m = out.get("macro") or {}
    return f"vix={m.get('vix')} crude={m.get('crude_wti')} us_10y={m.get('us_10y')}"


def check_chroma_query():
    """Verify that filtered semantic retrieval works end-to-end."""
    from src.rag.chroma_store import query_events
    rows = query_events(symbol="RELIANCE.NS", query="quarterly results",
                        days_back=365, k=5)
    if not rows:
        raise RuntimeError("no rows returned, corpus may be stale")
    return f"returned {len(rows)} hits, top distance={rows[0].get('distance', 'n/a')}"


def check_orchestrator():
    from src.agents.orchestrator import orchestrate
    plan = orchestrate("Why did RELIANCE drop today?")
    if plan.get("intent") != "explain_move":
        raise RuntimeError(f"expected explain_move, got {plan}")
    if plan.get("symbol") != "RELIANCE.NS":
        raise RuntimeError(f"expected RELIANCE.NS, got {plan.get('symbol')}")
    return f"parsed -> intent={plan['intent']} symbol={plan['symbol']}"


def check_llm_router():
    from src.agents.llm_client import call_llm
    r = call_llm(
        system="Reply with exactly: ok",
        user="respond",
        agent="orchestrator",
        max_tokens=5, temperature=0,
    )
    return f"routed to {r.provider}/{r.model}, {r.latency_ms}ms, tokens={r.input_tokens}+{r.output_tokens}"


def check_market_overview():
    from src.agents.handlers import market_overview
    from src.utils.dates import latest_trading_date
    out = market_overview(latest_trading_date())
    if out.get("error"):
        raise RuntimeError(out["error"])
    return f"summary length={len(out.get('summary', ''))}, {len(out.get('top_gainers', []))} gainers"


def check_stock_screen():
    from src.agents.handlers import stock_screen
    from src.utils.dates import latest_trading_date
    out = stock_screen(latest_trading_date(), "biggest movers")
    rows = out.get("rows", [])
    return f"{len(rows)} movers returned"


def check_search_filings():
    from src.agents.handlers import search_filings
    out = search_filings("dividend", days_back=60, k=5)
    hits = out.get("hits", [])
    return f"{len(hits)} filings matched"


def check_full_pipeline():
    from src.agents.graph import run
    from src.utils.dates import latest_trading_date
    state = run("RELIANCE.NS", latest_trading_date(), "")
    if not state.get("explanation"):
        raise RuntimeError("empty explanation")
    return (
        f"driver={state.get('primary_driver')} "
        f"conf={state.get('confidence')} "
        f"val_ok={state.get('validation_ok')}"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true",
                    help="Print full tracebacks and set DEBUG=1 globally.")
    ap.add_argument("--skip-llm", action="store_true",
                    help="Skip LLM-touching checks. Useful when quota is drained.")
    args = ap.parse_args()

    if args.verbose:
        os.environ["DEBUG"] = "1"

    results: list[bool] = []

    _header("Environment")
    results.append(_check("API keys and budget config", check_env))

    _header("Data layer")
    results.append(_check("DuckDB tables populated", check_duckdb))
    results.append(_check("Latest trading date", check_latest_date))
    results.append(_check("ChromaDB collection size", check_chroma))

    _header("Retrieval layer")
    results.append(_check("Filtered semantic query", check_chroma_query))

    _header("Data agents (no LLM)")
    results.append(_check("price_agent", check_price_agent))
    results.append(_check("event_agent", check_event_agent))
    results.append(_check("flow_agent", check_flow_agent))
    results.append(_check("macro_agent", check_macro_agent))

    if not args.skip_llm:
        _header("LLM layer")
        results.append(_check("orchestrator (Groq)", check_orchestrator))
        results.append(_check("LLM router single call", check_llm_router))

        _header("Query handlers")
        results.append(_check("market_overview", check_market_overview))
        results.append(_check("stock_screen", check_stock_screen))
        results.append(_check("search_filings", check_search_filings))

        _header("End-to-end pipeline")
        results.append(_check("full LangGraph run", check_full_pipeline))
    else:
        print("\n(LLM checks skipped per --skip-llm)")

    passed = sum(1 for r in results if r)
    total = len(results)
    print()
    print("=" * 60)
    if passed == total:
        print(f"ALL CHECKS PASSED ({passed} of {total}). System is ready.")
    else:
        print(f"{passed} of {total} checks passed. Address failures above.")
    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
