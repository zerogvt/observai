"""Configuration for the inference service.

Everything comes from environment variables (see .env.example). This service
talks to a local Ollama instance and computes the real AI signals — tokens,
latency, throughput, a confidence proxy — that the gateway just forwards.
"""
import os


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # --- Service identity (shows up in traces) ---
    SERVICE_NAME = os.getenv("SERVICE_NAME", "observai_inference")
    SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.1.0")
    ENV = os.getenv("ENV", "local")
    PORT = int(os.getenv("PORT", "8001"))

    # --- Ollama (local LLM) ---
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen:0.5b")
    OLLAMA_TIMEOUT_S = float(os.getenv("OLLAMA_TIMEOUT_S", "120"))
    # Cap output length; also used by the confidence proxy (a response that
    # hits this cap was truncated, which we treat as lower confidence).
    MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "512"))
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))

    # --- OpenTelemetry export (Collector -> Dynatrace) ---
    OTEL_ENABLED = _bool("OTEL_ENABLED", False)
    OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
    )

    # --- Confidence proxy ---
    # The model itself doesn't return a calibrated confidence. We compute a
    # cheap, *explainable* proxy here and let the eval service supply a real
    # quality score later. This floor decides when we ask for human review.
    CONFIDENCE_REVIEW_FLOOR = float(os.getenv("CONFIDENCE_REVIEW_FLOOR", "0.6"))
