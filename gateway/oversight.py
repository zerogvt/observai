"""Human-oversight hook.

This is the governance-aware part of the gateway. The idea (straight out of
the AI-management-system thinking — transparency, human oversight, risk
monitoring) is that not every model output should be trusted automatically.
When a response looks low-confidence or risky, we *flag it for human review*
rather than silently passing it downstream.

In a real system the flagged item would land in a review queue (a DB table,
a Slack channel, a ticket). Here we log it and attach a flag to the response
so the caller knows it shouldn't be auto-trusted. Swap `_record_for_review`
for your real sink later.
"""
import logging
from dataclasses import dataclass, field

from config import Config

log = logging.getLogger(__name__)


@dataclass
class OversightResult:
    flagged: bool
    reasons: list = field(default_factory=list)


def review_response(req, inference_result: dict) -> OversightResult:
    """Decide whether a model response needs human eyes before it's trusted.

    `inference_result` is whatever the inference service returns; we look for
    a confidence/quality score and a few cheap risk signals. Everything here
    is deliberately simple and rule-based so it's auditable — you can explain
    exactly why something was flagged, which is the whole point of oversight.
    """
    reasons = []

    # 1) Confidence floor: the model (or eval service) told us how sure it is.
    confidence = inference_result.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < Config.OVERSIGHT_CONFIDENCE_FLOOR:
        reasons.append(
            f"confidence {confidence:.2f} below floor {Config.OVERSIGHT_CONFIDENCE_FLOOR:.2f}"
        )

    # 2) Empty / refusal-shaped output is worth a human glance.
    output = (inference_result.get("output") or "").strip()
    if not output:
        reasons.append("empty model output")

    # 3) The model itself asked for escalation (e.g. it was unsure or the
    #    request touched something sensitive). A real inference service can
    #    set this flag; we honor it here.
    if inference_result.get("needs_review") is True:
        reasons.append("inference service requested review")

    result = OversightResult(flagged=bool(reasons), reasons=reasons)
    if result.flagged:
        _record_for_review(req, inference_result, result)
    return result


def _record_for_review(req, inference_result: dict, result: OversightResult):
    """Send a flagged item to the review sink.

    Replace this with a write to your review queue / DB table / alert channel.
    Kept as a structured log so it's traceable and shows up correlated with
    the request's trace in your backend.
    """
    log.warning(
        "OVERSIGHT_FLAG task=%s reasons=%s confidence=%s",
        getattr(req, "task", "?"),
        "; ".join(result.reasons),
        inference_result.get("confidence"),
    )
