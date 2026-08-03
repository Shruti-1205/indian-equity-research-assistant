"""Shrink the committed data files before the daily refresh commits them.

Run from project root:  python -m scripts.compact_data

Both stores grow every run because the refresh re-upserts overlapping data:
DuckDB never returns freed blocks to the OS, and SQLite leaves free pages
behind. Left alone, market.duckdb went 23 MiB (April) -> 97 MiB (June) and the
next run crossed GitHub's hard 100 MiB per-file limit, which is what broke
`git push` in the daily-refresh workflow.

This script rewrites both files compactly and then fails loudly if either is
still large enough to be heading for that limit, so a silent regression shows
up as a red build with an explanation instead of a rejected push months later.
"""
from __future__ import annotations

import sys

from config import CHROMA_DIR, DUCKDB_PATH
from src.data.db import compact as compact_duckdb
from src.rag.chroma_store import prune_older_than, vacuum as vacuum_chroma

MIB = 1024 * 1024

# GitHub rejects any file over 100 MiB outright and warns above 50 MiB. Fail at
# 90 so there is room to notice and react before pushes start bouncing.
FAIL_ABOVE_MIB = 90.0
WARN_ABOVE_MIB = 50.0


def _report(label: str, before: int, after: int) -> None:
    if before == 0:
        print(f"  {label:<22} (missing, skipped)")
        return
    saved = 100 * (1 - after / before) if before else 0.0
    print(f"  {label:<22} {before / MIB:7.2f} MiB -> {after / MIB:7.2f} MiB  ({saved:.1f}% reclaimed)")


def main() -> int:
    print("Compacting data files:")
    _report("data/market.duckdb", *compact_duckdb())

    pruned = prune_older_than(400)
    print(f"  {'chroma prune':<22} {pruned} announcement(s) older than 400d removed")
    _report("chroma_db/chroma.sqlite3", *vacuum_chroma())

    print("\nSize check (GitHub hard limit is 100.00 MiB per file):")
    oversized = []
    for path in (DUCKDB_PATH, CHROMA_DIR / "chroma.sqlite3"):
        if not path.exists():
            continue
        mib = path.stat().st_size / MIB
        if mib > FAIL_ABOVE_MIB:
            status = "OVER LIMIT"
            oversized.append((path, mib))
        elif mib > WARN_ABOVE_MIB:
            status = "warn"
        else:
            status = "ok"
        print(f"  {status:<11} {mib:7.2f} MiB  {path}")

    if oversized:
        print(
            f"\nERROR: {len(oversized)} file(s) above {FAIL_ABOVE_MIB:.0f} MiB even after "
            "compaction. GitHub will reject the push once they pass 100 MiB.\n"
            "Compaction alone can no longer keep these files in the repo — move them "
            "out (release asset / external storage) or trim the retained history."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
