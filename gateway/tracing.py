"""OpenTelemetry wiring.

We instrument with vendor-neutral OTel and export OTLP to a Collector,
which forwards to Dynatrace. Doing it this way (rather than dropping in a
vendor agent) keeps the telemetry portable and is the whole point of the
project: observability as a discipline, not a single dashboard.
"""
import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

from config import Config

log = logging.getLogger(__name__)


def init_tracing(app):
    """Set up a tracer provider and auto-instrument Flask + outbound requests.

    Call once, after the Flask app is created. Returns the tracer so the app
    can open its own manual spans for the AI-specific work.
    """
    resource = Resource.create(
        {
            "service.name": Config.SERVICE_NAME,
            "service.version": Config.SERVICE_VERSION,
            "deployment.environment": Config.ENV,
        }
    )
    provider = TracerProvider(resource=resource)

    if Config.OTEL_ENABLED:
        # OTLP/HTTP to the Collector. The SDK appends /v1/traces.
        exporter = OTLPSpanExporter(
            endpoint=f"{Config.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces"
        )
        log.info("OTel exporting to %s", Config.OTEL_EXPORTER_OTLP_ENDPOINT)
    else:
        # Handy for local dev with no Collector running.
        exporter = ConsoleSpanExporter()
        log.info("OTel export disabled; spans go to console")

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Auto-instrument: every inbound request becomes a span, and the call we
    # make to the inference service is captured as a child span automatically.
    FlaskInstrumentor().instrument_app(app)
    RequestsInstrumentor().instrument()

    return trace.get_tracer(Config.SERVICE_NAME)
