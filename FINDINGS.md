# Running findings

Observations made while building the harness, each with the check that produced it.
Kept separate from results so that method notes and measurements never get confused.

## F1 — The tool-listing endpoint's filter fails open
`GET /api/v3/tools` filters on `toolkit_slug` (singular). Passing `toolkit_slugs`,
`toolkits`, `toolkit`, `app` or `apps` returns **HTTP 200 and the unfiltered global
catalogue** — no error. Asking for Gmail that way returns 500 rows, zero of them Gmail.
*Check:* asserted that every returned slug carries the requested toolkit prefix
(`bench/catalogue.py::_assert_narrowed`).

## F2 — Toolkit metadata disagrees with what the tools endpoint serves
> **Deflated 2026-09-09 by the same cause as F3.** `meta.tools_count` counts the latest
> toolkit version; the v3 listing serves the pinned base. Mean |metadata - listing| over
> the same 23 toolkits falls from **60.7 on v3 to 6.2 on v3.1**, closer on 23 of 23, and
> the two reverse-direction cases below (HubSpot 244 vs 304, Trello 322 vs 345) become
> 245 and 329. A residual survives — 1 of 23 matches exactly — so the summed figure is
> still an upper bound, but "23/23 disagreed, in both directions" overstated it.
> Reproduce with `python -m bench.version_check`.
`meta.tools_count` on a toolkit does not match the number of tools the endpoint serves
for it. In a 23-toolkit sample **23/23 disagreed**, in both directions:
Gmail 61 vs 23, Stripe 425 vs 33, Dropbox 174 vs 11, but HubSpot 244 vs **304** and
Trello 322 vs **345**. So the summed catalogue figure (50,489 tools over 1,467 toolkits)
is an upper bound, not a count.
*Check:* paginated to exhaustion and compared against the endpoint's own `total_items`.

## F3 — The router surface is a superset of the *default* catalogue listing
> **Corrected 2026-09-09.** The measurement below stands; the conclusion drawn from it in
> point 2 does not. `GET /api/v3/tools` serves each toolkit's pinned base version while
> search returns latest, so the two endpoints describe different catalogues. **All 100
> "absent" slugs resolve on `/api/v3.1/tools/{slug}`** (negative control: a nonexistent
> slug still 404s there). Composio's maintainers documented this on
> [ComposioHQ/composio#4320](https://github.com/ComposioHQ/composio/issues/4320) on
> 2026-08-31, before this was published. Reproduce with `python -m bench.version_check`.
> The original wording is kept below unedited.
`COMPOSIO_SEARCH_TOOLS` returns tools that `GET /api/v3/tools` will not list and that
`GET /api/v3/tools/{slug}` answers **404** for — e.g. `SLACK_ARCHIVE_CONVERSATION`,
`SLACKBOT_ARCHIVE_CONVERSATION`, `GITHUB_ADD_EMAIL_ADDRESS_FOR_AUTHENTICATED_USER`.

**These are not hallucinations.** Each arrives with a full schema in `tool_schemas`, and
executing one fails on *"No active connection found for toolkit 'slack'"* — the
missing-credential path, not an unknown-tool path. They are real, routable tools that the
public catalogue does not expose.

**Measured, not anecdotal:** of 584 returned slugs from snapshotted toolkits, **100 (17%)
are absent from the catalogue**; a 30-slug sample all returned 404 live while a 15-slug
control of known-good slugs all returned 200. See the README section "The search surface is
larger than the documented catalogue", reproducible with `python -m bench.surface`.

Two consequences:
1. **Methodological.** A baseline that indexes the documented catalogue cannot see part of
   what the router can return. Benchmark targets are therefore drawn only from the
   documented catalogue, so both systems can reach every answer.
2. **Substantive.** ~~An operator cannot enumerate, through the public API, the full set of
   tools an agent in a session is able to invoke. That is an auditability gap rather than
   a bug.~~ **Wrong — retracted, see the correction above.** What is left is that the
   default listing under-reports the invocable surface by about a sixth with nothing in the
   response to say a version was chosen for you.

*Check:* fetched each slug individually (404), then confirmed schema presence and
execution behaviour inside a session.

## F4 — Naming the app resolves most apparent errors
"send an email to a colleague" returns `SALESFORCE_SEND_EMAIL` / `OUTLOOK_SEND_EMAIL` and
no Gmail tool at all. This looked like a retrieval failure and is not one — the query
never says which mail system. "send an email using Gmail" returns `GMAIL_SEND_EMAIL`
alone. **App-unspecified queries have no single correct answer and must not be scored as
though they do.** This is why the fixture separates app-specified cases (scored strictly)
from app-unspecified ones (scored against an acceptable set).

## F5 — Session allowlists reject toolkits that need a manual auth config
`sessions.create(toolkits=[...])` fails with HTTP 400 when any toolkit's auth config
cannot be auto-created (`twitter`, `docusign`, `snowflake`, and most API-key toolkits).
Of 1,467 toolkits only **153** are session-safe (Composio-managed auth, or no auth), which
caps how wide a restricted-session sweep can go. Unrestricted sessions still exercise the
whole catalogue.

## F6 — The catalogue carries near-duplicate and versioned tools
Several tools that perform the same operation exist under separate slugs:
`TODOIST_CLOSE_TASK` / `TODOIST_CLOSE_TASK_V1`, `AIRTABLE_CREATE_RECORD` /
`AIRTABLE_CREATE_RECORDS`, `GOOGLEDRIVE_COPY_FILE` / `GOOGLEDRIVE_COPY_FILE_ADVANCED`,
`SLACK_ARCHIVE_A_PUBLIC_OR_PRIVATE_CHANNEL` / `SLACK_ARCHIVE_CONVERSATION`, and two
independently-named GitHub tools that both star a repository.

Each pair is a disambiguation the router must perform, and a place a downstream agent can
select a tool that behaves differently from the one intended. It also depresses any
exact-slug benchmark score without any retrieval error having occurred — 6 of the 8
`exact` misses measured here are of this kind.
*Check:* manual review of every `exact` miss; the full list is in the README.

## F7 — No published accuracy number for Composio's tool search
Searched their full docs corpus (`llms-full.txt`, 1.07 MB — zero occurrences of
"benchmark", zero percentage figures), all 16 blog posts, the homepage, and the repo. The
only Tool Router post is the beta announcement; the one post with "Accuracy" in the title
benchmarks **GPT-4's** function calling, not their router.

The repo does contain ranked-retrieval eval machinery — `docs/evals/kb-search-v1.json` and
`docs/scripts/eval-kb-search.ts`, scoring `exact` vs `paraphrase` cases against expected
results — but it is pointed at their **documentation search**, not at
`COMPOSIO_SEARCH_TOOLS`.

Meanwhile a competitor publishes head-to-head figures over 2,792 tools (see the README's
prior-work section). **The claim to make is "I could not find a published number", never
"they have never measured this"** — internal benchmarks, investor material and conference
talks are not visible from outside.
