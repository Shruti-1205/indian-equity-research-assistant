"""Show LLM usage + spend report.

Usage:
  python -m scripts.usage            :: last 7 days summary
  python -m scripts.usage --days 30  :: longer window
"""
import argparse

from src.agents.llm_client import usage_summary, budget_headroom_usd
from config import DAILY_USD_BUDGET


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--clean", action="store_true",
                    help="Purge all historical failure log rows (keeps successful calls).")
    args = ap.parse_args()

    if args.clean:
        from src.data.db import get_conn
        con = get_conn()
        deleted = con.execute(
            "DELETE FROM llm_usage WHERE note IS NOT NULL AND note != '' AND note != 'free-tier'"
        )
        # DuckDB DELETE doesn't return rowcount; recount for feedback.
        remaining = con.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0]
        con.close()
        print(f"Purged historical failure rows. Remaining llm_usage rows: {remaining}")
        return

    s = usage_summary(days=args.days)

    print("=" * 68)
    print(f"  Today's spend:        ${s['today_spend_usd']:.4f}")
    print(f"  Daily budget cap:     ${s['daily_budget_usd']:.2f}")
    print(f"  Remaining today:      ${s['budget_remaining_usd']:.4f}")
    print("=" * 68)
    rows = s[f"by_agent_last_{args.days}d"]
    if not rows:
        print("\nNo LLM calls logged yet.")
        return
    print(f"\nLast {args.days} days — breakdown by agent × model:")
    print(f"  {'agent':14s} {'provider':10s} {'model':34s} {'calls':>6s} {'tokens':>9s} {'cost USD':>10s}")
    print("  " + "-" * 86)
    for r in rows:
        print(f"  {r['agent']:14s} {r['provider']:10s} {r['model']:34s} "
              f"{int(r['calls']):>6d} {int(r['tok']):>9d} {float(r['cost_usd']):>10.4f}")

    total_cost = sum(float(r["cost_usd"]) for r in rows)
    total_calls = sum(int(r["calls"]) for r in rows)
    print("  " + "-" * 86)
    print(f"  {'TOTAL':14s} {'':10s} {'':34s} {total_calls:>6d} {'':>9s} ${total_cost:>9.4f}")

    # Only show failure notes from the LAST HOUR so stale historical entries
    # (from earlier model-ID attempts that have since been fixed) don't pollute
    # the report. Use `python -m scripts.usage --clean` to wipe old notes.
    from src.data.db import get_conn
    con = get_conn()
    fails = con.execute("""
        SELECT ts, provider, model, agent, note
        FROM llm_usage
        WHERE note IS NOT NULL AND note != '' AND note != 'free-tier'
          AND ts >= CURRENT_TIMESTAMP - INTERVAL '1' HOUR
        ORDER BY ts DESC LIMIT 10
    """).df()
    con.close()
    if not fails.empty:
        print("\nRecent failures (last hour):")
        print(fails.to_string(index=False))


if __name__ == "__main__":
    main()
