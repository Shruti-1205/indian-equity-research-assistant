"""Orchestrator: parses the user's free-text query into structured task fields.

Uses Groq (fast, cheap) with a strict JSON-output prompt. Deterministic
fast-path for queries that already look structured (e.g. "EICHERMOT.NS 2026-04-13").
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from config import COMPANY_NAMES, GROQ_API_KEY
from src.agents.llm_client import call_llm
from src.agents.prompts import ORCHESTRATOR_SYSTEM
from src.data.bse_codes import NSE_TO_BSE

VALID_SYMBOLS = set(NSE_TO_BSE.keys())

# The UI labels everything with company names, so a user reasonably types (or
# the LLM echoes back) "Tata Motors Passenger Vehicles" rather than TMPV.NS.
# Resolve those to tickers instead of failing to a blank "unknown" intent.
_NAME_TO_SYMBOL = {name.upper(): sym for sym, name in COMPANY_NAMES.items()}
_TICKER_RE = re.compile(r"\b([A-Z&\-]{2,12})\.NS\b")
_DATE_RE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")


def _today_iso() -> str:
    return date.today().isoformat()


def _fast_parse(text: str) -> dict | None:
    """Deterministic fast-path: if the query is already 'TICKER.NS YYYY-MM-DD',
    skip the LLM to save latency + tokens."""
    sym_match = _TICKER_RE.search(text.upper())
    date_match = _DATE_RE.search(text)
    if sym_match:
        sym = sym_match.group(0).upper()
        if sym in VALID_SYMBOLS:
            query_date = _today_iso()
            if date_match:
                y, m, d = date_match.groups()
                try:
                    query_date = datetime(int(y), int(m), int(d)).date().isoformat()
                except ValueError:
                    pass
            return {
                "intent": "explain_move",
                "symbol": sym,
                "query_date": query_date,
                "user_hint": "",
            }
    return None


def _coerce_symbol(sym: str | None) -> str | None:
    if not sym:
        return None
    s = sym.strip().upper()
    if s in _NAME_TO_SYMBOL:
        return _NAME_TO_SYMBOL[s]
    if not s.endswith(".NS"):
        s = s + ".NS"
    return s if s in VALID_SYMBOLS else None


def _coerce_date(s: str | None, today: str) -> str:
    if not s:
        return today
    s = s.strip().lower()
    if s in ("today", "<today>", ""):
        return today
    if s in ("yesterday",):
        return (date.today() - timedelta(days=1)).isoformat()
    m = _DATE_RE.search(s)
    if m:
        y, mo, d = m.groups()
        try:
            return datetime(int(y), int(mo), int(d)).date().isoformat()
        except ValueError:
            pass
    return today


def orchestrate(user_query: str) -> dict:
    """Parse free-text into a task dict consumable by the main pipeline."""
    user_query = (user_query or "").strip()
    if not user_query:
        return {"intent": "unknown", "symbol": None, "query_date": _today_iso(), "user_hint": ""}

    fast = _fast_parse(user_query)
    if fast is not None:
        return fast

    if not GROQ_API_KEY:
        # Degraded fallback: try to detect a ticker in raw text.
        for sym in VALID_SYMBOLS:
            bare = sym.replace(".NS", "")
            if re.search(rf"\b{re.escape(bare)}\b", user_query.upper()):
                return {"intent": "explain_move", "symbol": sym,
                        "query_date": _today_iso(), "user_hint": ""}
        return {"intent": "unknown", "symbol": None,
                "query_date": _today_iso(), "user_hint": ""}

    today = _today_iso()
    system = ORCHESTRATOR_SYSTEM.replace("<today>", today)

    r = call_llm(
        system=system,
        user=user_query,
        agent="orchestrator",       # forced to the small free Groq model by the router
        json_mode=True,
        max_tokens=200,
        temperature=0.0,
    )
    try:
        parsed = json.loads(r.text or "{}")
    except json.JSONDecodeError:
        parsed = {}

    return {
        "intent": parsed.get("intent") or "unknown",
        "symbol": _coerce_symbol(parsed.get("symbol")),
        "query_date": _coerce_date(parsed.get("query_date"), today),
        "user_hint": (parsed.get("user_hint") or "").strip(),
    }


if __name__ == "__main__":
    tests = [
        "Why did RELIANCE drop today?",
        "What happened to Eichermot on April 13?",
        "Any TCS earnings news this week?",
        "EICHERMOT.NS 2026-04-13",
        "how is maruti doing",
    ]
    for q in tests:
        print(f"> {q}")
        print(f"  → {orchestrate(q)}")
