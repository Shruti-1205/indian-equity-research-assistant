"""Pull global macro series from FRED and upsert into DuckDB.

Why these series (all free, daily or business-daily):
  DCOILWTICO  - WTI crude oil spot price ($/bbl). India imports ~85% of oil.
  VIXCLS      - US VIX (fear index). Proxies global risk-off behaviour.
  DGS10       - US 10-year Treasury yield. When this spikes, FIIs leave EMs.
  DEXINUS     - USD/INR daily reference rate.
  DTWEXBGS    - Broad dollar index (trade-weighted). EM flows correlate inversely.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from fredapi import Fred

from config import FRED_API_KEY
from src.data.db import get_conn, init_schema

FRED_SERIES = {
    "CRUDE_WTI":   "DCOILWTICO",
    "US_VIX":      "VIXCLS",
    "US_10Y":      "DGS10",
    "USD_INR":     "DEXINUS",
    "DXY_BROAD":   "DTWEXBGS",
}


def _require_key() -> Fred:
    if not FRED_API_KEY:
        raise RuntimeError(
            "FRED_API_KEY missing — add it to .env (get one free at "
            "https://fredaccount.stlouisfed.org/apikeys)"
        )
    return Fred(api_key=FRED_API_KEY)


def fetch_series(lookback_days: int = 365) -> pd.DataFrame:
    """Return a long-format DataFrame (date, series, value) for all FRED_SERIES."""
    fred = _require_key()
    start = (datetime.now() - timedelta(days=lookback_days)).date()
    frames: list[pd.DataFrame] = []
    for name, code in FRED_SERIES.items():
        s = fred.get_series(code, observation_start=start)
        df = s.rename("value").reset_index().rename(columns={"index": "date"})
        df["series"] = name
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.dropna(subset=["value"])
        frames.append(df[["date", "series", "value"]])
        print(f"  {name:12s} ({code:12s})  {len(df):>4d} obs, last={df['date'].max() if len(df) else 'n/a'}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", "series", "value"])


def upsert_macro(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    con = get_conn()
    con.register("_m", df)
    con.execute("""
        INSERT INTO macro SELECT * FROM _m
        ON CONFLICT (date, series) DO UPDATE SET value = excluded.value;
    """)
    con.unregister("_m")
    n = len(df)
    con.close()
    return n


def refresh_macro(lookback_days: int = 365) -> None:
    init_schema()
    print(f"Fetching FRED macro series, lookback={lookback_days}d:")
    df = fetch_series(lookback_days)
    n = upsert_macro(df)
    print(f"Upserted {n} rows into `macro`.")


if __name__ == "__main__":
    refresh_macro()
