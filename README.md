# observAI

A Kubernetes-native reference stack for instrumenting local LLM inference with OpenTelemetry, built with AI governance in mind.

observAI runs a complete LLM serving pipeline on Kubernetes and instruments every hop — from request ingress to token generation — with OpenTelemetry traces and metrics. Telemetry is exported to Dynatrace, giving you request-level tracing, model performance signals (tokens, latency, confidence), and a foundation for AI governance and EU AI Act–style compliance reporting.

It's built to be run locally on [minikube](https://minikube.sigs.k8s.io/) as a portfolio / reference project, but the patterns carry over to any Kubernetes cluster.

## Why

Most observability tooling treats an LLM service as an opaque HTTP endpoint. observAI instead instruments the *inside* of the pipeline — how many tokens were generated, how long inference actually took, how confident the model was — and wires that into a standards-based telemetry backbone (OpenTelemetry) rather than a proprietary agent. That makes the same signals portable across backends and gives you the raw material for governance questions: what was asked, what the model produced, how it behaved over time.

## Architecture

Requests flow through a gateway into an inference service backed by a local Ollama model. Every component emits OpenTelemetry data to a central collector, which forwards it to Dynatrace.

```
        ┌───────────┐      ┌─────────────┐      ┌──────────┐
client ─▶  gateway   ─────▶   inference   ─────▶  Ollama  
        └─────┬─────┘      └──────┬──────┘      └──────────┘
              │                   │
              │                   │
              |                   │
              |                   │ 
              ▼                   ▼
        ┌──────────────────────────────┐      ┌──────────────┐
        │   OpenTelemetry Collector      ─────▶   Dynatrace  
        └──────────────────────────────┘      └──────────────┘
                     ▲
                     │
              ┌──────────────┐
              │   loadgen      (optional traffic generator)
              └──────────────┘
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


2. **Build images** 

   ```
   docker build -t observai-inference:0.1.0 inference/
   docker build -t observai-gateway:0.1.0 gateway/
   docker build -t observai-loadgen:0.1.0 loadgen/
   ```

3. **Configure the Dynatrace export.** Set your Dynatrace OTLP endpoint and API token for the collector as a secret in `observai` namespace:
```
 kubectl create secret generic observai-collector   \
 --from-literal=DT_API_TOKEN='[your_dynatrace_API_token]' \
 --from-literal=DT_OTLP_ENDPOINT=https://[your_dynatrace_tenant].live.dynatrace.com/api/v2/otlp \
 -n observai
```
Dynatrace Api token must have the `Ingest metrics` and `Ingest OpenTelemetry traces` API scopes.

4. **Apply the manifests** for each component you want to run.
Start with creating the namespace:
`kubectl apply -f k8s/observai_ns.yaml`

And continue with the services:
```
kubectl apply -f ollama/k8s/observai-ollama.yaml
kubectl apply -f inference/k8s/observai-inference.yaml
kubectl apply -f gateway/k8s/observai-gateway.yaml
kubectl apply -f collector/k8s/observai-collector.yaml
```

5. Test Messages

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

6. **Optionally enable loadgen** to generate continuous traffic and populate the dashboards.
`kubectl apply -f loadgen/k8s/observai-loadgen.yaml`

## Observability & governance

The stack is designed so that observability doubles as a governance surface:

- **Traces** follow a request end-to-end across gateway → inference → model.
- **Metrics** capture LLM-specific signals — tokens, latency, and model confidence — not just generic HTTP timings.
- **Portability** comes from OpenTelemetry: swapping the export backend doesn't require re-instrumenting the code.
- **Compliance angle**: the same telemetry that answers "is it fast?" also feeds the questions frameworks like the EU AI Act and ISO/IEC 42001 care about — traceability of inputs and outputs, monitoring over time, and demonstrable operational control.

## Status

Active development / portfolio project, currently deployed and iterated.

## License

_TBD._
