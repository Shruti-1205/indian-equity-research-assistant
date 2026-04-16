"""Dump the raw BSE JSON for one announcement so we can see all available fields."""
import json
from src.data.announcements_fetcher import fetch_announcements_for_scrip


def main():
    rows = fetch_announcements_for_scrip("500325", days_back=14)
    if not rows:
        print("No rows returned.")
        return
    print(f"Got {len(rows)} rows. Showing keys + first row in full:\n")
    print("Keys present:", sorted(rows[0].keys()))
    print("\nFirst row:")
    print(json.dumps(rows[0], indent=2, default=str))


if __name__ == "__main__":
    main()
