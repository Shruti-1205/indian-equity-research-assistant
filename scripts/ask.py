"""Natural language CLI for the research system.

Supported query types:
  1. explain_move      why did one stock move on one day
  2. market_overview   how markets or a sector did on a day
  3. stock_screen      filter stocks by a numeric criterion
  4. search_filings    semantic search across corporate filings

Examples:
  python -m scripts.ask "Why did Eichermot drop on April 13?"
  python -m scripts.ask "How did the market do today?"
  python -m scripts.ask "Which stocks hit 52 week highs today?"
  python -m scripts.ask "Stocks with 3x volume spike today"
  python -m scripts.ask "Any bonus share announcements this month?"
  python -m scripts.ask "What did Reliance say about renewables?"
"""
from __future__ import annotations

import sys
import time

from src.agents.orchestrator import orchestrate
from src.agents.graph import run
from src.agents.handlers import market_overview, stock_screen, search_filings


def _section(title: str):
    print()
    print(title)
    print("-" * len(title))


def _fmt_pct(v, nd=2):
    return "n/a" if v is None else f"{v:+.{nd}f}%"


def _fmt_cr(v):
    return "n/a" if v is None else f"Rs {v:+,.0f} cr"


def _fmt_num(v, nd=2):
    if v is None:
        return "n/a"
    try:
        return f"{float(v):,.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


# ─────────── explain_move ───────────

def _render_explain_move(state: dict):
    symbol = state.get("symbol")
    date = state.get("query_date")
    _section(f"Summary for {symbol} on {date}")
    print(state.get("explanation", "No explanation generated."))

    _section("Verdict")
    driver = state.get("primary_driver", "unclear")
    conf = state.get("confidence", "low")
    print(f"Likely driver     : {driver}")
    print(f"Confidence        : {conf}")
    citations = state.get("citations") or []
    print(f"Sources cited     : {', '.join(citations) if citations else 'none'}")
    val_ok = state.get("validation_ok")
    if val_ok is True:
        print("Grounding check   : every figure in the summary matches source data.")
    elif val_ok is False:
        unv = state.get("unverified_claims", [])
        print(f"Grounding check   : unverified claims flagged and removed: {unv}")
    if state.get("changes_made"):
        removed = state.get("hallucinations_removed", [])
        print(f"Auto corrections  : {len(removed)} unsupported claim(s) redacted")

    _section("Evidence used")
    price = state.get("price") or {}
    if price:
        print("Price and volume:")
        print(f"  One day return       : {_fmt_pct(price.get('pct_change_1d'))}")
        print(f"  Sector index return  : {_fmt_pct(price.get('sector_return_pct'))}")
        print(f"  Nifty return         : {_fmt_pct(price.get('nifty_return_pct'))}")
        print(f"  Move vs sector       : {_fmt_pct(price.get('move_vs_sector_pct'))}")
        print(f"  Volume vs 20d avg    : {_fmt_num(price.get('vol_vs_20d_avg'))}x")

    events = (state.get("events") or {}).get("events", [])
    if events:
        print("\nBSE announcements considered:")
        for ev in events[:5]:
            flag = "[material] " if ev.get("material") else "           "
            print(f"  {flag}{ev.get('date')}  {ev.get('text','')[:100]}")

    flow = state.get("flow") or {}
    if flow.get("fii_net_cr") is not None:
        print("\nInstitutional flow:")
        print(f"  FII net : {_fmt_cr(flow.get('fii_net_cr'))}")
        print(f"  DII net : {_fmt_cr(flow.get('dii_net_cr'))}")

    macro = state.get("macro") or {}
    if macro.get("vix") is not None:
        print("\nGlobal macro:")
        print(f"  Crude oil WTI  : {_fmt_num(macro.get('crude_wti'))}")
        print(f"  US VIX         : {_fmt_num(macro.get('vix'))} "
              f"(20d avg {_fmt_num(macro.get('vix_20d_avg'))})")
        print(f"  US 10Y         : {_fmt_num(macro.get('us_10y'))}%")
        print(f"  Risk off       : {'yes' if macro.get('risk_off') else 'no'}")


# ─────────── market_overview ───────────

def _render_market_overview(r: dict):
    date = r.get("date")
    _section(f"Market overview for {date}")
    print(r.get("summary", ""))

    _section("Key figures")
    nifty = r.get("nifty_return_pct")
    print(f"Nifty 50 return  : {_fmt_pct(nifty)}")
    flow = r.get("flow") or {}
    print(f"FII net          : {_fmt_cr(flow.get('fii_net_cr'))}")
    print(f"DII net          : {_fmt_cr(flow.get('dii_net_cr'))}")

    _section("Top gainers")
    for row in r.get("top_gainers", []):
        sym = row["symbol"].replace(".NS", "")
        print(f"  {sym:15s}  {row['pct_1d']:+6.2f}%   vol {row['vol_mult']}x")

    _section("Top losers")
    for row in r.get("top_losers", []):
        sym = row["symbol"].replace(".NS", "")
        print(f"  {sym:15s}  {row['pct_1d']:+6.2f}%   vol {row['vol_mult']}x")

    _section("Sector leaderboard")
    for s in r.get("sector_breakdown", []):
        print(f"  {s['sector']:12s}  {s['avg_return']:+6.2f}%")


# ─────────── stock_screen ───────────

def _render_stock_screen(r: dict):
    _section(r.get("filter_label", "Stock screen"))
    print(r.get("summary", ""))
    print()
    rows = r.get("rows", [])
    if not rows:
        print("No matches.")
        return
    # Determine columns present
    cols = [k for k in ("symbol", "pct_1d", "vol_mult",
                        "from_52w_high", "from_52w_low",
                        "dist_50dma") if k in rows[0]]
    header = "  " + "  ".join(f"{c:>14s}" for c in cols)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in rows:
        line = "  " + "  ".join(
            f"{row[c]:>14}" if not isinstance(row[c], float)
            else f"{row[c]:>14.2f}" for c in cols
        )
        print(line)


# ─────────── search_filings ───────────

def _render_search_filings(r: dict):
    _section(f"Filings matching '{r.get('topic')}'")
    print(r.get("summary", ""))
    print()
    hits = r.get("hits", [])
    if not hits:
        return
    _section("Top matches")
    for h in hits:
        dist = h.get("distance")
        score = f" score {1 - dist:.2f}" if dist is not None else ""
        print(f"  {h.get('date')}  {h.get('symbol','')}  [{h.get('category','')}]"
              f"{score}")
        print(f"    {h.get('text','')[:140]}")


# ─────────── entry point ───────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.ask \"Your question\"")
        sys.exit(1)

    user_query = " ".join(sys.argv[1:])
    t0 = time.time()
    print(f"Query: {user_query}")

    plan = orchestrate(user_query)
    intent = plan.get("intent")
    print(f"Routing to: {intent}")

    if intent == "explain_move":
        if not plan.get("symbol"):
            print("\nCould not identify a stock. "
                  "Try: \"Why did RELIANCE drop today?\" or \"EICHERMOT.NS 2026-04-13\"")
            return
        state = run(plan["symbol"], plan["query_date"], plan.get("user_hint", ""))
        _render_explain_move(state)

    elif intent == "market_overview":
        r = market_overview(plan["query_date"], plan.get("user_hint", ""))
        if "error" in r:
            print(r["error"])
            return
        _render_market_overview(r)

    elif intent == "stock_screen":
        r = stock_screen(plan["query_date"], plan.get("user_hint", ""))
        _render_stock_screen(r)

    elif intent == "search_filings":
        r = search_filings(plan.get("user_hint", ""),
                           symbol=plan.get("symbol"))
        _render_search_filings(r)

    else:
        print("\nI could not understand this query. Supported types:")
        print("  Why did STOCK move on DATE       (explain a single stock)")
        print("  How did the market do today      (market overview)")
        print("  Which stocks hit 52 week highs   (stock screen)")
        print("  Any bonus share announcements    (search filings)")

    print(f"\n(completed in {time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
