"""Shared state passed between LangGraph agents."""
from __future__ import annotations

from typing import Optional, TypedDict


class PriceContext(TypedDict, total=False):
    symbol: str
    date: str
    pct_change_1d: Optional[float]
    pct_from_52w_high: Optional[float]
    pct_from_52w_low: Optional[float]
    dist_50dma_pct: Optional[float]
    dist_200dma_pct: Optional[float]
    vol_vs_20d_avg: Optional[float]
    vol_zscore_20d: Optional[float]
    sector_return_pct: Optional[float]
    nifty_return_pct: Optional[float]
    move_vs_sector_pct: Optional[float]  # stock_pct - sector_pct
    notes: list[str]


class EventContext(TypedDict, total=False):
    events: list[dict]   # each: {date, category, headline, full_text, page_url, pdf_status}
    event_count: int
    has_material: bool
    note: str


class FlowContext(TypedDict, total=False):
    date: str
    fii_net_cr: Optional[float]
    dii_net_cr: Optional[float]
    fii_5d_trend_cr: Optional[float]
    days_available: int
    note: str


class MacroContext(TypedDict, total=False):
    date: str
    crude_wti: Optional[float]
    crude_1d_chg_pct: Optional[float]
    vix: Optional[float]
    vix_20d_avg: Optional[float]
    usd_inr: Optional[float]
    us_10y: Optional[float]
    dxy: Optional[float]
    risk_off: bool
    notes: list[str]


class AgentState(TypedDict, total=False):
    # Inputs
    symbol: str
    query_date: str            # YYYY-MM-DD
    user_query: str            # free-text, optional
    # Populated by data agents
    price: PriceContext
    events: EventContext
    flow: FlowContext
    macro: MacroContext
    # Populated by synthesis
    explanation: str
    confidence: str                 # 'high' | 'medium' | 'low'
    primary_driver: str             # 'company' | 'sector' | 'unclear'
    classification_reason: str      # short numeric justification for driver choice
    citations: list[str]
    # Populated by verifier
    validation_ok: bool
    unverified_claims: list[str]
    changes_made: bool
    hallucinations_removed: list[str]
