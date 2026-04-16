"""Flow agent: FII/DII context from DuckDB. Degrades gracefully when history is short."""
from __future__ import annotations

from src.agents.state import AgentState, FlowContext
from src.data.db import get_conn


def flow_agent(state: AgentState) -> dict:
    date = state["query_date"]
    con = get_conn()

    row = con.execute(
        "SELECT date, fii_net, dii_net FROM fii_dii WHERE date = CAST(? AS DATE)",
        [date],
    ).fetchone()

    if row is None:
        row = con.execute(
            "SELECT date, fii_net, dii_net FROM fii_dii WHERE date <= CAST(? AS DATE) ORDER BY date DESC LIMIT 1",
            [date],
        ).fetchone()

    days = con.execute("SELECT COUNT(*) FROM fii_dii").fetchone()[0]

    trend_5d = None
    if row and days >= 5:
        trend_5d = con.execute("""
            SELECT SUM(fii_net) FROM (
              SELECT fii_net FROM fii_dii WHERE date <= CAST(? AS DATE) ORDER BY date DESC LIMIT 5
            )
        """, [str(row[0])]).fetchone()[0]

    con.close()

    if row is None:
        return {"flow": FlowContext(
            date=date, days_available=days,
            note="no FII/DII data yet; accumulates daily from first refresh_macro run",
        )}

    ctx: FlowContext = {
        "date": str(row[0]),
        "fii_net_cr": row[1],
        "dii_net_cr": row[2],
        "fii_5d_trend_cr": trend_5d,
        "days_available": days,
    }
    if days < 5:
        ctx["note"] = f"only {days} day(s) of history; 5-day trend not yet available"
    elif row[1] is not None and abs(row[1]) >= 2000:
        ctx["note"] = f"FII net {row[1]:+.0f} cr is a sizeable single-day flow"
    return {"flow": ctx}


if __name__ == "__main__":
    import json
    out = flow_agent({"symbol": "ANY", "query_date": "2026-04-13"})
    print(json.dumps(out, indent=2, default=str))
