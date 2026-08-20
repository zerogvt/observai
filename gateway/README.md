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

## The three things you asked for, and where they live

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
which is the point of oversight. Flagged items are logged via
`_record_for_review`; swap that for a real review queue / DB table / alert
channel. The flag is also returned to the caller and recorded on the trace.

## Notes / next steps

- This wires to a **mock** inference service. The real one is the next piece:
  it builds the prompt, calls the actual LLM, and computes the real
  token/cost/confidence numbers this gateway just forwards.
- Production: run under gunicorn (`gunicorn -w 4 -b 0.0.0.0:8000 app:app`),
  not Flask's dev server.
- The oversight rules here are starter logic. As the eval service comes
  online, its quality scores can feed richer flagging decisions.
```
