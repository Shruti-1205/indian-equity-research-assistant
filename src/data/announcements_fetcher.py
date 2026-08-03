"""Fetch corporate announcements from BSE's public JSON API.

BSE is cookie-sensitive: you MUST hit bseindia.com first to get session cookies
before the API will return data. Otherwise it silently returns an empty Table.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Iterable

from curl_cffi import requests as cffi_requests
from tqdm import tqdm

from src.data.bse_codes import NSE_TO_BSE

# BSE retired AnnGetData/w around 2026-05-29: it still answers 200 but the body
# is the bare JSON string "No Record Found!" for every scrip. AnnSubCategoryGetData/w
# is the endpoint their site uses now and returns the identical Table/Table1 shape.
BSE_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
WARMUP_URLS = [
    "https://www.bseindia.com/",
    "https://www.bseindia.com/corporates/ann.html",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://www.bseindia.com/corporates/ann.html",
    "Origin": "https://www.bseindia.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def _fmt(d: datetime) -> str:
    # BSE expects YYYYMMDD (no slashes) despite what their UI shows.
    return d.strftime("%Y%m%d")


def _new_session() -> cffi_requests.Session:
    s = cffi_requests.Session(impersonate="chrome")
    s.headers.update(HEADERS)
    for url in WARMUP_URLS:
        try:
            s.get(url, timeout=15)
        except Exception:
            pass
    return s


def fetch_announcements_for_scrip(
    scripcode: str,
    days_back: int = 180,
    max_pages: int = 10,
    pause: float = 0.8,
    debug: bool = False,
    session: cffi_requests.Session | None = None,
) -> list[dict]:
    """Return all announcements for a BSE scripcode over the last `days_back` days."""
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days_back)

    s = session or _new_session()

    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "pageno": str(page),
            "strCat": "-1",
            "strPrevDate": _fmt(from_date),
            "strScrip": scripcode,
            "strSearch": "P",
            "strToDate": _fmt(to_date),
            "strType": "C",
            "subcategory": "-1",
        }
        try:
            r = s.get(BSE_URL, params=params, timeout=20)
            if debug:
                print(f"  [dbg] {r.status_code} {r.url}")
                print(f"  [dbg] body[:300]: {r.text[:300]}")
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            if debug:
                print(f"  [err] {scripcode} p{page}: {e}")
            break

        # A retired/rotated endpoint answers 200 with a bare string like
        # "No Record Found!" rather than an object. Treat that as "no data"
        # instead of raising AttributeError on .get.
        if not isinstance(data, dict):
            if debug:
                print(f"  [err] {scripcode} p{page}: unexpected body {data!r:.80}")
            break

        rows = data.get("Table") or []
        if not rows:
            break
        out.extend(rows)

        meta = data.get("Table1") or []
        if meta:
            try:
                total = int(meta[0].get("ROWCNT", 0) or 0)
                if len(out) >= total:
                    break
            except (TypeError, ValueError):
                pass
        time.sleep(pause)

    return out


def fetch_watchlist_announcements(
    days_back: int = 180,
    symbols: Iterable[str] | None = None,
) -> dict[str, list[dict]]:
    symbols = list(symbols) if symbols is not None else list(NSE_TO_BSE.keys())
    session = _new_session()  # single warmed session reused across stocks
    result: dict[str, list[dict]] = {}
    for sym in tqdm(symbols, desc="BSE announcements"):
        code = NSE_TO_BSE.get(sym)
        if not code:
            print(f"  [skip] no scripcode for {sym}")
            continue
        try:
            rows = fetch_announcements_for_scrip(code, days_back=days_back, session=session)
            result[sym] = rows
        except Exception as e:
            print(f"  [err]  {sym}: {e}")
            result[sym] = []
    return result


if __name__ == "__main__":
    # Smoke test with debug output so we can see the HTTP response.
    print("Smoke test: RELIANCE (500325), last 30 days, verbose mode\n")
    rows = fetch_announcements_for_scrip("500325", days_back=30, debug=True)
    print(f"\nFetched {len(rows)} announcements.")
    for r in rows[:5]:
        print(f"  {r.get('NEWS_DT')} | {r.get('CATEGORYNAME')} | {r.get('HEADLINE','')[:80]}")
