"""Quick sanity-check of what's in DuckDB."""
from src.data.db import get_conn


def main():
    con = get_conn()

    print("--- Row counts ---")
    for tbl in ("prices", "features", "fii_dii", "macro", "pdf_cache"):
        n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl:10s} {n:>10,}")

    print("\n--- Biggest movers on most recent day ---")
    df = con.execute("""
        WITH latest AS (SELECT MAX(date) AS d FROM features)
        SELECT f.symbol, f.date, ROUND(f.pct_change_1d, 2) AS pct_1d,
               ROUND(f.pct_from_52w_high, 1) AS pct_from_52wH,
               ROUND(f.dist_50dma_pct, 1)    AS dist_50dma,
               ROUND(f.vol_vs_20d_avg, 2)    AS vol_mult
        FROM features f, latest
        WHERE f.date = latest.d AND f.symbol NOT LIKE '^%'
        ORDER BY ABS(f.pct_change_1d) DESC
        LIMIT 8
    """).df()
    print(df.to_string(index=False))

    print("\n--- Latest macro (FRED) ---")
    df = con.execute("""
        WITH r AS (
          SELECT series, MAX(date) AS d FROM macro GROUP BY series
        )
        SELECT m.series, m.date, ROUND(m.value, 3) AS value
        FROM macro m JOIN r ON m.series = r.series AND m.date = r.d
        ORDER BY m.series;
    """).df()
    print(df.to_string(index=False))

    print("\n--- Recent FII/DII net flow (₹ crore) ---")
    df = con.execute("""
        SELECT date, ROUND(fii_net, 0) AS fii_net, ROUND(dii_net, 0) AS dii_net
        FROM fii_dii
        ORDER BY date DESC
        LIMIT 10;
    """).df()
    if df.empty:
        print("  (empty — NSE publishes ~6:30 PM IST, retry later)")
    else:
        print(df.to_string(index=False))

    con.close()


if __name__ == "__main__":
    main()
