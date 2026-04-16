"""Centralised trading-date helpers.

Used everywhere that "today's date" needs to be resolved to the most recent
trading day with actual data in the database. Avoids scattered fallback
logic across handlers.
"""
from __future__ import annotations

from datetime import date, datetime

from src.data.db import get_conn


def latest_trading_date() -> str:
    """Return the most recent YYYY-MM-DD that has feature data."""
    con = get_conn()
    d = con.execute("SELECT MAX(date) FROM features").fetchone()[0]
    con.close()
    return str(d) if d else date.today().isoformat()


def effective_date(requested: str) -> str:
    """Resolve a requested date to the closest trading date on or before it.

    If the requested date has no data (weekend, holiday, future date), we fall
    back to the most recent prior trading day in the database. The returned
    string is always YYYY-MM-DD.
    """
    con = get_conn()
    row = con.execute(
        "SELECT MAX(date) FROM features WHERE date <= CAST(? AS DATE)",
        [requested],
    ).fetchone()
    con.close()
    if row and row[0]:
        return str(row[0])
    # Fallback to absolute latest if the requested date is before our data window.
    return latest_trading_date()


def is_verbose() -> bool:
    """Check whether DEBUG=1 is set in the environment. Used for verbose logs."""
    import os
    return os.getenv("DEBUG", "").lower() in ("1", "true", "yes")
