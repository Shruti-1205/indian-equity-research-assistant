"""Macro agent: reads FRED series from DuckDB and flags risk-off conditions."""
from __future__ import annotations

from src.agents.state import AgentState, MacroContext
from src.data.db import get_conn


def _latest_on_or_before(con, series: str, date: str) -> tuple | None:
    return con.execute("""
        SELECT date, value FROM macro
        WHERE series = ? AND date <= CAST(? AS DATE)
        ORDER BY date DESC LIMIT 1
    """, [series, date]).fetchone()


def _value_n_days_back(con, series: str, date: str, n: int) -> float | None:
    row = con.execute("""
        SELECT value FROM macro
        WHERE series = ? AND date <= CAST(? AS DATE)
        ORDER BY date DESC LIMIT 1 OFFSET ?
    """, [series, date, n]).fetchone()
    return row[0] if row else None


def _vix_20d_avg(con, date: str) -> float | None:
    row = con.execute("""
        SELECT AVG(value) FROM (
          SELECT value FROM macro WHERE series = 'US_VIX' AND date <= CAST(? AS DATE)
          ORDER BY date DESC LIMIT 20
        )
    """, [date]).fetchone()
    return row[0] if row else None


def macro_agent(state: AgentState) -> dict:
    date = state["query_date"]
    con = get_conn()
    notes: list[str] = []

    def _latest(s):
        r = _latest_on_or_before(con, s, date)
        return r[1] if r else None

    crude = _latest("CRUDE_WTI")
    crude_prev = _value_n_days_back(con, "CRUDE_WTI", date, 1)
    crude_chg = None
    if crude is not None and crude_prev and crude_prev != 0:
        crude_chg = round((crude / crude_prev - 1) * 100, 2)

    vix = _latest("US_VIX")
    vix_avg = _vix_20d_avg(con, date)
    usd_inr = _latest("USD_INR")
    us_10y = _latest("US_10Y")
    dxy = _latest("DXY_BROAD")

    risk_off = False
    if vix is not None and vix_avg is not None and vix >= 1.2 * vix_avg:
        risk_off = True
        notes.append(f"VIX {vix:.1f} is elevated vs 20d avg {vix_avg:.1f}")
    if crude_chg is not None and abs(crude_chg) >= 2:
        direction = "rose" if crude_chg > 0 else "fell"
        notes.append(f"crude {direction} {abs(crude_chg):.1f}% dod")
    if us_10y is not None and us_10y >= 4.5:
        notes.append(f"US 10Y at {us_10y:.2f}% is restrictive — EM headwind")

    con.close()

    ctx: MacroContext = {
        "date": date,
        "crude_wti": crude,
        "crude_1d_chg_pct": crude_chg,
        "vix": vix,
        "vix_20d_avg": round(vix_avg, 2) if vix_avg else None,
        "usd_inr": usd_inr,
        "us_10y": us_10y,
        "dxy": dxy,
        "risk_off": risk_off,
        "notes": notes,
    }
    return {"macro": ctx}


if __name__ == "__main__":
    import json
    print(json.dumps(macro_agent({"symbol": "ANY", "query_date": "2026-04-13"}),
                     indent=2, default=str))
