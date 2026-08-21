"""Configuration for the load generator.

All settings come from environment variables. Defaults target the gateway so
load flows through the whole pipeline (gateway -> inference -> Ollama) and shows
up end-to-end in your traces and metrics.
"""
import os


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SERVICE_NAME = os.getenv("SERVICE_NAME", "loadgen")
    ENV = os.getenv("ENV", "local")

    # When true, log the model's reply text each turn — a readable transcript in
    # the logs, so you can watch the chat live with `kubectl logs -f`. Turn off
    # for quiet, high-volume load.
    LOG_RESPONSES = _bool("LOG_RESPONSES", False)
    RESPONSE_LOG_CHARS = int(os.getenv("RESPONSE_LOG_CHARS", "2500"))

    # Where to send prompts. Default: the gateway's /prompt (full pipeline).
    # Point at the inference service's /infer to bypass the gateway (and its
    # rate limit) and load inference directly.
    TARGET_URL = os.getenv("TARGET_URL", "http://localhost:8000/prompt")
    TASK = os.getenv("TASK", "chat")

    # Roughly one prompt every INTERVAL_SECONDS, plus up to JITTER extra so the
    # traffic isn't perfectly periodic. NOTE: the gateway's default prompt limit
    # is 10/min; 20s (=3/min) stays comfortably under it. Lower the interval or
    # scale replicas and you'll start seeing 429s (which is itself observable).
    INTERVAL_SECONDS = float(os.getenv("INTERVAL_SECONDS", "20"))
    INTERVAL_JITTER_SECONDS = float(os.getenv("INTERVAL_JITTER_SECONDS", "5"))

    # Model calls can be slow; give the request room before giving up.
    REQUEST_TIMEOUT_S = float(os.getenv("REQUEST_TIMEOUT_S", "120"))

    # Conversation shaping. We keep a sliding window of recent turns as context,
    # cap the transcript length (stay under the gateway's MAX_INPUT_CHARS), and
    # start a fresh conversation every so often so load stays varied and bounded.
    HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "6"))
    MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "8000"))
    RESET_AFTER_TURNS = int(os.getenv("RESET_AFTER_TURNS", "10"))
