# Gateway / API service

The front door of the AI-observability project. It validates incoming
requests, rate-limits callers, opens a trace span enriched with AI-relevant
attributes, forwards to the inference service, and runs a human-oversight
hook on the response before returning it.

It holds **no model logic** — that lives in the inference service. The
gateway is about traffic control, validation, tracing, and governance hooks.

## Layout

```
gateway/
  app.py             # Flask app + /prompt endpoint (wires everything together)
  config.py          # all settings, from env vars
  tracing.py         # OpenTelemetry setup (OTLP -> Collector -> Dynatrace)
  validation.py      # request validation (unit-testable, no Flask deps)
  oversight.py       # human-oversight hook (the governance-aware part)
  audit.py           # audit sink for flagged prompts/replies (OTel logs)
  mock_inference.py  # throwaway stub so you can run end-to-end now
  requirements.txt
  .env.example
```

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit if needed

# Terminal 1 — mock inference on :8001
python mock_inference.py

# Terminal 2 — gateway on :8000
# (set OTEL_ENABLED=false in .env if you have no Collector yet;
#  spans will print to the console instead)
python app.py
```

Send a request:

```bash
curl -s localhost:8000/prompt \
  -H 'Content-Type: application/json' \
  -d '{"task":"summarize","input":"some long text to summarize"}' | jq

# Trigger the human-oversight flag on demand:
curl -s localhost:8000/prompt \
  -H 'Content-Type: application/json' \
  -d '{"task":"summarize","input":"x","options":{"force_low_confidence":true}}' | jq
```


**Request-level tracing** — `tracing.py` sets up OpenTelemetry and
auto-instruments Flask (every inbound request becomes a span) and outbound
`requests` (the call to inference becomes a child span automatically). In
`app.py` the `/prompt` handler opens a manual `gateway.handle_prompt` span and
tags it with AI attributes (`ai.task`, `ai.tokens.in/out`, `ai.cost.usd`,
`ai.confidence`, `ai.oversight.flagged`) so you can slice on them in Dynatrace.
Every request also gets an `X-Request-ID` propagated downstream for
end-to-end traceability.

**Rate limiting** — Flask-Limiter in `app.py`. A default limit applies to
everything; `/prompt` gets a tighter per-endpoint limit. Storage is in-memory
by default (fine for one replica / a demo). **Before running more than one
gateway instance, set `RATE_LIMIT_STORAGE_URI` to a `redis://` URL** — in-memory
counters aren't shared across processes, so per-process limits would let
callers exceed your intended rate.

**Human-oversight hook** — `oversight.py`. After inference responds, the hook
decides whether the output should be trusted automatically or flagged for a
human. It's deliberately simple and rule-based (confidence floor, empty
output, an explicit `needs_review` signal) so every flag is *explainable* —
which is the point of oversight. The flag is returned to the caller and
recorded on the trace. `oversight.py` itself stays free of Flask and of any
sink — it decides, nothing more — which is why its tests can call
`review_response` with a bare `SimpleNamespace`.

**Audit sink** — `audit.py` (feature: flagged chats sink). The trace records
*that* something was flagged; this records *what was said*. One OpenTelemetry
log record per oversight decision, carrying the prompt, the reply, the reasons
and the trace/span ids, so an auditor pivots from span to record on
`request_id`. Attributes are namespaced `audit.*`. Two things to know before
changing it: a record is written for unflagged decisions too (an auditor needs
a denominator, so "nothing flagged" can't be confused with "records lost"), and
the sink is fail-open (a broken sink must not turn a good answer into a 500 —
failures surface as `ai.audit.sink_error` on the span). Text retention is
configurable: full text, sha256-only, or off. See the root README's "Audit
records" section for the field list and the DQL.

## Notes / next steps

- This wires to a **mock** inference service. The real one is the next piece:
  it builds the prompt, calls the actual LLM, and computes the real
  token/cost/confidence numbers this gateway just forwards.
- Production: run under gunicorn (`gunicorn -w 4 -b 0.0.0.0:8000 app:app`),
  not Flask's dev server.
- The oversight rules here are starter logic. As the eval service comes
  online, its quality scores can feed richer flagging decisions.
```
