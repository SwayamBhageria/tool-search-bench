"""Build and validate the ground-truth case set.

Every case is hand-written. Queries are NOT generated from the tools' own descriptions:
that method (used by several published tool-search comparisons) leaks the target's
vocabulary into the query and inflates every score. The cost is a smaller set; the
benefit is that a score means something.

Three kinds, mirroring the `exact` / `paraphrase` split Composio already uses in its own
`docs/evals/kb-search-v1.json`:

  exact        names the app and states the action plainly. Unambiguous.
  paraphrase   names the app but describes the action the way a user would, avoiding the
               tool's own vocabulary. Tests semantic matching rather than string overlap.
  unspecified  names no app. There is no single right answer, so these are scored only
               against an acceptable set and reported separately. See FINDINGS.md F4.

`expected` is the tool that should come back. `acceptable` holds tools that perform the
same operation on the same resource — judged from each tool's own schema and description,
decided before running the benchmark, never widened afterwards to accommodate a result.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (toolkit, expected_slug, exact_query, paraphrase_query, acceptable[])
TARGETS = [
    ("gmail", "GMAIL_SEND_EMAIL",
     "send an email using Gmail",
     "let a teammate know over Gmail that the quarterly report is finished", []),
    ("gmail", "GMAIL_CREATE_EMAIL_DRAFT",
     "create an email draft in Gmail",
     "write a Gmail message but leave it unsent for review later", []),
    ("gmail", "GMAIL_FETCH_EMAILS",
     "fetch emails from Gmail",
     "go through what has arrived in my Gmail inbox this morning",
     ["GMAIL_LIST_THREADS"]),
    ("gmail", "GMAIL_ADD_LABEL_TO_EMAIL",
     "add a label to an email in Gmail",
     "tag a Gmail message so I can group it with the others later",
     ["GMAIL_MODIFY_THREAD_LABELS"]),

    ("github", "GITHUB_CREATE_AN_ISSUE",
     "create an issue in a GitHub repository",
     "raise a bug report on our GitHub project so someone picks it up", []),
    ("github", "GITHUB_CREATE_A_PULL_REQUEST",
     "create a pull request on GitHub",
     "propose merging my branch into main on GitHub for review", []),
    ("github", "GITHUB_ACTIVITY_STAR_REPO_FOR_AUTHENTICATED_USER",
     "star a GitHub repository",
     "bookmark a GitHub project so it shows in my favourites", []),
    ("github", "GITHUB_CREATE_AN_ISSUE_COMMENT",
     "create a comment on a GitHub issue",
     "reply in the discussion thread of an existing GitHub issue", []),

    ("slack", "SLACK_SEND_MESSAGE",
     "send a message to a Slack channel",
     "post an update for the team in Slack so everyone sees it",
     ["SLACK_CHAT_POST_MESSAGE", "SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL"]),
    ("slack", "SLACK_CREATE_CHANNEL",
     "create a new Slack channel",
     "open a fresh Slack space for the launch discussion",
     ["SLACK_CREATE_CHANNEL_BASED_CONVERSATION"]),
    ("slack", "SLACK_ARCHIVE_A_PUBLIC_OR_PRIVATE_CHANNEL",
     "archive a Slack channel",
     "shut down a Slack channel we have finished with but keep its history",
     ["SLACK_ARCHIVE_A_SLACK_CONVERSATION"]),

    ("googlecalendar", "GOOGLECALENDAR_CREATE_EVENT",
     "create an event in Google Calendar",
     "put a design review on my Google Calendar for Thursday afternoon", []),
    ("googlecalendar", "GOOGLECALENDAR_FIND_FREE_SLOTS",
     "find free slots in Google Calendar",
     "work out when I am actually available next week from my Google Calendar",
     ["GOOGLECALENDAR_FREE_BUSY_QUERY"]),
    ("googlecalendar", "GOOGLECALENDAR_DELETE_EVENT",
     "delete an event from Google Calendar",
     "drop the standup off my Google Calendar, it is not happening", []),

    ("notion", "NOTION_CREATE_NOTION_PAGE",
     "create a new page in Notion",
     "start a fresh Notion write-up for the onboarding process", []),
    ("notion", "NOTION_QUERY_DATABASE",
     "query a Notion database",
     "pull the rows out of a Notion table that match a condition", []),
    ("notion", "NOTION_ADD_PAGE_CONTENT",
     "add content to a Notion page",
     "append a paragraph to the bottom of an existing Notion write-up",
     ["NOTION_ADD_MULTIPLE_PAGE_CONTENT", "NOTION_APPEND_BLOCK_CHILDREN"]),

    ("linear", "LINEAR_CREATE_LINEAR_ISSUE",
     "create an issue in Linear",
     "log a piece of work in Linear so it lands on the board",
     ["LINEAR_CREATE_LINEAR_ISSUE_DETAILS"]),
    ("linear", "LINEAR_LIST_LINEAR_PROJECTS",
     "list projects in Linear",
     "show me what streams of work exist in Linear right now", []),

    ("jira", "JIRA_CREATE_ISSUE",
     "create an issue in Jira",
     "open a ticket in Jira for the caching work", []),
    ("jira", "JIRA_ADD_COMMENT",
     "add a comment to a Jira issue",
     "leave a note on a Jira ticket explaining what I found", []),
    ("jira", "JIRA_ASSIGN_ISSUE",
     "assign a Jira issue to a user",
     "put a Jira ticket on a specific engineer's plate", []),

    ("googlesheets", "GOOGLESHEETS_CREATE_SPREADSHEET_ROW",
     "create a new row in a Google Sheets spreadsheet",
     "add one more line of data to the bottom of my Google Sheet",
     ["GOOGLESHEETS_SPREADSHEETS_VALUES_APPEND"]),
    ("googlesheets", "GOOGLESHEETS_LOOKUP_SPREADSHEET_ROW",
     "look up a row in a Google Sheets spreadsheet",
     "find the line in my Google Sheet where the customer id matches", []),

    ("googledrive", "GOOGLEDRIVE_CREATE_FOLDER",
     "create a folder in Google Drive",
     "make a new place in Google Drive to keep the contracts together", []),
    ("googledrive", "GOOGLEDRIVE_COPY_FILE",
     "copy a file in Google Drive",
     "duplicate a Google Drive document so I can edit it without touching the original", []),

    ("asana", "ASANA_CREATE_A_TASK",
     "create a task in Asana",
     "add a piece of work to Asana so it is tracked", []),
    ("asana", "ASANA_CREATE_A_PROJECT",
     "create a project in Asana",
     "set up a new workstream in Asana for the migration", []),

    ("stripe", "STRIPE_CREATE_CUSTOMER",
     "create a customer in Stripe",
     "register a new buyer in Stripe before charging them", []),
    ("stripe", "STRIPE_CREATE_REFUND",
     "create a refund in Stripe",
     "give a customer their money back through Stripe", []),
    ("stripe", "STRIPE_LIST_INVOICES",
     "list invoices in Stripe",
     "show me the bills we have issued through Stripe", []),

    ("todoist", "TODOIST_CREATE_TASK",
     "create a task in Todoist",
     "add something to my Todoist list for tomorrow", []),
    ("todoist", "TODOIST_CLOSE_TASK",
     "close a task in Todoist",
     "mark a Todoist item finished now that it is done", []),

    ("airtable", "AIRTABLE_CREATE_RECORD",
     "create a record in Airtable",
     "add a new entry to my Airtable base", []),

    ("figma", "FIGMA_ADD_A_COMMENT_TO_A_FILE",
     "add a comment to a Figma file",
     "leave design feedback directly on a Figma mockup", []),

    ("zoom", "ZOOM_CREATE_A_MEETING",
     "create a Zoom meeting",
     "set up a Zoom call and get a joining link", []),

    ("dropbox", "DROPBOX_CREATE_FOLDER",
     "create a folder in Dropbox",
     "make a new directory in Dropbox for the client assets", []),
    ("dropbox", "DROPBOX_MOVE_FILE_OR_FOLDER",
     "move a file in Dropbox",
     "relocate something in Dropbox to a different directory", []),

    ("googledocs", "GOOGLEDOCS_CREATE_DOCUMENT",
     "create a document in Google Docs",
     "start a blank Google Doc for the meeting notes",
     ["GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN"]),
    ("googledocs", "GOOGLEDOCS_REPLACE_ALL_TEXT",
     "replace all occurrences of text in a Google Doc",
     "swap every mention of the old product name in a Google Doc for the new one", []),

    ("hubspot", "HUBSPOT_CREATE_CONTACT",
     "create a contact in HubSpot",
     "add a new person to our HubSpot CRM after a call", []),

    ("calendly", "CALENDLY_CANCEL_EVENT",
     "cancel a scheduled event in Calendly",
     "call off a Calendly booking that is no longer needed", []),

    ("trello", "TRELLO_ADD_CARDS",
     "add a card to a Trello board",
     "put a new item on our Trello board to track it", []),
]

# App-unspecified: no single right answer, scored only against the acceptable set.
UNSPECIFIED = [
    ("send an email to a colleague",
     ["GMAIL_SEND_EMAIL", "OUTLOOK_OUTLOOK_SEND_EMAIL", "SALESFORCE_SEND_EMAIL"]),
    ("schedule a meeting for next Tuesday",
     ["GOOGLECALENDAR_CREATE_EVENT", "OUTLOOK_OUTLOOK_CALENDAR_CREATE_EVENT",
      "ZOOM_CREATE_A_MEETING", "CALENDLY_CREATE_ONE_OFF_EVENT_TYPE"]),
    ("file a bug so the team can pick it up",
     ["GITHUB_CREATE_AN_ISSUE", "JIRA_CREATE_ISSUE", "LINEAR_CREATE_LINEAR_ISSUE"]),
    ("let the team know the deploy is done",
     ["SLACK_SEND_MESSAGE", "SLACK_CHAT_POST_MESSAGE",
      "SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL"]),
    ("save a note about this customer conversation",
     ["NOTION_CREATE_NOTION_PAGE", "HUBSPOT_CREATE_CONTACT", "GOOGLEDOCS_CREATE_DOCUMENT"]),
]


def build() -> dict:
    cases = []
    for toolkit, expected, exact_q, para_q, acceptable in TARGETS:
        stem = expected.lower()
        cases.append({
            "id": f"{stem}--exact", "kind": "exact", "toolkit": toolkit,
            "query": exact_q, "expected": [expected], "acceptable": acceptable,
        })
        cases.append({
            "id": f"{stem}--paraphrase", "kind": "paraphrase", "toolkit": toolkit,
            "query": para_q, "expected": [expected], "acceptable": acceptable,
        })
    for i, (query, acceptable) in enumerate(UNSPECIFIED, 1):
        cases.append({
            "id": f"unspecified-{i:02d}", "kind": "unspecified", "toolkit": None,
            "query": query, "expected": [], "acceptable": acceptable,
        })
    return cases


def validate(cases: list[dict], snapshot: dict) -> list[str]:
    """Every referenced slug must exist in the catalogue snapshot.

    A typo'd expected slug can never be returned, so it scores 0 and reads as a
    retrieval failure. That is the single most dangerous defect this benchmark can
    have, so it is a hard error rather than a warning.
    """
    known = {t["slug"] for tools in snapshot["tools"].values() for t in tools}
    errors = []
    seen_ids, seen_queries = set(), {}
    for c in cases:
        for slug in c["expected"]:
            if slug not in known:
                errors.append(f"{c['id']}: expected slug {slug!r} not in catalogue")
            if c["toolkit"] and not slug.startswith(
                c["toolkit"].replace("_", "").upper() + "_"
            ):
                errors.append(f"{c['id']}: expected {slug!r} is not in toolkit {c['toolkit']!r}")
        # Unspecified cases deliberately reference toolkits outside the snapshot,
        # so only check the ones drawn from snapshotted toolkits.
        for slug in c["acceptable"]:
            tk = slug.split("_")[0].lower()
            if tk in snapshot["tools"] and slug not in known:
                errors.append(f"{c['id']}: acceptable slug {slug!r} not in catalogue")
        if c["id"] in seen_ids:
            errors.append(f"duplicate case id {c['id']!r}")
        seen_ids.add(c["id"])
        if c["query"] in seen_queries:
            errors.append(f"{c['id']}: query duplicates {seen_queries[c['query']]}")
        seen_queries[c["query"]] = c["id"]
        if set(c["expected"]) & set(c["acceptable"]):
            errors.append(f"{c['id']}: slug appears in both expected and acceptable")
    return errors


if __name__ == "__main__":
    snapshot = json.loads((ROOT / "cache" / "snapshot.json").read_text())
    cases = build()
    errors = validate(cases, snapshot)
    if errors:
        print(f"FIXTURE INVALID — {len(errors)} problem(s):")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    # The catalogue summary is recorded here, in a committed file, so that the report
    # can be regenerated from a fresh clone without the (regenerable, uncommitted)
    # snapshot. `meta.tools_count` overstates what the API serves, so the served/metadata
    # ratio is carried too and used to scale the full-catalogue estimate.
    served = sum(len(v) for v in snapshot["tools"].values())
    meta = sum(d["meta_tools_count"] for d in snapshot["metadata_drift"].values())
    out = {
        "version": 1,
        "catalogue": {
            "fetched_at": snapshot["fetched_at"],
            "toolkit_count": snapshot["toolkit_count"],
            "toolkits_snapshotted": len(snapshot["tools"]),
            "tools_snapshotted": served,
            "tools_metadata_upper_bound": snapshot["tool_count_metadata_upper_bound"],
            "served_to_metadata_ratio": round(served / meta, 4) if meta else 1.0,
        },
        "cases": cases,
    }
    (ROOT / "fixtures" / "cases-v1.json").write_text(json.dumps(out, indent=1))
    kinds = {}
    for c in cases:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    print(f"fixture valid: {len(cases)} cases {kinds}")
