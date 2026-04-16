"""Download + parse BSE announcement PDFs, cached in DuckDB.

Called on-demand by the event agent: for the top-K semantically retrieved
announcements, this fetches + parses the attached PDF and returns its text.
Results are cached so a given announcement is only parsed once.

BSE PDF URL patterns:
  - https://www.bseindia.com/xml-data/corpfiling/AttachLive/<filename>.pdf
  - https://www.bseindia.com/xml-data/corpfiling/AttachHis/<filename>.pdf
  - Sometimes NSURL is already a full URL, sometimes a bare filename.
"""
from __future__ import annotations

import io
import time
from datetime import datetime

import fitz  # pymupdf
from curl_cffi import requests as cffi_requests

from src.data.db import get_conn

BSE_ATTACH_BASES = [
    "https://www.bseindia.com/xml-data/corpfiling/AttachLive/",
    "https://www.bseindia.com/xml-data/corpfiling/AttachHis/",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/pdf,*/*",
}
MAX_CHARS = 40_000  # per-doc cap; synthesis only needs the top of long filings


def _resolve_url(raw: str) -> list[str]:
    """Return a list of URL candidates to try in order.

    Accepts either a full URL, or a bare BSE attachment filename
    (e.g. '5f14f4bf-40d0-49ec-a0a9-fd0a4ffc9308.pdf').
    For bare filenames we try AttachLive first, then AttachHis.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.lower().startswith("http"):
        return [raw]
    return [base + raw for base in BSE_ATTACH_BASES]


def _parse_pdf_bytes(data: bytes) -> tuple[str, int]:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        parts = []
        total = 0
        for page in doc:
            t = page.get_text() or ""
            parts.append(t)
            total += len(t)
            if total > MAX_CHARS:
                break
        text = "\n".join(parts)
        return text[:MAX_CHARS].strip(), doc.page_count
    finally:
        doc.close()


def _get_cached(newsid: str) -> dict | None:
    con = get_conn()
    row = con.execute(
        "SELECT newsid, symbol, url, text, page_count, status FROM pdf_cache WHERE newsid = ?",
        [newsid],
    ).fetchone()
    con.close()
    if not row:
        return None
    return {
        "newsid": row[0], "symbol": row[1], "url": row[2],
        "text": row[3] or "", "page_count": row[4] or 0, "status": row[5],
    }


def _save(newsid: str, symbol: str, url: str, text: str, pages: int, status: str) -> None:
    con = get_conn()
    con.execute(
        """
        INSERT INTO pdf_cache (newsid, symbol, url, text, page_count, fetched_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (newsid) DO UPDATE SET
          symbol=excluded.symbol, url=excluded.url, text=excluded.text,
          page_count=excluded.page_count, fetched_at=excluded.fetched_at,
          status=excluded.status;
        """,
        [newsid, symbol, url, text, pages, datetime.now(), status],
    )
    con.close()


_SESSION: cffi_requests.Session | None = None


def _session() -> cffi_requests.Session:
    global _SESSION
    if _SESSION is None:
        s = cffi_requests.Session(impersonate="chrome")
        s.headers.update(HEADERS)
        try:
            s.get("https://www.bseindia.com/", timeout=15)
        except Exception:
            pass
        _SESSION = s
    return _SESSION


def fetch_pdf_text(
    newsid: str,
    url: str,
    symbol: str = "",
    force: bool = False,
    timeout: int = 20,
) -> dict:
    """Return {'text', 'page_count', 'status', 'url', 'cached': bool}.

    Hits DuckDB cache first. On miss, downloads + parses + stores.
    Non-fatal on failure (stores status, returns empty text).
    """
    if not force:
        cached = _get_cached(newsid)
        if cached is not None:
            cached["cached"] = True
            return cached

    candidates = _resolve_url(url)
    if not candidates:
        _save(newsid, symbol, url or "", "", 0, "empty")
        return {"text": "", "page_count": 0, "status": "empty", "url": url, "cached": False}

    s = _session()
    last_err = ""
    for cand in candidates:
        try:
            r = s.get(cand, timeout=timeout)
            if r.status_code != 200 or not r.content:
                last_err = f"http {r.status_code}"
                continue
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "pdf" not in ctype and not r.content.startswith(b"%PDF"):
                last_err = f"not-a-pdf ({ctype[:40]})"
                continue
            text, pages = _parse_pdf_bytes(r.content)
            status = "ok" if text else "empty"
            _save(newsid, symbol, cand, text, pages, status)
            return {"text": text, "page_count": pages, "status": status, "url": cand, "cached": False}
        except Exception as e:
            last_err = str(e)[:100]
            continue
        finally:
            time.sleep(0.3)  # gentle on BSE

    _save(newsid, symbol, url or "", "", 0, "http_error")
    return {"text": "", "page_count": 0, "status": f"http_error: {last_err}",
            "url": url, "cached": False}


def enrich_with_pdf_text(events: list[dict], symbol_hint: str = "") -> list[dict]:
    """For each event dict from query_events(), attach 'full_text' + 'page_count'.

    Prefers the 'attachment' field (bare BSE PDF filename). Falls back to
    legacy 'url' field for metadata written before that field existed.
    """
    for ev in events:
        nid = ev.get("id")
        attach = (ev.get("attachment") or "").strip()
        legacy = (ev.get("url") or "").strip()
        target = attach or legacy
        if not nid or not target:
            ev["full_text"] = ""
            ev["page_count"] = 0
            ev["pdf_status"] = "no_attachment"
            continue
        r = fetch_pdf_text(nid, target, symbol=ev.get("symbol") or symbol_hint)
        ev["full_text"] = r["text"]
        ev["page_count"] = r["page_count"]
        ev["pdf_status"] = r["status"]
    return events


def cache_stats() -> dict:
    con = get_conn()
    row = con.execute("""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status='ok'          THEN 1 ELSE 0 END) AS ok,
          SUM(CASE WHEN status='empty'       THEN 1 ELSE 0 END) AS empty,
          SUM(CASE WHEN status LIKE 'http%'  THEN 1 ELSE 0 END) AS http_err,
          SUM(CASE WHEN status='parse_error' THEN 1 ELSE 0 END) AS parse_err
        FROM pdf_cache
    """).fetchone()
    con.close()
    keys = ["total", "ok", "empty", "http_err", "parse_err"]
    return {k: (v or 0) for k, v in zip(keys, row)}


if __name__ == "__main__":
    # Smoke test: pick the most recent Reliance announcement and fetch its PDF.
    from src.rag.chroma_store import query_events
    from src.data.db import init_schema
    init_schema()

    events = query_events("RELIANCE.NS", days_back=30, k=3)
    if not events:
        print("No events found. Did you run build_rag?")
        raise SystemExit

    print(f"Enriching {len(events)} events with PDF text...\n")
    enrich_with_pdf_text(events)

    for ev in events:
        print(f"--- {ev.get('date')} [{ev.get('category')}] ({ev.get('pdf_status')}, {ev.get('page_count')} pages) ---")
        print(ev.get("full_text", "")[:800] or "  (no text extracted)")
        print()

    print("Cache stats:", cache_stats())
