# observAI

A Kubernetes-native reference stack for instrumenting local LLM inference with OpenTelemetry, built with AI governance in mind.

observAI runs a complete LLM serving pipeline on Kubernetes and instruments every hop — from request ingress to token generation — with OpenTelemetry traces and metrics. Telemetry is exported to Dynatrace, giving you request-level tracing, model performance signals (tokens, latency, confidence), and a foundation for AI governance and EU AI Act–style compliance reporting.

It's built to be run locally on [kubernets on docker desktop](https://www.docker.com/blog/how-to-set-up-a-kubernetes-cluster-on-docker-desktop/) and [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) as a reference project, but the patterns carry over to any Kubernetes cluster.

## Why

Most observability tooling treats an LLM service as an opaque HTTP endpoint. observAI instead instruments the *inside* of the pipeline — how many tokens were generated, how long inference actually took, how confident the model was — and wires that into a standards-based telemetry backbone (OpenTelemetry) rather than a proprietary agent. That makes the same signals portable across backends and gives you the raw material for governance questions: what was asked, what the model produced, how it behaved over time.

## Architecture

Requests flow through a gateway into an inference service backed by a local Ollama model. The gateway and inference services emit OpenTelemetry traces and metrics to a central collector, which forwards them to Dynatrace. `loadgen` and Ollama emit no telemetry of their own — loadgen is only a traffic source, and Ollama's timings reach Dynatrace because the inference service reads them out of the API response and puts them on its span.

```
   client ──┐
            │      ┌───────────┐      ┌─────────────┐      ┌──────────┐
            ├─────▶  gateway   ─────▶  inference     ───▶   Ollama 
            │      └─────┬─────┘      └──────┬──────┘      └──────────┘
  loadgen ──┘ (optional) │                   │
                         │                   │
                         ▼                   ▼
                 ┌──────────────────────────────────┐      ┌─────────────┐
                      OpenTelemetry Collector       ─────▶  Dynatrace  
                 └──────────────────────────────────┘      └─────────────┘
```

## Components

| Component | Stack | Role |
|-----------|-------|------|
| **observai-gateway** | Flask | Public entry point (`/prompt`), request rate limiting via Flask-Limiter, OTel tracing. |
| **observai-inference** | Flask | Calls the local model, emits token / latency / confidence metrics plus OTel traces and metrics. |
| **Ollama** | Ollama + qwen:0.5b | Local model backend. |
| **Redis** | Redis | Shared store backing distributed rate limiting. (not shown in above diagram)|
| **OpenTelemetry Collector** | OTel Collector | OTLP receiver, `cumulativetodelta` processing for Dynatrace compatibility, OTLP/HTTP export to Dynatrace. |
| **loadgen** | Python | Optional conversational load generator with graceful SIGTERM handling and a `LOG_RESPONSES` flag. |

## Conventions

The services share a consistent set of engineering conventions:

- **Config** is environment-driven through a per-service `config.py`.
- **Containers** use multi-stage, non-root Dockerfiles with a read-only root filesystem and a `/tmp` `emptyDir` mount for writable scratch space.
- **Tests** are pytest suites (`pythonpath = .` set in `pytest.ini`).
- **Deployment** is via single-file Kubernetes YAML manifests per component.
- **Image naming** follows `observai-<service>` (e.g. `observai-gateway`, `observai-inference`).

## Getting started

> Prerequisites: `kind`, `kubectl`, and Docker.

1. **Start a kubernetes cluster through docker desktop** with enough headroom for Ollama and the model: i.e. memory>=8192, cpus>=4

2. **Set needed Dynatrace env variables** Set your Dynatrace OTLP endpoint and API token for the collector as a secret in `observai` namespace:
```
 export DT_API_TOKEN='your_dynatrace_generated_token_see_next_for_needed_scope'
 export DT_TENANT='your_dynatrace_tenant_see_next_for_example'
```
Dynatrace Api token must have the `Ingest metrics` and `Ingest OpenTelemetry traces` API scopes.

Dynatrace tenant is the first part of you DT url. E.g. for https://bzu12345.apps.dynatrace.com/ tenant is `bzu12345`


3. **Build and Deploy** 
   ```
   bash build_deploy.sh --no-build
   ```

## See the loadgen chat in action
`k logs [observai-loadgen-container-id] -n observai -f`
![LoadGen](docs/loadgen.png)

## Observability & governance

The stack is designed so that observability doubles as a governance surface:

- **Traces** follow a request end-to-end across gateway → inference → model.
- **Metrics** capture LLM-specific signals — tokens, latency, and model confidence — not just generic HTTP timings.
- **Portability** comes from OpenTelemetry: swapping the export backend doesn't require re-instrumenting the code.
- **Compliance angle**: the same telemetry that answers "is it fast?" also feeds the questions frameworks like the EU AI Act and ISO/IEC 42001 care about — traceability of inputs and outputs, monitoring over time, and demonstrable operational control.

## Signals reference

### Metrics

Created in [`inference/tracing.py`](inference/tracing.py), emitted from
`inference/app.py`. All are dimensioned by `task` and `model`.

| Metric | Type | Unit | What it is |
|--------|------|------|------------|
| `observai.tokens.in` | counter | `1` | Input/prompt tokens consumed |
| `observai.tokens.out` | counter | `1` | Output/generated tokens |
| `observai.inference.latency` | histogram | `ms` | End-to-end inference latency, wall clock |
| `observai.inference.requests` | counter | `1` | Requests, also dimensioned `outcome` = `ok` \| `error` |

### Span attributes — `inference.generate`

| Attribute | What it is |
|-----------|------------|
| `ai.task` / `ai.model` | Task kind (`chat`, `summarize`…) and the model that served it |
| `ai.tokens.in` / `ai.tokens.out` | Prompt and generated token counts |
| `ai.tokens_per_sec` | Generation throughput — the "cost" proxy for a local model |
| `ai.latency.ms` | Wall clock the inference service measured around the Ollama call |
| `ai.latency.total.ms` | Ollama's own end-to-end for the request |
| `ai.latency.load.ms` | Model load time. ~0 when resident; seconds on a cold start |
| `ai.latency.prompt_eval.ms` | **Prefill** — reading the prompt. Scales with `ai.tokens.in` |
| `ai.latency.eval.ms` | **Generation** — producing tokens. Usually dominant |
| `ai.latency.overhead.ms` | Wall clock minus Ollama's total: HTTP, serialisation, queueing |
| `ai.confidence` / `ai.needs_review` | Confidence proxy and the review flag it triggers |
| `ai.done_reason` | `stop` (finished) or `length` (hit the token cap) |
| `error` / `error.kind` | `ollama_unavailable` |

The latency attributes nest, which is what makes a spike diagnosable:

```
ai.latency.ms                      wall clock
├── ai.latency.total.ms            Ollama's accounting
│   ├── ai.latency.load.ms         model load
│   ├── ai.latency.prompt_eval.ms  prefill  (input size)
│   └── ai.latency.eval.ms         generate (output size ÷ throughput)
└── ai.latency.overhead.ms         everything Ollama doesn't see
```

Whichever term moves is the answer: `eval` → longer outputs or CPU contention,
`prompt_eval` → bigger prompts, `load` → cold start, `overhead` → not the model
at all. Without this split every span in the chain reports the same number,
because `gateway → inference → Ollama` is synchronous and the model is ~99.9%
of it.

### Span attributes — gateway `/prompt`

| Attribute | What it is |
|-----------|------------|
| `ai.task` / `ai.input.chars` | Task kind and raw input size |
| `ai.tokens.in` / `.out` / `.cost.usd` / `.model` / `.confidence` | Copied from the inference response so the trace is readable end-to-end. `cost.usd` is always `0.0` — local model |
| `ai.oversight.flagged` / `ai.oversight.reasons` | Human-oversight verdict and why |
| `error` / `error.kind` | `inference_timeout` (504) or `inference_unavailable` (502) |

> **Namespaces:** span attributes are `ai.*` everywhere; metric *keys* are
> `observai.*`. That split is deliberate — the metric keys are product-scoped
> and renaming one orphans its history, whereas attribute names only affect
> queries from that point on. Note `observai.tokens.in` therefore still exists
> as a metric, while the span attribute of the same value is `ai.tokens.in`.

## Demo-only confidence hack

To make the `needs_review` / flagged-answer path easy to trigger for demos and screenshots, [`inference/confidence.py`](inference/confidence.py) contains a deliberate hack: any response whose output mentions "bicycle" gets an artificial confidence penalty, pushing it below the review floor and causing it to be flagged. This has nothing to do with real model quality — it's a cheap, reproducible way to induce a flagged answer on demand (e.g. "tell me about bicycles") so the oversight/flagging pipeline and the Dynatrace dashboards above have something to show. Remove this rule before using the confidence proxy for anything real.

## Dynatrace Example Queries

![Latency](docs/latency.png)

![Tokens in/out](docs/tokens_in_out.png)

![Flagged total](docs/flagged_total.png)

<img src="docs/total_flagged_errors.png" alt="Total flagged errors" width="68%">

## Dynatrace Sample Executive Dashboard

![Latency](docs/executive-dashboard.png)


## Debug/Dev Info

### Test Messages

**Send a prompt** to gateway:
```
kubectl port-forward service/observai-gateway 8000:8000 -n observai

curl -X POST http://<gateway-address>/prompt \
     -H 'Content-Type: application/json' \
     -d '{"prompt": "Hello"}'
```

**Send a prompt** to ollama:
```
kubectl port-forward service/ollama 11434:12434 -n observai

curl -sS -X POST http://localhost:11434/api/chat   \
-H 'Content-Type: application/json'   \
-d '{"model":"qwen:0.5b","messages":[{"role":"user","content":"hello"}]}'
```

**Send a prompt** to inference:
```
kubectl port-forward service/observai-inference 8001:8001 -n observai

curl -sS -X POST http://localhost:8001/infer   \
-H 'Content-Type: application/json' \
-d '{"task":"chat","input":"hello there", "request_id": "9f1c2e4a7b8d4f3a9c6e5d2b1a0f8e7c"}'
```


### Run tests
Prepare env
```
python3 -m venv .
source bin/activate
pip install -r gateway/requirements.txt -r gateway/requirements-dev.txt \
            -r inference/requirements.txt -r inference/requirements-dev.txt
```

Run tests
```
cd gateway && pytest && cd ../inference && pytest && cd ..
```
