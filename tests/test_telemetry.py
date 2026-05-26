"""Smoke test: emit a trace span and verify the OTel pipeline initializes."""
import time
from observability.setup import setup_telemetry
from opentelemetry import trace

tracer, meter = setup_telemetry()

# Create a test counter
test_counter = meter.create_counter("test.pipeline.runs")

with tracer.start_as_current_span("test.pipeline.verification") as span:
    span.set_attribute("test", True)
    span.set_attribute("hackathon.track", "dynatrace")
    test_counter.add(1, {"status": "success"})
    print("✅ Test trace emitted. Check Dynatrace Distributed Traces in 30 seconds.")
    print(f"   Trace ID: {format(span.get_span_context().trace_id, '032x')}")

time.sleep(2)  # Give exporter time to flush
