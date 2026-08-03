"""ChromaDB wrapper: one collection for BSE announcements.

Each document = one announcement.
  id        -> BSE NEWSID (stable, dedupes automatically on re-ingest)
  document  -> "{category}: {headline}"  (what gets embedded)
  metadata  -> {symbol, scripcode, date (YYYY-MM-DD), category, company, url}

The embedding model is `all-MiniLM-L6-v2` — 384-dim, free, CPU-friendly.
"""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

# Silence the ChromaDB/PostHog telemetry spam caused by a PostHog SDK version
# mismatch. The settings flag alone doesn't stop it — we no-op the capture()
# call at the source so no error line is ever printed.
try:
    from chromadb.telemetry.product import posthog as _chroma_posthog  # type: ignore
    if hasattr(_chroma_posthog, "Posthog"):
        _chroma_posthog.Posthog.capture = lambda self, *a, **k: None
except Exception:
    pass

from config import CHROMA_DIR

COLLECTION = "bse_announcements"
EMBED_MODEL = "all-MiniLM-L6-v2"


def _client():
    return chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )


def _embedder():
    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)


def get_collection():
    return _client().get_or_create_collection(
        name=COLLECTION,
        embedding_function=_embedder(),
        metadata={"hnsw:space": "cosine"},
    )


def _clean_date(raw: str | None) -> str:
    """BSE returns 'YYYY-MM-DDTHH:MM:SS' or 'YYYY-MM-DD'. Normalize to YYYY-MM-DD."""
    if not raw:
        return ""
    s = str(raw).strip().replace("T", " ")
    return s[:10]


def upsert_announcements(symbol: str, scripcode: str, rows: list[dict]) -> int:
    """Add/update announcements for one stock. Returns number of docs written."""
    if not rows:
        return 0

    col = get_collection()
    ids, docs, metas = [], [], []
    for r in rows:
        nid = str(r.get("NEWSID") or "").strip()
        if not nid:
            continue
        category = (r.get("CATEGORYNAME") or "").strip()
        headline = (r.get("HEADLINE") or r.get("NEWSSUB") or "").strip()
        if not headline:
            continue
        date = _clean_date(r.get("NEWS_DT") or r.get("DT_TM"))
        company = (r.get("SLONGNAME") or "").strip()
        page_url = (r.get("NSURL") or "").strip()
        attachment = (r.get("ATTACHMENTNAME") or "").strip()

        ids.append(nid)
        docs.append(f"{category}: {headline}")
        metas.append({
            "symbol": symbol,
            "scripcode": scripcode,
            "date": date,
            "category": category,
            "company": company,
            "page_url": page_url,         # stock-page URL (for UI linking)
            "attachment": attachment,     # PDF filename (for fetcher)
        })

    if not ids:
        return 0
    # Chroma's upsert replaces any existing doc with the same id.
    col.upsert(ids=ids, documents=docs, metadatas=metas)
    return len(ids)


def query_events(
    symbol: str,
    query: str = "",
    days_back: int = 60,
    k: int = 5,
) -> list[dict]:
    """Retrieve top-k relevant announcements for `symbol` over last `days_back` days.

    Date filter is applied in Python (Chroma's $gte doesn't accept strings).
    If `query` is empty, returns most recent announcements for the symbol.
    """
    col = get_collection()
    cutoff_date = datetime.fromordinal(datetime.now().date().toordinal() - days_back).strftime("%Y-%m-%d")
    where = {"symbol": symbol}

    # Load all documents for this symbol via metadata filter (no HNSW).
    # ChromaDB's HNSW index has a low default ef_search that rejects large
    # n_results queries. Using col.get avoids that limit entirely. Per-symbol
    # corpora are typically 100-300 docs so this is fast.
    got = col.get(where=where, limit=2000)
    rows = []
    for i, _id in enumerate(got["ids"]):
        meta = got["metadatas"][i]
        if meta.get("date", "") < cutoff_date:
            continue
        rows.append({
            "id": _id,
            "text": got["documents"][i],
            **meta,
        })

    if not rows:
        return []

    if query.strip():
        # Reuse ChromaDB's stored embeddings instead of re-encoding every doc
        # each call. Fetch them once here (via include=), embed the query once
        # via a module-level cached encoder, and score with pure numpy.
        got_with_emb = col.get(where=where, limit=2000,
                               include=["metadatas", "documents", "embeddings"])
        id_to_emb = {_id: got_with_emb["embeddings"][i]
                     for i, _id in enumerate(got_with_emb["ids"])}
        import numpy as np
        q_vec = _encode_query(query)
        for r in rows:
            emb = id_to_emb.get(r["id"])
            if emb is None:
                r["distance"] = 1.0
                continue
            v = np.asarray(emb, dtype=np.float32)
            v = v / (np.linalg.norm(v) + 1e-9)
            r["distance"] = float(1 - np.dot(v, q_vec))
        rows.sort(key=lambda r: r.get("distance", 1.0))
    else:
        rows.sort(key=lambda r: r.get("date", ""), reverse=True)

    return rows[:k]


# Module-level cached embedder to avoid reloading sentence-transformers on
# every query. First call takes ~3s to load the model; subsequent calls are
# ~10ms.
_ENCODER = None


def _encode_query(text: str):
    """Encode a single query string into a normalized float32 vector."""
    import numpy as np
    from sentence_transformers import SentenceTransformer
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = SentenceTransformer(EMBED_MODEL)
    vec = _ENCODER.encode([text], normalize_embeddings=True)[0]
    return np.asarray(vec, dtype=np.float32)


def stats() -> dict:
    col = get_collection()
    return {"count": col.count()}


def prune_older_than(days: int = 400) -> int:
    """Drop announcements older than `days`. Returns the number deleted.

    `ingest_all` only ever refreshes the trailing 365 days and no caller passes
    a `days_back` above 365, so anything past that is dead weight that only
    grows the committed file. The default keeps a ~5 week margin over the
    ingest window so nothing still in use is dropped.
    """
    col = get_collection()
    cutoff = datetime.fromordinal(datetime.now().date().toordinal() - days).strftime("%Y-%m-%d")

    # Chroma's where-filter can't do string range comparisons, so select in Python.
    got = col.get(include=["metadatas"])
    stale = [
        _id for i, _id in enumerate(got["ids"])
        if (got["metadatas"][i] or {}).get("date", "") and (got["metadatas"][i] or {})["date"] < cutoff
    ]
    if stale:
        # Chunked: a single delete of many thousands of ids blows past SQLite's
        # variable limit inside Chroma.
        for start in range(0, len(stale), 500):
            col.delete(ids=stale[start:start + 500])
    return len(stale)


def vacuum() -> tuple[int, int]:
    """VACUUM the Chroma SQLite file to reclaim space left by daily re-upserts.

    Each refresh re-upserts a full year of announcements, so the file carries a
    growing tail of free pages. Unlike DuckDB this one is not near GitHub's
    100 MiB per-file limit yet, but it is on the same trajectory.

    Returns (bytes_before, bytes_after).
    """
    import sqlite3

    path = CHROMA_DIR / "chroma.sqlite3"
    if not path.exists():
        return (0, 0)

    before = path.stat().st_size
    con = sqlite3.connect(str(path))
    try:
        con.execute("VACUUM")
    finally:
        con.close()
    return (before, path.stat().st_size)
