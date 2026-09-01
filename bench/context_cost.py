"""What retrieve-at-runtime actually saves in context.

The argument for searching a catalogue instead of preloading it is context cost, so it
deserves a measurement rather than an adjective.

Both sides are counted the same way, with a deliberately conservative bias against the
conclusion:

* **Preloading** is costed as name and description only — *no parameter schemas*. Real
  tool definitions carry full JSON Schema for their arguments and are several times
  larger, so this understates the preload side substantially.
* **Searching** is costed as the complete `tool_schemas` payload the search call returns,
  parameters included. That is the whole thing the model actually receives.

Tokens are estimated at 4 characters per token, applied identically to both sides. That is
approximate in absolute terms and fair in relative ones, which is what the ratio needs.
"""

from __future__ import annotations

import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

PROBE_QUERIES = [
    "send an email using Gmail",
    "create an issue in a GitHub repository",
    "create a refund in Stripe",
    "find free slots in Google Calendar",
    "create a new page in Notion",
    "add a card to a Trello board",
]


def _tokens(obj) -> int:
    return len(json.dumps(obj)) // 4


def main() -> dict:
    from composio import Composio

    snap = json.loads((ROOT / "cache" / "snapshot.json").read_text())
    tools = [t for v in snap["tools"].values() for t in v]

    preload_small = sum(
        _tokens({"name": t["slug"], "description": t.get("description", "")})
        for t in tools
    )
    scale = snap["toolkit_count"] / len(snap["tools"])
    preload_full = int(preload_small * scale)

    client = Composio(api_key=os.environ["COMPOSIO_API_KEY"])
    per_query = []
    for q in PROBE_QUERIES:
        session = client.sessions.create(user_id="ctxcost")
        resp = session.execute(
            "COMPOSIO_SEARCH_TOOLS",
            arguments={"queries": [{"use_case": q}], "session": {"generate_id": True}},
        )
        schemas = resp.model_dump()["data"].get("tool_schemas") or {}
        per_query.append({"query": q, "tokens": _tokens(schemas), "n_tools": len(schemas)})

    mean = sum(p["tokens"] for p in per_query) / len(per_query)
    return {
        "note": "4 chars/token estimate; preload counts name+description only (no "
                "parameter schemas), search counts full returned schemas",
        "catalogue_tools_snapshotted": len(tools),
        "catalogue_toolkits_snapshotted": len(snap["tools"]),
        "toolkit_count_total": snap["toolkit_count"],
        "preload_tokens_snapshot": preload_small,
        "preload_tokens_full_catalogue_estimate": preload_full,
        "search_tokens_mean": round(mean),
        "search_tokens_per_query": per_query,
        "ratio_vs_snapshot": round(preload_small / mean),
        "ratio_vs_full_catalogue": round(preload_full / mean),
    }


if __name__ == "__main__":
    res = main()
    (ROOT / "results" / "e10_context_cost.json").write_text(json.dumps(res, indent=1))
    print(f"preload, {res['catalogue_tools_snapshotted']} tools "
          f"(name+description only): {res['preload_tokens_snapshot']:,} tokens")
    print(f"preload, full catalogue estimate:      "
          f"{res['preload_tokens_full_catalogue_estimate']:,} tokens")
    print(f"search, mean per query:                "
          f"{res['search_tokens_mean']:,} tokens")
    print(f"\n{res['ratio_vs_snapshot']}x smaller than the snapshot, "
          f"{res['ratio_vs_full_catalogue']}x smaller than the full catalogue")
