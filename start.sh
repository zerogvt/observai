echo " * * * Creating namespace * * * "
kubectl apply -f k8s/observai_ns.yaml

echo " * * * Creating Dynatrace secret * * * "
if [ -n "$DT_API_TOKEN" ]; then
  echo "Using DT_API_TOKEN from environment"
else
  read -s -p "Enter DT_API_TOKEN: " DT_API_TOKEN
  echo
fi

kubectl create secret generic observai-collector   \
--from-literal=DT_API_TOKEN="$DT_API_TOKEN"   \
--from-literal=DT_OTLP_ENDPOINT=https://nzu34348.live.dynatrace.com/api/v2/otlp \
-n observai

echo " * * * Creating containers * * * "
kubectl apply -f ollama/k8s/observai-ollama.yaml
kubectl apply -f inference/k8s/observai-inference.yaml
kubectl apply -f gateway/k8s/observai-gateway.yaml
kubectl apply -f collector/k8s/observai-collector.yaml
kubectl apply -f loadgen/k8s/observai-loadgen.yaml
