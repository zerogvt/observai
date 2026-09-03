echo "* * * Building * * *"
docker build -t observai-inference inference/
docker build -t observai-gateway gateway/
docker build -t observai-loadgen loadgen/
docker build -t observai-fake-ollama fake_ollama/
