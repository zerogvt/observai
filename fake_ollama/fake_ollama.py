"""Throwaway fake Ollama — mimics /api/chat so you can test the inference
service (and the whole gateway -> inference chain) before pulling qwen:0.5b.

Run on port 11434, the Ollama default, then point the inference service at it
(OLLAMA_URL=http://localhost:11434, which is already the default).

Send input containing the word "truncate" to simulate a length-capped
response, or "empty" to simulate an empty output — both exercise the
confidence proxy / oversight path.
"""
from flask import Flask, request, jsonify

app = Flask(__name__)


@app.get("/api/tags")
def tags():
    # What the inference /health ping checks.
    return jsonify(models=[{"name": "qwen:0.5b"}])


@app.post("/api/chat")
def chat():
    body = request.get_json(silent=True) or {}
    msgs = body.get("messages", [])
    user_text = next(
        (m.get("content", "") for m in reversed(msgs) if m.get("role") == "user"), ""
    )

    if "empty" in user_text.lower():
        content, done_reason, eval_count = "", "stop", 0
    elif "truncate" in user_text.lower():
        content, done_reason, eval_count = "This response was cut off because", "length", 7
    else:
        content = f"[fake qwen:0.5b reply to {len(user_text)} chars of input]"
        done_reason, eval_count = "stop", 11

    return jsonify(
        model=body.get("model", "qwen:0.5b"),
        message={"role": "assistant", "content": content},
        done=True,
        done_reason=done_reason,
        prompt_eval_count=max(1, len(user_text) // 4),
        eval_count=eval_count,
        total_duration=420_000_000,     # ns
        eval_duration=350_000_000,      # ns -> ~tokens/sec
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=11434)
