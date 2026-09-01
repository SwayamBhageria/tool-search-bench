"""Run a retriever over the case set and score it.

Concurrency is bounded and every failure is recorded rather than dropped. A retrieval
run that quietly loses a third of its queries still produces a plausible-looking
accuracy figure, so `errors` is carried into the results file and the report refuses to
summarise a run that lost cases.
"""

from __future__ import annotations

import json
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from bench.metrics import CaseScore, aggregate, score_case

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_cases() -> list[dict]:
    return json.loads((ROOT / "fixtures" / "cases-v1.json").read_text())["cases"]


def run(retriever, cases: list[dict], workers: int = 4, repeat: int = 1) -> dict:
    """Score `retriever` over `cases`. Returns a result document."""
    jobs = [(c, r) for c in cases for r in range(repeat)]
    scores: list[CaseScore] = []
    errors: list[dict] = []
    latencies: list[float] = []
    started = time.time()

    def one(case: dict, rep: int):
        t0 = time.time()
        primary, related = retriever.search(
            case["query"], user_id=f"bench_{case['id']}_{rep}"
        )
        return case, time.time() - t0, primary, related

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, c, r): (c, r) for c, r in jobs}
        for fut in as_completed(futures):
            case, rep = futures[fut]
            try:
                case, dt, primary, related = fut.result()
                latencies.append(dt)
                scores.append(score_case(case, primary, related))
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                errors.append({
                    "case_id": case["id"], "repeat": rep,
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                })

    by_kind: dict[str, list[CaseScore]] = {}
    for s in scores:
        by_kind.setdefault(s.kind, []).append(s)

    latencies.sort()
    return {
        "retriever": retriever.name,
        "n_requested": len(jobs),
        "n_scored": len(scores),
        "n_errors": len(errors),
        "errors": errors,
        "wall_seconds": round(time.time() - started, 1),
        "latency_p50": round(latencies[len(latencies) // 2], 2) if latencies else None,
        "latency_p95": (
            round(latencies[int(len(latencies) * 0.95)], 2) if latencies else None
        ),
        "overall": aggregate(scores),
        "by_kind": {k: aggregate(v) for k, v in sorted(by_kind.items())},
        "cases": [s.as_dict() for s in sorted(scores, key=lambda s: s.case_id)],
    }


def save(result: dict, name: str) -> pathlib.Path:
    out = ROOT / "results" / f"{name}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    return out


def summarise(result: dict) -> str:
    o = result["overall"]
    lost = result["n_errors"]
    warn = f"  ** {lost} CASES LOST **" if lost else ""
    return (
        f"{result['retriever']:<28} n={o['n']:<4} "
        f"strict={o['hit_primary_strict']:.3f} lenient={o['hit_primary_lenient']:.3f} "
        f"any={o['hit_any_lenient']:.3f} mrr={o['mrr']:.3f} "
        f"tk={o['toolkit_correct']} p50={result['latency_p50']}s{warn}"
    )
