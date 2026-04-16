"""One-shot: init DB, download 2y of prices, build features.

Run from project root:  python -m scripts.bootstrap
"""
from src.data.db import init_schema
from src.data.price_fetcher import fetch_watchlist
from src.data.feature_builder import rebuild_features


def main():
    print("[1/3] Initializing DuckDB schema...")
    init_schema()

    print("[2/3] Downloading 2y of prices for Nifty50 + sector indices...")
    fetch_watchlist(period="2y")

    print("[3/3] Building feature table...")
    rebuild_features()

    print("\nDone. Inspect with:  python -m scripts.peek")


if __name__ == "__main__":
    main()
