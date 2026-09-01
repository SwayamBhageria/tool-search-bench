# tool-search-bench

**How well does an agent tool-search layer find the right tool?**

Agent platforms have largely stopped loading every tool schema into the model's context.
Instead the agent is given a search tool and retrieves what it needs at runtime, out of a
catalogue far too large to hold in context. That makes **retrieval accuracy the product**:
if search returns the wrong tool, nothing downstream recovers.

This is a harness for measuring that, plus a first run against
[Composio](https://composio.dev), whose session API is built on exactly this design — an
agent gets `COMPOSIO_SEARCH_TOOLS` and searches a catalogue of **1,467 toolkits** rather
than receiving tool definitions up front.

It is a measurement rig, not a verdict. The interesting results below run in both
directions.

---

## Results

91 hand-written cases. `strict` = the expected tool is in the returned primary list;
`lenient` also accepts tools performing the same operation on the same resource, fixed
before the run; `any` also counts the related list; `toolkit` = did it route to the right
application at all.

<!--AUTO:OVERALL-->
| retriever | condition | strict | lenient | any | MRR | toolkit | tools returned |
|---|---|---:|---:|---:|---:|---:|---:|
| BM25 @1 | documented catalogue, 23 toolkits | 0.407 | 0.462 | 0.462 | 0.462 | 0.791 | 1.0 |
| BM25 @2 | documented catalogue, 23 toolkits | 0.483 | 0.538 | 0.538 | 0.500 | 0.791 | 2.0 |
| BM25 @5 | documented catalogue, 23 toolkits | 0.516 | 0.571 | 0.571 | 0.509 | 0.791 | 5.0 |
| Composio | session restricted to the same 23 toolkits | 0.681 | 0.780 | 0.824 | 0.665 | 0.988 | 1.65 |
| Composio | unrestricted — full catalogue | 0.659 | 0.736 | 0.780 | 0.649 | 0.988 | 1.57 |
| Composio `tool_search` | unrestricted, cached plans bypassed | 0.560 | 0.604 | 0.626 | 0.543 | 0.930 | 2.42 |
<!--/AUTO:OVERALL-->

### The result that matters most is the split by query kind

<!--AUTO:BYKIND-->
| retriever | exact | paraphrase | app-unspecified |
|---|---:|---:|---:|
| BM25 @1 (documented catalogue) | 0.837 | 0.093 | 0.400 |
| BM25 @2 (documented catalogue) | 0.954 | 0.140 | 0.400 |
| BM25 @5 (documented catalogue) | 0.977 | 0.186 | 0.400 |
| Composio (session restricted to the same 23 toolkits) | 0.814 | 0.744 | 0.800 |
| Composio (unrestricted) | 0.814 | 0.698 | 0.400 |
| Composio `tool_search` (unrestricted) | 0.791 | 0.465 | 0.200 |
<!--/AUTO:BYKIND-->

`exact` names the app and the action plainly ("create an issue in a GitHub repository").
`paraphrase` names the app but describes the action as a person would ("raise a bug report
on our GitHub project so someone picks it up").

**BM25 wins on `exact` and collapses on `paraphrase`. Composio holds across both.**

That gap is the whole point. Measured vocabulary overlap between the query and its target
tool's slug and name is **0.88 for `exact` cases and 0.25 for `paraphrase`** — so on
`exact` queries a keyword matcher is largely reading the tool's name back out of the
question. Several published tool-search comparisons build their query sets by asking an
LLM to generate a query *from each tool's own description*, which produces exactly the
high-overlap regime where BM25 scores 0.977 and semantic retrieval looks unnecessary.

Phrase the same tasks the way a user would and keyword matching drops to **0.186** while
Composio holds at **0.698–0.744**. Any benchmark that reports only the first number is
measuring string overlap, not tool search.

Run `python -m bench.leakage` to reproduce the overlap figures.

### Four more things this found

**Scale costs less than expected.** Widening from 23 toolkits to the full 1,467 — roughly
64× the haystack — costs about 4 points of accuracy (0.780 → 0.736 lenient). The
retrieve-at-runtime design broadly holds at catalogue scale, which is the claim it exists
to make.

**Routing is close to solved; action selection is not.** Composio picks the correct
*application* 98.8% of the time in both conditions. Nearly all remaining error is choosing
the wrong *action within the right app* — a GitHub question answered with the wrong GitHub
tool. That is where the headroom is.

**Cached plans earn their place.** `search_strategy: tool_search` bypasses cached plans and
drops lenient accuracy from 0.736 to 0.604, while returning more tools per query (2.42 vs
1.57). The caching layer is worth about 13 points.

**Composio is more precise, not just more accurate.** It returns ~1.6 tools per query
against BM25's fixed 5, and still beats BM25 given the same budget (BM25@1: 0.462,
BM25@2: 0.538). Fewer, better candidates is the context-cost argument for this design, and
it holds.

---

## Every `exact` miss, and why the headline number is conservative

Composio missed 8 of 43 `exact` cases on the full catalogue. All eight, in full:

<!--AUTO:MISSES-->
| query | expected | returned |
|---|---|---|
| create a record in Airtable | `AIRTABLE_CREATE_RECORD` | `AIRTABLE_CREATE_RECORDS` |
| create a project in Asana | `ASANA_CREATE_A_PROJECT` | `ASANA_CREATE_PROJECT_FOR_WORKSPACE`, `ASANA_CREATE_PROJECT_FOR_TEAM` |
| cancel a scheduled event in Calendly | `CALENDLY_CANCEL_EVENT` | `CALENDLY_LIST_SCHEDULED_EVENTS`, `CALENDLY_GET_EVENT` |
| star a GitHub repository | `GITHUB_ACTIVITY_STAR_REPO_FOR_AUTHENTICATED_USER` | `GITHUB_STAR_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER`, `GITHUB_GET_A_REPOSITORY` |
| copy a file in Google Drive | `GOOGLEDRIVE_COPY_FILE` | `GOOGLEDRIVE_COPY_FILE_ADVANCED` |
| query a Notion database | `NOTION_QUERY_DATABASE` | `NOTION_SEARCH_NOTION_PAGE`, `NOTION_FETCH_DATABASE`, `NOTION_QUERY_DATABASE_WITH_FILTER` |
| archive a Slack channel | `SLACK_ARCHIVE_A_PUBLIC_OR_PRIVATE_CHANNEL` | `SLACK_ARCHIVE_CONVERSATION` |
| close a task in Todoist | `TODOIST_CLOSE_TASK` | `TODOIST_CLOSE_TASK_V1` |
<!--/AUTO:MISSES-->

**Six of these eight are the same operation under a different slug.** `TODOIST_CLOSE_TASK`
against `TODOIST_CLOSE_TASK_V1`; `AIRTABLE_CREATE_RECORD` against `AIRTABLE_CREATE_RECORDS`;
`GOOGLEDRIVE_COPY_FILE` against `GOOGLEDRIVE_COPY_FILE_ADVANCED`; two different GitHub tools
that both star a repository. Judged on whether an agent would accomplish the user's task,
`exact` accuracy is nearer **0.95 than the 0.814 reported above**.

That correction is **deliberately not folded into the headline tables.** It is a judgement
made after seeing the results, and silently widening the `acceptable` sets to absorb
outcomes is precisely how a benchmark becomes unfalsifiable. The conservative number stands
as the measurement; this section stands as the caveat, and the raw data in `results/` lets
anyone score it their own way.

Two of the eight look like genuine retrieval errors: the Calendly query asked to *cancel* an
event and got tools that list and fetch them, and the Notion query returned a search and a
fetch ahead of the query tool.

**The scoring artefact is itself a finding.** The catalogue carries many near-duplicate and
versioned tools that do the same job — `_V1` suffixes, singular/plural pairs, `_ADVANCED`
variants, and two independently-named GitHub star tools. Every one of those is a
disambiguation the router has to perform, and a place a downstream agent can pick a tool
that works differently than intended. Deduplicating them would likely raise measured
accuracy without touching the retrieval model at all.

---

## Scope: does a session's toolkit allowlist hold?

A session created with `toolkits=[...]` should never surface a tool from outside that list.
Each restricted session was given queries it **cannot** serve — asking for Gmail when only
`github, figma, stripe, dropbox, trello` are allowed — plus a positive control it can serve,
so that a merely broken session could not be mistaken for good containment.

<!--AUTO:SCOPE-->
- Positive controls passed: **4/4** (the restricted sessions do work)
- Allowlist leak rate: **0%** across 12 impossible queries
- Declined (returned no tool): **0%**
- Answered anyway with an in-scope but wrong tool: **100%**
<!--/AUTO:SCOPE-->

**The boundary holds perfectly. There is no "no match" signal at it.**

Containment never failed once. But in every impossible case the router returned a
confident, in-scope, semantically wrong tool rather than reporting that nothing suitable
was available:

<!--AUTO:SCOPE_EXAMPLES-->
| query (impossible within the allowlist) | tool returned |
|---|---|
| search my Outlook mail for a message about invoices | `STRIPE_SEARCH_INVOICES` |
| create an email draft in Gmail | `GITHUB_CREATE_DRAFT_ITEM_FOR_USER_PROJECT` |
| cancel a scheduled event in Calendly | `SLACK_DELETE_SCHEDULED_MESSAGE` |
| find free slots in my Google Calendar next week | `SLACK_RETRIEVE_CURRENT_USER_DND_STATUS` |
| create an event in Google Calendar | `NOTION_CREATE_VIEW` |
| create a customer in Stripe | `TODOIST_CREATE_PROJECT2` |
<!--/AUTO:SCOPE_EXAMPLES-->

A containment check alone would score this as a clean pass — the tools returned *are*
inside the allowlist. They are simply wrong, and an agent acting on `primary_tool_slugs`
will call them. For an operator, the failure mode is not a permissions breach but an agent
that confidently does the wrong thing at the edge of what it is allowed to do.

This is the one result here that suggests a concrete change: a no-match signal, or a
confidence floor below which the router returns nothing.

---

## What this does not show

- **91 cases across 23 of 1,467 toolkits**, written by one person. Enough to separate
  0.19 from 0.74; not enough for a leaderboard.
- **The app-unspecified set is 5 cases.** Its numbers are reported for completeness and
  should not be read as a result.
- **The baseline is handicapped in one direction.** `COMPOSIO_SEARCH_TOOLS` can return
  tools that `GET /api/v3/tools` does not list and that `/tools/{slug}` 404s — these are
  real, routable tools with full schemas, not hallucinations (see `FINDINGS.md` F3). BM25
  cannot index what the catalogue does not expose, so every benchmark target is drawn from
  the documented catalogue, where both systems can reach the answer.
- **BM25 is a floor, not a rival.** It is there to show what the task is worth without
  semantic retrieval. A dense-embedding baseline over the same catalogue would be the real
  comparison and is not implemented here, so "beats BM25" should be read as "clears the
  trivial bar", not "beats the state of the art".
- **`acceptable` sets are a judgement call.** They were fixed before running and never
  widened to accommodate a result, but a different author would draw them differently.
  `strict` numbers, which ignore them entirely, are reported alongside.
- **One vendor, one point in time**, on a catalogue that moves — the toolkit count changed
  during the session that built this.
- **Nothing here measures execution.** Whether the chosen tool then *works* is a separate
  question this harness does not touch.

Run-to-run stability was checked rather than assumed: 15 cases run 3× returned identical
tool lists in 14 of 15. Single-run figures are reported on that basis.

---

## Reproducing

```bash
python -m venv .venv && ./.venv/bin/pip install composio pytest
cp .env.example .env          # add a key — the free tier is 100k tool calls/month
export COMPOSIO_API_KEY=...

./.venv/bin/python -m bench.catalogue        # snapshot the catalogue
./.venv/bin/python fixtures/build_cases.py   # build + validate the fixture
./.venv/bin/python -m pytest tests/ -q       # scoring unit tests
./.venv/bin/python -m bench.leakage          # query/target vocabulary overlap
./.venv/bin/python -m bench.experiments      # all runs -> results/
./.venv/bin/python -m bench.report --write   # regenerate the tables in this file
```

Every number in this README is emitted by `bench/report.py` from the files in `results/`.
None are typed by hand.

## Layout

| path | what it is |
|---|---|
| `bench/catalogue.py` | catalogue snapshot, with the assertions that catch a filter failing open |
| `bench/retrievers.py` | `ComposioRetriever` and the `BM25Retriever` baseline |
| `bench/metrics.py` | scoring: strict/lenient hit rate, MRR, toolkit routing, containment |
| `bench/scope.py` | allowlist containment and out-of-scope behaviour |
| `bench/leakage.py` | query/target vocabulary overlap, by case kind |
| `bench/run.py` | bounded-concurrency runner; records lost cases rather than dropping them |
| `bench/report.py` | renders every table in this README |
| `fixtures/build_cases.py` | the case set and its validator |
| `FINDINGS.md` | platform observations made while building, each with its check |

## Licence

MIT.
