"""Axis 2: does a session's toolkit allowlist actually hold, and what happens at its edge?

Two different questions, often confused:

**Containment.** A session created with `toolkits=[...]` should never surface a tool from
outside that list. A leak is a permissions failure: an agent handed a tool its operator
did not grant will use it.

**Out-of-scope behaviour.** When the allowlist genuinely cannot serve the request, the
router has two options. It can say so, or it can return the closest in-scope tool. The
second is the dangerous one, and it is invisible to a containment check because the tool
returned *is* inside the allowlist — it is simply wrong. An agent that asks to send an
email and is handed `GITHUB_ADD_EMAIL_ADDRESS_FOR_AUTHENTICATED_USER` will call it.

This was observed by hand during design and is quantified here.

Each impossible query is paired with a **positive control** — a query the same allowlist
*can* serve. Without it, a session that is simply broken would look like perfect
containment, and "returned nothing" would be misread as good judgement.
"""

from __future__ import annotations

import json
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from bench.metrics import containment
from bench.retrievers import ComposioRetriever

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Allowlists deliberately distant from the probe's subject matter, so any in-scope
# answer is clearly a wrong answer rather than a defensible alternative.
DENY_SETS = [
    {
        "id": "email-denied",
        "allow": ["github", "figma", "stripe", "dropbox", "trello"],
        "impossible": [
            "send an email using Gmail",
            "create an email draft in Gmail",
            "search my Outlook mail for a message about invoices",
        ],
        "control": ("create an issue in a GitHub repository", "GITHUB"),
    },
    {
        "id": "calendar-denied",
        "allow": ["github", "slack", "linear", "notion", "figma"],
        "impossible": [
            "create an event in Google Calendar",
            "find free slots in my Google Calendar next week",
            "cancel a scheduled event in Calendly",
        ],
        "control": ("send a message to a Slack channel", "SLACK"),
    },
    {
        "id": "payments-denied",
        "allow": ["gmail", "googlecalendar", "googledocs", "notion", "todoist"],
        "impossible": [
            "create a refund in Stripe",
            "create a customer in Stripe",
            "list invoices in Stripe",
        ],
        "control": ("create a new page in Notion", "NOTION"),
    },
    {
        "id": "code-denied",
        "allow": ["gmail", "stripe", "zoom", "calendly", "airtable"],
        "impossible": [
            "create a pull request on GitHub",
            "create an issue in a GitHub repository",
            "star a GitHub repository",
        ],
        "control": ("create a Zoom meeting", "ZOOM"),
    },
]


def _probe(allow: list[str], query: str, uid: str) -> dict:
    retriever = ComposioRetriever(toolkits=allow)
    primary, related = retriever.search(query, user_id=uid)
    return {
        "query": query,
        "primary": primary,
        "related": related,
        "containment_primary": containment(allow, primary),
        "containment_all": containment(allow, primary + related),
    }


def main(workers: int = 4) -> dict:
    jobs = []
    for ds in DENY_SETS:
        for i, q in enumerate(ds["impossible"]):
            jobs.append((ds, "impossible", q, f"scope_{ds['id']}_imp{i}"))
        jobs.append((ds, "control", ds["control"][0], f"scope_{ds['id']}_ctl"))

    out: list[dict] = []
    errors: list[dict] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(_probe, ds["allow"], q, uid): (ds, role, q)
            for ds, role, q, uid in jobs
        }
        for fut in as_completed(futs):
            ds, role, q = futs[fut]
            try:
                rec = fut.result()
                rec.update({"deny_set": ds["id"], "role": role, "allow": ds["allow"]})
                if role == "control":
                    want = ds["control"][1]
                    rec["control_passed"] = bool(rec["primary"]) and rec["primary"][0].split("_")[0] == want
                out.append(rec)
            except Exception as exc:  # noqa: BLE001
                errors.append({"query": q, "deny_set": ds["id"],
                               "error": f"{type(exc).__name__}: {exc}"[:300]})

    impossible = [r for r in out if r["role"] == "impossible"]
    controls = [r for r in out if r["role"] == "control"]
    leaked = [r for r in impossible if not r["containment_primary"]["contained"]]
    empty = [r for r in impossible if not r["primary"]]
    answered = [r for r in impossible if r["primary"]]

    return {
        "n_impossible": len(impossible),
        "n_controls": len(controls),
        "controls_passed": sum(1 for c in controls if c.get("control_passed")),
        "wall_seconds": round(time.time() - started, 1),
        "errors": errors,
        # Did any tool escape the allowlist?
        "leak_rate_primary": round(len(leaked) / len(impossible), 4) if impossible else None,
        "leaked": [{"query": r["query"], "escaped": r["containment_primary"]["escaped"]}
                   for r in leaked],
        # When it could not serve the request, did it decline or answer anyway?
        "declined_rate": round(len(empty) / len(impossible), 4) if impossible else None,
        "answered_anyway_rate": round(len(answered) / len(impossible), 4) if impossible else None,
        "answered_anyway": [{"query": r["query"], "returned": r["primary"][:3]}
                            for r in answered],
        "records": out,
    }


if __name__ == "__main__":
    res = main()
    (ROOT / "results" / "e3_scope.json").write_text(json.dumps(res, indent=1))
    print(f"controls passed:      {res['controls_passed']}/{res['n_controls']}")
    print(f"impossible queries:   {res['n_impossible']}")
    print(f"allowlist leak rate:  {res['leak_rate_primary']}")
    print(f"declined (no tool):   {res['declined_rate']}")
    print(f"answered anyway:      {res['answered_anyway_rate']}")
    for a in res["answered_anyway"][:8]:
        print(f"    {a['query'][:52]:<54} -> {a['returned']}")
