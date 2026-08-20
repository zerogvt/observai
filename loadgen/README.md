# Load generator

Generates constant, conversational load against the observai pipeline so you
have live traffic to watch in Dynatrace (traces, token/latency metrics, the
occasional oversight flag). It keeps an ongoing chat going and sends a prompt
roughly every 20 seconds.

It's a worker loop, not an HTTP server — it produces traffic rather than
serving it.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# against the gateway (full pipeline) running on :8000
TARGET_URL=http://localhost:8000/prompt python loadgen.py
```

Each turn logs one line: status, latency, input/output size, tokens, and
whether the response was flagged for review. Ctrl-C (or SIGTERM) stops it
cleanly.

## Key settings (env vars)

- `TARGET_URL` — default `http://localhost:8000/prompt` (the gateway). Point at
  `http://localhost:8001/infer` to load the inference service directly and
  bypass the gateway's rate limit.
- `INTERVAL_SECONDS` (20) + `INTERVAL_JITTER_SECONDS` (5) — pacing.
- `HISTORY_TURNS` (6) — how many recent turns are replayed as context.
- `RESET_AFTER_TURNS` (20) — start a fresh conversation periodically.
- `MAX_INPUT_CHARS` (8000) — transcript cap (stay under the gateway's limit).
- `TASK` (chat).

## Note on the gateway rate limit

The default cadence (~one prompt per 20s = 3/min) sits under the gateway's
default prompt limit of 10/min. Lower `INTERVAL_SECONDS` or run multiple
replicas and you'll start getting HTTP 429s — which is itself useful to observe.
To drive heavy load without tripping the limit, target `/infer` directly, or
raise `RATE_LIMIT_PROMPT` on the gateway.

## In Kubernetes

Build as `observai-loadgen` and run it as a Deployment in the `observai`
namespace with `TARGET_URL=http://observai-gateway:8000/prompt`. Scale the
replica count to increase load.
