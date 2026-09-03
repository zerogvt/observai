echo "* * * Cleaning * * *"

for IMAGE in observai-inference observai-gateway observai-loadgen observai-fake-ollama; do
  docker images | grep "$IMAGE" | \
  awk '{print $2}' | while read I; do docker rmi $I; done
done
