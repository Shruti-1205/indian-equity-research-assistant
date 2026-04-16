"""Fetch daily FII/DII net trade data from NSE and upsert to DuckDB.

NSE's public API is cookie sensitive: we hit nseindia.com first to warm up a
session, then call the daily summary endpoint. Historical backfill via NSE
was not reliable at the time of writing (endpoints have rotated multiple
times), so this module captures a single day per run. Daily accumulation
over a scheduled cron is the intended pattern.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from curl_cffi import requests as cffi_requests

from src.data.db import get_conn, init_schema

NSE_BASE = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/reports/fii-dii",
}


def _new_session() -> cffi_requests.Session:
    s = cffi_requests.Session(impersonate="chrome")
    s.headers.update(HEADERS)
    for url in (f"{NSE_BASE}/", f"{NSE_BASE}/reports/fii-dii"):
        try:
            s.get(url, timeout=15)
        except Exception:
            pass
    return s


def _parse_number(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_today(session: cffi_requests.Session | None = None) -> pd.DataFrame:
    """Return a 1-row DataFrame (date, fii_net, dii_net) for the latest trade day.

    Returns empty DataFrame if NSE has not published today's numbers yet
    (typical cutover around 18:30 IST).
    """
    s = session or _new_session()
    r = s.get(f"{NSE_BASE}/api/fiidiiTradeReact", timeout=20)
    r.raise_for_status()
    rows = r.json() or []

    fii_net = dii_net = None
    date = None
    for row in rows:
        cat = (row.get("category") or "").upper()
        net = _parse_number(row.get("netValue"))
        date = row.get("date") or date
        if "FII" in cat:
            fii_net = net
        elif "DII" in cat:
            dii_net = net

    if not date:
        return pd.DataFrame(columns=["date", "fii_net", "dii_net"])
    try:
        d = datetime.strptime(date, "%d-%b-%Y").date()
    except ValueError:
        return pd.DataFrame(columns=["date", "fii_net", "dii_net"])

    return pd.DataFrame([{"date": d, "fii_net": fii_net, "dii_net": dii_net}])


def upsert_flow(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    con = get_conn()
    con.register("_f", df)
    con.execute("""
        INSERT INTO fii_dii SELECT * FROM _f
        ON CONFLICT (date) DO UPDATE SET
            fii_net = excluded.fii_net, dii_net = excluded.dii_net;
    """)
    con.unregister("_f")
    n = len(df)
    con.close()
    return n


def refresh_flow() -> None:
    """Capture today's FII/DII snapshot. Run via daily cron to build history."""
    init_schema()
    session = _new_session()
    print("Fetching NSE FII/DII (today's snapshot):")
    today = fetch_today(session)
    if today.empty:
        print("  No data published yet (NSE typically releases after 18:30 IST).")
    else:
        n = upsert_flow(today)
        print(f"  Upserted {n} row(s) into fii_dii.")


if __name__ == "__main__":
    refresh_flow()
