"""Throwaway mock inference service — lets you exercise the gateway before
the real inference service exists. Run it on port 8001.

It echoes a fake summary and returns the AI signal fields (tokens, cost,
confidence) the gateway expects, so you can watch the full flow, the trace
attributes, and the oversight hook all working. Send {"options":{"force_low_confidence":true}}
to trigger the human-oversight flag on demand.
"""
from flask import Flask, request, jsonify

app = Flask(__name__)


@app.post("/infer")
def infer():
    body = request.get_json(silent=True) or {}
    text = body.get("input", "")
    options = body.get("options", {})

    confidence = 0.3 if options.get("force_low_confidence") else 0.92
    output = "" if options.get("force_empty") else f"[mock summary of {len(text)} chars]"

    return jsonify(
        output=output,
        model="mock-llm-v0",
        tokens_in=max(1, len(text) // 4),
        tokens_out=12,
        cost_usd=0.0001,
        confidence=confidence,
        needs_review=bool(options.get("force_review")),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)
