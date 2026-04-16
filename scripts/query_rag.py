"""Interactive RAG query tester. Use --full to fetch+parse PDFs for top hits.

Usage:
  python -m scripts.query_rag RELIANCE.NS
  python -m scripts.query_rag RELIANCE.NS "earnings miss guidance cut"
  python -m scripts.query_rag RELIANCE.NS --full
  python -m scripts.query_rag INFY.NS "dividend buyback" --full
"""
import sys
from src.data.db import init_schema
from src.rag.chroma_store import query_events, stats
from src.data.pdf_fetcher import enrich_with_pdf_text, cache_stats


def main():
    args = [a for a in sys.argv[1:]]
    full = "--full" in args
    args = [a for a in args if a != "--full"]

    if not args:
        print("Usage: python -m scripts.query_rag <SYMBOL.NS> [semantic query] [--full]")
        print(f"\nCollection size: {stats()['count']}")
        sys.exit(1)

    init_schema()
    symbol = args[0]
    query = " ".join(args[1:])

    print(f"Collection size: {stats()['count']}")
    if full:
        print(f"PDF cache:       {cache_stats()}")
    print()

    if query:
        print(f"Semantic query for {symbol}: '{query}'\n")
    else:
        print(f"Most recent announcements for {symbol}:\n")

    results = query_events(symbol=symbol, query=query, days_back=365, k=5)
    if not results:
        print("  (no results — is the scripcode correct, and was ingestion run?)")
        return

    if full:
        print("Enriching top hits with PDF text (may take 1-5s each)...\n")
        enrich_with_pdf_text(results)

    for r in results:
        dist = f"  d={r['distance']:.3f}" if r.get("distance") is not None else ""
        print(f"  {r.get('date','?'):10s}  [{r.get('category','?')[:22]:22s}]  {r['text'][:90]}{dist}")
        if full:
            body = r.get("full_text", "") or "  (no text extracted)"
            status = r.get("pdf_status", "?")
            print(f"    pdf: {status}  ({r.get('page_count', 0)} pages)")
            # Print first ~500 chars of PDF body so you can eyeball what the synthesis agent will see.
            snippet = body.replace("\n", " ")[:500]
            print(f"    {snippet}")
            print()


if __name__ == "__main__":
    main()
