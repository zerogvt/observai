"""Unit tests for confidence.estimate — the explainable proxy.

These pin the *behavior we promise*: every flag has a stated reason, and the
score moves for understandable causes. If someone later changes the scoring,
these tests force them to update the story deliberately.
"""
from confidence import estimate


def test_normal_output_is_baseline_and_not_flagged():
    r = estimate({"output": "A reasonable answer.", "done_reason": "stop"})
    assert r["confidence"] == 0.85
    assert r["needs_review"] is False
    assert r["signals"] == []


def test_empty_output_is_zero_and_flagged():
    r = estimate({"output": "   ", "done_reason": "stop"})
    assert r["confidence"] == 0.0
    assert r["needs_review"] is True
    assert "empty output" in r["signals"]


def test_truncated_output_is_penalized_with_reason():
    r = estimate({"output": "This was cut off because", "done_reason": "length"})
    assert r["confidence"] == 0.60  # 0.85 - 0.25
    assert any("truncated" in s for s in r["signals"])


def test_short_output_is_penalized():
    r = estimate({"output": "ok", "done_reason": "stop"})
    assert r["confidence"] == 0.65  # 0.85 - 0.20
    assert any("short" in s for s in r["signals"])


def test_truncated_and_short_accumulate_and_drop_below_floor():
    r = estimate({"output": "Hi", "done_reason": "length"})
    assert r["confidence"] == 0.40  # 0.85 - 0.25 - 0.20
    assert r["needs_review"] is True
    # both root-cause signals present, plus the floor explanation
    assert any("truncated" in s for s in r["signals"])
    assert any("short" in s for s in r["signals"])
    assert any("below floor" in s for s in r["signals"])


def test_score_is_clamped_to_unit_interval():
    r = estimate({"output": "", "done_reason": "length"})
    assert 0.0 <= r["confidence"] <= 1.0
