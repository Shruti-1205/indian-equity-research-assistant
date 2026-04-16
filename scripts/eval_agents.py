"""Batch evaluation: run the full pipeline across many stocks and report stats.

Usage:
  python -m scripts.eval_agents                 # 10 random Nifty50 stocks
  python -m scripts.eval_agents --all           # every stock with data
  python -m scripts.eval_agents --date 2026-04-13
  python -m scripts.eval_agents --movers        # only the 10 biggest movers

Pass criteria per query:
  • no exception raised
  • explanation non-empty
  • validation_ok == True  (all numbers in explanation match source)
  • primary_driver ∈ {company, sector, macro, flow, unclear}
  • confidence   ∈ {high, medium, low}
"""
from __future__ import annotations

import argparse
import random
import time
import traceback
from statistics import mean

from src.agents.graph import run
from src.data.db import get_conn
from config import NIFTY50

VALID_DRIVERS = {"company", "sector", "macro", "flow", "unclear"}
VALID_CONF = {"high", "medium", "low"}


def _latest_date() -> str:
    con = get_conn()
    d = con.execute("SELECT MAX(date) FROM features").fetchone()[0]
    con.close()
    return str(d)


def _top_movers(date: str, k: int = 10) -> list[str]:
    con = get_conn()
    rows = con.execute("""
        SELECT symbol FROM features
        WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
        ORDER BY ABS(pct_change_1d) DESC LIMIT ?
    """, [date, k]).fetchall()
    con.close()
    return [r[0] for r in rows]


def _evaluate_one(symbol: str, date: str) -> dict:
    result: dict = {"symbol": symbol, "ok": False, "err": ""}
    t0 = time.time()
    try:
        state = run(symbol, date, "")
        expl = (state.get("explanation") or "").strip()
        driver = (state.get("primary_driver") or "").strip().lower()
        conf = (state.get("confidence") or "").strip().lower()
        validation_ok = state.get("validation_ok")
        unverified = state.get("unverified_claims") or []
        changes = bool(state.get("changes_made"))

        checks = {
            "nonempty_explanation": bool(expl),
            "validation_ok": bool(validation_ok) and not unverified,
            "valid_driver": driver in VALID_DRIVERS,
            "valid_confidence": conf in VALID_CONF,
        }
        result.update({
            "ok": all(checks.values()),
            "driver": driver,
            "confidence": conf,
            "validation_ok": validation_ok,
            "unverified": unverified,
            "changes_made": changes,
            "latency_s": round(time.time() - t0, 1),
            "checks": checks,
            "explanation_preview": expl[:160].replace("\n", " "),
        })
    except Exception as e:
        result["err"] = f"{type(e).__name__}: {e}"
        result["trace"] = traceback.format_exc()
        result["latency_s"] = round(time.time() - t0, 1)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="Run on all Nifty50.")
    ap.add_argument("--movers", action="store_true",
                    help="Run only on the 10 biggest movers of the chosen date.")
    ap.add_argument("--n", type=int, default=10, help="Sample size (default 10).")
    ap.add_argument("--date", type=str, default=None, help="YYYY-MM-DD. Default: latest feature date.")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    date = args.date or _latest_date()
    print(f"Evaluating on date: {date}\n")

    if args.all:
        symbols = NIFTY50
    elif args.movers:
        symbols = _top_movers(date, k=args.n)
    else:
        random.seed(args.seed)
        symbols = random.sample(NIFTY50, min(args.n, len(NIFTY50)))

    results: list[dict] = []
    for sym in symbols:
        print(f"→ {sym} ...", end=" ", flush=True)
        r = _evaluate_one(sym, date)
        results.append(r)
        if r["ok"]:
            print(f"OK  [{r['driver']}/{r['confidence']}]  ({r['latency_s']}s)")
        elif r["err"]:
            print(f"ERROR: {r['err']}  ({r['latency_s']}s)")
        else:
            failed = [k for k, v in r["checks"].items() if not v]
            print(f"FAIL  failed checks: {failed}  unverified={r.get('unverified')}  ({r['latency_s']}s)")

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    total = len(results)
    passed = sum(1 for r in results if r.get("ok"))
    errors = sum(1 for r in results if r.get("err"))
    failed = total - passed - errors
    print(f"  total:   {total}")
    print(f"  passed:  {passed}  ({passed/total*100:.0f}%)")
    print(f"  failed:  {failed}")
    print(f"  errored: {errors}")

    latencies = [r["latency_s"] for r in results if r.get("latency_s") is not None]
    if latencies:
        print(f"  latency: mean {mean(latencies):.1f}s  min {min(latencies):.1f}s  max {max(latencies):.1f}s")

    # Driver/confidence distribution
    drivers = [r.get("driver") for r in results if r.get("ok")]
    confs = [r.get("confidence") for r in results if r.get("ok")]
    if drivers:
        from collections import Counter
        print(f"  drivers: {dict(Counter(drivers))}")
        print(f"  conf:    {dict(Counter(confs))}")

    changes = sum(1 for r in results if r.get("changes_made"))
    print(f"  verifier rewrites triggered: {changes}/{total}")

    print("\nSample answers (one pass + one fail if available):")
    for tag, pick in (("PASS", next((r for r in results if r.get("ok")), None)),
                      ("FAIL", next((r for r in results if not r.get("ok") and not r.get("err")), None)),
                      ("ERR",  next((r for r in results if r.get("err")), None))):
        if pick is None:
            continue
        print(f"\n[{tag}] {pick['symbol']}  ({pick.get('driver', '?')}/{pick.get('confidence', '?')})")
        if pick.get("explanation_preview"):
            print(f"   {pick['explanation_preview']}")
        if pick.get("unverified"):
            print(f"   unverified: {pick['unverified']}")
        if pick.get("err"):
            print(f"   {pick['err']}")


if __name__ == "__main__":
    main()
