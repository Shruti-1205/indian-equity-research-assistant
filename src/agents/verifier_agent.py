"""Verifier agent: runs AFTER synthesis. Uses the numeric validator + a second
Groq call to catch and rewrite any hallucinated numbers in the explanation.

If the validator finds zero unverified claims, the verifier returns the draft
unchanged but annotated with 'validation_ok: true'. Otherwise it asks Groq to
rewrite, citing the flagged numbers explicitly.
"""
from __future__ import annotations

import json

from src.agents.llm_client import call_llm
from src.agents.prompts import VERIFIER_SYSTEM
from src.agents.state import AgentState
from src.agents.validator import validate_numbers
from src.agents.synthesis_agent import _format_context, _parse_json


def verifier_agent(state: AgentState) -> dict:
    explanation = state.get("explanation") or ""
    if not explanation:
        return {}

    audit = validate_numbers(state, explanation)
    unverified = audit["unverified"]

    # Fast path: nothing to fix. Annotate and return.
    if not unverified:
        return {
            "validation_ok": True,
            "unverified_claims": [],
            "changes_made": False,
        }

    context_block = _format_context(state)
    draft_block = json.dumps({
        "explanation": explanation,
        "primary_driver": state.get("primary_driver"),
        "confidence": state.get("confidence"),
        "citations": state.get("citations", []),
    }, indent=2)

    user_msg = f"""SOURCE CONTEXT
{context_block}

DRAFT EXPLANATION (to audit)
{draft_block}

UNVERIFIED CLAIMS (numbers from the draft that were NOT found in the source context):
{json.dumps(unverified, indent=2)}

Task: rewrite the explanation to remove or correct every unverified claim,
using only numbers that actually appear in the source context above.
"""

    r = call_llm(
        system=VERIFIER_SYSTEM,
        user=user_msg,
        agent="verifier",           # forced to free Groq 8B by the router
        json_mode=True,
        max_tokens=1200,
        temperature=0.0,
    )
    raw = r.text
    try:
        data = _parse_json(raw)
    except Exception as e:
        return {
            "validation_ok": False,
            "unverified_claims": unverified,
            "changes_made": False,
            "explanation": explanation + f"\n\n[verifier parse error: {e}]",
        }

    # Re-validate the rewritten explanation (should now be clean).
    new_expl = (data.get("explanation") or "").strip()
    post = validate_numbers(state, new_expl) if new_expl else {"unverified": []}

    # Last-resort deterministic cleaner: if the verifier LLM still left unverified
    # numbers in place, physically redact them. Better to show "[unverified]" to
    # the user than a fabricated figure.
    redacted_claims: list[str] = []
    if post["unverified"]:
        cleaned_expl, redacted_claims = _hard_redact(new_expl, post["unverified"])
        new_expl = cleaned_expl
        post = validate_numbers(state, new_expl)

    total_removed = list(data.get("hallucinations_removed", []) or []) + redacted_claims

    return {
        "explanation": new_expl or explanation,
        "primary_driver": (data.get("primary_driver") or state.get("primary_driver") or "unclear").lower(),
        "confidence": "low" if redacted_claims else (
            data.get("confidence") or state.get("confidence") or "low"
        ).lower(),
        "citations": data.get("citations") or state.get("citations", []),
        "validation_ok": len(post["unverified"]) == 0,
        "unverified_claims": post["unverified"],
        "changes_made": bool(data.get("changes_made", True)) or bool(redacted_claims),
        "hallucinations_removed": total_removed,
    }


def _hard_redact(text: str, unverified: list[str]) -> tuple[str, list[str]]:
    """Physically replace unverified numeric tokens with '[unverified]' in the text.

    `unverified` items look like '12,334 (int)' — strip the kind suffix first.
    """
    import re as _re
    out = text
    removed: list[str] = []
    for item in unverified:
        raw = item.split(" (")[0].strip()
        if not raw:
            continue
        # Build a pattern tolerant of optional %, comma, Indian lakh notation.
        base = _re.escape(raw)
        pattern = rf"(?<!\d){base}(?:\s?%)?"
        new, n = _re.subn(pattern, "[unverified]", out)
        if n > 0:
            removed.append(raw)
            out = new
    return out, removed
