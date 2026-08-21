"""Shared test setup for the gateway.

Sets env before anything imports the app (so no network exporter, no metric
reader), and provides fixtures: a Flask test client, a factory for fake
inference responses, and a per-test switch that keeps the rate limiter OFF for
everything except the one test that explicitly exercises it.
"""
import os

os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("OVERSIGHT_CONFIDENCE_FLOOR", "0.6")
# A small prompt limit so the rate-limit test is cheap; a high default so the
# global limit never interferes. These are read at import time by the
# @limiter.limit(...) decorator, so they must be set before importing app.
os.environ.setdefault("RATE_LIMIT_PROMPT", "5 per minute")
os.environ.setdefault("RATE_LIMIT_DEFAULT", "1000 per minute")

from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="session", autouse=True)
def _shutdown_tracing():
    """Flush + shut down tracing while stdout is open (avoids a harmless but
    ugly 'I/O operation on closed file' traceback at interpreter exit)."""
    yield
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _limiter_off_by_default():
    """Disable the rate limiter for every test by default, and clear its
    counters. The dedicated rate-limit test re-enables it explicitly. This
    stops limiter state leaking between tests in the same process."""
    from app import limiter

    limiter.enabled = False
    try:
        limiter.reset()
    except Exception:
        pass
    yield


@pytest.fixture
def client():
    from app import app as flask_app

    flask_app.config.update(TESTING=True)
    return flask_app.test_client()


@pytest.fixture
def inference_response():
    """Factory: build a fake `requests` response standing in for the inference
    service's reply. Pass overrides to simulate low confidence, empty output,
    an explicit review request, etc."""
    def _make(confidence=0.92, output="a perfectly fine answer", needs_review=False, **extra):
        body = {
            "output": output,
            "model": "qwen:0.5b",
            "tokens_in": 18,
            "tokens_out": 11,
            "cost_usd": 0.0,
            "confidence": confidence,
            "needs_review": needs_review,
        }
        body.update(extra)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = body
        return resp

    return _make
