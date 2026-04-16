"""One-shot: pull FRED macro + NSE FII/DII into DuckDB.

Run daily (or just now to backfill):  python -m scripts.refresh_macro
"""
from src.data.fred_fetcher import refresh_macro
from src.data.nse_flow_fetcher import refresh_flow


def main():
    print("== FRED macro ==")
    refresh_macro(lookback_days=365)
    print("\n== NSE FII/DII ==")
    refresh_flow()


if __name__ == "__main__":
    main()
