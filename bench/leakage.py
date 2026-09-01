"""Measure vocabulary overlap between each query and its target tool.

Query sets generated from a tool's own description leak that tool's wording into the
query, so a retriever can score well on string overlap alone. That inflation is
invisible unless it is measured, so it is measured here.

`exact` cases are expected to overlap (they name the action plainly). `paraphrase`
cases are the ones that must not: if their overlap were as high, the two kinds would be
testing the same thing and the paraphrase scores would mean nothing.
"""

from __future__ import annotations

import json
import pathlib
import statistics

from bench.retrievers import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOP = {
    "a", "an", "the", "to", "in", "on", "for", "of", "and", "or", "my", "me", "i",
    "it", "is", "so", "that", "this", "with", "from", "at", "as", "be", "can",
    "new", "one", "out", "up", "do", "not", "we", "us", "they", "them", "our",
}


def overlap(query: str, tool: dict) -> float:
    """Fraction of the target's slug/name tokens that appear in the query."""
    target = set(tokenize(tool["slug"].replace("_", " ") + " " + tool.get("name", "")))
    target -= STOP
    if not target:
        return 0.0
    q = set(tokenize(query)) - STOP
    return len(target & q) / len(target)


def main() -> None:
    snap = json.loads((ROOT / "cache" / "snapshot.json").read_text())
    fixture = json.loads((ROOT / "fixtures" / "cases-v1.json").read_text())
    by_slug = {t["slug"]: t for tools in snap["tools"].values() for t in tools}

    per_kind: dict[str, list[float]] = {}
    for case in fixture["cases"]:
        if not case["expected"]:
            continue
        tool = by_slug.get(case["expected"][0])
        if not tool:
            continue
        per_kind.setdefault(case["kind"], []).append(overlap(case["query"], tool))

    print(f"{'kind':<12} {'n':>4} {'mean':>7} {'median':>7} {'max':>7}")
    for kind, vals in sorted(per_kind.items()):
        print(f"{kind:<12} {len(vals):>4} {statistics.mean(vals):>7.3f} "
              f"{statistics.median(vals):>7.3f} {max(vals):>7.3f}")
    if {"exact", "paraphrase"} <= per_kind.keys():
        e, p = statistics.mean(per_kind["exact"]), statistics.mean(per_kind["paraphrase"])
        print(f"\nexact overlaps {e / p:.1f}x more than paraphrase" if p else
              "\nparaphrase overlap is zero")


if __name__ == "__main__":
    main()
