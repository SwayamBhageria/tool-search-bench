"""Run every experiment and write results/.

Ordered cheapest-first so a broken setup fails on the free baseline rather than after
several hundred API calls.
"""

from __future__ import annotations

import json
import pathlib

from bench.catalogue import require_snapshot
from bench.embeddings import EmbeddingIndex, EmbeddingRetriever
from bench.gate import ConfidenceGate, GatedRetriever
from bench.retrievers import BM25Retriever, ComposioRetriever
from bench.run import load_cases, run, save, summarise
from bench import scope

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKERS = 6


def main() -> None:
    snap = require_snapshot()
    tools = [t for v in snap["tools"].values() for t in v]
    slugs = sorted(snap["tools"].keys())
    cases = load_cases()
    print(f"{len(cases)} cases | baseline catalogue {len(tools)} tools "
          f"across {len(slugs)} toolkits\n")

    for k, name in ((1, "e0b_bm25_top1"), (2, "e0b_bm25_top2"), (5, "e0_bm25_23toolkits")):
        r = run(BM25Retriever(tools, top_k=k), cases, workers=1)
        if k != 5:
            r["retriever"] = f"bm25@{k}"
        save(r, name)
        print(summarise(r))

    for k, name in ((1, "e6_embed_top1"), (2, "e6_embed_top2"), (5, "e6_embed_top5")):
        r = run(EmbeddingRetriever(tools, top_k=k), cases, workers=1)
        save(r, name)
        print(summarise(r))

    for retr, name in (
        (ComposioRetriever(toolkits=slugs), "e1_composio_23toolkits"),
        (ComposioRetriever(), "e2_composio_full"),
        (ComposioRetriever(strategy="tool_search"), "e4_composio_toolsearch"),
    ):
        r = run(retr, cases, workers=WORKERS)
        save(r, name)
        print(summarise(r))

    # Run-to-run stability: the router is LLM-backed, so one run is not a measurement.
    subset = [c for c in cases if c["kind"] == "paraphrase"][:15]
    r = run(ComposioRetriever(), subset, workers=WORKERS, repeat=3)
    save(r, "e5_variance")
    print("stability " + summarise(r))

    # The confidence gate, and what gating costs on the real cases.
    gate = ConfidenceGate(EmbeddingIndex(tools), tools=tools)
    r = run(GatedRetriever(ComposioRetriever(), gate), cases, workers=WORKERS)
    save(r, "e8_composio_gated")
    print(summarise(r))

    from bench import context_cost
    cc = context_cost.main()
    (ROOT / "results" / "e10_context_cost.json").write_text(json.dumps(cc, indent=1))
    print(f"context: search {cc['search_tokens_mean']:,} tokens/query vs "
          f"~{cc['preload_tokens_full_catalogue_estimate']:,} to preload "
          f"({cc['ratio_vs_full_catalogue']}x)")

    from bench import surface
    sg = surface.main()
    (ROOT / "results" / "e11_surface.json").write_text(json.dumps(sg, indent=1))
    print(f"surface gap: {sg['absent_from_catalogue']}/{sg['judgeable']} returned tools "
          f"({sg['absent_rate']:.0%}) are absent from the public catalogue")

    res = scope.main(workers=4)
    (ROOT / "results" / "e3_scope.json").write_text(json.dumps(res, indent=1))
    print(f"\nscope: controls {res['controls_passed']}/{res['n_controls']} | "
          f"leak {res['leak_rate_primary']:.0%} | "
          f"answered-anyway {res['answered_anyway_rate']:.0%}")


if __name__ == "__main__":
    main()
