echo "* * * Building * * *"
docker build -t observai-inference:0.1.0 inference/
docker build -t observai-gateway:0.2.1 gateway/
docker build -t observai-loadgen:0.2.1 loadgen/
docker build -t observai-fake-ollama:0.1.0 fake_ollama/
