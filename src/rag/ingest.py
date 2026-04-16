"""Fetch BSE announcements for every watchlist stock and ingest into ChromaDB."""
from __future__ import annotations

from tqdm import tqdm

from src.data.bse_codes import NSE_TO_BSE
from src.data.announcements_fetcher import fetch_announcements_for_scrip
from src.rag.chroma_store import upsert_announcements, stats


def ingest_all(days_back: int = 365) -> None:
    total = 0
    per_stock: dict[str, int] = {}

    for symbol, code in tqdm(NSE_TO_BSE.items(), desc="Ingesting"):
        try:
            rows = fetch_announcements_for_scrip(code, days_back=days_back)
            n = upsert_announcements(symbol, code, rows)
            per_stock[symbol] = n
            total += n
        except Exception as e:
            print(f"  [err] {symbol}: {e}")
            per_stock[symbol] = 0

    print(f"\nTotal documents upserted: {total}")
    print(f"Collection size now: {stats()['count']}")

    # Top 10 most active companies in last year
    top = sorted(per_stock.items(), key=lambda kv: kv[1], reverse=True)[:10]
    print("\nMost active filers:")
    for sym, n in top:
        print(f"  {sym:15s} {n:>4d} announcements")


if __name__ == "__main__":
    ingest_all(days_back=365)
