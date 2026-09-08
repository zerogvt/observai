"""Gateway / API service.

The front door of the AI-observability project. Responsibilities:
  - expose POST /prompt
  - validate the incoming request
  - rate-limit callers
  - open a trace span enriched with AI-relevant attributes
  - forward to the inference service
  - run the human-oversight hook on the response
  - return the response, annotated if it was flagged

It deliberately holds no model logic itself — that lives in the inference
service. The gateway is about traffic control, validation, tracing, and
governance hooks.
"""
import logging
import uuid

import requests
from flask import Flask, jsonify, request, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from opentelemetry import trace

from config import Config
from tracing import init_tracing
from validation import validate_prompt, ValidationError
from oversight import review_response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("gateway")

app = Flask(__name__)

# Tracing first, so the tracer is ready before any request is served.
tracer = init_tracing(app)

# Rate limiting. Default limit applies to everything; /prompt gets a tighter
# one. Storage is in-memory by default — fine for a single replica / demo,
# but set RATE_LIMIT_STORAGE_URI to redis:// before scaling out.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[Config.RATE_LIMIT_DEFAULT],
    storage_uri=Config.RATE_LIMIT_STORAGE_URI,
)


@app.before_request
def assign_request_id():
    """Give every request a stable id, surfaced in responses and on the span.

    Lets you grep a single request across gateway logs, inference logs, and
    the trace backend — the basic traceability the oversight story relies on.
    """
    g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    span = trace.get_current_span()
    if span:
        span.set_attribute("request.id", g.request_id)


@app.get("/health")
def health():
    return jsonify(status="ok", service=Config.SERVICE_NAME, version=Config.SERVICE_VERSION)


@app.post("/prompt")
@limiter.limit(Config.RATE_LIMIT_PROMPT)
def prompt():
    # 1) Validate.
    try:
        req = validate_prompt(request.get_json(silent=True))
    except ValidationError as e:
        return jsonify(error="invalid_request", message=e.message, request_id=g.request_id), 400

    # 2) Open a manual span for the AI-meaningful work and tag it with
    #    attributes you'll actually want to slice on in Dynatrace.
    with tracer.start_as_current_span("gateway.handle_prompt") as span:
        span.set_attribute("ai.task", req.task)
        span.set_attribute("ai.input.chars", len(req.input_text))
        span.set_attribute("request.id", g.request_id)

        # 3) Forward to the inference service.
        try:
            resp = requests.post(
                Config.INFERENCE_URL,
                json={
                    "task": req.task,
                    "input": req.input_text,
                    "options": req.options,
                    "request_id": g.request_id,
                },
                timeout=Config.INFERENCE_TIMEOUT_S,
                headers={"X-Request-ID": g.request_id},
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.Timeout:
            span.set_attribute("error", True)
            span.set_attribute("error.kind", "inference_timeout")
            log.error("inference timeout request_id=%s", g.request_id)
            return jsonify(error="inference_timeout", request_id=g.request_id), 504
        except requests.RequestException as e:
            span.set_attribute("error", True)
            span.set_attribute("error.kind", "inference_unavailable")
            log.error("inference call failed request_id=%s err=%s", g.request_id, e)
            return jsonify(error="inference_unavailable", request_id=g.request_id), 502

        # 4) Record AI cost/quality signals on the span if the inference
        #    service reported them. (Inference owns the real metrics; the
        #    gateway just annotates the trace for end-to-end visibility.)
        log.info(result)
        # Span attributes use the ai.* namespace, matching what the inference
        # service publishes for the same values — these are copies of its
        # numbers, so they must not have different names. (Metric *keys* stay
        # observai.*; renaming those would orphan their history.)
        for key, attr in (
            ("tokens_in", "ai.tokens.in"),
            ("tokens_out", "ai.tokens.out"),
            ("cost_usd", "ai.cost.usd"),
            ("model", "ai.model"),
            ("confidence", "ai.confidence"),
        ):
            if key in result:
                log.info(f"setting {attr}={result[key]}")
                span.set_attribute(attr, result[key])

        # 5) Human-oversight hook.
        oversight = review_response(req, result)
        span.set_attribute("ai.oversight.flagged", oversight.flagged)
        if oversight.flagged:
            span.set_attribute("ai.oversight.reasons", "; ".join(oversight.reasons))

        # 6) Return the response, annotated so the caller knows whether this
        #    output is auto-trustworthy or pending human review.
        return jsonify(
            request_id=g.request_id,
            task=req.task,
            result=result,
            oversight={"flagged": oversight.flagged, "reasons": oversight.reasons},
        )


@app.errorhandler(429)
def rate_limited(e):
    rid = getattr(g, "request_id", None)
    return jsonify(error="rate_limited", message=str(e.description), request_id=rid), 429


if __name__ == "__main__":
    # Dev server only. Use gunicorn in anything real (see README).
    app.run(host="0.0.0.0", port=int(__import__("os").getenv("PORT", "8000")))
