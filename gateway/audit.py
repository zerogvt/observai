"""Audit sink for flagged prompts and replies.  (feature: flagged chats sink)

Why this module exists
----------------------
The trace already tells an auditor *that* a response was flagged and how it
scored — the dashboard's "Flagged responses — audit record" tile is built
entirely from `gateway.handle_prompt` spans. What a span deliberately does not
carry is the content: `ai.input.chars` is a character count, never the text.
Spans are the wrong home for kilobytes of free text, and putting prompts on
them would push that text into the trace store with no separate retention.

So the content goes to its own sink: one OpenTelemetry **log** record per
oversight decision, carrying the prompt, the reply, the verdict, the reasons
and the trace/span ids that stitch it back to the trace it came from. An
auditor starts from the span (fast, indexed, cheap) and pivots to the log
record on `request_id` when they need to see what was actually said.

Conventions
-----------
Every attribute is namespaced `audit.*`, matching the split the rest of the
project already uses (`ai.*` on spans, `observai.*` on metric keys). Records
go through stdlib `logging`, so a single `emit()` reaches two places:

  * the OTel handler  -> Collector -> Dynatrace   — this is the audit sink
  * the pod's stdout  -> `kubectl logs`           — debug convenience only

Treat Dynatrace as the record of truth. The stdout copy exists so you can see
the thing working without a backend, and it is the reason the formatter below
appends the attributes as JSON.

Two properties worth preserving if you change this
--------------------------------------------------
*Completeness.* A record is written for every oversight decision, not only the
flagged ones (see `Config.AUDIT_RECORD_UNFLAGGED`). With flagged rows alone,
"nothing was flagged" and "records went missing" are indistinguishable.

*Provability under truncation.* `audit.*.sha256` is computed over the **full**
text before any truncation, so a shortened `audit.prompt` still pins the exact
bytes that were reviewed.
"""
import hashlib
import json
import logging

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

from config import Config
from tracing import resource

log = logging.getLogger(__name__)

# The routing key. Everything downstream keys off this value: the DQL the
# dashboard runs, and the OpenPipeline rule that sends these records to a
# bucket with its own retention. Changing it orphans both.
EVENT_TYPE = "observai.oversight.audit"

# Bump when the field set changes in a way a consumer would notice. An audit
# record outlives the code that wrote it, so it has to say which shape it is.
SCHEMA_VERSION = 1

# Dedicated logger, kept off the root logger so app.py's basicConfig() doesn't
# print a second copy without the attributes.
LOGGER_NAME = "observai.audit"

_ATTR_PREFIX = "audit."

# Populated by init_audit_logging().
_logger = None


class _AuditFormatter(logging.Formatter):
    """Human-greppable line, with the `audit.*` attributes appended as JSON.

    Only used by the stdout handler. The OTel handler needs no formatter — it
    reads the same attributes off the LogRecord directly.
    """

    def __init__(self):
        super().__init__(fmt="%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record):
        base = super().format(record)
        fields = {
            k: v for k, v in vars(record).items() if k.startswith(_ATTR_PREFIX)
        }
        payload = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
        return f"{base} {payload}"


def init_audit_logging():
    """Wire the audit logger. Call once, after init_tracing().

    Idempotent: gunicorn's import behaviour can run module setup more than
    once per process, and a second set of handlers would duplicate every
    record — which for an audit log is worse than losing one, because it
    inflates the counts an auditor reconciles against.
    """
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    # Own handlers only; do not also bubble up to the root handler.
    logger.propagate = False

    if not logger.handlers:
        stream = logging.StreamHandler()
        stream.setFormatter(_AuditFormatter())
        logger.addHandler(stream)

        if Config.OTEL_ENABLED:
            provider = LoggerProvider(resource=resource())
            provider.add_log_record_processor(
                BatchLogRecordProcessor(
                    # The SDK does not append the path for logs the way it does
                    # for traces, so name /v1/logs explicitly.
                    OTLPLogExporter(
                        endpoint=f"{Config.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/logs"
                    )
                )
            )
            set_logger_provider(provider)
            # LoggingHandler stamps the active span's trace/span ids onto every
            # record, so Dynatrace correlates log to trace natively. We *also*
            # write them as attributes below — see build_record().
            logger.addHandler(
                LoggingHandler(level=logging.INFO, logger_provider=provider)
            )
            log.info("audit sink exporting to %s/v1/logs", Config.OTEL_EXPORTER_OTLP_ENDPOINT)
        else:
            log.info("audit sink: OTel export disabled, records go to stdout only")

    _logger = logger
    return _logger


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _content_mode(flagged: bool) -> str:
    """Why the record does or doesn't carry text — recorded, not inferred.

    An auditor looking at a row with no prompt must be able to tell a policy
    decision from a bug, so the reason is a field rather than an absence.
    """
    if not flagged:
        return "omitted:not_flagged"
    if not Config.AUDIT_LOG_CONTENT:
        return "omitted:disabled"
    if Config.AUDIT_HASH_CONTENT:
        return "hash"
    return "text"


def _add_content(record: dict, name: str, text: str, mode: str):
    """Attach one text field under `audit.<name>` according to `mode`."""
    record[f"{_ATTR_PREFIX}{name}.chars"] = len(text)
    if mode.startswith("omitted"):
        return

    # Digest over the full text, always, and before truncation.
    record[f"{_ATTR_PREFIX}{name}.sha256"] = _sha256(text)
    if mode == "hash":
        return

    cap = Config.AUDIT_MAX_TEXT_CHARS
    truncated = len(text) > cap
    record[f"{_ATTR_PREFIX}{name}"] = text[:cap] if truncated else text
    record[f"{_ATTR_PREFIX}{name}.truncated"] = truncated


def _trace_ids(span=None):
    """Hex trace/span ids for the record, or (None, None) if there's no trace.

    Written into the record explicitly even though the OTel handler already
    sets them on the log record itself: an audit row has to be readable on its
    own terms, without depending on how a given backend chose to surface
    correlation. Note also that if trace sampling is ever switched on (there is
    no sampler configured today, so everything exports), a `trace_id` here can
    point at a trace that was dropped — which is exactly why the record carries
    the full picture rather than a pointer to it.
    """
    ctx = (span or trace.get_current_span()).get_span_context()
    if not ctx or not ctx.trace_id:
        return None, None
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


def build_record(request_id, req, result, oversight, span=None) -> dict:
    """Build the audit record. Pure function — no I/O, so it unit-tests directly.

    `result` is the inference service's response body, which already carries
    more than the gateway puts on the span: `confidence_signals`, `done_reason`,
    `latency_ms` and `tokens_per_sec` all arrive and were previously dropped.
    """
    flagged = bool(getattr(oversight, "flagged", False))
    reasons = list(getattr(oversight, "reasons", []) or [])
    mode = _content_mode(flagged)
    trace_id, span_id = _trace_ids(span)

    record = {
        f"{_ATTR_PREFIX}event.type": EVENT_TYPE,
        f"{_ATTR_PREFIX}schema.version": SCHEMA_VERSION,
        f"{_ATTR_PREFIX}request_id": request_id,
        f"{_ATTR_PREFIX}flagged": flagged,
        # The list is the queryable form; the joined string matches what the
        # span carries in `ai.oversight.reasons`, so the dashboard's existing
        # splitString(reasons, "; ") tile works against either source.
        f"{_ATTR_PREFIX}reasons": reasons,
        f"{_ATTR_PREFIX}reasons.text": "; ".join(reasons),
        f"{_ATTR_PREFIX}task": getattr(req, "task", None),
        f"{_ATTR_PREFIX}model": result.get("model"),
        f"{_ATTR_PREFIX}confidence": result.get("confidence"),
        f"{_ATTR_PREFIX}confidence.signals": list(result.get("confidence_signals") or []),
        f"{_ATTR_PREFIX}done_reason": result.get("done_reason"),
        f"{_ATTR_PREFIX}tokens.in": result.get("tokens_in"),
        f"{_ATTR_PREFIX}tokens.out": result.get("tokens_out"),
        f"{_ATTR_PREFIX}latency.ms": result.get("latency_ms"),
        f"{_ATTR_PREFIX}tokens_per_sec": result.get("tokens_per_sec"),
        f"{_ATTR_PREFIX}content.mode": mode,
    }
    if trace_id:
        record[f"{_ATTR_PREFIX}trace_id"] = trace_id
        record[f"{_ATTR_PREFIX}span_id"] = span_id

    _add_content(record, "prompt", getattr(req, "input_text", "") or "", mode)
    _add_content(record, "response", result.get("output") or "", mode)

    # Drop keys the inference service didn't report rather than writing nulls:
    # a missing field in an audit row should mean "not reported", and an
    # explicit null in a log attribute is just noise to query around.
    return {k: v for k, v in record.items() if v is not None}


def emit(request_id, req, result, oversight, span=None):
    """Write one audit record. Returns the record, or None if nothing was written.

    Fail-open by design: a sink failure must not turn a successful model
    response into an error for the caller. The failure is made visible instead
    — an ERROR log plus `ai.audit.sink_error` on the current span, so it is
    both alertable and queryable. If your compliance posture requires the
    opposite (no record, no answer), raise from here and let /prompt 5xx.
    """
    if not Config.AUDIT_ENABLED:
        return None

    try:
        flagged = bool(getattr(oversight, "flagged", False))
        if not flagged and not Config.AUDIT_RECORD_UNFLAGGED:
            return None

        record = build_record(request_id, req, result, oversight, span=span)
        logger = init_audit_logging()
        logger.info(
            "oversight audit request_id=%s flagged=%s",
            request_id,
            flagged,
            extra=record,
        )
        return record
    except Exception:
        current = span or trace.get_current_span()
        try:
            current.set_attribute("ai.audit.sink_error", True)
        except Exception:
            pass
        log.exception("audit sink failed request_id=%s", request_id)
        return None
