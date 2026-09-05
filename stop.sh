#kubectl delete -f ollama/k8s/observai-ollama.yaml
kubectl delete -f inference/k8s/observai-inference.yaml
kubectl delete -f gateway/k8s/observai-gateway.yaml
kubectl delete -f collector/k8s/observai-collector.yaml
kubectl delete -f loadgen/k8s/observai-loadgen.yaml
