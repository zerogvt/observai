"""Unit tests for provider.generate / provider.ping.

The actual HTTP call to Ollama is mocked, so these run with no Ollama present
and assert that we parse Ollama's response shape correctly and translate
failures into InferenceError.
"""
from unittest.mock import patch, MagicMock

import requests
import pytest

from provider import generate, ping, InferenceError


def _ollama_response(
    content="hello from the model",
    prompt_eval_count=20,
    eval_count=10,
    eval_duration=500_000_000,  # ns -> 0.5s -> 20 tok/s
    done_reason="stop",
    model="llama3.2",
):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "model": model,
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "eval_duration": eval_duration,
    }
    return resp


@patch("provider.requests.post")
def test_generate_parses_response(mock_post):
    mock_post.return_value = _ollama_response()
    out = generate("system", [{"role": "user", "content": "hi"}])

    assert out["output"] == "hello from the model"
    assert out["tokens_in"] == 20
    assert out["tokens_out"] == 10
    assert out["done_reason"] == "stop"
    assert out["model"] == "llama3.2"
    # 10 tokens over 0.5s == 20 tok/s
    assert out["tokens_per_sec"] == pytest.approx(20.0, abs=0.1)
    assert isinstance(out["latency_ms"], float) and out["latency_ms"] >= 0


@patch("provider.requests.post")
def test_generate_handles_missing_token_fields(mock_post):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    # An Ollama response missing the count/duration fields entirely.
    resp.json.return_value = {"message": {"content": "x"}, "done_reason": "stop"}
    mock_post.return_value = resp

    out = generate("system", [{"role": "user", "content": "hi"}])
    assert out["tokens_in"] == 0
    assert out["tokens_out"] == 0
    assert out["tokens_per_sec"] == 0.0  # no divide-by-zero on missing duration


@patch("provider.requests.post")
def test_generate_empty_message_is_empty_string(mock_post):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"done_reason": "stop"}  # no "message" key at all
    mock_post.return_value = resp

    out = generate("system", [{"role": "user", "content": "hi"}])
    assert out["output"] == ""


@patch("provider.requests.post")
def test_generate_timeout_raises_inference_error(mock_post):
    mock_post.side_effect = requests.Timeout()
    with pytest.raises(InferenceError):
        generate("system", [{"role": "user", "content": "hi"}])


@patch("provider.requests.post")
def test_generate_connection_error_raises_inference_error(mock_post):
    mock_post.side_effect = requests.ConnectionError("refused")
    with pytest.raises(InferenceError):
        generate("system", [{"role": "user", "content": "hi"}])


@patch("provider.requests.post")
def test_generate_http_error_raises_inference_error(mock_post):
    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.HTTPError("500")
    mock_post.return_value = resp
    with pytest.raises(InferenceError):
        generate("system", [{"role": "user", "content": "hi"}])


@patch("provider.requests.get")
def test_ping_true_on_200(mock_get):
    mock_get.return_value = MagicMock(status_code=200)
    assert ping() is True


@patch("provider.requests.get")
def test_ping_false_on_exception(mock_get):
    mock_get.side_effect = requests.ConnectionError()
    assert ping() is False
