"""LangGraph orchestration: user query → 4 parallel data agents → synthesis.

Shape:
              ┌── price_agent ──┐
   START ──┬──┤                 ├── synthesis ── END
           ├──┤── event_agent ──┤
           ├──┤── flow_agent  ──┤
           └──┤── macro_agent ──┘

All four data agents run in parallel (via LangGraph's parallel-node pattern)
and their outputs merge into a shared AgentState before synthesis reads it.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.agents.state import AgentState
from src.agents.price_agent import price_agent
from src.agents.event_agent import event_agent
from src.agents.flow_agent import flow_agent
from src.agents.macro_agent import macro_agent
from src.agents.synthesis_agent import synthesis_agent
from src.agents.verifier_agent import verifier_agent


def _build_graph():
    g = StateGraph(AgentState)

    g.add_node("price_node", price_agent)
    g.add_node("event_node", event_agent)
    g.add_node("flow_node",  flow_agent)
    g.add_node("macro_node", macro_agent)
    g.add_node("synthesis_node", synthesis_agent)
    g.add_node("verify_node", verifier_agent)

    for n in ("price_node", "event_node", "flow_node", "macro_node"):
        g.add_edge(START, n)
        g.add_edge(n, "synthesis_node")

    g.add_edge("synthesis_node", "verify_node")
    g.add_edge("verify_node", END)
    return g.compile()


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph()
    return _GRAPH


def run(symbol: str, query_date: str, user_query: str = "") -> AgentState:
    """Run the full pipeline for a single stock on a single date."""
    initial: AgentState = {
        "symbol": symbol,
        "query_date": query_date,
        "user_query": user_query,
    }
    return get_graph().invoke(initial)


if __name__ == "__main__":
    import json
    out = run("EICHERMOT.NS", "2026-04-13")
    print("=" * 72)
    print(f"symbol:         {out.get('symbol')}")
    print(f"query_date:     {out.get('query_date')}")
    print(f"primary_driver: {out.get('primary_driver')}")
    print(f"confidence:     {out.get('confidence')}")
    print(f"citations:      {out.get('citations')}")
    print("-" * 72)
    print(out.get("explanation"))
    print("=" * 72)
