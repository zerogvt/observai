set -eo pipefail

echo " * * * Creating namespace * * * "
kubectl apply -f k8s/observai_ns.yaml

echo " * * * Creating Dynatrace secret * * * "
if [ -n "$DT_API_TOKEN" ]; then
  echo "Using DT_API_TOKEN from environment"
else
  read -s -p "Enter DT_API_TOKEN: " DT_API_TOKEN
  echo
fi

if [ -n "$DT_TENANT" ]; then
  echo "Using DT_TENANT from environment ($DT_TENANT)"
else
  read -p "Enter DT_TENANT: " DT_TENANT
fi
if [ -z "$DT_TENANT" ]; then
  echo "DT_TENANT is required" >&2
  exit 1
fi

kubectl create secret generic observai-collector \
  --from-literal=DT_API_TOKEN="$DT_API_TOKEN" \
  --from-literal=DT_OTLP_ENDPOINT=https://$DT_TENANT.live.dynatrace.com/api/v2/otlp \
  -n observai --dry-run=client -o yaml | kubectl apply -f -


echo " * * * Deploying Ollama * * * "
kubectl apply -f ollama/k8s/observai-ollama.yaml

echo "* * * Building * * *"
# feature build tag
TAG="$(date +%Y%m%d%H%M%S)"
docker build -t observai-inference:${TAG} inference/
docker build -t observai-gateway:${TAG} gateway/
docker build -t observai-loadgen:${TAG} loadgen/
docker build -t observai-fake-ollama:${TAG} fake_ollama/

# feature build tag
# Deploy the three services just built, tagged with $TAG, via a Kustomize
# overlay generated fresh in a temp dir each run — so none of the checked-in
# Deployment yamls (or any other tracked file) ever change; only this
# throwaway overlay carries the tag. --load-restrictor is needed because the
# overlay's resource path points back into the repo, outside the temp dir
# Kustomize otherwise treats as its root. No such mechanism for ollama: its
# image isn't built here (it's pulled from Docker Hub), so there's nothing
# to tag or redeploy.
echo "* * * Deploying ${TAG} * * *"
for svc in inference gateway loadgen; do
  tmp="$(mktemp -d)"
  cat > "${tmp}/kustomization.yaml" <<EOF
resources:
  - $(pwd)/${svc}/k8s/observai-${svc}.yaml
images:
  - name: observai-${svc}
    newTag: "${TAG}"
EOF
  kubectl kustomize --load-restrictor LoadRestrictionsNone "${tmp}" | kubectl apply -f -
  rm -rf "${tmp}"
done

echo "* * * Deploying OTEL collector * * *"
kubectl apply -f collector/k8s/observai-collector.yaml
