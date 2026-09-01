"""Tests for the confidence gate.

The gate's own scoring is an embedding call, so these use a stub index: what is under
test is the decision logic and the sweep arithmetic, not the model.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np

from bench.gate import ConfidenceGate, GatedRetriever


class _StubIndex:
    """Returns a fixed similarity by encoding everything to controlled vectors."""

    def __init__(self, sim: float):
        self._sim = sim

        class _M:
            @staticmethod
            def encode(texts, **_):
                return np.array([[1.0, 0.0]], dtype=float)

        self.model = _M()

    def encode_query(self, _q):
        return np.array([self._sim, 0.0], dtype=float)


def _gate(sim: float, threshold: float = 0.57) -> ConfidenceGate:
    return ConfidenceGate(_StubIndex(sim), threshold=threshold, tools=[])


def test_high_similarity_passes():
    d = _gate(0.90).check("send an email using Gmail", ["GMAIL_SEND_EMAIL"])
    assert d.passed and d.score == 0.90


def test_low_similarity_refuses():
    d = _gate(0.31).check("star a GitHub repository", ["ZOOM_GET_PROJECT"])
    assert not d.passed and "0.310" in d.reason


def test_threshold_is_exclusive_lower_bound():
    # exactly at the threshold should pass, not refuse
    assert _gate(0.57, threshold=0.57).check("q", ["X_Y"]).passed


def test_empty_primary_is_not_gated():
    d = _gate(0.10).check("q", [])
    assert d.passed and d.score is None


def test_gated_retriever_suppresses_primary_but_keeps_related():
    class Inner:
        name = "inner"

        def search(self, *_a, **_k):
            return ["ZOOM_GET_PROJECT"], ["ZOOM_GET_A_MEETING"]

    g = GatedRetriever(Inner(), _gate(0.20))
    primary, related = g.search("star a GitHub repository")
    assert primary == []
    assert related == ["ZOOM_GET_A_MEETING"]
    assert "gate@0.57" in g.name


def test_gated_retriever_passes_through_when_confident():
    class Inner:
        name = "inner"

        def search(self, *_a, **_k):
            return ["GMAIL_SEND_EMAIL"], []

    primary, _ = GatedRetriever(Inner(), _gate(0.95)).search("send an email using Gmail")
    assert primary == ["GMAIL_SEND_EMAIL"]


def test_unknown_slug_falls_back_to_slug_words():
    # Tools absent from the catalogue (FINDINGS.md F3) must still be scorable.
    g = _gate(0.80)
    assert g._tool_text("SLACK_ARCHIVE_CONVERSATION") == "SLACK ARCHIVE CONVERSATION"


def test_known_slug_uses_catalogue_text():
    tool = {"slug": "GMAIL_SEND_EMAIL", "name": "Send email", "description": "Sends mail."}
    g = ConfidenceGate(_StubIndex(0.8), tools=[tool])
    assert "Sends mail." in g._tool_text("GMAIL_SEND_EMAIL")


def test_sweep_monotonic_in_threshold():
    from bench.gate import sweep

    res = sweep([0.50, 0.60, 0.70])
    refused = [r["out_of_scope_refused"] for r in res["rows"]]
    lost = [r["correct_answers_lost"] for r in res["rows"]]
    # Raising the threshold can only refuse more of both.
    assert refused == sorted(refused)
    assert lost == sorted(lost)
