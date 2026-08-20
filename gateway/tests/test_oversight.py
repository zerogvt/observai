"""Unit tests for the human-oversight hook.

Pins the promise that *every flag has a stated reason* and that the trigger
conditions (low confidence, empty output, explicit review request) each fire.
"""
from types import SimpleNamespace

from oversight import review_response

REQ = SimpleNamespace(task="summarize")


def test_healthy_response_is_not_flagged():
    r = review_response(REQ, {"confidence": 0.92, "output": "a good answer", "needs_review": False})
    assert r.flagged is False
    assert r.reasons == []


def test_low_confidence_is_flagged_with_reason():
    r = review_response(REQ, {"confidence": 0.3, "output": "ok"})
    assert r.flagged is True
    assert any("confidence" in reason for reason in r.reasons)


def test_confidence_exactly_at_floor_is_not_flagged():
    # floor is 0.6; the check is strict "< floor", so 0.6 passes.
    r = review_response(REQ, {"confidence": 0.6, "output": "ok"})
    assert r.flagged is False


def test_empty_output_is_flagged():
    r = review_response(REQ, {"confidence": 0.92, "output": "   "})
    assert r.flagged is True
    assert "empty model output" in r.reasons


def test_explicit_review_request_is_flagged():
    r = review_response(REQ, {"confidence": 0.92, "output": "ok", "needs_review": True})
    assert r.flagged is True
    assert any("requested review" in reason for reason in r.reasons)


def test_missing_confidence_does_not_crash_or_flag():
    # No confidence key at all: the isinstance check skips it; output is fine.
    r = review_response(REQ, {"output": "a good answer"})
    assert r.flagged is False


def test_multiple_problems_accumulate_reasons():
    r = review_response(REQ, {"confidence": 0.1, "output": "", "needs_review": True})
    assert r.flagged is True
    assert len(r.reasons) == 3  # low confidence + empty output + explicit review
