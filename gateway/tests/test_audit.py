"""Tests for the flagged-chat audit sink.  (feature: flagged chats sink)

`build_record` is a pure function, so most of this is direct assertion on the
record shape. The properties worth pinning are the ones an auditor would
actually rely on:

  - a flagged response carries the prompt and the reply
  - an unflagged one carries the metadata but not the content
  - the digest survives truncation, so a shortened field still proves its bytes
  - why content is absent is a recorded field, never an inference
  - the sink can never break the response it is recording
"""
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import audit
from config import Config

REQ = SimpleNamespace(task="chat", input_text="tell me about bicycles", options={})

RESULT = {
    "output": "Bicycles are human-powered vehicles.",
    "model": "qwen:0.5b",
    "tokens_in": 18,
    "tokens_out": 11,
    "cost_usd": 0.0,
    "confidence": 0.25,
    "needs_review": True,
    "latency_ms": 1234.5,
    "tokens_per_sec": 8.9,
    "done_reason": "stop",
    "confidence_signals": ["discussion about bicycles", "confidence 0.25 below floor 0.70"],
}

FLAGGED = SimpleNamespace(flagged=True, reasons=["confidence 0.25 below floor 0.60"])
CLEAN = SimpleNamespace(flagged=False, reasons=[])


@pytest.fixture
def audit_config(monkeypatch):
    """Set the audit knobs explicitly, so a changed default can't hide a bug."""
    def _set(**kw):
        defaults = {
            "AUDIT_ENABLED": True,
            "AUDIT_RECORD_UNFLAGGED": True,
            "AUDIT_LOG_CONTENT": True,
            "AUDIT_HASH_CONTENT": False,
            "AUDIT_MAX_TEXT_CHARS": 2000,
        }
        defaults.update(kw)
        for k, v in defaults.items():
            monkeypatch.setattr(Config, k, v)
    return _set


# --- record shape -----------------------------------------------------------

def test_flagged_record_carries_prompt_and_reply(audit_config):
    audit_config()
    r = audit.build_record("req-1", REQ, RESULT, FLAGGED)

    assert r["audit.event.type"] == audit.EVENT_TYPE
    assert r["audit.schema.version"] == audit.SCHEMA_VERSION
    assert r["audit.request_id"] == "req-1"
    assert r["audit.flagged"] is True
    assert r["audit.content.mode"] == "text"
    assert r["audit.prompt"] == REQ.input_text
    assert r["audit.response"] == RESULT["output"]


def test_record_carries_the_signals_the_span_drops(audit_config):
    # These four arrive from the inference service and were previously thrown
    # away by the gateway — the audit record is the only place they land.
    audit_config()
    r = audit.build_record("req-1", REQ, RESULT, FLAGGED)

    assert r["audit.done_reason"] == "stop"
    assert r["audit.latency.ms"] == 1234.5
    assert r["audit.tokens_per_sec"] == 8.9
    assert r["audit.confidence.signals"] == RESULT["confidence_signals"]


def test_reasons_available_as_list_and_joined_string(audit_config):
    # The joined form matches `ai.oversight.reasons` on the span, so the
    # dashboard's splitString(..., "; ") works against either source.
    audit_config()
    r = audit.build_record("req-1", REQ, RESULT, FLAGGED)

    assert r["audit.reasons"] == FLAGGED.reasons
    assert r["audit.reasons.text"] == "confidence 0.25 below floor 0.60"


def test_char_counts_are_recorded_for_both_fields(audit_config):
    audit_config()
    r = audit.build_record("req-1", REQ, RESULT, FLAGGED)

    assert r["audit.prompt.chars"] == len(REQ.input_text)
    assert r["audit.response.chars"] == len(RESULT["output"])


def test_unreported_fields_are_omitted_not_nulled(audit_config):
    # A field absent from the inference response should be absent from the
    # record, so "not reported" doesn't arrive as a null to query around.
    audit_config()
    r = audit.build_record("req-1", REQ, {"output": "hi"}, FLAGGED)

    assert "audit.done_reason" not in r
    assert "audit.confidence" not in r
    assert r["audit.response"] == "hi"


# --- content modes ----------------------------------------------------------

def test_unflagged_record_has_metadata_but_no_content(audit_config):
    audit_config()
    r = audit.build_record("req-2", REQ, RESULT, CLEAN)

    assert r["audit.flagged"] is False
    assert r["audit.content.mode"] == "omitted:not_flagged"
    assert "audit.prompt" not in r
    assert "audit.response" not in r
    assert "audit.prompt.sha256" not in r
    # The denominator still exists: counts are kept even with no text.
    assert r["audit.prompt.chars"] == len(REQ.input_text)
    assert r["audit.tokens.out"] == 11


def test_content_disabled_records_reason_and_drops_text(audit_config):
    audit_config(AUDIT_LOG_CONTENT=False)
    r = audit.build_record("req-3", REQ, RESULT, FLAGGED)

    assert r["audit.content.mode"] == "omitted:disabled"
    assert "audit.prompt" not in r
    assert "audit.prompt.sha256" not in r
    assert r["audit.prompt.chars"] == len(REQ.input_text)


def test_hash_mode_proves_content_without_storing_it(audit_config):
    audit_config(AUDIT_HASH_CONTENT=True)
    r = audit.build_record("req-4", REQ, RESULT, FLAGGED)

    expected = hashlib.sha256(REQ.input_text.encode("utf-8")).hexdigest()
    assert r["audit.content.mode"] == "hash"
    assert r["audit.prompt.sha256"] == expected
    assert "audit.prompt" not in r
    assert "audit.response" not in r


# --- truncation -------------------------------------------------------------

def test_truncation_caps_text_but_digest_covers_the_full_input(audit_config):
    audit_config(AUDIT_MAX_TEXT_CHARS=10)
    long_req = SimpleNamespace(task="chat", input_text="x" * 50, options={})
    r = audit.build_record("req-5", long_req, RESULT, FLAGGED)

    assert r["audit.prompt"] == "x" * 10
    assert r["audit.prompt.truncated"] is True
    # Length and digest both describe the original, not the stored copy.
    assert r["audit.prompt.chars"] == 50
    assert r["audit.prompt.sha256"] == hashlib.sha256(b"x" * 50).hexdigest()


def test_text_exactly_at_the_cap_is_not_marked_truncated(audit_config):
    audit_config(AUDIT_MAX_TEXT_CHARS=10)
    exact = SimpleNamespace(task="chat", input_text="y" * 10, options={})
    r = audit.build_record("req-6", exact, RESULT, FLAGGED)

    assert r["audit.prompt"] == "y" * 10
    assert r["audit.prompt.truncated"] is False


# --- trace correlation ------------------------------------------------------

def test_trace_and_span_ids_are_hex_of_the_right_width(audit_config):
    audit_config()
    span = SimpleNamespace(
        get_span_context=lambda: SimpleNamespace(trace_id=0xABC, span_id=0xDEF)
    )
    r = audit.build_record("req-7", REQ, RESULT, FLAGGED, span=span)

    assert r["audit.trace_id"] == "abc".rjust(32, "0")
    assert r["audit.span_id"] == "def".rjust(16, "0")
    assert len(r["audit.trace_id"]) == 32
    assert len(r["audit.span_id"]) == 16


def test_no_trace_context_omits_the_ids(audit_config):
    # trace_id 0 is what a non-recording / absent span reports.
    audit_config()
    span = SimpleNamespace(
        get_span_context=lambda: SimpleNamespace(trace_id=0, span_id=0)
    )
    r = audit.build_record("req-8", REQ, RESULT, FLAGGED, span=span)

    assert "audit.trace_id" not in r
    assert "audit.span_id" not in r


# --- emit() gating and failure behaviour ------------------------------------

def test_emit_writes_one_record_and_returns_it(audit_config):
    audit_config()
    with patch.object(audit, "init_audit_logging") as init:
        r = audit.emit("req-9", REQ, RESULT, FLAGGED)

    assert r["audit.request_id"] == "req-9"
    assert init.return_value.info.call_count == 1
    # The record is passed as logging `extra`, which is what turns it into
    # OTel log attributes rather than an opaque message string.
    assert init.return_value.info.call_args.kwargs["extra"] == r


def test_emit_disabled_writes_nothing(audit_config):
    audit_config(AUDIT_ENABLED=False)
    with patch.object(audit, "init_audit_logging") as init:
        assert audit.emit("req-10", REQ, RESULT, FLAGGED) is None
    init.assert_not_called()


def test_emit_skips_unflagged_when_denominator_is_switched_off(audit_config):
    audit_config(AUDIT_RECORD_UNFLAGGED=False)
    with patch.object(audit, "init_audit_logging") as init:
        assert audit.emit("req-11", REQ, RESULT, CLEAN) is None
        assert audit.emit("req-12", REQ, RESULT, FLAGGED) is not None
    assert init.return_value.info.call_count == 1


def test_emit_is_fail_open_and_marks_the_span(audit_config):
    audit_config()
    span = SimpleNamespace(
        get_span_context=lambda: SimpleNamespace(trace_id=1, span_id=1),
        set_attribute=lambda *a: None,
    )
    calls = []
    span.set_attribute = lambda k, v: calls.append((k, v))

    with patch.object(audit, "build_record", side_effect=RuntimeError("sink down")):
        assert audit.emit("req-13", REQ, RESULT, FLAGGED, span=span) is None

    assert ("ai.audit.sink_error", True) in calls


# --- wiring through the route ----------------------------------------------

def test_prompt_route_emits_an_audit_record(client, inference_response):
    with patch("app.requests.post", return_value=inference_response(confidence=0.1)):
        with patch.object(audit, "emit") as emit:
            resp = client.post("/prompt", json={"task": "chat", "input": "hello"})

    assert resp.status_code == 200
    assert resp.get_json()["oversight"]["flagged"] is True
    assert emit.call_count == 1
    # Called with the same request id the caller is handed back.
    assert emit.call_args.args[0] == resp.get_json()["request_id"]


def test_prompt_route_still_answers_when_the_sink_raises(client, inference_response):
    # Fail-open, end to end: a broken audit sink must not turn a good answer
    # into a 500. If you need fail-closed, this is the test to invert.
    with patch("app.requests.post", return_value=inference_response()):
        with patch.object(audit, "build_record", side_effect=RuntimeError("boom")):
            resp = client.post("/prompt", json={"task": "chat", "input": "hello"})

    assert resp.status_code == 200


def test_failed_inference_writes_no_audit_record(client):
    # Nothing was generated, so there is no prompt/reply pair to audit. The
    # failure is already visible as error.kind on the span.
    import requests as _requests

    with patch("app.requests.post", side_effect=_requests.ConnectionError("refused")):
        with patch.object(audit, "emit") as emit:
            resp = client.post("/prompt", json={"task": "chat", "input": "hello"})

    assert resp.status_code == 502
    emit.assert_not_called()
