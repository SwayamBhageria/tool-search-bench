"""Dense-embedding retrieval over the tool catalogue.

This is the baseline that matters. BM25 shows what the task is worth with no semantic
knowledge at all; a sentence-embedding retriever is what a competent team would actually
build before buying anything, so it is the honest bar to clear.

It is deliberately given its best shot: a model trained for retrieval rather than the
smallest one available, the same catalogue text the BM25 baseline sees, and cached
embeddings so the comparison can be re-run cheaply. A baseline that has been quietly
handicapped proves nothing about the system it is compared against.

Runs locally on CPU with no API key, so anyone can reproduce the baseline half of this
benchmark without an account.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"

# bge-small is a retrieval-trained model (BEIR-competitive at 33M params). Its documented
# convention is to prefix queries — not documents — with an instruction, which is followed
# here; omitting it measurably degrades the model and would understate the baseline.
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def tool_text(tool: dict) -> str:
    """The text a retriever sees for one tool. Identical to the BM25 baseline's view."""
    return (
        tool["slug"].replace("_", " ")
        + " " + (tool.get("name") or "")
        + " " + (tool.get("description") or "")
    ).strip()


class EmbeddingIndex:
    """Cosine-similarity index over tool text, with an on-disk embedding cache."""

    def __init__(self, tools: list[dict], model_name: str = DEFAULT_MODEL):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.slugs = [t["slug"] for t in tools]
        texts = [tool_text(t) for t in tools]

        key = hashlib.sha256(
            (model_name + "|" + "|".join(self.slugs)).encode()
        ).hexdigest()[:16]
        cache_file = CACHE / f"emb_{key}.npy"
        if cache_file.exists():
            self.matrix = np.load(cache_file)
        else:
            self.matrix = self.model.encode(
                texts, batch_size=64, normalize_embeddings=True,
                show_progress_bar=True, convert_to_numpy=True,
            )
            CACHE.mkdir(exist_ok=True)
            np.save(cache_file, self.matrix)

    def encode_query(self, query: str) -> np.ndarray:
        return self.model.encode(
            [QUERY_PREFIX + query], normalize_embeddings=True, convert_to_numpy=True
        )[0]

    def rank(self, query: str, top_k: int) -> list[tuple[str, float]]:
        sims = self.matrix @ self.encode_query(query)
        order = np.argsort(-sims)[:top_k]
        return [(self.slugs[i], float(sims[i])) for i in order]

    def similarity(self, query: str, slug: str) -> float | None:
        """Cosine similarity between a query and one named tool."""
        try:
            i = self.slugs.index(slug)
        except ValueError:
            return None
        return float(self.matrix[i] @ self.encode_query(query))


class EmbeddingRetriever:
    def __init__(self, tools: list[dict], top_k: int = 5, model_name: str = DEFAULT_MODEL):
        self.index = EmbeddingIndex(tools, model_name)
        self.top_k = top_k
        self.name = f"embed[{model_name.split('/')[-1]}]@{top_k}"

    def search(self, query: str, **_) -> tuple[list[str], list[str]]:
        return [slug for slug, _ in self.index.rank(query, self.top_k)], []
