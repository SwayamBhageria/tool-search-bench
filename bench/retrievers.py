"""Retrievers under test.

A retriever takes a natural-language task and returns (primary, related) tool slugs.

Two are implemented:

  ComposioRetriever  the product: `COMPOSIO_SEARCH_TOOLS` inside a session.
  BM25Retriever      a deliberately dumb keyword baseline over the same catalogue.

The baseline exists because an accuracy figure on its own says nothing. "Composio scores
X" is only meaningful against what a trivial method scores on the identical task set.
BM25 is the right foil: it is well understood, has no semantic knowledge at all, and is
what a team would reach for before building anything clever.

One caveat is recorded in FINDINGS.md F3 — the router can return tools the documented
catalogue does not list, which BM25 therefore cannot index. Benchmark targets are drawn
only from the documented catalogue so that both retrievers can reach every answer.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class BM25Retriever:
    """Okapi BM25 over each tool's slug, name and description.

    Implemented here rather than pulled in as a dependency so the baseline is fully
    visible — a baseline nobody can read is not a baseline.
    """

    name = "bm25"

    def __init__(self, tools: list[dict], k1: float = 1.5, b: float = 0.75, top_k: int = 5):
        self.k1, self.b, self.top_k = k1, b, top_k
        self.slugs = [t["slug"] for t in tools]
        docs = [
            tokenize(t["slug"].replace("_", " ") + " " + t.get("name", "") + " "
                     + t.get("description", ""))
            for t in tools
        ]
        self.docs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.avgdl = sum(self.lens) / len(self.lens) if self.lens else 0.0
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {
            term: math.log(1 + (n - c + 0.5) / (c + 0.5)) for term, c in df.items()
        }

    def search(self, query: str, **_) -> tuple[list[str], list[str]]:
        q = tokenize(query)
        scores = []
        for i, doc in enumerate(self.docs):
            s = 0.0
            dl = self.lens[i]
            for term in q:
                tf = doc.get(term)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                s += self.idf.get(term, 0.0) * tf * (self.k1 + 1) / denom
            if s > 0:
                scores.append((s, self.slugs[i]))
        scores.sort(reverse=True)
        ranked = [slug for _, slug in scores[: self.top_k]]
        # BM25 has no notion of primary vs related; treat its whole ranked list as
        # primary so it is scored the same way the router's primary list is.
        return ranked, []


class ComposioRetriever:
    """`COMPOSIO_SEARCH_TOOLS` inside a Composio session.

    A **fresh session per query**. Composio's meta tools deliberately share context
    across calls within a session ("storing discovered IDs and relationships"), so
    reusing one session would let earlier queries influence later ones and the cases
    would stop being independent.
    """

    def __init__(self, toolkits: list[str] | None = None, strategy: str | None = None):
        from composio import Composio

        self.client = Composio(api_key=os.environ["COMPOSIO_API_KEY"])
        self.toolkits = toolkits
        self.strategy = strategy
        width = "all" if toolkits is None else str(len(toolkits))
        self.name = f"composio[w={width},s={strategy or 'auto'}]"

    def search(self, query: str, user_id: str = "bench") -> tuple[list[str], list[str]]:
        session = (
            self.client.sessions.create(user_id=user_id, toolkits=self.toolkits)
            if self.toolkits is not None
            else self.client.sessions.create(user_id=user_id)
        )
        args: dict = {
            "queries": [{"use_case": query}],
            "session": {"generate_id": True},
        }
        if self.strategy:
            args["search_strategy"] = self.strategy
        resp = session.execute("COMPOSIO_SEARCH_TOOLS", arguments=args)
        data = resp.model_dump()["data"]
        results = data.get("results") or []
        if not results:
            raise RuntimeError(f"search returned no results block for {query!r}")
        r = results[0]
        if r.get("error"):
            raise RuntimeError(f"search error for {query!r}: {r['error']}")
        return list(r.get("primary_tool_slugs") or []), list(r.get("related_tool_slugs") or [])
