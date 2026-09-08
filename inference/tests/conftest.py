"""Shared test setup.

Critically, we set OTEL_ENABLED=false *before* anything imports the app, so
tests never try to open a network exporter and no metric reader is attached
(no console spam). conftest is imported by pytest before any test module, so
this runs first.
"""
import os

os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("OLLAMA_MODEL", "qwen:0.5b")
os.environ.setdefault("CONFIDENCE_REVIEW_FLOOR", "0.6")

import pytest


@pytest.fixture(scope="session", autouse=True)
def _shutdown_tracing():
    """Flush + shut down the tracer provider while stdout is still open.

    In dev/test mode spans go to a console exporter. Without this, the
    BatchSpanProcessor tries to flush at interpreter exit — after pytest has
    closed its captured stdout — producing a harmless but ugly
    "I/O operation on closed file" traceback. Shutting down here pre-empts it.
    """
    yield
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:
        pass


@pytest.fixture
def client():
    # Imported here (not at module top) so the env above is applied first.
    from app import app as flask_app

    flask_app.config.update(TESTING=True)
    return flask_app.test_client()


@pytest.fixture
def make_result():
    """Factory fixture: build a provider.generate()-shaped result dict.

    Exposed as a fixture (rather than a plain importable function) so test
    modules get it by injection and never need `from tests.conftest import ...`,
    which would couple them to this folder's name/location.
    """
    def _make(
        output="A concise summary of the input text.",
        done_reason="stop",
        tokens_in=18,
        tokens_out=11,
        latency_ms=12.3,
        tokens_per_sec=31.4,
        model="qwen:0.5b",
        total_ms=12.0,
        load_ms=0.5,
        prompt_eval_ms=1.2,
        eval_ms=10.0,
        overhead_ms=0.3,
    ):
        return {
            "output": output,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
            "tokens_per_sec": tokens_per_sec,
            "done_reason": done_reason,
            # Ollama's timing breakdown — app.py puts these on the span, so
            # they have to be present or the happy path raises KeyError.
            "total_ms": total_ms,
            "load_ms": load_ms,
            "prompt_eval_ms": prompt_eval_ms,
            "eval_ms": eval_ms,
            "overhead_ms": overhead_ms,
        }

    return _make


@pytest.fixture
def normal_result(make_result):
    return make_result()
