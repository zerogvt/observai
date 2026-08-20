"""HTTP-layer tests for /prompt and /health.

The outbound call to the inference service (app.requests.post) is mocked, so
these run with no inference service present. The real validation and oversight
logic run, so we're testing the gateway's wiring and error mapping.
"""
from unittest.mock import patch

import requests


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["service"] == "gateway"


def test_prompt_happy_path(client, inference_response):
    with patch("app.requests.post", return_value=inference_response()):
        resp = client.post("/prompt", json={"task": "summarize", "input": "some text"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["task"] == "summarize"
    assert body["request_id"]
    assert body["result"]["model"] == "llama3.2"
    assert body["oversight"]["flagged"] is False


def test_prompt_validation_error_is_400(client):
    # Bad task fails validation before any forwarding happens.
    resp = client.post("/prompt", json={"task": "translate", "input": "x"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_request"


def test_prompt_inference_timeout_is_504(client):
    with patch("app.requests.post", side_effect=requests.Timeout()):
        resp = client.post("/prompt", json={"task": "chat", "input": "hi"})
    assert resp.status_code == 504
    assert resp.get_json()["error"] == "inference_timeout"


def test_prompt_inference_connection_error_is_502(client):
    with patch("app.requests.post", side_effect=requests.ConnectionError("refused")):
        resp = client.post("/prompt", json={"task": "chat", "input": "hi"})
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "inference_unavailable"


def test_prompt_inference_http_error_is_502(client, inference_response):
    resp_obj = inference_response()
    resp_obj.raise_for_status.side_effect = requests.HTTPError("500")
    with patch("app.requests.post", return_value=resp_obj):
        resp = client.post("/prompt", json={"task": "chat", "input": "hi"})
    assert resp.status_code == 502


def test_prompt_low_confidence_propagates_oversight_flag(client, inference_response):
    with patch("app.requests.post", return_value=inference_response(confidence=0.3)):
        resp = client.post("/prompt", json={"task": "chat", "input": "hi"})
    assert resp.status_code == 200
    assert resp.get_json()["oversight"]["flagged"] is True


def test_prompt_rate_limit_returns_429(client, inference_response):
    # The only test that exercises the limiter: enable it, clear counters,
    # then exceed the 5/min prompt limit.
    from app import limiter

    limiter.enabled = True
    try:
        limiter.reset()
    except Exception:
        pass

    with patch("app.requests.post", return_value=inference_response()):
        codes = [
            client.post("/prompt", json={"task": "chat", "input": "hi"}).status_code
            for _ in range(6)
        ]

    assert codes[:5] == [200, 200, 200, 200, 200]
    assert codes[5] == 429
