"""Price agent: reads price + feature + sector-index data from DuckDB.

No LLM call. Just structured context for the synthesis agent.
"""
from __future__ import annotations

from src.agents.state import AgentState, PriceContext
from src.data.db import get_conn
from config import STOCK_TO_SECTOR, SECTOR_INDICES


def _pct_between(con, symbol: str, date: str) -> float | None:
    row = con.execute("""
        WITH prior AS (
          SELECT close FROM prices
          WHERE symbol = ? AND date < CAST(? AS DATE)
          ORDER BY date DESC LIMIT 1
        )
        SELECT p.close, (SELECT close FROM prior) AS prev
        FROM prices p WHERE p.symbol = ? AND p.date = CAST(? AS DATE)
    """, [symbol, date, symbol, date]).fetchone()
    if not row or row[0] is None or row[1] is None or row[1] == 0:
        return None
    return round((row[0] / row[1] - 1) * 100, 3)


def price_agent(state: AgentState) -> dict:
    symbol = state["symbol"]
    date = state["query_date"]
    notes: list[str] = []

    con = get_conn()
    feat = con.execute("""
        SELECT pct_change_1d, pct_from_52w_high, pct_from_52w_low,
               dist_50dma_pct, dist_200dma_pct, vol_vs_20d_avg, vol_zscore_20d
        FROM features WHERE symbol = ? AND date = CAST(? AS DATE)
    """, [symbol, date]).fetchone()

    if feat is None:
        row = con.execute(
            "SELECT MAX(date) FROM features WHERE symbol = ? AND date <= CAST(? AS DATE)",
            [symbol, date],
        ).fetchone()
        effective = row[0] if row else None
        if effective:
            notes.append(f"no data for {date}; using most recent trading day {effective}")
            date = str(effective)
            feat = con.execute("""
                SELECT pct_change_1d, pct_from_52w_high, pct_from_52w_low,
                       dist_50dma_pct, dist_200dma_pct, vol_vs_20d_avg, vol_zscore_20d
                FROM features WHERE symbol = ? AND date = CAST(? AS DATE)
            """, [symbol, date]).fetchone()

    if feat is None:
        con.close()
        return {"price": PriceContext(
            symbol=symbol, date=date, notes=["no price data available for this symbol/date"],
        )}

    sector = STOCK_TO_SECTOR.get(symbol)
    sector_idx = SECTOR_INDICES.get(sector) if sector else None
    nifty_idx = SECTOR_INDICES["NIFTY50"]

    sector_ret = _pct_between(con, sector_idx, date) if sector_idx else None
    nifty_ret = _pct_between(con, nifty_idx, date)
    con.close()

    stock_ret = feat[0]
    move_vs_sector = (
        round(stock_ret - sector_ret, 2) if (stock_ret is not None and sector_ret is not None) else None
    )

    if sector:
        notes.append(f"sector={sector} ({sector_idx})")
    if stock_ret is not None and abs(stock_ret) >= 3:
        notes.append("move size >= 3%")
    if feat[5] is not None and feat[5] >= 1.5:
        notes.append(f"volume spike: {feat[5]:.2f}x 20d avg")
    if feat[1] is not None and feat[1] <= -20:
        notes.append(f"stock is {feat[1]:.1f}% off 52w high")

    ctx: PriceContext = {
        "symbol": symbol,
        "date": date,
        "pct_change_1d": stock_ret,
        "pct_from_52w_high": feat[1],
        "pct_from_52w_low": feat[2],
        "dist_50dma_pct": feat[3],
        "dist_200dma_pct": feat[4],
        "vol_vs_20d_avg": feat[5],
        "vol_zscore_20d": feat[6],
        "sector_return_pct": sector_ret,
        "nifty_return_pct": nifty_ret,
        "move_vs_sector_pct": move_vs_sector,
        "notes": notes,
    }
    return {"price": ctx}


if __name__ == "__main__":
    out = price_agent({"symbol": "EICHERMOT.NS", "query_date": "2026-04-13"})
    import json
    print(json.dumps(out, indent=2, default=str))
