"""Download OHLCV via yfinance and upsert into DuckDB.

Uses a curl_cffi browser-impersonating session to avoid Yahoo's bot detection
(JSONDecodeError on empty responses is the classic symptom of being rate-limited).
"""
import time
import pandas as pd
import yfinance as yf
from curl_cffi import requests as cffi_requests
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

from config import WATCHLIST, SECTOR_INDICES
from src.data.db import get_conn, init_schema


def _make_session():
    # Impersonate Chrome so Yahoo doesn't return an empty body.
    return cffi_requests.Session(impersonate="chrome")


_SESSION = _make_session()


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=20))
def _download(symbol: str, period: str = "2y") -> pd.DataFrame:
    t = yf.Ticker(symbol, session=_SESSION)
    df = t.history(period=period, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"Empty response for {symbol} (likely rate-limited)")

    df = df.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
    })
    # .history() on some tickers omits 'Adj Close' — fall back to close.
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"]
    df["symbol"] = symbol
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[["symbol", "date", "open", "high", "low", "close", "adj_close", "volume"]]


def upsert_prices(df: pd.DataFrame) -> int:
    con = get_conn()
    con.register("_incoming", df)
    con.execute("""
        INSERT INTO prices
        SELECT * FROM _incoming
        ON CONFLICT (symbol, date) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low,
            close=excluded.close, adj_close=excluded.adj_close, volume=excluded.volume;
    """)
    con.unregister("_incoming")
    n = len(df)
    con.close()
    return n


def fetch_all(symbols: list[str], period: str = "2y", pause: float = 1.5):
    init_schema()
    total = 0
    failed = []
    for sym in tqdm(symbols, desc="Fetching prices"):
        try:
            df = _download(sym, period=period)
            total += upsert_prices(df)
            time.sleep(pause)
        except Exception as e:
            failed.append((sym, str(e)[:120]))
    print(f"\nUpserted {total} rows across {len(symbols) - len(failed)} symbols.")
    if failed:
        print(f"Failed ({len(failed)}):")
        for s, err in failed:
            print(f"  {s}: {err}")

    # Individual symbols fail routinely (renamed or delisted tickers), so those
    # stay non-fatal. Every symbol failing means Yahoo is blocking or down, and
    # that must not pass as a green build with stale data.
    if symbols and len(failed) == len(symbols):
        raise RuntimeError(
            f"All {len(symbols)} symbols failed to download — Yahoo is blocking or "
            "unreachable. Last error: " + failed[-1][1]
        )


def fetch_watchlist(period: str = "2y"):
    fetch_all(WATCHLIST + list(SECTOR_INDICES.values()), period=period)


if __name__ == "__main__":
    fetch_watchlist()
