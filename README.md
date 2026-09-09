# tool-search-bench

**How well does an agent tool-search layer find the right tool?**

Agent platforms have largely stopped loading every tool schema into the model's context.
Instead the agent is given a search tool and retrieves what it needs at runtime, out of a
catalogue far too large to hold in context. That makes **retrieval accuracy the product**:
if search returns the wrong tool, nothing downstream recovers.

This is a harness for measuring that, plus a first run against
[Composio](https://composio.dev), whose session API is built on exactly this design — an
agent gets `COMPOSIO_SEARCH_TOOLS` and searches the whole catalogue at runtime rather than
receiving tool definitions up front.

<!--AUTO:CATALOGUE-->
*Catalogue as measured: **1,468 toolkits**, ~33,000 served tools, snapshotted 2026-09-01. It moves — the toolkit count changed three times during the session that built this, so every count here is derived from the fixture rather than typed.*
<!--/AUTO:CATALOGUE-->

It is a measurement rig, not a verdict — the results below run in both directions, and a
local embedding index beats the hosted router on one of them. Where a finding implied a
concrete change, the change is implemented and its cost measured rather than left as a
suggestion.

---

## Results

91 hand-written cases. `strict` = the expected tool is in the returned primary list;
`lenient` also accepts tools performing the same operation on the same resource, fixed
before the run; `toolkit` = did it route to the right application at all. **`candidates`
is the mean number of tools returned per query** — the context the agent has to pay for,
and the column that makes the rest of the table comparable.

<!--AUTO:OVERALL-->
| retriever | catalogue searched | candidates | strict | lenient | MRR | toolkit |
|---|---|---:|---:|---:|---:|---:|
| BM25 @1 | 2,347 tools · 23 toolkits | 1.0 | 0.407 | 0.462 | 0.462 | 0.791 |
| BM25 @2 | 2,347 tools · 23 toolkits | 2.0 | 0.483 | 0.538 | 0.500 | 0.791 |
| BM25 @5 | 2,347 tools · 23 toolkits | 5.0 | 0.516 | 0.571 | 0.509 | 0.791 |
| Embedding @1 | 2,347 tools · 23 toolkits | 1.0 | 0.560 | 0.593 | 0.593 | 0.988 |
| Embedding @2 | 2,347 tools · 23 toolkits | 2.0 | 0.670 | 0.692 | 0.643 | 0.988 |
| Embedding @5 | 2,347 tools · 23 toolkits | 5.0 | 0.780 | 0.846 | 0.687 | 0.988 |
| **Composio** | 2,347 tools · 23 toolkits | 1.65 | 0.681 | 0.780 | 0.665 | 0.988 |
| **Composio** | ~33,000 tools · 1,468 toolkits | 1.57 | 0.659 | 0.736 | 0.649 | 0.988 |
| Composio `tool_search` | ~33,000 tools · 1,468 toolkits, cached plans bypassed | 2.42 | 0.560 | 0.604 | 0.543 | 0.930 |
| Composio + confidence gate | ~33,000 tools · 1,468 toolkits | 1.57 | 0.648 | 0.736 | 0.638 | 0.988 |
<!--/AUTO:OVERALL-->

Two baselines: BM25 shows what the task is worth with no semantic knowledge at all, and a
`bge-small-en-v1.5` embedding index over the same catalogue shows what a competent team
would build before buying anything. Both run locally, no API key.

*On catalogue size:* summing each toolkit's `meta.tools_count` gives 50,624 tools, but that
field overstates what the API actually serves — across the 23 snapshotted toolkits it claims
3,577 where the endpoint serves 2,347, a ratio of 0.66. Scaling by that gives **~33,000
served tools**, which is the figure used throughout. See `FINDINGS.md` F2.

> **Correction, 2026-09-09 — the ~33,000 figure is too low, and every table below inherits
> it.** The 0.66 ratio was measured against `GET /api/v3/tools`, which serves each toolkit's
> pinned base version; search returns latest. On `/api/v3.1` the same 23 toolkits serve
> **3,720** against metadata's 3,577, a ratio of **1.04** — so `meta.tools_count` was
> roughly right and slightly conservative, not a 1.5x overstatement. The corresponding
> global figure is **~52,600 served tools**, not ~33,000. The "catalogue searched" column
> in the results table therefore understates the full-catalogue rows by about a third.
> This cuts in Composio's favour: the router held 0.736 lenient over a catalogue larger
> than the one it is credited with searching. The tables are left as they were generated;
> re-running them against a v3.1 snapshot is the honest fix and has not been done.
> Reproduce the ratio with `python -m bench.version_check`.

### Read that table by candidate budget, not by the top score

**At five candidates the local embedding index beats Composio outright — 0.846 against
0.736.** That is the honest headline and it should be said first.

It is not the whole picture. To get there it spends **3× the context** and searches a
catalogue **14× smaller** — 2,347 tools against roughly 33,000. Matched on candidates, the
ordering reverses:

| | candidates | lenient |
|---|---:|---:|
| Embedding @2 | 2.0 | 0.692 |
| **Composio, same 23 toolkits** | **1.65** | **0.780** |

Composio returns fewer tools and gets more of them right, over a catalogue 14× larger, with
no index to build or keep in sync. That is the claim the design
exists to support, and on this evidence it holds — but "beats a hosted router" is within
reach of a 33M-parameter model on a laptop for anyone whose tool surface is small and
static, and that is worth knowing in both directions.

### The result that matters most is the split by query kind

<!--AUTO:BYKIND-->
| retriever | exact | paraphrase | app-unspecified |
|---|---:|---:|---:|
| BM25 @1 | 0.837 | 0.093 | 0.400 |
| BM25 @2 | 0.954 | 0.140 | 0.400 |
| BM25 @5 | 0.977 | 0.186 | 0.400 |
| Embedding @1 | 0.930 | 0.302 | 0.200 |
| Embedding @2 | 0.977 | 0.465 | 0.200 |
| Embedding @5 | 0.977 | 0.767 | 0.400 |
| **Composio** · 23 toolkits | 0.814 | 0.744 | 0.800 |
| **Composio** · full catalogue | 0.814 | 0.698 | 0.400 |
| Composio `tool_search` · full catalogue | 0.791 | 0.465 | 0.200 |
| Composio + confidence gate · full catalogue | 0.814 | 0.674 | 0.600 |
<!--/AUTO:BYKIND-->

`exact` names the app and the action plainly ("create an issue in a GitHub repository").
`paraphrase` names the app but describes the action as a person would ("raise a bug report
on our GitHub project so someone picks it up").

**Both baselines are far better on `exact` than on `paraphrase`. Composio is close to flat.**

Measured vocabulary overlap between the query and its target tool's slug and name is
**0.88 for `exact` cases and 0.25 for `paraphrase`** — so on `exact` queries a keyword
matcher is largely reading the tool's name back out of the question. Several published
tool-search comparisons build their query sets by asking an LLM to generate a query *from
each tool's own description*, which produces exactly the high-overlap regime where BM25
scores 0.977 and semantic retrieval looks unnecessary.

Phrase the same tasks the way a user would and BM25 drops to **0.186** and the embedding
index to **0.767**, while Composio holds at **0.698–0.744**. A benchmark reporting only the
first number is measuring string overlap, not tool search.

Run `python -m bench.leakage` to reproduce the overlap figures.

#### Prior work, and why this benchmark is shaped differently

The closest published comparison is Stacklok's, benchmarking their MCP Optimizer against
[Anthropic's Tool Search Tool](https://dev.to/stacklok/stackloks-mcp-optimizer-vs-anthropics-tool-search-tool-a-head-to-head-comparison-2f32)
over **2,792 tools** from the MCP-tools dataset (Alejandro Ponce de León, Stacklok). Their
reported numbers:

| | selection | retrieval |
|---|---:|---:|
| MCP Optimizer (theirs) | 93.95% | 98.03% |
| Anthropic Tool Search, BM25 | 33.70% | 47.85% |
| Anthropic Tool Search, regex | 30.01% | 39.00% |

Two things to say about it. It is a vendor publishing a comparison in which their own
product wins, which is worth holding in mind — though the methodology is described openly,
which is more than most. And the query set was built by, in their words, generating "a
synthetic query using an LLM that would naturally require that specific tool", for each
tool.

**That is precisely the construction measured above.** Queries derived from a tool's own
definition carry its vocabulary, and on this benchmark that regime is where BM25 reaches
0.977 — a keyword matcher reading the tool's name back out of the question. Which is why
the case set here is hand-written and split by phrasing, and why the overlap between query
and target is reported as a number rather than assumed away.

Composio appears in none of these comparisons, which is part of why this exists.


### What the retrieve-at-runtime design actually buys

The argument for searching instead of preloading is context cost, so it is worth a number.
Both sides are counted the same way, biased against the conclusion: preloading is costed as
**name and description only, with no parameter schemas**, while a search call is costed as
the **complete schemas it returns**, parameters included.

<!--AUTO:CONTEXTCOST-->
| | tokens |
|---|---:|
| Preload 2,347 tools (23 toolkits), name + description only | 115,542 |
| Preload all 1,468 toolkits (extrapolated) | ~7,374,593 |
| One search call, full schemas returned (mean of 6 queries) | **5,092** |

That is **23× less than preloading the small catalogue and ~1,448× less than the full one.**
<!--/AUTO:CONTEXTCOST-->

Real tool definitions carry full argument schemas, so the preload side is understated and
the true gap is wider. This is the part of the design that is not really in dispute.

### Three more things this found

**Scale costs less than expected.** Widening from 23 toolkits to the whole catalogue — 64×
the toolkits, about 14× the tools — costs roughly 4 points of accuracy (0.780 → 0.736 lenient). The
retrieve-at-runtime design broadly holds at catalogue scale, which is the claim it exists
to make.

**Routing is close to solved; action selection is not.** Composio picks the correct
*application* 98.8% of the time in both conditions. Nearly all remaining error is choosing
the wrong *action within the right app* — a GitHub question answered with the wrong GitHub
tool. That is where the headroom is.

**Cached plans earn their place.** `search_strategy: tool_search` bypasses cached plans and
drops lenient accuracy from 0.736 to 0.604, while returning more tools per query (2.42 vs
1.57). The caching layer is worth about 13 points.

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
| create a refund in Stripe | `TODOIST_CREATE_PROJECT2` |
| send an email using Gmail | `DROPBOX_SEND_TEAM_MEMBER_WELCOME_EMAIL` |
| list invoices in Stripe | `TODOIST_LIST_SECTIONS` |
| create a pull request on GitHub | `GMAIL_CREATE_PROMPT_POST` |
| create an issue in a GitHub repository | `STRIPE_CREATE_SOURCE` |
| star a GitHub repository | `ZOOM_GET_PROJECT` |
<!--/AUTO:SCOPE_EXAMPLES-->

A containment check alone would score this as a clean pass — the tools returned *are*
inside the allowlist. They are simply wrong, and an agent acting on `primary_tool_slugs`
will call them. For an operator, the failure mode is not a permissions breach but an agent
that confidently does the wrong thing at the edge of what it is allowed to do.

This is the one result here that suggests a concrete change: a no-match signal, or a
confidence floor below which the router returns nothing.

---

## A fix for the scope finding, and what it costs

The out-of-scope result above is the one thing here that implies a change, so it is
implemented rather than just reported. `bench/gate.py` wraps the retriever and refuses
answers it cannot justify.

The search response carries no confidence score, so the gate supplies one from outside:
embed the query and the top returned tool, and refuse below a cosine-similarity threshold.
It reuses the same embedding index as the baseline, so it adds no new dependency and runs
locally in about 10 ms.

Any threshold trades refusing bad answers against refusing good ones, so the whole curve is
published rather than a single tuned number:

<!--AUTO:GATE-->
| threshold | out-of-scope answers refused | correct answers lost |
|---:|---:|---:|
| 0.49 | 0/12 (0%) | 0/67 (0%) |
| 0.51 | 1/12 (8%) | 0/67 (0%) |
| 0.53 | 2/12 (17%) | 0/67 (0%) |
| 0.55 | 3/12 (25%) | 0/67 (0%) |
| 0.57 ← | 5/12 (42%) | 0/67 (0%) |
| 0.59 | 5/12 (42%) | 1/67 (1%) |
| 0.61 | 5/12 (42%) | 3/67 (4%) |
| 0.63 | 7/12 (58%) | 6/67 (9%) |
| 0.65 | 9/12 (75%) | 9/67 (13%) |
| 0.67 | 10/12 (83%) | 11/67 (16%) |
| 0.69 | 11/12 (92%) | 19/67 (28%) |
| 0.71 | 11/12 (92%) | 28/67 (42%) |
| 0.73 | 12/12 (100%) | 29/67 (43%) |
<!--/AUTO:GATE-->

The marked row is the default: **the highest threshold that costs no correct answers at
all.** A gate that suppresses working behaviour gets switched off, so costing nothing comes
first and recall second.

Measured live, end to end, rather than only from the cached scores:

<!--AUTO:GATELIVE-->
- Out-of-scope answers refused, live, 3 repeats of 12 queries: **[6, 7, 6] — mean 6.3/12 (53%)**
- Accuracy on the 91 real cases: **0.736 ungated → 0.736 gated**
- Correct answers suppressed by the gate: **none**
<!--/AUTO:GATELIVE-->

So roughly **half the out-of-scope false confidence disappears for free**, and pushing
further is available to anyone willing to trade accuracy for caution — at 0.65 it refuses
75% of them and costs 13% of correct answers.

**What this gate does not do.** The signal separates out-of-scope answers from everything
else, and nothing else from each other:

<!--AUTO:GATEPOP-->
| tools returned to… | n | mean gate score |
|---|---:|---:|
| answerable queries, answered correctly | 67 | 0.766 |
| answerable queries, answered wrongly | 24 | 0.749 |
| queries the allowlist could not serve | 12 | 0.606 |
<!--/AUTO:GATEPOP-->

Tools returned *wrongly to answerable queries* are indistinguishable from correct ones. So
this detects "nothing here fits the request", not "this particular tool is the wrong one".
It is a scope gate, not an accuracy gate, and it is only claimed as the former.

**One honest caveat about the numbers.** Out-of-scope responses are less stable run to run
than in-scope ones: the router returns different wrong tools each time, which is what you
would expect when no good answer exists. That is why the live figure is a mean of three
repeats (6, 7, 6) rather than a single run, and why the offline sweep — computed against one
stored run — reports 42% where live measurement gives 53%.

---

## The search surface is larger than the *default* catalogue listing

> **Correction, 2026-09-09.** An earlier version of this section called this an
> auditability gap: tools the router will hand an agent that an operator cannot
> enumerate through the public API. **That conclusion was wrong.** The measurement
> below is reproducible and still holds, but its cause is version resolution, not an
> undocumented surface. All 100 of the "absent" tools resolve on `/api/v3.1`. The
> original text is kept below, with the wrong paragraph marked in place rather than
> deleted, so the mistake stays legible.

`GET /api/v3/tools` resolves each toolkit to its **pinned base version**.
`COMPOSIO_SEARCH_TOOLS` returns tools from the **latest** version. The two endpoints are
answering about different catalogues. A tool added after a toolkit's base version is
therefore routable and simultaneously 404s on the endpoint the docs reach for first.

Composio's maintainers said as much on
[ComposioHQ/composio#4320](https://github.com/ComposioHQ/composio/issues/4320) on
2026-08-31: *"The search results are also based on the latest toolkit version. For tools
returned by search, use `/api/v3.1`, or pass `version: latest`."* This benchmark's
snapshot did neither, so it compared a latest-version search surface against a
base-version listing.

<!--AUTO:VERSION-->
| | |
|---|---:|
| Slugs absent under `GET /api/v3/tools/{slug}` | 100 |
| Of those, resolving under `GET /api/v3.1/tools/{slug}` | **100 (100%)** |
| Still unresolved | 0 |
| Negative control, a nonexistent slug on v3.1 | 404 |
| Positive control, `GMAIL_SEND_EMAIL` | 200 on both |
<!--/AUTO:VERSION-->

Reproduce with `python -m bench.version_check`.

**What survives.** The default listing under-reports the invocable surface by about a
sixth, and nothing in the response signals that a version was chosen for you. That is a
documented-behaviour footgun, not a hole: an operator who reads the versioning docs, or
asks, gets the complete list. It is worth a sentence in the API reference beside
`GET /tools`, and no more than that.

**What does not survive.** Any claim that the invocable set is unenumerable, that an
allowlist or audit log built from the public API is necessarily incomplete, or that the
difference is invisible from both sides. It is enumerable, on a documented endpoint,
with one parameter.

**The same cause deflates F2.** `meta.tools_count` counts the latest version while the
v3 listing serves the base, which is most of the disagreement that finding reported.
Mean |metadata - listing| across the 23 snapshotted toolkits falls from **60.7 on v3 to
6.2 on v3.1**, closer on 23 of 23. A residual remains — only 1 of 23 matches exactly —
so the count is still not authoritative, but the dramatic version of that finding was
mine, not theirs.

### The original section, as published 2026-09-02

`COMPOSIO_SEARCH_TOOLS` returns tools that `GET /api/v3/tools` will not list and that
`GET /api/v3/tools/{slug}` answers **404** for — `SLACK_ARCHIVE_CONVERSATION`,
`TODOIST_CLOSE_TASK_V1`, `GITHUB_STAR_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER` among them.

**These are not hallucinations.** Each arrives with a complete schema in `tool_schemas`, and
executing one fails on *"No active connection found for toolkit 'slack'"* — the
missing-credential path, not an unknown-tool path. They are real, routable tools that the
public catalogue does not expose.

Measured across every slug this benchmark ever saw returned:

<!--AUTO:SURFACE-->
| | |
|---|---:|
| Distinct tools the router was seen to return | 614 |
| Of those, in a toolkit this benchmark snapshotted | 584 |
| **Absent from `GET /api/v3/tools`** | **100 (17%)** |
| Sampled and checked live: returned 404 | 30/30 |
| Control set of known-good slugs: returned 200 | 15/15 |

Spread across toolkits rather than concentrated in one: `TODOIST` 13, `DROPBOX` 12, `NOTION` 10, `STRIPE` 10, `GMAIL` 7, `SLACK` 7, `ASANA` 6, `GITHUB` 4.
<!--/AUTO:SURFACE-->

Two guards, because the naive version of this measurement is wrong in both directions. Only
slugs from toolkits this benchmark actually snapshotted are judged — a `MICROSOFT_TEAMS_*`
slug is missing from the local snapshot merely because that toolkit was never fetched, and
counting it would inflate the gap. And "absent from my snapshot" is a different claim from
"absent from the API", so a sample is checked against the live endpoint alongside a control
set of known-good slugs; if the control does not fully resolve, the run raises rather than
reporting a result.

**Why it matters beyond tidiness.** *(Retracted 2026-09-09 — see the correction at the
top of this section. It is enumerable; this paragraph is wrong.)* An operator cannot
enumerate, through the public API, the full set of tools an agent in a session is able to
invoke. Roughly one in six of the
tools the router will hand an agent cannot be found in the catalogue that documents them.
Anyone building an allowlist, an audit log, or a review process from the public API is
working from an incomplete inventory — and will not know it, because nothing surfaces the
difference.

That is an auditability gap rather than a bug, and it is invisible from either side on its
own: the catalogue looks complete, and the router looks correct.

**What this does not establish is why.** Deprecated-but-routable, versioned variants, aliases
and simple listing omissions would all look identical from outside — a slug that 404s cannot
be asked about its own status. Several of the absent tools are near-duplicates of documented
ones (`TODOIST_CLOSE_TASK_V1`, `AIRTABLE_CREATE_RECORDS`), which is suggestive but not
evidence. The measurement here is the size of the gap, not its cause.

Reproduce with `python -m bench.surface`.

---

## What this does not show

- **91 cases across 23 toolkits**, written by one person. Enough to separate
  0.19 from 0.74; not enough for a leaderboard.
- **The app-unspecified set is 5 cases.** Its numbers are reported for completeness and
  should not be read as a result.
- **The baseline is handicapped in one direction, and the reason is now known.** 17% of the
  tools the router returns are not in the catalogue this benchmark snapshotted, and a local
  index cannot rank what it cannot see. The snapshot was built from `GET /api/v3/tools`,
  which serves each toolkit's pinned base version, while search returns latest — so the
  baseline indexed an older catalogue than the router searched. Every benchmark target is
  drawn from the snapshotted catalogue, where both systems can reach the answer, but the
  router is being scored on a task where it has strictly more to work with. Rebuilding the
  snapshot from `/api/v3.1` would narrow this and has not been done.
- **The baselines search a smaller catalogue than Composio does.** Both index 2,347 tools
  across 23 toolkits; unrestricted Composio searches roughly 33,000. The like-for-like row
  (Composio restricted to the same 23 toolkits) is the one to compare against, and it is in
  the table.
- **One embedding model, untuned.** `bge-small-en-v1.5` off the shelf, no fine-tuning, no
  reranker, no hybrid retrieval. A team that cared would beat it, which makes it a floor for
  what a self-built index achieves, not a ceiling.
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
python -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env                    # add your key to it
set -a && . ./.env && set +a            # the code reads the environment, not the file

./.venv/bin/python -m bench.catalogue        # snapshot the catalogue
./.venv/bin/python fixtures/build_cases.py   # build + validate the fixture
./.venv/bin/python -m pytest tests/ -q       # scoring unit tests
./.venv/bin/python -m bench.leakage          # query/target vocabulary overlap
./.venv/bin/python -m bench.experiments      # all runs -> results/
./.venv/bin/python -m bench.gate             # gate threshold sweep
./.venv/bin/python -m bench.report --write   # regenerate the tables in this file
```

**Every table in this README is generated** by `bench/report.py` from the files in
`results/` — the `<!--AUTO:...-->` blocks are rewritten in place, so a table can never drift
from the run it describes. Figures quoted in the prose are read off those tables by hand and
are checked against the raw results; the raw per-case data is in `results/` if you would
rather score it yourself.

## Layout

| path | what it is |
|---|---|
| `bench/catalogue.py` | catalogue snapshot, with the assertions that catch a filter failing open |
| `bench/retrievers.py` | `ComposioRetriever` and the `BM25Retriever` baseline |
| `bench/embeddings.py` | dense-embedding index and retriever; runs locally, no API key |
| `bench/gate.py` | the confidence gate, its wrapper, and the threshold sweep |
| `bench/metrics.py` | scoring: strict/lenient hit rate, MRR, toolkit routing, containment |
| `bench/scope.py` | allowlist containment and out-of-scope behaviour |
| `bench/surface.py` | how much of what the router returns is missing from the catalogue |
| `bench/leakage.py` | query/target vocabulary overlap, by case kind |
| `bench/run.py` | bounded-concurrency runner; records lost cases rather than dropping them |
| `bench/report.py` | renders every table in this README |
| `bench/context_cost.py` | tokens per search call vs preloading the catalogue |
| `bench/experiments.py` | runs every experiment, cheapest first |
| `fixtures/build_cases.py` | the case set and its validator |
| `tests/` | unit tests for the scorer and the gate |
| `FINDINGS.md` | platform observations made while building, each with its check |

## Licence

MIT.
