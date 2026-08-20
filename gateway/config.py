"""Configuration for the gateway service.

All settings come from environment variables so the same image runs
unchanged across local / staging / prod. See .env.example for the full list.
"""
import os


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # --- Service identity (shows up in traces) ---
    SERVICE_NAME = os.getenv("SERVICE_NAME", "gateway")
    SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.1.0")
    ENV = os.getenv("ENV", "local")

    # --- Where the inference service lives ---
    INFERENCE_URL = os.getenv("INFERENCE_URL", "http://localhost:8001/infer")
    INFERENCE_TIMEOUT_S = float(os.getenv("INFERENCE_TIMEOUT_S", "60"))

    # --- OpenTelemetry export (Collector -> Dynatrace) ---
    # Point this at your OTel Collector's OTLP/HTTP endpoint.
    OTEL_ENABLED = _bool("OTEL_ENABLED", True)
    OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
    )

    # --- Rate limiting ---
    # In-memory by default (per-process!). Set RATE_LIMIT_STORAGE_URI to a
    # redis:// URL once you run more than one gateway replica.
    RATE_LIMIT_DEFAULT = os.getenv("RATE_LIMIT_DEFAULT", "60 per minute")
    RATE_LIMIT_PROMPT = os.getenv("RATE_LIMIT_PROMPT", "10 per minute")
    RATE_LIMIT_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")

    # --- Validation bounds for incoming prompts ---
    MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "20000"))
    ALLOWED_TASKS = set(
        os.getenv("ALLOWED_TASKS", "summarize,chat,classify,extract").split(",")
    )

    # --- Human-oversight thresholds ---
    # If the inference service reports a quality/confidence score below this,
    # the response is flagged for human review before it's trusted downstream.
    OVERSIGHT_CONFIDENCE_FLOOR = float(os.getenv("OVERSIGHT_CONFIDENCE_FLOOR", "0.6"))
