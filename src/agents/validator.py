"""Programmatic numeric-claim validator for synthesis output.

We extract every percentage, rupee figure, and significant integer from the
explanation and check that it appears in the combined source context. Numbers
that can't be matched (after light normalization) are flagged as possible
hallucinations so the verifier agent can correct them.

Intentionally conservative: we'd rather flag a few false positives (the LLM
rephrased "13.6%" as "14%") than miss real fabrications.
"""
from __future__ import annotations

import re
from typing import Iterable

from src.agents.state import AgentState

# Patterns chosen to cover: "-5.04%", "+23%", "₹1,983 crore", "₹1983cr",
# "101,071 units", "13,113", "4.30", "94,047"
_RE_PCT = re.compile(r"(?<![\w\d.])(-?\+?\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s?%")
_RE_RUPEE = re.compile(
    r"(?:₹|Rs\.?\s*)\s?(-?\+?\d[\d,]*(?:\.\d+)?)\s?(?:cr|crore|crores|lakh|lakhs)?",
    flags=re.IGNORECASE,
)
_RE_BIG_INT = re.compile(r"(?<![\w.])(-?\+?\d{2,3}(?:,\d{3})+(?:\.\d+)?)(?!\w)")
_RE_PLAIN_DEC = re.compile(r"(?<![\w\d.])(-?\d+\.\d{1,3})(?!\w)")


def _normalise(tok: str) -> str:
    """Strip whitespace, leading +, and commas; keep sign and decimals."""
    t = tok.strip().replace(",", "").lstrip("+")
    return t


def _number_variants(tok: str) -> set[str]:
    """Return the set of string forms a number might take in source text.

    e.g. '13.6' -> {'13.6', '13.60', '13'}; '-69.4' -> {'-69.4', '-69.40', '-69', '69.4', '69'}.
    """
    variants: set[str] = set()
    t = _normalise(tok)
    if not t:
        return variants
    variants.add(t)
    try:
        n = float(t)
    except ValueError:
        return variants

    # Sign-stripped form — source tables often show negatives via layout/colour.
    abs_str = t.lstrip("-")
    variants.add(abs_str)

    # Integer truncation
    int_str = str(int(n)) if n == int(n) else str(int(n))
    variants.add(int_str)
    variants.add(int_str.lstrip("-"))

    # Fixed 1-decimal
    variants.add(f"{n:.1f}")
    variants.add(f"{abs(n):.1f}")

    # Fixed 2-decimal
    variants.add(f"{n:.2f}")
    variants.add(f"{abs(n):.2f}")

    # Strip trailing .0
    if t.endswith(".0"):
        variants.add(t[:-2])

    return {v for v in variants if v}


def _extract_claims(text: str) -> list[tuple[str, str]]:
    """Return a list of (kind, token) pairs. `kind` is used for diagnostics only."""
    claims: list[tuple[str, str]] = []
    for m in _RE_PCT.finditer(text):
        claims.append(("pct", m.group(1)))
    for m in _RE_RUPEE.finditer(text):
        claims.append(("rupee", m.group(1)))
    for m in _RE_BIG_INT.finditer(text):
        claims.append(("int", m.group(1)))
    for m in _RE_PLAIN_DEC.finditer(text):
        claims.append(("dec", m.group(1)))
    return claims


def _haystack(state: AgentState) -> str:
    """Flatten everything the LLM was allowed to see into one searchable string."""
    parts: list[str] = []

    price = state.get("price") or {}
    for k, v in price.items():
        parts.append(f"{k}={v}")

    events = (state.get("events") or {}).get("events", [])
    for ev in events:
        parts.append(ev.get("text", ""))
        parts.append(ev.get("full_text", "") or "")

    flow = state.get("flow") or {}
    for k, v in flow.items():
        parts.append(f"{k}={v}")

    macro = state.get("macro") or {}
    for k, v in macro.items():
        parts.append(f"{k}={v}")

    return " \n ".join(str(p) for p in parts if p)


_HAYSTACK_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _haystack_number_tokens(hay: str) -> set[str]:
    """Extract all distinct numeric tokens and tight rounded variants.

    Rounding tolerance: 2dp and 1dp only. We intentionally do NOT include
    integer rounding, because 10.6 → 11 would false-match fabricated '11%'.
    """
    cleaned = hay.replace(",", "")
    raw_tokens = set(_HAYSTACK_NUM.findall(cleaned))
    out: set[str] = set(raw_tokens)
    for tok in raw_tokens:
        try:
            n = float(tok)
        except ValueError:
            continue
        # 2dp and 1dp rounding are always safe.
        for form in (f"{n:.2f}", f"{n:.1f}"):
            out.add(form)
            out.add(form.lstrip("+-"))
            trimmed = form.rstrip("0").rstrip(".")
            if trimmed:
                out.add(trimmed)
                out.add(trimmed.lstrip("+-"))
        # Integer rounding: only safe for values >= 100 (rupee crore, vol units).
        # For small decimals like 10.6 rounding to 11 would false-match fabricated '11%'.
        if abs(n) >= 100 or n == int(n):
            out.add(str(int(n)))
            out.add(str(int(n)).lstrip("+-"))
    return out


def _match(variants: set[str], haystack_nums: set[str]) -> bool:
    """True if any variant matches exactly, or matches after sign-stripping."""
    if variants & haystack_nums:
        return True
    # Tolerate sign differences: '+13.6' should still match '13.6'.
    unsigned = {v.lstrip("-+") for v in variants}
    unsigned_hay = {v.lstrip("-+") for v in haystack_nums}
    return bool(unsigned & unsigned_hay)


def validate_numbers(state: AgentState, explanation: str) -> dict:
    """Return {'unverified': [...], 'checked': N, 'haystack_tokens': N}.

    A number is verified iff one of its variants appears as a WHOLE token in
    the haystack. No substring matching.
    """
    if not explanation:
        return {"unverified": [], "checked": 0, "haystack_tokens": 0}

    haystack_nums = _haystack_number_tokens(_haystack(state))
    claims = _extract_claims(explanation)

    unverified: list[str] = []
    seen: set[str] = set()

    for kind, raw in claims:
        norm = _normalise(raw)
        if norm in seen:
            continue
        seen.add(norm)
        try:
            if abs(float(norm)) < 1.0 and kind != "pct":
                continue
        except ValueError:
            continue

        variants = _number_variants(norm)
        if not _match(variants, haystack_nums):
            unverified.append(f"{raw} ({kind})")

    return {
        "unverified": unverified,
        "checked": len(seen),
        "haystack_tokens": len(haystack_nums),
    }


if __name__ == "__main__":
    # Smoke test
    fake_state: AgentState = {
        "price": {"pct_change_1d": -5.04, "sector_return_pct": -2.09},
        "events": {"events": [
            {"text": "Sales volume", "full_text": "Total Domestic 13.6% growth. Exports -38.8%."},
        ]},
        "flow": {"fii_net_cr": -1983.18, "dii_net_cr": 2432.30},
        "macro": {},
    }
    # The next line intentionally fabricates +23% to test detection.
    fake_expl = "Stock fell 5.04% vs sector -2.09%. Domestic sales grew 23% while exports rose 23%."
    r = validate_numbers(fake_state, fake_expl)
    print(r)  # should flag 23 (appearing twice but dedup'd to 1)
