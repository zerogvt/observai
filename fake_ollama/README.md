# fake-ollama

A throwaway stand-in for the real Ollama backend, packaged as its own service so
you can run it **in the cluster exactly like the real one** — but with instant
startup and instant replies. Use it to iterate on the gateway → inference →
collector chain, probes, tracing, and dashboards without waiting on a 2GB model
pull or CPU inference.

It implements only the two endpoints the inference service actually calls:

- `GET /api/tags` — the reachability check (also used by inference's `ping()`).
- `POST /api/chat` — mimics Ollama's real response shape (`message.content`,
  `prompt_eval_count`, `eval_count`, `total_duration`, `eval_duration`,
  `done_reason`) so the token / latency / tokens-per-sec math downstream has real
  fields to work with.

The code is a verbatim copy of the manual test stub that lived in
`inference/fake_ollama.py` — same behavior, just promoted to a deployable
service.

## Magic words (exercise the governance path)

Send input containing:

- **`empty`** → empty output → trips the confidence proxy's empty-output rule.
- **`truncate`** → `done_reason: "length"` → trips the truncation penalty.

Both drive `confidence.py` low enough to fire the gateway's oversight flag, so
you can test the whole review path deterministically.

## Run it in Kubernetes (drop-in for real Ollama)

The Service is named `ollama` on port `11434` — identical to the real backend —
so inference's existing `OLLAMA_URL=http://ollama:11434` works unchanged. It's an
either/or: run this **instead of** the real ollama, not alongside it.

```bash
# 1) namespace must exist
kubectl apply -f ../k8s/observai_ns.yaml

# 2) build into minikube's docker daemon (no registry needed)
eval $(minikube docker-env)
docker build -t observai-fake-ollama:0.1.0 .

# 3) swap the backend: remove real ollama if it's running, apply the fake
kubectl -n observai delete -f ../ollama/k8s/observai-ollama.yaml   # if present
kubectl apply -f k8s/observai-fake-ollama.yaml
```

Go back to the real model whenever you want:

```bash
kubectl delete -f k8s/observai-fake-ollama.yaml
kubectl apply -f ../ollama/k8s/observai-ollama.yaml
```

Want both at once instead? Rename the Service in the manifest to `fake-ollama`
and repoint inference's `OLLAMA_URL` at `http://fake-ollama:11434`.

## Run it locally (no cluster)

```bash
pip install -r requirements.txt
python fake_ollama.py         # serves on 0.0.0.0:11434

# point the inference service at it (this is already the default):
export OLLAMA_URL=http://localhost:11434
```

## Smoke test

```bash
curl -s http://localhost:11434/api/tags
curl -s -X POST http://localhost:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen:0.5b","messages":[{"role":"user","content":"hello"}]}'
```
