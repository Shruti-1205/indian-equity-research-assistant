"""DuckDB connection + schema bootstrap."""
import os
from pathlib import Path

import duckdb
from config import DUCKDB_PATH


def get_conn():
    return duckdb.connect(str(DUCKDB_PATH))


def compact() -> tuple[int, int]:
    """Rewrite the database into a fresh file to reclaim dead space.

    DuckDB never hands freed blocks back to the OS, and the daily refresh
    re-upserts 2y of prices and rebuilds the whole `features` table on every
    run. That grew the committed file by ~5 MiB/day: 23 MiB in April, 97 MiB
    by June, at which point the next run crossed GitHub's hard 100 MiB
    per-file limit and the workflow's `git push` started being rejected.

    Copying into a new file drops it back to the live-data size (~13 MiB).
    Sequence positions are carried over, so `llm_usage_seq` keeps counting
    past the existing rows instead of restarting and colliding on the PK.

    Returns (bytes_before, bytes_after).
    """
    src = Path(DUCKDB_PATH)
    if not src.exists():
        return (0, 0)

    before = src.stat().st_size
    tmp = src.with_name(src.name + ".compact")
    if tmp.exists():
        tmp.unlink()

    con = duckdb.connect()
    try:
        # as_posix() because DuckDB treats backslashes in a quoted path as escapes.
        con.execute(f"ATTACH '{src.as_posix()}' AS src_db")
        con.execute(f"ATTACH '{tmp.as_posix()}' AS dst_db")
        con.execute("COPY FROM DATABASE src_db TO dst_db")
    finally:
        con.close()

    os.replace(tmp, src)
    # The old file's WAL belongs to the file we just replaced; leaving it would
    # make the next open try to replay it against unrelated content.
    wal = src.with_name(src.name + ".wal")
    if wal.exists():
        wal.unlink()

    return (before, src.stat().st_size)


def init_schema():
    con = get_conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            symbol      VARCHAR,
            date        DATE,
            open        DOUBLE,
            high        DOUBLE,
            low         DOUBLE,
            close       DOUBLE,
            adj_close   DOUBLE,
            volume      BIGINT,
            PRIMARY KEY (symbol, date)
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS features (
            symbol              VARCHAR,
            date                DATE,
            pct_change_1d       DOUBLE,
            pct_from_52w_high   DOUBLE,
            pct_from_52w_low    DOUBLE,
            dist_50dma_pct      DOUBLE,
            dist_200dma_pct     DOUBLE,
            vol_vs_20d_avg      DOUBLE,
            vol_zscore_20d      DOUBLE,
            PRIMARY KEY (symbol, date)
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS fii_dii (
            date       DATE PRIMARY KEY,
            fii_net    DOUBLE,
            dii_net    DOUBLE
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS macro (
            date    DATE,
            series  VARCHAR,
            value   DOUBLE,
            PRIMARY KEY (date, series)
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS pdf_cache (
            newsid       VARCHAR PRIMARY KEY,
            symbol       VARCHAR,
            url          VARCHAR,
            text         TEXT,
            page_count   INTEGER,
            fetched_at   TIMESTAMP,
            status       VARCHAR       -- 'ok' | 'empty' | 'http_error' | 'parse_error'
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS llm_usage (
            id               BIGINT PRIMARY KEY,
            ts               TIMESTAMP,
            provider         VARCHAR,   -- 'anthropic' | 'groq'
            model            VARCHAR,
            agent            VARCHAR,   -- 'synthesis' | 'verifier' | 'orchestrator'
            input_tokens     INTEGER,
            output_tokens    INTEGER,
            cache_read_tokens  INTEGER, -- Anthropic prompt caching (paid at 10x discount)
            cache_write_tokens INTEGER, -- Anthropic prompt caching (paid at ~1.25x)
            cost_usd         DOUBLE,
            latency_ms       INTEGER,
            note             VARCHAR
        );
    """)
    con.execute("CREATE SEQUENCE IF NOT EXISTS llm_usage_seq START 1;")
    con.close()


if __name__ == "__main__":
    init_schema()
    print(f"Initialized DuckDB at {DUCKDB_PATH}")
