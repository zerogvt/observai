"""Ollama backend — the actual local LLM call.

Talks to Ollama's native /api/chat endpoint over plain HTTP (no SDK needed).
Returns a normalized result dict plus the raw timing/token fields Ollama
reports, which we turn into the AI observability signals upstream.

Ollama /api/chat (stream=false) responds with, among others:
  message.content         -> the generated text
  prompt_eval_count       -> input ("prompt") tokens
  eval_count              -> output (generated) tokens
  total_duration          -> end-to-end, nanoseconds
  eval_duration           -> generation time, nanoseconds  (-> tokens/sec)
  done_reason             -> "stop" (finished) or "length" (hit token cap)
"""
import time
import requests

from config import Config


class InferenceError(Exception):
    """Raised when the Ollama call fails (unreachable, timeout, bad status)."""


def generate(system: str, messages: list) -> dict:
    """Call Ollama and return a normalized result.

    Keys returned:
      output, model, tokens_in, tokens_out, latency_ms,
      tokens_per_sec, done_reason
    """
    payload = {
        "model": Config.OLLAMA_MODEL,
        "messages": ([{"role": "system", "content": system}] + messages),
        "stream": False,
        "options": {
            "num_predict": Config.MAX_OUTPUT_TOKENS,
            "temperature": Config.TEMPERATURE,
        },
    }

    start = time.perf_counter()
    try:
        resp = requests.post(
            f"{Config.OLLAMA_URL}/api/chat",
            json=payload,
            timeout=Config.OLLAMA_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.Timeout as e:
        raise InferenceError(f"Ollama timed out after {Config.OLLAMA_TIMEOUT_S}s") from e
    except requests.RequestException as e:
        raise InferenceError(f"Ollama call failed: {e}") from e

    wall_ms = (time.perf_counter() - start) * 1000.0

    output = (data.get("message") or {}).get("content", "") or ""
    tokens_in = int(data.get("prompt_eval_count") or 0)
    tokens_out = int(data.get("eval_count") or 0)

    # tokens/sec from Ollama's own generation timer (nanoseconds). This is the
    # throughput signal that stands in for "cost" on a local model.
    eval_ns = int(data.get("eval_duration") or 0)
    tokens_per_sec = (tokens_out / (eval_ns / 1e9)) if eval_ns > 0 else 0.0

    return {
        "output": output,
        "model": data.get("model", Config.OLLAMA_MODEL),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": round(wall_ms, 1),
        "tokens_per_sec": round(tokens_per_sec, 1),
        "done_reason": data.get("done_reason", "stop"),
    }


def ping() -> bool:
    """Lightweight reachability check for /health."""
    try:
        r = requests.get(f"{Config.OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except requests.RequestException:
        return False
