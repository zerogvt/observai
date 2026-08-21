kubectl apply -f k8s/observai_ns.yaml
kubectl apply -f fake_ollama/k8s/observai-fake-ollama.yaml
kubectl apply -f inference/k8s/observai-inference.yaml
kubectl apply -f gateway/k8s/observai-gateway.yaml
kubectl apply -f collector/k8s/observai-collector.yaml
kubectl apply -f loadgen/k8s/observai-loadgen.yaml
