"""Populate ChromaDB with BSE announcements for the full watchlist.

Run from project root:  python -m scripts.build_rag
"""
from src.rag.ingest import ingest_all


if __name__ == "__main__":
    # 1 year of announcements is a good balance — most "why did X move" questions
    # only need the last 30-90 days, but having a year lets the event agent
    # spot recurring patterns (e.g. chronic litigation, serial guidance cuts).
    ingest_all(days_back=365)
