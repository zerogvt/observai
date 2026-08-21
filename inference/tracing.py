"""OpenTelemetry: traces AND metrics.

The gateway annotates traces; the inference service is where the real AI
*metrics* are born — tokens, latency, throughput — because this is the service
that actually knows them. We set up both a tracer and a meter here and export
OTLP to the Collector, which forwards to Dynatrace.
"""
import logging

from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

from config import Config

log = logging.getLogger(__name__)

# Module-level handles for the instruments, populated by init_tracing().
tokens_in_counter = None
tokens_out_counter = None
latency_hist = None
requests_counter = None


def init_tracing(app):
    """Set up tracer + meter, auto-instrument Flask/requests, create instruments.

    Returns the tracer. Metric instruments are stored at module level and
    imported by app.py.
    """
    global tokens_in_counter, tokens_out_counter, latency_hist, requests_counter

    resource = Resource.create(
        {
            "service.name": Config.SERVICE_NAME,
            "service.version": Config.SERVICE_VERSION,
            "deployment.environment": Config.ENV,
        }
    )

    # --- Traces ---
    tracer_provider = TracerProvider(resource=resource)
    if Config.OTEL_ENABLED:
        span_exporter = OTLPSpanExporter(
            endpoint=f"{Config.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces"
        )
    else:
        span_exporter = ConsoleSpanExporter()
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    # Only attach a *periodic* exporter when OTel is enabled (i.e. a real
    # Collector is listening). In local/dev mode (OTEL_ENABLED=false) we
    # deliberately attach NO metric reader: a PeriodicExportingMetricReader
    # paired with a console exporter re-dumps every cumulative metric on each
    # interval, which spams the terminal after the first request. The
    # instruments created below still work (their .add()/.record() calls are
    # just never collected/exported), so app.py is unchanged. Turn on
    # OTEL_ENABLED to see metrics actually flow to the Collector/Dynatrace.
    metric_readers = []
    if Config.OTEL_ENABLED:
        metric_readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=f"{Config.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/metrics"
                ),
                export_interval_millis=10000,
            )
        )
    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    metrics.set_meter_provider(meter_provider)
    meter = meter_provider.get_meter(Config.SERVICE_NAME)

    # The AI metrics you'll actually chart and alert on in Dynatrace.
    tokens_in_counter = meter.create_counter(
        "observai.tokens.in", unit="1", description="Input/prompt tokens consumed"
    )
    tokens_out_counter = meter.create_counter(
        "observai.tokens.out", unit="1", description="Output/generated tokens"
    )
    latency_hist = meter.create_histogram(
        "observai.inference.latency", unit="ms", description="End-to-end inference latency"
    )
    requests_counter = meter.create_counter(
        "observai.inference.requests", unit="1", description="Inference requests by task/outcome"
    )

    FlaskInstrumentor().instrument_app(app)
    RequestsInstrumentor().instrument()

    if not Config.OTEL_ENABLED:
        log.info(
            "OTel export disabled: spans -> console, metrics not exported "
            "(set OTEL_ENABLED=true with a Collector to ship metrics)"
        )
    return trace.get_tracer(Config.SERVICE_NAME)
