"""HTTP-layer tests for the /infer and /health endpoints.

We mock provider.generate (the external Ollama call) but let the real
confidence proxy run, so these exercise the app's wiring + the contract it
returns, while staying hermetic (no Ollama needed).

`make_result` / `normal_result` come from conftest as fixtures.
"""
from unittest.mock import patch

from provider import InferenceError


def test_health_reports_model(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["service"] == "observai_inference"
    assert body["model"] == "qwen:0.5b"
    # /health deliberately does NOT probe Ollama: the ollama_reachable=ping()
    # line is commented out in app.py so a liveness check can't be turned into
    # an outbound call. If that line is restored, assert the field here again
    # (and patch app.ping, so the test stays hermetic).
    assert "ollama_reachable" not in body


def test_infer_happy_path_returns_full_contract(client, normal_result):
    with patch("app.generate", return_value=normal_result):
        resp = client.post("/infer", json={"task": "summarize", "input": "long text here"})
    assert resp.status_code == 200
    body = resp.get_json()
    # the contract the gateway depends on
    for key in (
        "output", "model", "tokens_in", "tokens_out", "cost_usd",
        "confidence", "needs_review", "latency_ms", "tokens_per_sec", "done_reason",
    ):
        assert key in body, f"missing contract key: {key}"
    assert body["cost_usd"] == 0.0          # local model: always zero
    assert body["confidence"] == 0.85       # real proxy on a normal result
    assert body["needs_review"] is False


def test_infer_empty_input_is_400(client):
    resp = client.post("/infer", json={"task": "chat", "input": "   "})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "empty_input"


def test_infer_missing_input_is_400(client):
    resp = client.post("/infer", json={"task": "chat"})
    assert resp.status_code == 400


def test_infer_provider_failure_is_503(client):
    with patch("app.generate", side_effect=InferenceError("ollama down")):
        resp = client.post("/infer", json={"task": "chat", "input": "hi"})
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "inference_failed"


def test_infer_low_confidence_sets_needs_review(client, make_result):
    # An empty model output drives the proxy to 0.0 -> flagged for review.
    with patch("app.generate", return_value=make_result(output="")):
        resp = client.post("/infer", json={"task": "chat", "input": "hi"})
    body = resp.get_json()
    assert body["needs_review"] is True
    assert body["confidence"] == 0.0


def test_infer_defaults_task_to_chat(client, normal_result):
    # No task supplied -> defaults to chat, still succeeds.
    with patch("app.generate", return_value=normal_result) as m:
        resp = client.post("/infer", json={"input": "hi"})
    assert resp.status_code == 200
    assert m.called
