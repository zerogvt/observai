"""Inference service.

Receives a forwarded request from the gateway, builds the prompt, calls the
local Ollama model, computes the AI observability signals, and returns them in
the contract the gateway expects:

    output, model, tokens_in, tokens_out, cost_usd, confidence, needs_review

(plus latency_ms and tokens_per_sec, which the gateway ignores but Dynatrace
will happily chart).

Because the model is local, cost_usd is always 0.0 — the meaningful "cost"
signals for a local model are latency and tokens/sec, which we record as
metrics and span attributes instead.
"""
import logging

from flask import Flask, jsonify, request, g
from opentelemetry import trace

import tracing as t
from config import Config
from prompts import build_messages
from provider import generate, ping, InferenceError
from requests.exceptions import ReadTimeout
import confidence as conf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("inference")

app = Flask(__name__)
tracer = t.init_tracing(app)


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        service=Config.SERVICE_NAME,
        version=Config.SERVICE_VERSION,
        model=Config.OLLAMA_MODEL,
        #ollama_reachable=ping(),
    )


@app.post("/infer")
def infer():
    body = request.get_json(silent=True) or {}
    task = (body.get("task") or "chat").strip().lower()
    input_text = body.get("input") or ""
    options = body.get("options") or {}
    request_id = body.get("request_id") or request.headers.get("X-Request-ID")

    if not input_text.strip():
        return jsonify(error="empty_input", request_id=request_id), 400

    with tracer.start_as_current_span("inference.generate") as span:
        span.set_attribute("ai.task", task)
        span.set_attribute("ai.model", Config.OLLAMA_MODEL)
        if request_id:
            span.set_attribute("request.id", request_id)

        system, messages = build_messages(task, input_text, options)

        # --- The actual model call ---
        try:
            result = generate(system, messages)
        except (InferenceError, ReadTimeout) as e:
            span.set_attribute("error", True)
            span.set_attribute("error.kind", "ollama_unavailable")
            if t.requests_counter:
                t.requests_counter.add(1, {"task": task, "outcome": "error"})
            log.error("inference failed request_id=%s err=%s", request_id, e)
            # 503: the model backend is down/unreachable — gateway maps this
            # to a 502 for the end user.
            return jsonify(error="inference_failed", message=str(e), request_id=request_id), 503

        # --- Confidence proxy + review flag ---
        c = conf.estimate(result)

        # --- Record AI signals on the span ---
        span.set_attribute("ai.tokens.in", result["tokens_in"])
        span.set_attribute("ai.tokens.out", result["tokens_out"])
        span.set_attribute("ai.latency.ms", result["latency_ms"])
        span.set_attribute("ai.tokens_per_sec", result["tokens_per_sec"])
        span.set_attribute("ai.confidence", c["confidence"])
        span.set_attribute("ai.needs_review", c["needs_review"])
        span.set_attribute("ai.done_reason", result["done_reason"])

        # --- Emit metrics (these are what you chart/alert on) ---
        attrs = {"task": task, "model": Config.OLLAMA_MODEL}
        if t.tokens_in_counter:
            t.tokens_in_counter.add(result["tokens_in"], attrs)
            t.tokens_out_counter.add(result["tokens_out"], attrs)
            t.latency_hist.record(result["latency_ms"], attrs)
            t.requests_counter.add(1, {**attrs, "outcome": "ok"})

        log.info(
            "infer ok request_id=%s task=%s tok_in=%s tok_out=%s "
            "lat_ms=%s tps=%s conf=%s review=%s",
            request_id, task, result["tokens_in"], result["tokens_out"],
            result["latency_ms"], result["tokens_per_sec"],
            c["confidence"], c["needs_review"],
        )

        # --- Return the gateway contract ---
        return jsonify(
            output=result["output"],
            model=result["model"],
            tokens_in=result["tokens_in"],
            tokens_out=result["tokens_out"],
            cost_usd=0.0,  # local model: no per-token dollar cost
            confidence=c["confidence"],
            needs_review=c["needs_review"],
            # extra, gateway-ignored signals — handy in the trace/UI:
            latency_ms=result["latency_ms"],
            tokens_per_sec=result["tokens_per_sec"],
            done_reason=result["done_reason"],
            confidence_signals=c["signals"],
            request_id=request_id,
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT)
