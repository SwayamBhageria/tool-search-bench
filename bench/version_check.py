"""Why the router returns tools that `GET /api/v3/tools/{slug}` answers 404 for.

`bench.surface` measured a gap: 100 of 584 slugs the router returned are absent from
the catalogue this benchmark snapshotted, and a sampled 30 of them 404 live. That
measurement is correct. The conclusion originally drawn from it — that an operator
cannot enumerate the invocable surface — was not.

`GET /api/v3/tools` resolves each toolkit to its **pinned base version**.
`COMPOSIO_SEARCH_TOOLS` returns tools from the **latest** version. The two endpoints
are answering about different catalogues, so a tool added after a toolkit's base
version is routable and simultaneously 404s on the documented default endpoint.

This re-probes every absent slug against `/api/v3.1/tools/{slug}`, which defaults to
latest, and reports how many resolve. It carries the same discipline as the original:

* **A negative control.** A slug that does not exist must still 404 on v3.1. Without
  it, a v3.1 that answers 200 for anything would look like a complete explanation.
* **A positive control.** A known-good documented slug must resolve on both, so a
  200 on v3.1 is not just the endpoint being more permissive about everything.

If either control fails the run raises rather than reporting a number.
"""

from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent

NEGATIVE_CONTROL = "DEFINITELY_NOT_A_REAL_TOOL_9X7"
POSITIVE_CONTROL = "GMAIL_SEND_EMAIL"


def _status(base: str, slug: str) -> int | str:
    req = urllib.request.Request(
        f"https://backend.composio.dev/api/{base}/tools/{slug}",
        headers={"x-api-key": os.environ["COMPOSIO_API_KEY"]},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__


def _listing_count(base: str, toolkit: str) -> int | None:
    req = urllib.request.Request(
        f"https://backend.composio.dev/api/{base}/tools"
        f"?toolkit_slug={toolkit}&limit=1000",
        headers={"x-api-key": os.environ["COMPOSIO_API_KEY"]},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return len(json.load(resp).get("items") or [])
    except Exception:  # noqa: BLE001
        return None


def _metadata_count(toolkit: str) -> int | None:
    req = urllib.request.Request(
        f"https://backend.composio.dev/api/v3/toolkits/{toolkit}",
        headers={"x-api-key": os.environ["COMPOSIO_API_KEY"]},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp).get("meta", {}).get("tools_count")
    except Exception:  # noqa: BLE001
        return None


def counts() -> dict:
    """Re-run F2's metadata-vs-listing comparison against both API versions.

    F2 reported that `meta.tools_count` disagrees with what the tools endpoint serves,
    23/23, "in both directions". Most of that gap is the same version artefact: the
    metadata counts the latest toolkit version, the v3 listing serves the pinned base.
    """
    from bench.catalogue import require_snapshot

    rows = []
    for toolkit in require_snapshot()["tools"]:
        rows.append(
            {
                "toolkit": toolkit,
                "metadata": _metadata_count(toolkit),
                "v3": _listing_count("v3", toolkit),
                "v3_1": _listing_count("v3.1", toolkit),
            }
        )

    def _gap(row: str) -> list[int]:
        return [
            abs(r["metadata"] - r[row])
            for r in rows
            if r["metadata"] is not None and r[row] is not None
        ]

    gap_v3, gap_v31 = _gap("v3"), _gap("v3_1")
    return {
        "toolkits": len(rows),
        "exact_match_v3": sum(1 for r in rows if r["metadata"] == r["v3"]),
        "exact_match_v3_1": sum(1 for r in rows if r["metadata"] == r["v3_1"]),
        "closer_on_v3_1": sum(
            1
            for r in rows
            if None not in (r["metadata"], r["v3"], r["v3_1"])
            and abs(r["metadata"] - r["v3_1"]) < abs(r["metadata"] - r["v3"])
        ),
        "mean_abs_gap_v3": round(sum(gap_v3) / len(gap_v3), 1) if gap_v3 else None,
        "mean_abs_gap_v3_1": round(sum(gap_v31) / len(gap_v31), 1) if gap_v31 else None,
        "rows": rows,
    }


def main() -> dict:
    surface = json.loads((ROOT / "results" / "e11_surface.json").read_text())
    absent: list[str] = surface["absent_slugs"]

    neg = _status("v3.1", NEGATIVE_CONTROL)
    pos_v3 = _status("v3", POSITIVE_CONTROL)
    pos_v31 = _status("v3.1", POSITIVE_CONTROL)
    if neg != 404:
        raise RuntimeError(
            f"negative control resolved on v3.1 ({neg}); the endpoint answers for "
            "slugs that do not exist, so the 200s below prove nothing"
        )
    if pos_v3 != 200 or pos_v31 != 200:
        raise RuntimeError(
            f"positive control failed (v3={pos_v3}, v3.1={pos_v31}); the probe is broken"
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = dict(
            zip(absent, pool.map(lambda s: _status("v3.1", s), absent), strict=True)
        )

    # Anything that came back as neither 200 nor 404 was a transport failure, not an
    # answer — under concurrency this endpoint intermittently drops the first few
    # requests of a burst. Re-probe those serially rather than scoring them as absent.
    retried = sorted(s for s, st in statuses.items() if st not in (200, 404))
    for slug in retried:
        statuses[slug] = _status("v3.1", slug)

    resolved = sorted(s for s, st in statuses.items() if st == 200)
    unresolved = sorted(s for s, st in statuses.items() if st != 200)

    return {
        "absent_on_v3": len(absent),
        "resolved_on_v3_1": len(resolved),
        "resolved_rate": round(len(resolved) / len(absent), 4) if absent else None,
        "still_unresolved": len(unresolved),
        "unresolved_slugs": unresolved,
        "retried_after_transport_failure": len(retried),
        "statuses": {s: statuses[s] for s in sorted(statuses)},
        "negative_control": {"slug": NEGATIVE_CONTROL, "v3.1": neg},
        "positive_control": {"slug": POSITIVE_CONTROL, "v3": pos_v3, "v3.1": pos_v31},
        "counts": counts(),
    }


if __name__ == "__main__":
    res = main()
    (ROOT / "results" / "e12_version_check.json").write_text(json.dumps(res, indent=1))
    print(f"absent under /api/v3            : {res['absent_on_v3']}")
    print(f"resolve under /api/v3.1 (latest): {res['resolved_on_v3_1']} "
          f"({res['resolved_rate']:.0%})")
    print(f"still unresolved                : {res['still_unresolved']}")
    print(f"controls: fake slug on v3.1 -> {res['negative_control']['v3.1']}; "
          f"{POSITIVE_CONTROL} -> v3 {res['positive_control']['v3']}, "
          f"v3.1 {res['positive_control']['v3.1']}")
    c = res["counts"]
    print(f"\nF2 re-run over {c['toolkits']} toolkits — mean |metadata - listing|: "
          f"{c['mean_abs_gap_v3']} on v3, {c['mean_abs_gap_v3_1']} on v3.1 "
          f"({c['closer_on_v3_1']}/{c['toolkits']} closer on v3.1)")
