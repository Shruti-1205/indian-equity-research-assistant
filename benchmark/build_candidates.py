"""Generate candidate cases for the labeled benchmark with all evidence inline.

For each of the last N trading days we take the top K biggest movers and
assemble a compact single-line summary containing every signal the synthesis
agent would see. The resulting file is handed to an independent judge (Claude
Opus) who produces ground-truth driver labels.

Output: benchmark/candidates.csv, one row per (symbol, date) case.
Columns include price context, up to three material event headlines, flow and
macro context. All numeric values are 2dp rounded for readability.

Run with:
  python -m benchmark.build_candidates --days 7 --per_day 15
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from config import STOCK_TO_SECTOR, SECTOR_INDICES
from src.data.db import get_conn
from src.rag.chroma_store import query_events

OUT = Path(__file__).resolve().parent / "candidates.csv"

MATERIAL_KEYWORDS = (
    "result", "earnings", "quarterly", "dividend", "buyback", "bonus",
    "acquisition", "merger", "demerger", "divestment", "stake sale",
    "guidance", "rating", "downgrade", "upgrade", "bulk deal", "block deal",
    "fund raising", "qip", "preferential", "resignation",
    "sales volume", "dispatch", "production",
)


def _round(v, nd=2):
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def _sector_ret(con, symbol: str, date: str) -> float | None:
    sec = STOCK_TO_SECTOR.get(symbol)
    idx = SECTOR_INDICES.get(sec) if sec else None
    if not idx:
        return None
    row = con.execute("""
        WITH prior AS (
          SELECT close FROM prices WHERE symbol = ? AND date < CAST(? AS DATE)
          ORDER BY date DESC LIMIT 1
        )
        SELECT p.close, (SELECT close FROM prior)
        FROM prices p WHERE p.symbol = ? AND p.date = CAST(? AS DATE)
    """, [idx, date, idx, date]).fetchone()
    if not row or row[0] is None or row[1] is None or row[1] == 0:
        return None
    return _round((row[0] / row[1] - 1) * 100)


def _nifty_ret(con, date: str) -> float | None:
    row = con.execute("""
        WITH prior AS (
          SELECT close FROM prices WHERE symbol = '^NSEI' AND date < CAST(? AS DATE)
          ORDER BY date DESC LIMIT 1
        )
        SELECT p.close, (SELECT close FROM prior)
        FROM prices p WHERE p.symbol = '^NSEI' AND p.date = CAST(? AS DATE)
    """, [date, date]).fetchone()
    if not row or row[0] is None or row[1] is None or row[1] == 0:
        return None
    return _round((row[0] / row[1] - 1) * 100)


def _material_events(symbol: str, date: str, lookback: int = 5) -> list[dict]:
    out = []
    for e in query_events(symbol=symbol, query="", days_back=lookback + 2, k=12):
        if e.get("date", "") > date:
            continue
        blob = (e.get("text") or "") + " " + (e.get("category") or "")
        if any(k in blob.lower() for k in MATERIAL_KEYWORDS):
            out.append(e)
    return out[:3]


def _flow(con, date: str) -> tuple[float | None, float | None]:
    row = con.execute(
        "SELECT fii_net, dii_net FROM fii_dii WHERE date = CAST(? AS DATE)",
        [date],
    ).fetchone()
    if not row:
        return None, None
    return row[0], row[1]


def _macro(con, date: str) -> dict:
    out: dict = {}
    df = con.execute(
        "SELECT series, value FROM macro WHERE date = CAST(? AS DATE)", [date]
    ).df()
    for _, r in df.iterrows():
        out[r["series"]] = _round(r["value"])
    # VIX 20d avg
    avg = con.execute("""
        SELECT AVG(value) FROM (
          SELECT value FROM macro WHERE series = 'US_VIX' AND date <= CAST(? AS DATE)
          ORDER BY date DESC LIMIT 20
        )
    """, [date]).fetchone()
    out["VIX_20D_AVG"] = _round(avg[0]) if avg else None
    return out


def build(days: int, per_day: int) -> list[dict]:
    con = get_conn()
    trading_days = con.execute("""
        SELECT DISTINCT date FROM features
        ORDER BY date DESC LIMIT ?
    """, [days]).df()["date"].astype(str).tolist()

    cases: list[dict] = []
    for d in trading_days:
        movers = con.execute("""
            SELECT symbol,
                   ROUND(pct_change_1d, 2) AS pct_1d,
                   ROUND(vol_vs_20d_avg, 2) AS vol_mult,
                   ROUND(pct_from_52w_high, 1) AS from_52wH
            FROM features
            WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
            ORDER BY ABS(pct_change_1d) DESC LIMIT ?
        """, [d, per_day]).df().to_dict(orient="records")

        nifty = _nifty_ret(con, d)
        macro = _macro(con, d)
        fii, dii = _flow(con, d)

        for m in movers:
            sec_ret = _sector_ret(con, m["symbol"], d)
            events = _material_events(m["symbol"], d)
            ev_lines = " | ".join(
                f"{e.get('date')} {e.get('text','')[:90]}" for e in events
            ) or "(no material filings in last 5 trading days)"

            cases.append({
                "symbol": m["symbol"],
                "date": d,
                "pct_1d": m["pct_1d"],
                "sector_ret": sec_ret,
                "nifty_ret": nifty,
                "vol_mult": m["vol_mult"],
                "from_52wH": m["from_52wH"],
                "material_events": ev_lines,
                "fii_net_cr": _round(fii, 0) if fii is not None else None,
                "dii_net_cr": _round(dii, 0) if dii is not None else None,
                "vix": macro.get("US_VIX"),
                "vix_20d_avg": macro.get("VIX_20D_AVG"),
                "crude_wti": macro.get("CRUDE_WTI"),
                "us_10y": macro.get("US_10Y"),
            })

    con.close()
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8,
                    help="Number of most recent trading days to cover.")
    ap.add_argument("--per_day", type=int, default=15,
                    help="Top K biggest movers to include per day.")
    args = ap.parse_args()

    print(f"Building candidate cases from last {args.days} days, "
          f"top {args.per_day} movers each day...")
    cases = build(args.days, args.per_day)
    if not cases:
        print("No cases generated. Run bootstrap first.")
        return

    fields = list(cases[0].keys())
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for c in cases:
            w.writerow(c)

    print(f"Wrote {len(cases)} candidate cases to {OUT}")
    print("\nDistribution by date:")
    from collections import Counter
    print(Counter(c["date"] for c in cases))
    print(f"\nTotal cases ready for labelling: {len(cases)}")
    print("Next step: share the CSV contents for independent ground-truth labelling.")


if __name__ == "__main__":
    main()
