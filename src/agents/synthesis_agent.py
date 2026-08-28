"""Synthesis agent: unified LLM client (Claude Haiku 4.5 if available + budget
ok, a free provider otherwise) + strict source-grounding prompt.
"""
from __future__ import annotations

import json
import re as _re

from src.agents.prompts import SYNTHESIS_SYSTEM
from src.agents.state import AgentState
from src.agents.llm_client import call_llm


# ────────────────────────────────────────────────────────────────────────────
# Boilerplate stripping + PDF formatting helpers
# ────────────────────────────────────────────────────────────────────────────
_BOILERPLATE_PATTERNS = [
    r"Regd\.?\s*Office:.*?(?=\n\n|\nSub:|\nDear)",
    r"Corporate Office:.*?(?=\n\n|\nSub:|\nDear)",
    r"CIN[-:]\s*[A-Z0-9]+",
    r"Tel\s*\+?91[^\n]{0,40}",
    r"E-?mail:[^\n]{0,80}",
    r"Website:[^\n]{0,80}",
    r"BSE Limited[\s\S]{0,200}Mumbai[\s\S]{0,40}",
    r"National Stock Exchange[\s\S]{0,200}Mumbai[\s\S]{0,40}",
    r"Scrip Code:\s*\d+",
    r"Trading Symbol:[^\n]{0,40}",
    r"Dear Sirs?,?",
]


def _strip_boilerplate(text: str) -> str:
    out = text
    for pat in _BOILERPLATE_PATTERNS:
        out = _re.sub(pat, "", out, flags=_re.IGNORECASE | _re.DOTALL)
    out = _re.sub(r"\s{2,}", " ", out)
    return out.strip()


def _format_events(events: list[dict]) -> str:
    lines = []
    for ev in events:
        date = ev.get("date", "?")
        cat = ev.get("category", "?")
        headline = ev.get("text", "")
        mark = "*" if ev.get("material") else " "
        lines.append(f"{mark} [event:{date}] {cat}: {headline}")
        if ev.get("material") and ev.get("full_text"):
            cleaned = _strip_boilerplate(ev["full_text"])
            snippet = cleaned[:2000].replace("\n", " ")
            lines.append(f"    PDF excerpt: {snippet}")
    return "\n".join(lines) if lines else "  (no recent announcements)"


def _r(v, nd=2):
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return v


def _format_context(state: AgentState) -> str:
    symbol = state.get("symbol", "?")
    date = state.get("query_date", "?")

    price = state.get("price") or {}
    events = (state.get("events") or {}).get("events", [])
    flow = state.get("flow") or {}
    macro = state.get("macro") or {}

    price_block = json.dumps({
        "symbol": price.get("symbol"),
        "date": price.get("date"),
        "pct_change_1d": _r(price.get("pct_change_1d")),
        "pct_from_52w_high": _r(price.get("pct_from_52w_high"), 1),
        "dist_50dma_pct": _r(price.get("dist_50dma_pct"), 1),
        "vol_vs_20d_avg": _r(price.get("vol_vs_20d_avg")),
        "sector_return_pct": _r(price.get("sector_return_pct")),
        "nifty_return_pct": _r(price.get("nifty_return_pct")),
        "move_vs_sector_pct": _r(price.get("move_vs_sector_pct")),
        "notes": price.get("notes", []),
    }, indent=2, default=str)

    flow_block = json.dumps({
        "date": flow.get("date"),
        "fii_net_cr": _r(flow.get("fii_net_cr"), 0),
        "dii_net_cr": _r(flow.get("dii_net_cr"), 0),
        "fii_5d_trend_cr": _r(flow.get("fii_5d_trend_cr"), 0),
        "days_available": flow.get("days_available"),
        "note": flow.get("note"),
    }, indent=2, default=str)

    macro_block = json.dumps({
        "date": macro.get("date"),
        "crude_wti": _r(macro.get("crude_wti")),
        "crude_1d_chg_pct": _r(macro.get("crude_1d_chg_pct")),
        "vix": _r(macro.get("vix")),
        "vix_20d_avg": _r(macro.get("vix_20d_avg")),
        "us_10y": _r(macro.get("us_10y"), 2),
        "usd_inr": _r(macro.get("usd_inr"), 2),
        "risk_off": macro.get("risk_off"),
        "notes": macro.get("notes", []),
    }, indent=2, default=str)

    context = f"""
QUERY: Explain what drove {symbol} on {date}. User context: "{state.get('user_query','')}"

========== [price] ==========
{price_block}

========== [event] (recent BSE filings for this stock) ==========
{_format_events(events)}

========== [flow] (NSE FII/DII net, Rs crore) ==========
{flow_block}

========== [macro] (FRED global indicators) ==========
{macro_block}
"""
    # Cap total context to stay within model input limits across all providers.
    if len(context) > 12000:
        context = context[:12000] + "\n\n[context truncated to fit model input limit]"
    return context


def _parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:].strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found in model output: {text[:200]}")
    return json.loads(t[start:end + 1])


def synthesis_agent(state: AgentState) -> dict:
    context = _format_context(state)

    # call_llm() handles routing: Claude Haiku if budget allows, else a free provider.
    # Prompt caching on the system message keeps repeat calls cheap on Anthropic.
    r = call_llm(
        system=SYNTHESIS_SYSTEM,
        user=context,
        agent="synthesis",
        json_mode=True,
        max_tokens=1200,
        temperature=0.1,
        prefer="paid",
        cache_system=True,
    )
    raw = r.text
    if not raw.strip():
        return {
            "explanation": "(LLM returned an empty response — likely budget cap or provider error)",
            "confidence": "low",
            "primary_driver": "unclear",
            "citations": [],
        }
    try:
        data = _parse_json(raw)
    except Exception as e:
        return {
            "explanation": f"(synthesis parse error: {e})\nRaw model output:\n{raw}",
            "confidence": "low",
            "primary_driver": "unclear",
            "citations": [],
        }

    return {
        "explanation": (data.get("explanation") or "").strip(),
        "primary_driver": (data.get("primary_driver") or "unclear").lower().strip(),
        "classification_reason": (data.get("classification_reason") or "").strip(),
        "confidence": (data.get("confidence") or "low").lower().strip(),
        "citations": data.get("citations") or [],
    }


if __name__ == "__main__":
    from src.agents.price_agent import price_agent
    from src.agents.event_agent import event_agent
    from src.agents.flow_agent import flow_agent
    from src.agents.macro_agent import macro_agent
    from src.agents.llm_client import budget_headroom_usd

    print(f"Daily budget headroom: ${budget_headroom_usd():.4f}")

    state: AgentState = {"symbol": "EICHERMOT.NS", "query_date": "2026-04-13", "user_query": ""}
    state.update(price_agent(state))
    state.update(event_agent(state))
    state.update(flow_agent(state))
    state.update(macro_agent(state))

    out = synthesis_agent(state)
    print("=" * 70)
    print(f"primary_driver: {out['primary_driver']}")
    print(f"confidence:     {out['confidence']}")
    print(f"citations:      {out['citations']}")
    print("-" * 70)
    print(out["explanation"])
    print("=" * 70)
