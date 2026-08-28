"""Unified LLM client with cost tracking, hard daily-budget cap, and Anthropic
prompt caching. Every call is logged to `llm_usage` so you can audit spend.

Design goals
────────────
1. Never silently exceed DAILY_USD_BUDGET. If the next call would push today's
   spend over the cap, we raise BudgetExceededError rather than spending.
2. Prompt caching: the system prompt is marked cacheable so repeat calls within
   ~5 min pay ~10× less on those tokens. The synthesis system prompt is ~4k
   tokens, so this is most of the input cost.
3. One log row per call in DuckDB. Use `scripts.usage` to review.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any

from config import (
    ANTHROPIC_API_KEY,
    DAILY_USD_BUDGET,
    SYNTHESIS_PRIMARY_MODEL, FAST_MODEL,
)
from src.data.db import get_conn, init_schema


def _debug(msg: str) -> None:
    """Print a diagnostic line when DEBUG=1 is in the env."""
    import os as _os
    if _os.getenv("DEBUG", "").lower() in ("1", "true", "yes"):
        print(f"[llm] {msg}")


class BudgetExceededError(RuntimeError):
    pass


# ────────────── Pricing table (USD per 1M tokens) ──────────────
# Anthropic Haiku 4.5 prompt caching: cached reads are ~$0.10/M vs $1.00/M.
PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input": 1.00, "output": 5.00,
        "cache_read": 0.10, "cache_write": 1.25,
    },
    "claude-sonnet-4-5": {
        "input": 3.00, "output": 15.00,
        "cache_read": 0.30, "cache_write": 3.75,
    },
}


@dataclass
class LLMResult:
    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


def _compute_cost(model: str, in_tok: int, out_tok: int,
                  cache_r: int = 0, cache_w: int = 0) -> float:
    """Compute USD cost for a single LLM call.

    Anthropic reports input_tokens, cache_read_input_tokens, and
    cache_creation_input_tokens as separate non-overlapping fields. We bill
    each category at its own rate. Earlier versions of this function
    subtracted cache counts from input_tokens, which double-deducted and
    produced a negative that got clamped to zero.
    """
    p = PRICING.get(model, {})
    c = 0.0
    c += in_tok * p.get("input", 0) / 1_000_000
    c += out_tok * p.get("output", 0) / 1_000_000
    c += cache_r * p.get("cache_read", 0) / 1_000_000
    c += cache_w * p.get("cache_write", 0) / 1_000_000
    return max(c, 0.0)


def _spend_today() -> float:
    init_schema()
    con = get_conn()
    row = con.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage WHERE CAST(ts AS DATE) = CURRENT_DATE"
    ).fetchone()
    con.close()
    return float(row[0] or 0.0)


def budget_headroom_usd() -> float:
    """How much of today's DAILY_USD_BUDGET remains before paid calls are blocked."""
    return max(DAILY_USD_BUDGET - _spend_today(), 0.0)


def _log(provider: str, model: str, agent: str, r: LLMResult, note: str = "") -> None:
    init_schema()
    con = get_conn()
    con.execute(
        """
        INSERT INTO llm_usage (
          id, ts, provider, model, agent,
          input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
          cost_usd, latency_ms, note
        )
        VALUES (nextval('llm_usage_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            datetime.now(), provider, model, agent,
            r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens,
            r.cost_usd, r.latency_ms, note,
        ],
    )
    con.close()


# ────────────── Anthropic (Claude) ──────────────

def _call_anthropic(
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    use_cache: bool,
) -> LLMResult:
    from anthropic import Anthropic
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    system_param: Any = system
    if use_cache:
        # Anthropic prompt caching: mark the system block as cacheable.
        system_param = [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }]

    t0 = time.time()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_param,
        messages=[{"role": "user", "content": user}],
    )
    latency = int((time.time() - t0) * 1000)

    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    usage = resp.usage
    in_tok  = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0
    cache_r = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_w = getattr(usage, "cache_creation_input_tokens", 0) or 0

    cost = _compute_cost(model, in_tok, out_tok, cache_r, cache_w)
    return LLMResult(
        text=text, model=model, provider="anthropic",
        input_tokens=in_tok, output_tokens=out_tok,
        cache_read_tokens=cache_r, cache_write_tokens=cache_w,
        cost_usd=cost, latency_ms=latency,
    )


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _coerce_json_text(text: str) -> str:
    """Strip markdown fencing / prose so `json.loads` succeeds.

    Anthropic has no `response_format=json_object` equivalent, so Claude
    routinely wraps JSON in a ```json fence even when the prompt forbids it.
    Callers that json.loads() the raw text would fail on every response, so we
    normalise here rather than in each agent.
    """
    t = _FENCE_RE.sub("", text.strip())
    if t.startswith("{"):
        return t
    start, end = t.find("{"), t.rfind("}")
    return t[start:end + 1] if start != -1 and end > start else t


# ────────────── Public router ──────────────

def call_llm(
    system: str,
    user: str,
    agent: str,
    *,
    json_mode: bool = False,
    max_tokens: int = 1200,
    temperature: float = 0.0,
    cache_system: bool = True,
) -> LLMResult:
    """Run an LLM call with budget enforcement + logging.

    Every agent runs on Claude. `agent` selects the token ceiling, not the
    provider: synthesis reasons over the full evidence bundle, while the
    orchestrator and verifier do cheap structured work.

    Raises BudgetExceededError when today's spend has reached DAILY_USD_BUDGET,
    and RuntimeError when no API key is configured. Both are surfaced to the
    caller rather than silently degrading the answer.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env locally, or to the "
            "app's secrets when deployed."
        )

    spend = _spend_today()
    if DAILY_USD_BUDGET <= 0 or spend >= DAILY_USD_BUDGET:
        raise BudgetExceededError(
            f"Daily budget of ${DAILY_USD_BUDGET:.2f} reached (spent ${spend:.4f}). "
            "Raise DAILY_USD_BUDGET or wait for the counter to reset at midnight UTC."
        )

    model = SYNTHESIS_PRIMARY_MODEL if agent == "synthesis" else FAST_MODEL
    _debug(f"routing agent={agent} model={model} spend={spend:.4f}")

    try:
        r = _call_anthropic(
            model, system, user,
            max_tokens=max_tokens, temperature=temperature,
            use_cache=cache_system,
        )
    except Exception as e:
        # Log the failure so a bad key or a retired model id shows up in
        # `scripts.usage` instead of only in a traceback.
        _log("anthropic", model, agent,
             LLMResult("", model, "anthropic", 0, 0),
             note=f"failed: {type(e).__name__}")
        _debug(f"Anthropic failed: {type(e).__name__}: {e}")
        raise

    if json_mode:
        r.text = _coerce_json_text(r.text)

    # A logging failure must not discard a call that already succeeded and cost money.
    try:
        _log("anthropic", model, agent, r)
    except Exception as e:
        _debug(f"usage logging failed (call still succeeded): {type(e).__name__}: {e}")

    _debug(f"Anthropic OK in={r.input_tokens} out={r.output_tokens} cost=${r.cost_usd:.4f}")
    return r


def usage_summary(days: int = 7) -> dict:
    init_schema()
    con = get_conn()
    today_spend = _spend_today()
    # DuckDB doesn't allow parameterised INTERVALs; we coerce to int to prevent injection.
    days_int = int(days)
    by_agent = con.execute(f"""
        SELECT agent, provider, model,
               COUNT(*)       AS calls,
               SUM(input_tokens + output_tokens) AS tok,
               ROUND(SUM(cost_usd), 4) AS cost_usd
        FROM llm_usage
        WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '{days_int}' DAY
        GROUP BY agent, provider, model
        ORDER BY cost_usd DESC
    """).df()
    con.close()
    return {
        "today_spend_usd": round(today_spend, 4),
        "daily_budget_usd": DAILY_USD_BUDGET,
        "budget_remaining_usd": round(max(DAILY_USD_BUDGET - today_spend, 0), 4),
        "by_agent_last_{}d".format(days): by_agent.to_dict(orient="records"),
    }
