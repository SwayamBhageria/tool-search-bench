"""How much of what the router returns is missing from the public catalogue?

`COMPOSIO_SEARCH_TOOLS` returns tools that `GET /api/v3/tools` will not list and that
`GET /api/v3/tools/{slug}` answers 404 for. They are not hallucinations — each arrives
with a full schema and executes as far as a missing-credential error — so the search
surface is a *superset* of the documented one.

This measures the size of that gap across every slug the benchmark ever saw returned.

Two guards, because the naive version of this measurement is wrong in both directions:

* **Only slugs from snapshotted toolkits are judged.** A `MICROSOFT_TEAMS_*` slug is
  absent from the local snapshot merely because that toolkit was never fetched; counting
  it would inflate the gap.
* **A sample is verified against the live API, with a control.** "Absent from my snapshot"
  and "absent from the API" are different claims, and only the second one matters. The
  control set is known-good slugs: if those do not all resolve, the probe is broken and
  the result is meaningless rather than interesting.
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import random
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE_SIZE = 30
CONTROL_SIZE = 15


def _toolkit(slug: str) -> str:
    return slug.split("_", 1)[0].upper()


def returned_slugs() -> set[str]:
    """Every distinct tool slug any run recorded the router returning."""
    seen: set[str] = set()
    for path in sorted((ROOT / "results").glob("*.json")):
        data = json.loads(path.read_text())
        for case in data.get("cases", []):
            seen.update(case.get("returned_primary") or [])
        for rec in data.get("records", []):
            seen.update(rec.get("primary") or [])
            seen.update(rec.get("related") or [])
    return seen


def _status(slug: str) -> tuple[str, int | str]:
    req = urllib.request.Request(
        f"https://backend.composio.dev/api/v3/tools/{slug}",
        headers={"x-api-key": os.environ["COMPOSIO_API_KEY"]},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return slug, resp.status
    except urllib.error.HTTPError as exc:
        return slug, exc.code
    except Exception as exc:  # noqa: BLE001
        return slug, type(exc).__name__


def main(seed: int = 7) -> dict:
    from bench.catalogue import require_snapshot

    snap = require_snapshot()
    documented = {t["slug"] for v in snap["tools"].values() for t in v}
    snapshotted = {k.replace("_", "").upper() for k in snap["tools"]}

    seen = returned_slugs()
    judgeable = sorted(s for s in seen if _toolkit(s) in snapshotted)
    absent = sorted(s for s in judgeable if s not in documented)

    rng = random.Random(seed)
    sample = rng.sample(absent, min(SAMPLE_SIZE, len(absent)))
    control = rng.sample(sorted(documented), CONTROL_SIZE)

    with ThreadPoolExecutor(max_workers=6) as pool:
        sample_status = list(pool.map(_status, sample))
        control_status = list(pool.map(_status, control))

    control_ok = sum(1 for _, s in control_status if s == 200)
    if control_ok != len(control_status):
        raise RuntimeError(
            f"control failed: only {control_ok}/{len(control_status)} known slugs "
            "resolved, so the 404s below prove nothing"
        )

    return {
        "distinct_slugs_returned": len(seen),
        "judgeable": len(judgeable),
        "absent_from_catalogue": len(absent),
        "absent_rate": round(len(absent) / len(judgeable), 4) if judgeable else None,
        "verified_sample_size": len(sample),
        "verified_404": sum(1 for _, s in sample_status if s == 404),
        "verified_200": sum(1 for _, s in sample_status if s == 200),
        "control_size": len(control_status),
        "control_200": control_ok,
        "by_toolkit": dict(
            collections.Counter(_toolkit(s) for s in absent).most_common()
        ),
        "absent_slugs": absent,
    }


if __name__ == "__main__":
    res = main()
    (ROOT / "results" / "e11_surface.json").write_text(json.dumps(res, indent=1))
    print(f"distinct slugs returned by search : {res['distinct_slugs_returned']}")
    print(f"judgeable (snapshotted toolkits)  : {res['judgeable']}")
    print(f"absent from the public catalogue  : {res['absent_from_catalogue']} "
          f"({res['absent_rate']:.0%})")
    print(f"live check: {res['verified_404']}/{res['verified_sample_size']} sampled "
          f"returned 404; control {res['control_200']}/{res['control_size']} returned 200")
