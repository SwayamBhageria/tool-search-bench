"""Scoring for tool-retrieval results.

Definitions used throughout:

  primary   the tools the router puts forward as the answer (`primary_tool_slugs`).
  related   tools it offers as adjacent (`related_tool_slugs`).
  strict    only the case's `expected` slug counts as correct.
  lenient   `expected` or any `acceptable` slug counts — acceptable slugs perform the
            same operation on the same resource and are fixed before any run.

`hit_primary` is the headline: an agent acts on the primary list, so a correct tool that
only appears under `related` is not the same as getting it right. Both are reported.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


def _toolkit_of(slug: str) -> str:
    return slug.split("_", 1)[0].upper()


@dataclass
class CaseScore:
    case_id: str
    kind: str
    hit_primary_strict: bool
    hit_primary_lenient: bool
    hit_any_lenient: bool
    rank: int | None          # 1-based rank in primary, lenient; None if absent
    reciprocal_rank: float
    toolkit_correct: bool | None
    n_primary: int
    n_related: int
    returned_primary: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


def score_case(case: dict, primary: list[str], related: list[str]) -> CaseScore:
    primary = list(primary or [])
    related = list(related or [])
    expected = set(case.get("expected") or [])
    lenient = expected | set(case.get("acceptable") or [])

    hit_primary_strict = bool(expected & set(primary))
    hit_primary_lenient = bool(lenient & set(primary))
    hit_any_lenient = bool(lenient & set(primary + related))

    rank = None
    for i, slug in enumerate(primary, start=1):
        if slug in lenient:
            rank = i
            break

    # Did it at least route to the right application? Undefined when no app was named.
    toolkit_correct: bool | None = None
    if case.get("toolkit") and primary:
        want = {_toolkit_of(s) for s in lenient}
        toolkit_correct = _toolkit_of(primary[0]) in want

    return CaseScore(
        case_id=case["id"],
        kind=case["kind"],
        hit_primary_strict=hit_primary_strict,
        hit_primary_lenient=hit_primary_lenient,
        hit_any_lenient=hit_any_lenient,
        rank=rank,
        reciprocal_rank=(1.0 / rank) if rank else 0.0,
        toolkit_correct=toolkit_correct,
        n_primary=len(primary),
        n_related=len(related),
        returned_primary=primary,
    )


def aggregate(scores: list[CaseScore]) -> dict:
    """Summarise scores. Rates are over the cases that define them."""
    if not scores:
        return {"n": 0}
    n = len(scores)

    def rate(attr: str) -> float:
        return round(sum(bool(getattr(s, attr)) for s in scores) / n, 4)

    tk = [s for s in scores if s.toolkit_correct is not None]
    return {
        "n": n,
        "hit_primary_strict": rate("hit_primary_strict"),
        "hit_primary_lenient": rate("hit_primary_lenient"),
        "hit_any_lenient": rate("hit_any_lenient"),
        "mrr": round(sum(s.reciprocal_rank for s in scores) / n, 4),
        "toolkit_correct": (
            round(sum(bool(s.toolkit_correct) for s in tk) / len(tk), 4) if tk else None
        ),
        "mean_primary_returned": round(sum(s.n_primary for s in scores) / n, 2),
    }


def containment(allowed: list[str], returned: list[str]) -> dict:
    """Did every returned tool stay inside the session's toolkit allowlist?"""
    allow = {a.replace("_", "").replace("-", "").upper() for a in allowed}
    out = [s for s in returned if _toolkit_of(s) not in allow]
    return {
        "contained": not out,
        "n_returned": len(returned),
        "escaped": out,
    }
