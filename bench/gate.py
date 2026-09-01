"""A confidence gate over tool search, and the measurement of what it costs.

The finding this exists for: when a session's toolkit allowlist cannot serve a request,
`COMPOSIO_SEARCH_TOOLS` does not say so. In 12 of 12 impossible queries it returned a
confident, in-scope, semantically wrong tool — `star a GitHub repository` answered with
`ZOOM_GET_PROJECT`. An agent acting on `primary_tool_slugs` will call it.

The response carries no confidence score, so the gate supplies one from outside: embed
the query and the top returned tool, and refuse below a cosine-similarity threshold.

**What this gate does and does not do.** Measured on the runs in `results/`, similarity
for tools returned to *impossible* queries averages 0.606, against 0.766 for correct
answers — separable. But tools returned *wrongly to answerable queries* average 0.749,
which is indistinguishable from correct. So this detects "nothing here fits the request",
not "this particular tool is the wrong one". It is a scope gate, not an accuracy gate,
and it is only claimed as the former.

Any threshold trades refusals of good answers against refusals of bad ones, so the
threshold is not hard-coded: `sweep()` reports the whole curve and the README publishes
it, leaving the operating point to whoever deploys it.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Default operating point, chosen from the sweep in results/e7_gate_sweep.json as the
# highest threshold that refuses no correct answer. Deliberately conservative: a gate
# that suppresses working behaviour will be turned off, so it must cost nothing first.
DEFAULT_THRESHOLD = 0.57


@dataclass
class GateDecision:
    passed: bool
    score: float | None
    reason: str


class ConfidenceGate:
    """Scores a (query, tool) pair and decides whether to let it through."""

    def __init__(self, index, threshold: float = DEFAULT_THRESHOLD, tools: list[dict] | None = None):
        from bench.embeddings import tool_text

        self.index = index
        self.threshold = threshold
        self._text = tool_text
        self._by_slug = {t["slug"]: t for t in (tools or [])}

    def _tool_text(self, slug: str) -> str:
        """Text for a returned tool.

        The router can return tools the documented catalogue does not list (FINDINGS.md
        F3), so fall back to the slug's own words. That is weaker signal, and the
        fallback rate is reported alongside any result rather than hidden.
        """
        tool = self._by_slug.get(slug)
        return self._text(tool) if tool else slug.replace("_", " ")

    def score(self, query: str, slug: str) -> float:
        import numpy as np

        vec = self.index.model.encode(
            [self._tool_text(slug)], normalize_embeddings=True, convert_to_numpy=True
        )[0]
        return float(vec @ self.index.encode_query(query))

    def check(self, query: str, primary: list[str]) -> GateDecision:
        if not primary:
            return GateDecision(True, None, "nothing returned; nothing to gate")
        s = self.score(query, primary[0])
        if s < self.threshold:
            return GateDecision(False, s, f"top tool scored {s:.3f} < {self.threshold}")
        return GateDecision(True, s, f"top tool scored {s:.3f}")


class GatedRetriever:
    """Wraps a retriever and suppresses answers the gate rejects.

    A rejected query returns an empty primary list, which the scorer already treats as a
    miss — so the accuracy cost of gating shows up in the ordinary metrics rather than
    needing a special case.
    """

    def __init__(self, inner, gate: ConfidenceGate):
        self.inner, self.gate = inner, gate
        self.name = f"{inner.name}+gate@{gate.threshold}"

    def search(self, query: str, **kw) -> tuple[list[str], list[str]]:
        primary, related = self.inner.search(query, **kw)
        decision = self.gate.check(query, primary)
        return (primary, related) if decision.passed else ([], related)


def compute_similarities() -> dict:
    """Gate scores for three populations, derived from completed runs.

    Written to `results/` rather than the ignored cache directory so the sweep is
    reproducible from a fresh clone without re-spending API calls.

      correct     tools returned for real queries that were right
      wrong       tools returned for real queries that were wrong
      impossible  tools returned for queries the allowlist could not serve
    """
    from bench.catalogue import require_snapshot
    from bench.embeddings import EmbeddingIndex

    snap = require_snapshot()
    tools = [t for v in snap["tools"].values() for t in v]
    gate = ConfidenceGate(EmbeddingIndex(tools), tools=tools)

    fixture = {c["id"]: c for c in
               json.loads((ROOT / "fixtures" / "cases-v1.json").read_text())["cases"]}
    real = json.loads((ROOT / "results" / "e2_composio_full.json").read_text())
    correct, wrong = [], []
    for c in real["cases"]:
        if not c["returned_primary"]:
            continue
        score = gate.score(fixture[c["case_id"]]["query"], c["returned_primary"][0])
        (correct if c["hit_primary_lenient"] else wrong).append(score)

    scope_run = json.loads((ROOT / "results" / "e3_scope.json").read_text())
    impossible = [
        gate.score(r["query"], r["primary"][0])
        for r in scope_run["records"]
        if r["role"] == "impossible" and r["primary"]
    ]
    return {"correct": correct, "wrong": wrong, "impossible": impossible}


def _load_similarities() -> dict:
    path = ROOT / "results" / "e7_gate_similarities.json"
    if not path.exists():
        sims = compute_similarities()
        path.write_text(json.dumps(sims, indent=1))
        return sims
    return json.loads(path.read_text())


def sweep(thresholds: list[float] | None = None) -> dict:
    """Cost/benefit of the gate at each threshold.

    Computed offline from completed runs so the curve can be re-derived without spending
    API calls, and so the operating point is chosen from the same data the README shows.
    """
    sims = _load_similarities()
    correct, wrong, impossible = sims["correct"], sims["wrong"], sims["impossible"]
    if thresholds is None:
        thresholds = [round(0.45 + 0.02 * i, 2) for i in range(16)]

    rows = []
    for t in thresholds:
        refused_bad = sum(1 for s in impossible if s < t)
        refused_good = sum(1 for s in correct if s < t)
        refused_wrong = sum(1 for s in wrong if s < t)
        rows.append({
            "threshold": t,
            "out_of_scope_refused": refused_bad,
            "out_of_scope_total": len(impossible),
            "out_of_scope_refused_rate": round(refused_bad / len(impossible), 4),
            "correct_answers_lost": refused_good,
            "correct_answers_total": len(correct),
            "correct_answers_lost_rate": round(refused_good / len(correct), 4),
            "wrong_answers_also_refused": refused_wrong,
        })
    free = [r for r in rows if r["correct_answers_lost"] == 0]
    return {
        "rows": rows,
        "best_free_threshold": max((r["threshold"] for r in free), default=None),
        "best_free_recall": max((r["out_of_scope_refused_rate"] for r in free), default=0.0),
    }


def _means(sims: dict) -> dict:
    return {k: round(sum(v) / len(v), 4) for k, v in sims.items() if v}


if __name__ == "__main__":
    sims = _load_similarities()
    res = sweep()
    res["mean_score"] = _means(sims)
    res["n"] = {k: len(v) for k, v in sims.items()}
    (ROOT / "results" / "e7_gate_sweep.json").write_text(json.dumps(res, indent=1))
    print(f"{'thresh':>7}{'out-of-scope refused':>23}{'correct lost':>15}{'wrong also refused':>21}")
    for r in res["rows"]:
        print(f"{r['threshold']:>7.2f}"
              f"{r['out_of_scope_refused']:>13}/{r['out_of_scope_total']:<9}"
              f"{r['correct_answers_lost']:>7}/{r['correct_answers_total']:<7}"
              f"{r['wrong_answers_also_refused']:>15}")
    print(f"\nhighest threshold costing zero correct answers: {res['best_free_threshold']} "
          f"(refuses {res['best_free_recall']:.0%} of out-of-scope queries)")
    print("\nmean gate score by population:")
    for k, v in res["mean_score"].items():
        print(f"   {k:<12} {v:.3f}  (n={res['n'][k]})")
