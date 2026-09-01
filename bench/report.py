"""Render the results tables from the raw result files.

Every number in the README is emitted by this script. Hand-copied figures drift the
moment an experiment is re-run, so the report is generated rather than written.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

MAIN = [
    ("e0b_bm25_top1", "BM25 @1", "documented catalogue, 23 toolkits"),
    ("e0b_bm25_top2", "BM25 @2", "documented catalogue, 23 toolkits"),
    ("e0_bm25_23toolkits", "BM25 @5", "documented catalogue, 23 toolkits"),
    ("e1_composio_23toolkits", "Composio", "session restricted to the same 23 toolkits"),
    ("e2_composio_full", "Composio", "unrestricted — full catalogue"),
    ("e4_composio_toolsearch", "Composio `tool_search`", "unrestricted, cached plans bypassed"),
]


def load(name: str) -> dict | None:
    p = RESULTS / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def overall_table() -> str:
    rows = [
        "| retriever | condition | strict | lenient | any | MRR | toolkit | tools returned |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label, cond in MAIN:
        d = load(key)
        if not d:
            continue
        if d["n_errors"]:
            rows.append(f"| {label} | {cond} | **run lost {d['n_errors']} cases — not summarised** |||||| ")
            continue
        o = d["overall"]
        rows.append(
            f"| {label} | {cond} | {o['hit_primary_strict']:.3f} | "
            f"{o['hit_primary_lenient']:.3f} | {o['hit_any_lenient']:.3f} | "
            f"{o['mrr']:.3f} | {o['toolkit_correct']:.3f} | {o['mean_primary_returned']} |"
        )
    return "\n".join(rows)


def kind_table() -> str:
    rows = [
        "| retriever | exact | paraphrase | app-unspecified |",
        "|---|---:|---:|---:|",
    ]
    for key, label, cond in MAIN:
        d = load(key)
        if not d or d["n_errors"]:
            continue
        k = d["by_kind"]
        def cell(name: str) -> str:
            return f"{k[name]['hit_primary_lenient']:.3f}" if name in k else "—"
        tag = f"{label} ({cond.split(',')[0].split('—')[0].strip()})"
        rows.append(f"| {tag} | {cell('exact')} | {cell('paraphrase')} | {cell('unspecified')} |")
    return "\n".join(rows)


def scope_summary() -> str:
    d = load("e3_scope")
    if not d:
        return "_not run_"
    lines = [
        f"- Positive controls passed: **{d['controls_passed']}/{d['n_controls']}** "
        "(the restricted sessions do work)",
        f"- Allowlist leak rate: **{d['leak_rate_primary']:.0%}** "
        f"across {d['n_impossible']} impossible queries",
        f"- Declined (returned no tool): **{d['declined_rate']:.0%}**",
        f"- Answered anyway with an in-scope but wrong tool: "
        f"**{d['answered_anyway_rate']:.0%}**",
    ]
    return "\n".join(lines)


def scope_examples(n: int = 6) -> str:
    d = load("e3_scope")
    if not d:
        return ""
    rows = ["| query (impossible within the allowlist) | tool returned |", "|---|---|"]
    for a in d["answered_anyway"][:n]:
        rows.append(f"| {a['query']} | `{a['returned'][0]}` |")
    return "\n".join(rows)


def _cli() -> None:
    import sys
    if "--write" in sys.argv:
        readme = ROOT / "README.md"
        inject(readme)
        print(f"regenerated tables in {readme}")
        return
    print("## Overall\n")
    print(overall_table())
    print("\n## By query kind (lenient hit rate in the primary list)\n")
    print(kind_table())
    print("\n## Scope\n")
    print(scope_summary())
    print()
    print(scope_examples())




def miss_table(run_key: str = "e2_composio_full", kind: str = "exact") -> str:
    """Every miss of the given kind, in full.

    Printed exhaustively rather than summarised: the reader should be able to judge
    each one, since several are arguably scoring artefacts rather than retrieval
    failures. See the README section on near-duplicate slugs.
    """
    d = load(run_key)
    fixture = json.loads((ROOT / "fixtures" / "cases-v1.json").read_text())
    by_id = {c["id"]: c for c in fixture["cases"]}
    if not d:
        return "_not run_"
    rows = ["| query | expected | returned |", "|---|---|---|"]
    for c in d["cases"]:
        if c["kind"] != kind or c["hit_primary_lenient"]:
            continue
        f = by_id[c["case_id"]]
        got = ", ".join(f"`{s}`" for s in c["returned_primary"]) or "_nothing_"
        rows.append(f"| {f['query']} | `{f['expected'][0]}` | {got} |")
    return "\n".join(rows)


MARKERS = {
    "OVERALL": overall_table,
    "BYKIND": kind_table,
    "SCOPE": scope_summary,
    "SCOPE_EXAMPLES": scope_examples,
    "MISSES": miss_table,
}


def inject(path: pathlib.Path) -> bool:
    """Replace each `<!--AUTO:NAME-->...<!--/AUTO:NAME-->` block with fresh output."""
    text = path.read_text()
    for name, fn in MARKERS.items():
        start, end = f"<!--AUTO:{name}-->", f"<!--/AUTO:{name}-->"
        if start not in text or end not in text:
            continue
        head = text.split(start)[0]
        tail = text.split(end, 1)[1]
        text = f"{head}{start}\n{fn()}\n{end}{tail}"
    path.write_text(text)
    return True


if __name__ == "__main__":
    _cli()
