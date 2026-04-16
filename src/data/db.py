"""DuckDB connection + schema bootstrap."""
import duckdb
from config import DUCKDB_PATH


def get_conn():
    return duckdb.connect(str(DUCKDB_PATH))


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
