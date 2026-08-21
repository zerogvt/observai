# Inference service

The service that actually calls the model. The gateway forwards a validated
request here; this service builds the prompt, calls **local Ollama
(qwen:0.5b)**, computes the AI observability signals, and returns them in the
contract the gateway expects.

Because the model is local, **`cost_usd` is always 0.0** — the meaningful
"cost" signals for a local model are **latency** and **tokens/sec
throughput**, which this service records as metrics and span attributes.

## Layout

```
inference/
  app.py           # Flask app + /infer endpoint (wires it together)
  config.py        # all settings, from env vars
  tracing.py       # OpenTelemetry traces AND metrics (this is where AI metrics are born)
  prompts.py       # per-task system prompts (summarize/chat/classify/extract)
  provider.py      # the Ollama /api/chat call + token/latency parsing
  confidence.py    # honest confidence proxy + review flag
  fake_ollama.py   # throwaway stub so you can test before pulling the model
  requirements.txt
  .env.example
```

## Response contract (what the gateway reads)

```json
{
  "output": "...",
  "model": "qwen:0.5b",
  "tokens_in": 18,
  "tokens_out": 11,
  "cost_usd": 0.0,
  "confidence": 0.85,
  "needs_review": false,
  "latency_ms": 412.0,
  "tokens_per_sec": 31.4,
  "done_reason": "stop",
  "confidence_signals": []
}
```

## Run it for real (with Ollama)

```bash
# 1) install + start Ollama, then pull the model
ollama pull qwen:0.5b
ollama serve            # if not already running; default port 11434

# 2) the inference service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # set OTEL_ENABLED=false for a quick local test
python app.py            # listens on :8001
```

Check it: `curl -s localhost:8001/health` — you want `"ollama_reachable": true`.

Then drive it through the gateway (in the gateway folder, with
`INFERENCE_URL=http://localhost:8001/infer`):

```bash
curl -s localhost:8000/prompt -H 'Content-Type: application/json' \
  -d '{"task":"summarize","input":"some text to summarize"}' | jq
```

## Test the wiring WITHOUT Ollama (fake stub)

If you haven't pulled the model yet, use the included stub:

```bash
python fake_ollama.py        # :11434, pretends to be Ollama
python app.py                # :8001, points at it by default
```

Inputs containing `truncate` or `empty` trigger the low-confidence /
oversight paths so you can see the governance flow without a real model.

## How the AI observability signals work

**Tokens** — `provider.py` reads `prompt_eval_count` (input) and `eval_count`
(output) straight from Ollama's response. Emitted as OTel counters
(`ai.tokens.in`, `ai.tokens.out`) and set as span attributes.

**Latency & throughput** — wall-clock latency plus tokens/sec computed from
Ollama's own `eval_duration`. These are the local-model stand-in for "cost".
Latency is an OTel histogram (`ai.inference.latency`); both are span attrs.

**Confidence** — `confidence.py`. **Honesty note baked into the code:** a
text LLM does *not* give you a calibrated confidence number, so this is an
*explainable proxy* (truncated output, empty output, suspiciously short)
with every adjustment recorded in `confidence_signals`. The real quality
score will come later from the eval service; this is the honest placeholder.
When the proxy falls below `CONFIDENCE_REVIEW_FLOOR`, `needs_review` is set,
which the gateway's oversight hook acts on.

**Metrics vs. the gateway** — the gateway annotates traces; this service is
where the real metrics are *emitted*, because it's the service that actually
knows them. That division is intentional and worth being able to explain.

## Notes / next steps

- Production: run under gunicorn (`gunicorn -w 2 -b 0.0.0.0:8001 app:app`).
  Note model calls are CPU/GPU-bound and serialized by Ollama, so more
  workers won't beat your hardware's throughput — they just prevent one slow
  request from blocking the health check.
- The natural next piece is the **eval service**: it pulls completed
  request/response pairs off a queue and scores them out-of-band (rule-based,
  LLM-as-judge, or a fixed eval set), replacing the confidence *proxy* with a
  real quality signal and giving you the drift metric to chart over time.
- OTel package versions move fast; if `pip install` complains, that's the
  first place to look.
```
