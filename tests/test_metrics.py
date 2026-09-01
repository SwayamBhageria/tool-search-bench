"""Unit tests for scoring.

The scorer is the one component whose bugs are invisible in the output — a wrong
rate still looks like a plausible number — so it is tested against hand-worked cases.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bench.metrics import aggregate, containment, score_case

CASE = {
    "id": "t", "kind": "exact", "toolkit": "gmail",
    "expected": ["GMAIL_SEND_EMAIL"], "acceptable": ["GMAIL_SEND_DRAFT"],
}


def test_exact_hit_at_rank_one():
    s = score_case(CASE, ["GMAIL_SEND_EMAIL"], [])
    assert s.hit_primary_strict and s.hit_primary_lenient
    assert s.rank == 1 and s.reciprocal_rank == 1.0
    assert s.toolkit_correct is True


def test_acceptable_is_lenient_only():
    s = score_case(CASE, ["GMAIL_SEND_DRAFT"], [])
    assert not s.hit_primary_strict
    assert s.hit_primary_lenient
    assert s.rank == 1


def test_rank_two_halves_reciprocal_rank():
    s = score_case(CASE, ["GMAIL_CREATE_EMAIL_DRAFT", "GMAIL_SEND_EMAIL"], [])
    assert s.rank == 2 and s.reciprocal_rank == 0.5
    # first primary tool is still Gmail, so routing was right even though rank was 2
    assert s.toolkit_correct is True


def test_hit_only_in_related_is_not_a_primary_hit():
    s = score_case(CASE, ["SLACK_SEND_MESSAGE"], ["GMAIL_SEND_EMAIL"])
    assert not s.hit_primary_lenient
    assert s.hit_any_lenient
    assert s.rank is None and s.reciprocal_rank == 0.0
    assert s.toolkit_correct is False


def test_empty_primary_scores_zero_not_crash():
    s = score_case(CASE, [], [])
    assert not s.hit_any_lenient and s.reciprocal_rank == 0.0
    assert s.toolkit_correct is None


def test_unspecified_case_has_no_toolkit_judgement():
    case = {"id": "u", "kind": "unspecified", "toolkit": None,
            "expected": [], "acceptable": ["GMAIL_SEND_EMAIL"]}
    s = score_case(case, ["GMAIL_SEND_EMAIL"], [])
    assert s.hit_primary_lenient and not s.hit_primary_strict
    assert s.toolkit_correct is None


def test_aggregate_rates():
    a = score_case(CASE, ["GMAIL_SEND_EMAIL"], [])
    b = score_case(CASE, ["SLACK_SEND_MESSAGE"], [])
    agg = aggregate([a, b])
    assert agg["n"] == 2
    assert agg["hit_primary_strict"] == 0.5
    assert agg["mrr"] == 0.5


def test_containment_detects_escape():
    c = containment(["github", "slack"], ["GITHUB_CREATE_AN_ISSUE", "GMAIL_SEND_EMAIL"])
    assert not c["contained"] and c["escaped"] == ["GMAIL_SEND_EMAIL"]


def test_containment_normalises_multiword_toolkits():
    # googlecalendar -> GOOGLECALENDAR_ prefix
    c = containment(["googlecalendar"], ["GOOGLECALENDAR_CREATE_EVENT"])
    assert c["contained"]
