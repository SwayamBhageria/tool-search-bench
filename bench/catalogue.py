"""Snapshot the Composio tool catalogue.

The catalogue is the ground the benchmark stands on: every expected tool slug in a
fixture is validated against it, and the BM25 baseline indexes it. So this module
asserts what it fetched rather than trusting a 200.

Two traps live in this endpoint and both are guarded here:

1. The filter parameter is ``toolkit_slug`` (singular). Passing ``toolkit_slugs``,
   ``toolkits``, ``app`` or ``toolkit`` returns HTTP 200 and the *unfiltered global
   catalogue* — no error, no warning. Asking for Gmail that way yields 500 rows of
   which zero are Gmail. ``_assert_narrowed`` makes that failure loud.
2. A page can come back short without being the last page, so pagination follows
   ``next_cursor`` and the final count is checked against the endpoint's own
   ``total_items``.

A note on catalogue size. A toolkit's ``meta.tools_count`` disagrees with the number
of tools the ``/tools`` endpoint will actually serve for it — Gmail reports 61 in
metadata and 23 from the endpoint, Stripe 425 against 33 — and in a few cases the
metadata is *lower* than what is served (HubSpot 244 against 304). The endpoint's
``total_items`` is treated as authoritative here, so the summed ``meta.tools_count``
is reported only as an upper bound.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://backend.composio.dev/api/v3"

# The toolkits the benchmark draws its cases from. Chosen to be widely known (so a
# hand-written query has an obvious right answer), session-safe (see
# `session_safe_toolkits`), and spread across categories rather than clustered in one.
FIXTURE_TOOLKITS = [
    "gmail", "github", "slack", "googlecalendar", "googledrive", "googlesheets",
    "notion", "linear", "jira", "hubspot", "outlook", "discord", "trello", "asana",
    "airtable", "stripe", "zoom", "dropbox", "todoist", "clickup", "figma",
    "googledocs", "calendly",
]
CACHE = Path(__file__).resolve().parent.parent / "cache"


class CatalogueError(RuntimeError):
    pass


def _key() -> str:
    key = os.environ.get("COMPOSIO_API_KEY")
    if not key:
        raise CatalogueError(
            "COMPOSIO_API_KEY is not set. Copy .env.example to .env and add a key."
        )
    return key


def _get(path: str, params: dict | None = None, retries: int = 4) -> dict:
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-api-key": _key()})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            # 429 and 5xx are worth retrying; a 4xx is our bug and should surface now.
            if exc.code != 429 and exc.code < 500:
                raise
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise CatalogueError(f"unreachable: {path}")


def _paginate(path: str, params: dict) -> tuple[list[dict], int | None]:
    """Walk every page. Returns (items, total_items_reported_by_endpoint)."""
    items: list[dict] = []
    cursor = None
    reported: int | None = None
    seen_cursors: set[str] = set()
    while True:
        page = dict(params)
        if cursor:
            page["cursor"] = cursor
        data = _get(path, page)
        if reported is None:
            reported = data.get("total_items")
        items += data.get("items", [])
        cursor = data.get("next_cursor")
        if not cursor:
            return items, reported
        # A cursor that repeats means the endpoint is looping; bail rather than hang.
        if cursor in seen_cursors:
            raise CatalogueError(f"{path}: repeated pagination cursor {cursor!r}")
        seen_cursors.add(cursor)
    raise CatalogueError("unreachable")


def fetch_toolkits() -> list[dict]:
    """Every toolkit in the catalogue."""
    toolkits, _ = _paginate("toolkits", {})
    if not toolkits:
        raise CatalogueError("toolkits endpoint returned nothing")
    return toolkits


def _assert_narrowed(slug: str, tools: list[dict]) -> None:
    """Fail loudly if the toolkit filter was ignored.

    Tool slugs are ``{TOOLKIT}_{ACTION}``, but the toolkit part is the slug with
    separators stripped (``google_calendar`` -> ``GOOGLECALENDAR_``), so compare on
    the normalised prefix.
    """
    if not tools:
        return
    prefix = slug.replace("-", "").replace("_", "").upper() + "_"
    foreign = [t["slug"] for t in tools if not t["slug"].upper().startswith(prefix)]
    if foreign:
        raise CatalogueError(
            f"toolkit filter for {slug!r} was ignored: {len(foreign)}/{len(tools)} "
            f"returned tools are not {prefix}* (e.g. {foreign[:3]}). "
            "The working parameter is `toolkit_slug` (singular)."
        )


def fetch_tools(slug: str) -> list[dict]:
    """Every tool in one toolkit, verified complete and verified to belong to it."""
    tools, reported = _paginate("tools", {"toolkit_slug": slug, "limit": 100})
    _assert_narrowed(slug, tools)
    # A partial read that returns a plausible number is the failure this guards.
    if reported is not None and len(tools) != reported:
        raise CatalogueError(
            f"{slug}: paginated {len(tools)} tools but endpoint reports "
            f"total_items={reported} — pagination is incomplete"
        )
    if not tools:
        raise CatalogueError(f"{slug}: returned no tools")
    return tools


def snapshot(slugs: list[str]) -> dict:
    """Build a catalogue snapshot for the given toolkits."""
    toolkits = fetch_toolkits()
    by_slug = {t["slug"]: t for t in toolkits}
    missing = [s for s in slugs if s not in by_slug]
    if missing:
        raise CatalogueError(f"unknown toolkits: {missing}")

    tools: dict[str, list[dict]] = {}
    metadata_drift: dict[str, dict] = {}
    for slug in slugs:
        meta = by_slug[slug].get("meta") or {}
        got = fetch_tools(slug)
        drift = meta.get("tools_count")
        if drift is not None and drift != len(got):
            metadata_drift[slug] = {"meta_tools_count": drift, "served": len(got)}
        tools[slug] = [
            {
                "slug": t["slug"],
                "name": t.get("name") or "",
                "description": t.get("description") or "",
            }
            for t in got
        ]
        print(f"  {slug:<16} {len(got):>4} tools")

    return {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "toolkit_count": len(toolkits),
        # Upper bound only — see the module docstring on metadata drift.
        "tool_count_metadata_upper_bound": sum(
            (t.get("meta") or {}).get("tools_count", 0) for t in toolkits
        ),
        "metadata_drift": metadata_drift,
        "toolkits": {
            s: {
                "name": by_slug[s].get("name"),
                "auth_schemes": by_slug[s].get("auth_schemes"),
                "managed_auth": by_slug[s].get("composio_managed_auth_schemes"),
            }
            for s in slugs
        },
        "tools": tools,
    }


def session_safe_toolkits(toolkits: list[dict]) -> list[str]:
    """Toolkits that can go in a session allowlist without a manual auth config.

    Sessions reject toolkits whose auth config cannot be auto-created (``twitter``,
    ``docusign``, ``snowflake`` and most API-key toolkits), which caps how wide the
    catalogue-width sweep can go. Composio-managed and no-auth toolkits are safe.
    """
    return sorted(
        t["slug"]
        for t in toolkits
        if t.get("composio_managed_auth_schemes")
        or "NO_AUTH" in (t.get("auth_schemes") or [])
    )


if __name__ == "__main__":
    CACHE.mkdir(exist_ok=True)
    tk = fetch_toolkits()
    (CACHE / "toolkits.json").write_text(json.dumps(tk, indent=1))
    safe = session_safe_toolkits(tk)
    (CACHE / "session_safe_toolkits.json").write_text(json.dumps(safe, indent=1))
    print(f"toolkits: {len(tk)}")
    print(f"tools (summed catalogue metadata, an upper bound): "
          f"{sum((t.get('meta') or {}).get('tools_count', 0) for t in tk)}")
    print(f"session-safe toolkits: {len(safe)}")

    unsafe = [t for t in FIXTURE_TOOLKITS if t not in set(safe)]
    if unsafe:
        print(f"  ! fixture toolkits that are not session-safe: {unsafe}")
    print("\nsnapshotting fixture toolkits:")
    snap = snapshot(FIXTURE_TOOLKITS)
    (CACHE / "snapshot.json").write_text(json.dumps(snap, indent=1))
    print(f"\nsnapshot: {sum(len(v) for v in snap['tools'].values())} tools "
          f"across {len(snap['tools'])} toolkits")
    print(f"toolkits whose metadata count disagrees with what is served: "
          f"{len(snap['metadata_drift'])}/{len(FIXTURE_TOOLKITS)}")
