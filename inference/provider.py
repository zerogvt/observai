"""Ollama backend — the actual local LLM call.

Talks to Ollama's native /api/chat endpoint over plain HTTP (no SDK needed).
Returns a normalized result dict plus the raw timing/token fields Ollama
reports, which we turn into the AI observability signals upstream.

Ollama /api/chat (stream=false) responds with, among others:
  message.content         -> the generated text
  prompt_eval_count       -> input ("prompt") tokens
  eval_count              -> output (generated) tokens
  total_duration          -> end-to-end, nanoseconds
  load_duration           -> model load time, nanoseconds
  prompt_eval_duration    -> prefill: reading the prompt, nanoseconds
  eval_duration           -> generation time, nanoseconds  (-> tokens/sec)
  done_reason             -> "stop" (finished) or "length" (hit token cap)

All four durations are surfaced, because the span chain on its own cannot
answer where the time went. gateway -> inference -> Ollama is synchronous, so
every span in it reports very nearly the same number: the model's time is
~99.9% of the total and each hop adds single-digit milliseconds. Splitting
Ollama's own report into load / prefill / generation is the only way to see
*why* a request took 30s rather than 4s.
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

    # Ollama's own timing breakdown, all nanoseconds. Any of these can be
    # absent (older Ollama, or a cached/short-circuited response), so each
    # defaults to 0 rather than blowing up.
    eval_ns = int(data.get("eval_duration") or 0)
    prompt_eval_ns = int(data.get("prompt_eval_duration") or 0)
    total_ns = int(data.get("total_duration") or 0)
    load_ns = int(data.get("load_duration") or 0)

    # tokens/sec from Ollama's own generation timer. This is the throughput
    # signal that stands in for "cost" on a local model.
    tokens_per_sec = (tokens_out / (eval_ns / 1e9)) if eval_ns > 0 else 0.0

    # Whatever the wall clock saw that Ollama does not account for: HTTP,
    # serialisation, and queueing before Ollama picked the request up. Clamped
    # at zero — a negative value only ever means the two clocks disagree
    # slightly, never real time. Zero when Ollama reported no total_duration,
    # since there is then nothing to subtract from.
    overhead_ms = max(0.0, wall_ms - total_ns / 1e6) if total_ns > 0 else 0.0

    return {
        "output": output,
        "model": data.get("model", Config.OLLAMA_MODEL),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": round(wall_ms, 1),
        "tokens_per_sec": round(tokens_per_sec, 1),
        "done_reason": data.get("done_reason", "stop"),
        # Ollama's breakdown, ns -> ms. total_ms is Ollama's end-to-end, so
        # load + prompt_eval + eval accounts for nearly all of it.
        "total_ms": round(total_ns / 1e6, 1),
        "load_ms": round(load_ns / 1e6, 1),
        "prompt_eval_ms": round(prompt_eval_ns / 1e6, 1),
        "eval_ms": round(eval_ns / 1e6, 1),
        "overhead_ms": round(overhead_ms, 1),
    }


def ping() -> bool:
    """Lightweight reachability check for /health."""
    try:
        r = requests.get(f"{Config.OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except requests.RequestException:
        return False
