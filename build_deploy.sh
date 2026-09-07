set -eo pipefail

# Usage:
#   ./build_deploy.sh                  build fresh images and deploy them
#   ./build_deploy.sh --no-build       redeploy the newest images already built
#   ./build_deploy.sh --tag 20260905184017   redeploy one specific build

BUILD=1
TAG=""
SVCS="inference gateway loadgen"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-build) BUILD=0 ;;
    --tag)      shift; TAG="$1"; BUILD=0 ;;
    -h|--help)  sed -n '3,7p' "$0"; exit 0 ;;
    *)          echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

echo " * * * Creating namespace * * * "
kubectl apply -f k8s/observai_ns.yaml

echo " * * * Creating Dynatrace secret * * * "
# On a redeploy the secret usually survived (stop.sh removes Deployments, not
# the namespace or this imperatively-created secret), so don't prompt for a
# token we already have. Setting DT_API_TOKEN/DT_TENANT still forces a rewrite.
if [ -z "$DT_API_TOKEN" ] && kubectl get secret observai-collector -n observai >/dev/null 2>&1; then
  echo "Secret observai-collector already exists, keeping it"
else
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
fi


echo " * * * Deploying Ollama * * * "
kubectl apply -f ollama/k8s/observai-ollama.yaml

if [ "$BUILD" -eq 1 ]; then
  echo "* * * Building * * *"
  # feature build tag
  TAG="$(date +%Y%m%d%H%M%S)"
  docker build -t observai-inference:${TAG} inference/
  docker build -t observai-gateway:${TAG} gateway/
  docker build -t observai-loadgen:${TAG} loadgen/
  docker build -t observai-fake-ollama:${TAG} fake_ollama/
elif [ -z "$TAG" ]; then
  # Reuse the newest build. Only timestamp tags are considered (the hand-rolled
  # 0.0.x ones aren't produced by this script), and only a tag present on ALL
  # deployed services counts — a half-built tag would otherwise deploy a mix of
  # generations. Timestamps sort lexically, so `sort -r | head -1` is newest.
  want="$(echo $SVCS | wc -w)"
  TAG="$(for svc in $SVCS; do
           docker images "observai-${svc}" --format '{{.Tag}}' | grep -E '^[0-9]{14}$'
         done | sort | uniq -c | awk -v n="$want" '$1 == n {print $2}' | sort -r | head -1)"
  if [ -z "$TAG" ]; then
    echo "No build found covering all of: $SVCS" >&2
    echo "Run without --no-build to build them, or pass --tag <tag>." >&2
    exit 1
  fi
  echo "* * * Reusing newest build ${TAG} * * *"
else
  for svc in $SVCS; do
    if ! docker image inspect "observai-${svc}:${TAG}" >/dev/null 2>&1; then
      echo "Image observai-${svc}:${TAG} not found locally" >&2
      exit 1
    fi
  done
  echo "* * * Reusing build ${TAG} * * *"
fi

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
for svc in $SVCS; do
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
