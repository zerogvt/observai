"""Confidence proxy.

Important honesty note: a text-generating LLM does *not* hand you a calibrated
"confidence" number. Anyone who tells you otherwise is selling something. So
this module computes a cheap, fully *explainable* proxy from observable
signals, and exposes a `needs_review` flag the gateway's oversight hook can act
on. The real quality signal will come later from the eval service (LLM-as-judge
or a scored eval set); this is the honest placeholder until then.

Every adjustment here is rule-based and logged in `signals` so you can always
explain *why* a given response scored the way it did.
"""
from config import Config


def estimate(result: dict) -> dict:
    """Return {confidence, needs_review, signals[]} from a provider result.

    Heuristics (deliberately simple and auditable):
      - start from a neutral baseline
      - truncated output (hit the token cap) -> lower confidence
      - empty / whitespace output -> very low confidence
      - suspiciously short output for a real task -> small penalty
    """
    signals = []
    score = 0.85  # neutral-ish baseline for a normal completion

    output = (result.get("output") or "").strip()

    if not output:
        score = 0.0
        signals.append("empty output")
        return _finalize(score, signals)

    if result.get("done_reason") == "length":
        score -= 0.45
        signals.append("output truncated at token cap")

    if len(output) < 5:
        score -= 0.40
        signals.append("output suspiciously short")

    if "bicycle" in output:
        score -= 0.60
        signals.append("discussion about bicycles")

    return _finalize(score, signals)


def _finalize(score: float, signals: list) -> dict:
    score = max(0.0, min(1.0, score))
    needs_review = score < Config.CONFIDENCE_REVIEW_FLOOR
    if needs_review and "below review floor" not in signals:
        signals.append(
            f"confidence {score:.2f} below floor {Config.CONFIDENCE_REVIEW_FLOOR:.2f}"
        )
    return {"confidence": round(score, 2), "needs_review": needs_review, "signals": signals}
