"""Auto-seed a labeled benchmark set from the live DuckDB data.

NOT the source of the current `labels.csv`. This is the legacy rule-based
seeder, kept for bootstrapping a fresh label set from scratch. The labels the
benchmark actually scores against are produced by an independent Claude Opus
judge over `build_candidates.py` output — see that module and the methodology
note in `report.md`. Replaying the rules below reproduces only ~73% of the
current labels, which is the quickest way to confirm they are not rule-derived.

Strategy: for each stock on each of the last ~10 trading days, classify the
"likely correct" primary_driver using a deterministic, evidence-based rule:

  Rule 1: if Nifty50 fell > 1% AND (VIX elevated ≥ 1.2× avg OR |FII| ≥ ₹3000cr)
          → expected: macro
  Rule 2: elif |stock_return - sector_return| < 1.5pp AND |sector_return| ≥ 1%
          → expected: sector
  Rule 3: elif |stock_return - sector_return| ≥ 2.5pp AND there exists a
          material BSE filing in the last 3 trading days
          → expected: company
  Rule 4: else → expected: unclear

These rules encode the same taxonomy as the synthesis prompt — so "accuracy"
against them would be essentially self-consistency. That is precisely why the
scored labels come from an independent judge instead.

We pick 20 rows biased toward larger moves (|pct_change_1d| ≥ 2%) across
multiple dates so the benchmark covers many drivers.
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

from src.data.db import get_conn
from src.rag.chroma_store import query_events

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "labels.csv"

MATERIAL_KEYWORDS = (
    "result", "earnings", "quarterly", "dividend", "buyback", "bonus",
    "acquisition", "merger", "demerger", "divestment", "stake sale",
    "guidance", "rating", "downgrade", "upgrade",
    "fund raising", "qip", "preferential", "resignation", "ceo", "cfo",
    "bulk deal", "block deal",
    "sales volume", "dispatch", "production",
)


def _has_material_event(symbol: str, date: str, lookback: int = 3) -> bool:
    evts = query_events(symbol=symbol, query="", days_back=lookback + 2, k=15)
    for e in evts:
        if e.get("date", "") > date:
            continue
        blob = (e.get("text") or "") + " " + (e.get("category") or "")
        if any(k in blob.lower() for k in MATERIAL_KEYWORDS):
            return True
    return False


def _label_one(row: dict, macro_row: dict, flow_row: dict) -> str:
    stock_ret = row["pct_1d"]
    sector_ret = row["sector_ret"]
    nifty_ret = row["nifty_ret"]
    vix = macro_row.get("vix") or 0
    vix_avg = macro_row.get("vix_avg") or 1
    fii = abs(flow_row.get("fii_net") or 0)

    if (nifty_ret is not None) and (nifty_ret < -1.0) and ((vix and vix_avg and vix >= 1.2 * vix_avg) or fii >= 3000):
        return "macro"

    diff = None
    if stock_ret is not None and sector_ret is not None:
        diff = abs(stock_ret - sector_ret)
    if diff is not None and sector_ret is not None and diff < 1.5 and abs(sector_ret) >= 1.0:
        return "sector"

    if diff is not None and diff >= 2.5:
        if _has_material_event(row["symbol"], row["date"]):
            return "company"

    return "unclear"


def build_labels(n: int = 20, min_abs_move: float = 2.0) -> list[dict]:
    con = get_conn()
    # Collect candidate rows: biggest movers of each of the last ~15 trading days.
    rows = con.execute(f"""
        WITH recent AS (
            SELECT DISTINCT date FROM features
            WHERE symbol NOT LIKE '^%' AND pct_change_1d IS NOT NULL
            ORDER BY date DESC LIMIT 15
        )
        SELECT f.symbol, f.date,
               f.pct_change_1d AS pct_1d,
               f.vol_vs_20d_avg AS vol_mult
        FROM features f JOIN recent r ON f.date = r.date
        WHERE ABS(f.pct_change_1d) >= {float(min_abs_move)} AND f.symbol NOT LIKE '^%'
        ORDER BY ABS(f.pct_change_1d) DESC
    """).df().to_dict(orient="records")

    # Enrich with sector / nifty returns + macro + flow context for labeling.
    from config import STOCK_TO_SECTOR, SECTOR_INDICES
    candidates: list[dict] = []
    seen_stocks: set[tuple[str, str]] = set()
    for r in rows:
        key = (r["symbol"], str(r["date"]))
        if key in seen_stocks:
            continue
        seen_stocks.add(key)

        sec = STOCK_TO_SECTOR.get(r["symbol"])
        sec_idx = SECTOR_INDICES.get(sec) if sec else None
        sec_ret = None
        if sec_idx:
            row = con.execute(f"""
                WITH prior AS (
                  SELECT close FROM prices WHERE symbol = ? AND date < CAST(? AS DATE)
                  ORDER BY date DESC LIMIT 1
                )
                SELECT p.close, (SELECT close FROM prior) AS prev
                FROM prices p WHERE p.symbol = ? AND p.date = CAST(? AS DATE)
            """, [sec_idx, str(r["date"]), sec_idx, str(r["date"])]).fetchone()
            if row and row[0] and row[1]:
                sec_ret = round((row[0] / row[1] - 1) * 100, 2)

        nifty_idx = SECTOR_INDICES["NIFTY50"]
        nifty_row = con.execute(f"""
            WITH prior AS (
              SELECT close FROM prices WHERE symbol = ? AND date < CAST(? AS DATE)
              ORDER BY date DESC LIMIT 1
            )
            SELECT p.close, (SELECT close FROM prior) AS prev
            FROM prices p WHERE p.symbol = ? AND p.date = CAST(? AS DATE)
        """, [nifty_idx, str(r["date"]), nifty_idx, str(r["date"])]).fetchone()
        nifty_ret = None
        if nifty_row and nifty_row[0] and nifty_row[1]:
            nifty_ret = round((nifty_row[0] / nifty_row[1] - 1) * 100, 2)

        # Macro + flow on that date
        macro_row = {}
        m = con.execute("""
            SELECT series, value FROM macro WHERE date = CAST(? AS DATE)
        """, [str(r["date"])]).df()
        if not m.empty:
            for _, mm in m.iterrows():
                macro_row[mm["series"]] = mm["value"]
        vix_avg = con.execute("""
            SELECT AVG(value) FROM (
              SELECT value FROM macro WHERE series = 'US_VIX' AND date <= CAST(? AS DATE)
              ORDER BY date DESC LIMIT 20
            )
        """, [str(r["date"])]).fetchone()
        macro_row["vix"] = macro_row.get("US_VIX")
        macro_row["vix_avg"] = vix_avg[0] if vix_avg else None

        flow_row = con.execute(
            "SELECT fii_net, dii_net FROM fii_dii WHERE date = CAST(? AS DATE)",
            [str(r["date"])],
        ).fetchone()
        flow_dict = {
            "fii_net": flow_row[0] if flow_row else None,
            "dii_net": flow_row[1] if flow_row else None,
        }

        enriched = {
            "symbol": r["symbol"],
            "date": str(r["date"]),
            "pct_1d": r["pct_1d"],
            "sector_ret": sec_ret,
            "nifty_ret": nifty_ret,
        }
        expected = _label_one(enriched, macro_row, flow_dict)
        enriched["expected_driver"] = expected
        candidates.append(enriched)

    con.close()

    # Try to make the set diverse across expected drivers if possible.
    random.seed(42)
    random.shuffle(candidates)
    buckets: dict[str, list] = {"company": [], "sector": [], "macro": [], "unclear": []}
    for c in candidates:
        buckets[c["expected_driver"]].append(c)
    picked: list[dict] = []
    per_bucket = max(1, n // 4)
    for drv in ("company", "sector", "macro", "unclear"):
        picked.extend(buckets[drv][:per_bucket])
    # Fill remaining slots with whatever's left
    remaining = [c for c in candidates if c not in picked]
    picked.extend(remaining[: n - len(picked)])
    picked = picked[:n]

    return picked


def main():
    print("Generating benchmark labels from live data...")
    rows = build_labels(n=20)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "date", "pct_1d", "sector_ret", "nifty_ret", "expected_driver", "note"])
        for r in rows:
            w.writerow([
                r["symbol"], r["date"], r["pct_1d"],
                r.get("sector_ret"), r.get("nifty_ret"),
                r["expected_driver"], "",
            ])
    print(f"Wrote {len(rows)} labels → {OUT}")
    print("\nDistribution:")
    from collections import Counter
    print(Counter(r["expected_driver"] for r in rows))
    print("\nReview/edit the CSV by hand if you disagree with any label, then run:")
    print("  python -m scripts.benchmark")


if __name__ == "__main__":
    main()
