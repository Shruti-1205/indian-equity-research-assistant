"""Unified LLM client with cost tracking, hard daily-budget cap, and Anthropic
prompt caching. Every call is logged to `llm_usage` so you can audit spend.

Design goals
────────────
1. Never silently exceed DAILY_USD_BUDGET. If the next call would push today's
   spend over the cap, we raise BudgetExceededError — no fallback to paid.
2. Free providers (Groq) are always available regardless of budget state.
3. Prompt caching for Anthropic: the system prompt is marked cacheable so
   repeat calls within ~5 min pay ~10× less on those tokens.
4. One log row per call in DuckDB. Use `scripts.usage` to review.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any

from config import (
    ANTHROPIC_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY,
    DAILY_USD_BUDGET,
    SYNTHESIS_PRIMARY_MODEL, SYNTHESIS_CEREBRAS_MODEL, SYNTHESIS_GROQ_MODEL,
    GROQ_FAST_MODEL,
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
    # Groq free tier — billed as $0 for tracking purposes. The "openai/" prefix
    # is part of Groq's model id and keeps these distinct from the Cerebras
    # gpt-oss entry below, which is genuinely paid.
    "openai/gpt-oss-120b":     {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
    "openai/gpt-oss-20b":      {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
    # Cerebras — free daily quota, then pay-as-you-go at these rates.
    "llama-3.3-70b":           {"input": 0.0,  "output": 0.0,  "cache_read": 0.0, "cache_write": 0.0},
    "llama3.1-8b":             {"input": 0.10, "output": 0.10, "cache_read": 0.0, "cache_write": 0.0},
    "gpt-oss-120b":            {"input": 0.35, "output": 0.75, "cache_read": 0.0, "cache_write": 0.0},
    "zai-glm-4.7":             {"input": 2.25, "output": 2.75, "cache_read": 0.0, "cache_write": 0.0},
    "qwen-3-235b-a22b-instruct-2507": {"input": 0.60, "output": 1.20, "cache_read": 0.0, "cache_write": 0.0},
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


# ────────────── Cerebras (OpenAI-compatible) ──────────────

def _call_cerebras(
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
) -> LLMResult:
    from openai import OpenAI
    client = OpenAI(
        base_url="https://api.cerebras.ai/v1",
        api_key=CEREBRAS_API_KEY,
    )

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    # Cerebras free-tier sometimes returns queue_exceeded (429) under load.
    # Short retry with exponential backoff handles this gracefully; after ~12s
    # total wait, we bubble up so the router can cascade to Groq.
    t0 = time.time()
    last_err: Exception | None = None
    for attempt, wait in enumerate((0, 1.5, 3, 6)):
        if wait:
            time.sleep(wait)
        try:
            resp = client.chat.completions.create(**kwargs)
            last_err = None
            break
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            # Only retry for transient queue/load errors. Don't retry auth / not-found.
            if "queue" not in msg and "too_many_requests" not in msg and "overloaded" not in msg:
                raise
    if last_err is not None:
        raise last_err
    latency = int((time.time() - t0) * 1000)

    text = resp.choices[0].message.content or ""
    usage = resp.usage
    in_tok  = getattr(usage, "prompt_tokens", 0) or 0
    out_tok = getattr(usage, "completion_tokens", 0) or 0
    return LLMResult(
        text=text, model=model, provider="cerebras",
        input_tokens=in_tok, output_tokens=out_tok,
        cost_usd=0.0,  # Cerebras free tier
        latency_ms=latency,
    )


# ────────────── Groq ──────────────

def _call_groq(
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
) -> LLMResult:
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    t0 = time.time()
    resp = client.chat.completions.create(**kwargs)
    latency = int((time.time() - t0) * 1000)

    text = resp.choices[0].message.content or ""
    usage = resp.usage
    in_tok  = getattr(usage, "prompt_tokens", 0) or 0
    out_tok = getattr(usage, "completion_tokens", 0) or 0
    return LLMResult(
        text=text, model=model, provider="groq",
        input_tokens=in_tok, output_tokens=out_tok,
        cost_usd=0.0,  # Groq free tier
        latency_ms=latency,
    )


# ────────────── Public router ──────────────

def call_llm(
    system: str,
    user: str,
    agent: str,
    *,
    json_mode: bool = False,
    max_tokens: int = 1200,
    temperature: float = 0.0,
    prefer: str = "paid",        # "paid" (Claude if budget) or "free" (Groq)
    cache_system: bool = True,
) -> LLMResult:
    """Route an LLM call with budget enforcement + logging.

    Routing cascade for agent='synthesis' (tries each in order, falls back on failure):
      1. Claude Haiku 4.5 — if ANTHROPIC_API_KEY set AND today's spend ≤ DAILY_USD_BUDGET
      2. Cerebras Qwen 3 235B — if CEREBRAS_API_KEY set (free, 10× Groq quota)
      3. Groq gpt-oss-120b — always (free, small daily quota)

    agent='verifier' or 'orchestrator' → always routes to the small free Groq model.
    """
    # Force free path for low-stakes agents regardless of 'prefer'.
    if agent in ("orchestrator", "verifier"):
        prefer = "free"

    # Step 1: try Claude if paid is preferred and budget allows.
    use_paid = (
        prefer == "paid"
        and ANTHROPIC_API_KEY
        and DAILY_USD_BUDGET > 0
        and _spend_today() < DAILY_USD_BUDGET
    )
    _debug(f"routing agent={agent} prefer={prefer} use_paid={use_paid} spend={_spend_today():.4f}")
    if use_paid:
        try:
            _debug(f"attempting Anthropic {SYNTHESIS_PRIMARY_MODEL}")
            r = _call_anthropic(
                SYNTHESIS_PRIMARY_MODEL, system, user,
                max_tokens=max_tokens, temperature=temperature,
                use_cache=cache_system,
            )
            _log("anthropic", SYNTHESIS_PRIMARY_MODEL, agent, r)
            _debug(f"Anthropic OK in={r.input_tokens} out={r.output_tokens} cost=${r.cost_usd:.4f}")
            if _spend_today() > DAILY_USD_BUDGET:
                r.text = r.text + f"\n\n[note: daily USD budget (${DAILY_USD_BUDGET}) reached, subsequent synthesis calls will use a free provider]"
            return r
        except Exception as e:
            _debug(f"Anthropic failed: {type(e).__name__}: {e}")
            _log("anthropic", SYNTHESIS_PRIMARY_MODEL, agent,
                 LLMResult("", SYNTHESIS_PRIMARY_MODEL, "anthropic", 0, 0),
                 note=f"failed, cascading: {type(e).__name__}")

    # Step 2: try Cerebras if configured (free, big quota).
    if agent == "synthesis" and CEREBRAS_API_KEY:
        try:
            _debug(f"attempting Cerebras {SYNTHESIS_CEREBRAS_MODEL}")
            r = _call_cerebras(
                SYNTHESIS_CEREBRAS_MODEL, system, user,
                max_tokens=max_tokens, temperature=temperature, json_mode=json_mode,
            )
            _log("cerebras", SYNTHESIS_CEREBRAS_MODEL, agent, r, note="free-tier")
            _debug(f"Cerebras OK in={r.input_tokens} out={r.output_tokens}")
            return r
        except Exception as e:
            _debug(f"Cerebras failed: {type(e).__name__}: {e}")
            _log("cerebras", SYNTHESIS_CEREBRAS_MODEL, agent,
                 LLMResult("", SYNTHESIS_CEREBRAS_MODEL, "cerebras", 0, 0),
                 note=f"failed, cascading: {type(e).__name__}")

    # Step 3: Groq (always free, small quota).
    free_model = SYNTHESIS_GROQ_MODEL if agent == "synthesis" else GROQ_FAST_MODEL
    _debug(f"attempting Groq {free_model}")
    r = _call_groq(
        free_model, system, user,
        max_tokens=max_tokens, temperature=temperature, json_mode=json_mode,
    )
    _log("groq", free_model, agent, r, note="free-tier")
    _debug(f"Groq OK in={r.input_tokens} out={r.output_tokens}")
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
