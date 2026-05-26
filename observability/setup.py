"""OpenTelemetry TracerProvider and MeterProvider setup."""
import os
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes

def setup_telemetry():
    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: "reliability-agent",
        ResourceAttributes.SERVICE_VERSION: "1.0.0",
        ResourceAttributes.DEPLOYMENT_ENVIRONMENT: "production",
        "gcp.project.id": os.getenv("GOOGLE_CLOUD_PROJECT", "unknown"),
    })

    dt_token = os.getenv("DYNATRACE_API_TOKEN", "")
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    # Traces
    trace_exporter = OTLPSpanExporter(
        endpoint=f"{otel_endpoint}/v1/traces",
        headers={"Authorization": f"Api-Token {dt_token}"}
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(tracer_provider)

    # Metrics
    metric_exporter = OTLPMetricExporter(
        endpoint=f"{otel_endpoint}/v1/metrics",
        headers={"Authorization": f"Api-Token {dt_token}"}
    )
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=10000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    return trace.get_tracer("reliability-agent", "1.0.0"), metrics.get_meter("reliability-agent", "1.0.0")
